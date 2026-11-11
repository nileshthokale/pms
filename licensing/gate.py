"""Connection admission gate. Existing connection leases always finish normally."""
import threading


class LicenseRestricted(RuntimeError):
    pass


class OperationGate:
    def __init__(self):
        self._lock = threading.RLock()
        self.allowed = False
        self.active = 0
        self.message = "Internet license validation is required."

    def set_access(self, allowed, message):
        with self._lock:
            self.allowed, self.message = allowed, message

    def acquire(self):
        with self._lock:
            if not self.allowed:
                raise LicenseRestricted(self.message)
            self.active += 1

    def release(self):
        with self._lock:
            self.active -= 1

    @property
    def ready_to_lock(self):
        with self._lock:
            return not self.allowed and self.active == 0


_gate = None


def install_gate(gate):
    global _gate
    _gate = gate


def current_gate():
    return _gate
