"""Shared licensing security primitives; no access to pharmacy databases."""
import hashlib
import hmac
from datetime import timezone


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def digest(value, pepper):
    return hmac.new(pepper.encode(), value.encode(), hashlib.sha256).hexdigest()
