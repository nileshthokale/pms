from dataclasses import dataclass
import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@dataclass(frozen=True)
class Settings:
    database_url: str
    private_key: Ed25519PrivateKey
    pepper: str
    key_id: str = "primary"
    heartbeat_threshold: int = 900
    recent_threshold: int = 86400
    session_seconds: int = 28800
    cookie_name: str = "license_admin"
    admin_origin: str = ""
    environment: str = "development"
    vercel: bool = False

    @classmethod
    def from_env(cls):
        url = os.environ["LICENSE_DATABASE_URL"]
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("The central licensing database must be PostgreSQL")
        pepper = os.environ["LICENSE_SECRET_PEPPER"]
        if len(pepper) < 32:
            raise ValueError("LICENSE_SECRET_PEPPER must contain at least 32 random characters")
        vercel = os.environ.get("VERCEL") == "1"
        environment = os.environ.get("VERCEL_ENV", "development") if vercel else "development"
        if vercel:
            dep_env = os.environ.get("LICENSE_DEPLOYMENT_ENV")
            if dep_env and dep_env != environment:
                raise ValueError("License environment must match Vercel production/preview/development")
            from sqlalchemy.engine import make_url
            parsed_url = make_url(url)
            if parsed_url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("Managed PostgreSQL requires TLS")
            # Preview credentials must identify a distinct database/branch, never production.
            if environment != "production":
                production_id = os.environ.get("LICENSE_PRODUCTION_DATABASE_ID", "")
                if production_id:
                    current_id = os.environ.get("LICENSE_DATABASE_ID", "")
                    if not current_id or production_id == current_id:
                        raise ValueError("Preview requires a distinct managed PostgreSQL branch/database ID")
                    production_identity = os.environ.get("LICENSE_PRODUCTION_DATABASE_HOST", "")
                    production_name = os.environ.get("LICENSE_PRODUCTION_DATABASE_NAME", "")
                    if not production_identity or not production_name:
                        raise ValueError("Preview requires production database host/name guards")
                    if parsed_url.host == production_identity and parsed_url.database == production_name:
                        raise ValueError("Preview must not connect to the production licensing database")
                    production_key_id = os.environ.get("LICENSE_PRODUCTION_KEY_ID", "")
                    if not production_key_id or os.environ.get("LICENSE_KEY_ID", "primary") == production_key_id:
                        raise ValueError("Preview must use its own signing key ID")
        encoded_key = os.environ.get("LICENSE_SIGNING_KEY_PEM_B64")
        if encoded_key:
            try:
                material = base64.b64decode(encoded_key, validate=True)
            except ValueError as exc:
                raise ValueError("Invalid server signing-key encoding") from exc
        elif not vercel:
            material = Path(os.environ["LICENSE_SIGNING_KEY_FILE"]).read_bytes()
        else:
            raise ValueError("Vercel requires a server-side LICENSE_SIGNING_KEY_PEM_B64 secret")
        key = serialization.load_pem_private_key(material, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("An Ed25519 signing key is required")
        if vercel and environment != "production":
            production_fingerprint = os.environ.get("LICENSE_PRODUCTION_SIGNING_KEY_SHA256", "")
            if production_fingerprint and len(production_fingerprint) == 64:
                fingerprint = hashlib.sha256(key.public_key().public_bytes_raw()).hexdigest()
                if fingerprint == production_fingerprint:
                    raise ValueError("Preview must use a separate signing key from production")
        threshold = int(os.environ.get("LICENSE_ONLINE_THRESHOLD_SECONDS", "900"))
        if not 60 <= threshold <= 3600:
            raise ValueError("Online threshold must be between 60 and 3600 seconds")
        recent_threshold = int(os.environ.get("LICENSE_RECENT_THRESHOLD_SECONDS", "86400"))
        if not 60 <= recent_threshold <= 604800:
            raise ValueError("Recent threshold must be between 60 and 604800 seconds")
        origin = os.environ.get("LICENSE_ADMIN_ORIGIN", "").rstrip("/")
        if vercel and not origin:
            hostname = os.environ.get("VERCEL_URL", "")
            origin = "https://" + hostname if hostname else ""
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                raise ValueError("LICENSE_ADMIN_ORIGIN must be an exact HTTPS origin")
        if vercel and not origin:
            raise ValueError("A trusted Super Admin HTTPS origin is required")
        return cls(url, key, pepper, os.environ.get("LICENSE_KEY_ID", "primary"), threshold,
                   recent_threshold=recent_threshold,
                   cookie_name="license_admin_" + environment if vercel else "license_admin",
                   admin_origin=origin, environment=environment, vercel=vercel)
