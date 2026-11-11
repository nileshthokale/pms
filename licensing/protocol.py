"""Strict Ed25519 signed protocol shared by desktop and licensing service."""
import base64
import json
import math

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ISSUER = "pharmacy-license-service"
AUDIENCE = "pharmacy-desktop"
OFFLINE_SECONDS = 48 * 60 * 60
STATUSES = {"AUTHORIZED", "PENDING", "REVOKED", "EXPIRED", "LIMIT_REACHED"}


class InvalidLicense(ValueError):
    pass


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sign_license(private_key, key_id, payload):
    return {"payload": payload, "key_id": key_id,
            "signature": base64.b64encode(private_key.sign(canonical(payload))).decode()}


def verify_license(envelope, public_keys, device_id, nonce=None):
    try:
        if set(envelope) != {"payload", "key_id", "signature"}:
            raise ValueError("Not a signed license envelope")
        payload = envelope["payload"]
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_keys[envelope["key_id"]], validate=True))
        key.verify(base64.b64decode(envelope["signature"], validate=True), canonical(payload))
        if (payload["schema"] != 1 or payload["issuer"] != ISSUER
                or payload["audience"] != AUDIENCE or payload["device_id"] != device_id
                or payload["status"] not in STATUSES):
            raise ValueError("Wrong license scope")
        if nonce is not None and payload["nonce"] != nonce:
            raise ValueError("Replayed response")
        for name in ("issued_at", "offline_until", "license_expires_at"):
            value = payload[name]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid license timestamp")
        if type(payload["revision"]) is not int or payload["revision"] < 1:
            raise ValueError("Invalid license revision")
        if not (payload["issued_at"] <= payload["offline_until"] <= payload["issued_at"] + OFFLINE_SECONDS):
            raise ValueError("Invalid offline lease")
        if payload["status"] == "AUTHORIZED" and (
                payload["license_expires_at"] <= payload["issued_at"]
                or payload["offline_until"] > payload["license_expires_at"]
                or not payload.get("license_id")):
            raise ValueError("Invalid authorization expiry")
        return payload
    except (KeyError, TypeError, ValueError, InvalidSignature) as exc:
        raise InvalidLicense("License signature or claims are invalid") from exc
