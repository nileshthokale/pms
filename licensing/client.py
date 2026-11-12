"""HTTPS client, persistent signed lease, and controlled-clock policy engine."""
from dataclasses import dataclass
import json
import logging
import logging.handlers
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit
import uuid

import httpx

from licensing.protocol import InvalidLicense, verify_license
from licensing.storage import DPAPIStore, StorageError

log = logging.getLogger("pharmacy.licensing")


class Clock:
    def wall(self):
        return time.time()

    def monotonic(self):
        return time.monotonic()


@dataclass(frozen=True)
class Decision:
    allowed: bool
    status: str
    message: str
    connectivity: str


def load_config():
    config = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
    if config.get("activation_mode") != "ALERT" or config.get("offline_grace_hours") != 48:
        raise ValueError("Unsupported licensing policy")
    return config


class LicenseClient:
    def __init__(self, config, store, *, clock=None, transport=None):
        self.config, self.store = config, store
        self.clock = clock or Clock()
        self._lock = threading.RLock()
        self.transport = transport
        self.connectivity = "NOT_CHECKED"
        self.last_transition = None
        self.state = store.read()
        if self.state is None:
            self.state = {"device_id": str(uuid.uuid4()), "device_secret": secrets.token_urlsafe(48),
                          "registered": False, "license": None, "activation_key": ""}
            store.write(self.state)  # persist identity before the first network request
        if not self.state.get("device_id") or not self.state.get("device_secret"):
            raise StorageError("Invalid device credentials; contact support")
        self._trusted_start = self.state.get("trusted_time", 0)
        self._mono_start = self.clock.monotonic()

    def _effective_time(self):
        wall = self.clock.wall()
        high = self.state.get("wall_high", wall)
        rollback = wall < high - 300
        trusted = self._trusted_start + max(0, self.clock.monotonic() - self._mono_start)
        anchor = self.state.get("validated_wall", wall)
        estimated = self.state.get("validated_server", 0) + max(0, wall - anchor)
        now = max(trusted, estimated, self.state.get("trusted_time", 0))
        self.state["wall_high"] = max(high, wall)
        self.state["trusted_time"] = now
        if rollback:
            self.state["clock_rollback"] = True
        return now

    def decision(self):
        with self._lock:
            return self._decision()

    def _decision(self):
        envelope = self.state.get("license")
        now = self._effective_time()
        self.store.write(self.state)
        if not self.config.get("server_url") or not self.config.get("public_keys"):
            result = Decision(False, "NOT_CONFIGURED", "Licensing service is not configured. Contact support.", self.connectivity)
        elif self.connectivity == "AUTHENTICATION_ERROR" or not envelope:
            msg = "This computer's registration was removed or rejected in Super Admin. Please activate with an active license." if self.connectivity == "AUTHENTICATION_ERROR" else "Connect to the internet and activate this installation to continue."
            status = "AUTHENTICATION_ERROR" if self.connectivity == "AUTHENTICATION_ERROR" else "VALIDATION_REQUIRED"
            result = Decision(False, status, msg, self.connectivity)
        else:
            try:
                payload = verify_license(envelope, self.config["public_keys"], self.state["device_id"])
            except InvalidLicense:
                result = Decision(False, "INVALID_LICENSE", "License verification failed. Connect to the internet or contact support.", self.connectivity)
            else:
                status = payload["status"]
                if status != "AUTHORIZED":
                    messages = {"REVOKED": "This device license was revoked. Contact support for reactivation.",
                                "PENDING": "An active license is required. Enter your activation key or contact support.",
                                "LIMIT_REACHED": "The license device limit has been reached. Contact support.",
                                "EXPIRED": "The license has expired. Contact support to renew it."}
                    result = Decision(False, status, messages[status], self.connectivity)
                elif self.state.get("clock_rollback"):
                    result = Decision(False, "CLOCK_ROLLBACK", "The system clock changed. Internet validation is required.", self.connectivity)
                elif now >= payload["license_expires_at"]:
                    result = Decision(False, "EXPIRED", "The license has expired. Contact support to renew it.", self.connectivity)
                elif now >= payload["offline_until"]:
                    result = Decision(False, "OFFLINE_EXPIRED", "48-hour offline allowance ended. Internet license validation is required.", self.connectivity)
                else:
                    online = self.connectivity == "ONLINE"
                    result = Decision(True, "AUTHORIZED" if online else "OFFLINE_GRACE",
                                      "License validated." if online else "Operating with a verified offline license (up to 48 hours).", self.connectivity)
        transition = (result.status, result.connectivity)
        if transition != self.last_transition:
            log.info("license_transition status=%s connectivity=%s", *transition)
            self.last_transition = transition
        return result

    def validate(self, *, activation_key=None, heartbeat=False):
        with self._lock:
            explicit_key = activation_key.strip() if activation_key else None
            # Do not persist activation keys locally: access requires explicit entry or server authorization
            self.state.pop("activation_key", None)
            url = self.config.get("server_url", "").rstrip("/")
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                self.connectivity = "CONFIGURATION_ERROR"
                return self._decision()
            nonce = secrets.token_urlsafe(32)
            from version import APP_VERSION
            body = {"device_id": self.state["device_id"], "device_secret": self.state["device_secret"],
                    "app_version": APP_VERSION, "nonce": nonce}
            register = explicit_key is not None
            if register:
                endpoint = "/v1/devices/register"
                body["activation_key"] = explicit_key
            elif heartbeat and self.state.get("registered"):
                endpoint = "/v1/devices/heartbeat"
            else:
                endpoint = "/v1/devices/validate"
            try:
                with httpx.Client(timeout=httpx.Timeout(12), verify=True, follow_redirects=False, transport=self.transport) as http:
                    started = time.monotonic()
                    with http.stream("POST", url + endpoint, json=body) as response:
                        status_code = response.status_code
                        received = bytearray()
                        for chunk in response.iter_bytes():
                            if time.monotonic() - started > 15:
                                raise httpx.ReadTimeout("License response exceeded deadline")
                            received.extend(chunk)
                            if len(received) > 65536:
                                raise InvalidLicense("Oversized license response")
                if status_code >= 500 or status_code == 429:
                    self.connectivity = "SERVER_UNAVAILABLE"
                elif status_code != 200:
                    self.connectivity = "AUTHENTICATION_ERROR" if status_code in (401, 403) else "PROTOCOL_ERROR"
                    if status_code in (401, 403):
                        # Explicit rejection from server (device deleted, unlinked, or unauthorized).
                        # Invalidate cached license envelope immediately so offline grace is terminated.
                        self.state["license"] = None
                        self.state["registered"] = False
                        self.state.pop("activation_key", None)
                        self.store.write(self.state)
                else:
                    envelope = json.loads(received)
                    payload = verify_license(envelope, self.config["public_keys"], self.state["device_id"], nonce)
                    previous = self.state.get("license")
                    if not register and previous and previous.get("payload", {}).get("license_id") == payload.get("license_id") and payload["revision"] <= previous.get("payload", {}).get("revision", 0):
                        raise InvalidLicense("Stale license revision")
                    self.state.update(license=envelope, registered=True, validated_server=payload["issued_at"],
                                      validated_wall=self.clock.wall(), wall_high=self.clock.wall(),
                                      trusted_time=payload["issued_at"], clock_rollback=False,
                                      last_successful_validation=payload["issued_at"])
                    self._trusted_start, self._mono_start = payload["issued_at"], self.clock.monotonic()
                    self.store.write(self.state)
                    self.connectivity = "ONLINE"
            except httpx.TimeoutException:
                self.connectivity = "TIMEOUT"
            except httpx.ConnectError:
                self.connectivity = "NETWORK_UNAVAILABLE"
            except httpx.HTTPError:
                self.connectivity = "NETWORK_ERROR"
            except (InvalidLicense, ValueError, KeyError):
                self.connectivity = "INVALID_RESPONSE"
            log.info("license_check outcome=%s heartbeat=%s", self.connectivity, heartbeat)
            return self._decision()

    def notify_offline(self, *, timeout=2.0) -> bool:
        """Notify the license server that the local application is closing gracefully."""
        with self._lock:
            url = self.config.get("server_url", "").rstrip("/")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                return False
            nonce = secrets.token_urlsafe(32)
            from version import APP_VERSION
            body = {
                "device_id": self.state["device_id"],
                "device_secret": self.state["device_secret"],
                "app_version": APP_VERSION,
                "nonce": nonce,
            }
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(timeout),
                    verify=True,
                    follow_redirects=False,
                    transport=self.transport,
                ) as http:
                    response = http.post(url + "/v1/devices/offline", json=body)
                    if response.status_code == 200:
                        self.connectivity = "OFFLINE"
                        log.info("license_shutdown outcome=SUCCESS device=%s", self.state["device_id"])
                        return True
            except Exception as exc:
                log.debug("notify_offline failed: %s", exc)
            return False

    def close(self) -> bool:
        return self.notify_offline()


def desktop_client():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    # Separate test-release credentials from the production installation.
    directory = base / ("PharmacyManagementSystem-Test" if os.environ.get("PHARMACY_TEST_RELEASE") == "1" else "PharmacyManagementSystem") / "licensing"
    directory.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(directory / "audit.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return LicenseClient(load_config(), DPAPIStore(directory))
