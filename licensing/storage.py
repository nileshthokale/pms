"""User-bound Windows DPAPI storage. There is no plaintext credential fallback."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile


class StorageError(RuntimeError):
    pass


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, protect):
    if os.name != "nt":
        raise StorageError("Windows secure storage is required on this desktop")
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    target = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise StorageError("Windows could not unlock the licensing credentials")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


class DPAPIStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "license-state.bin"

    def read(self):
        try:
            if not self.path.exists():
                return None
            return json.loads(_dpapi(self.path.read_bytes(), False))
        except (OSError, ValueError) as exc:
            raise StorageError("Licensing state is damaged; contact support for recovery") from exc

    def write(self, state):
        try:
            protected = _dpapi(json.dumps(state, allow_nan=False).encode(), True)
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, filename = tempfile.mkstemp(prefix="license-", suffix=".tmp", dir=self.directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(protected)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(filename, self.path)
            finally:
                if os.path.exists(filename):
                    os.unlink(filename)
        except OSError as exc:
            raise StorageError("Licensing state could not be saved securely") from exc
