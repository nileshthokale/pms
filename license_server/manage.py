"""Developer CLI. Schema/credentials never flow into the desktop package."""
import argparse
import base64
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import secrets
import uuid

from argon2 import PasswordHasher
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from license_server.app import digest
from license_server.models import Administrator, Audit, Base, Customer, License
from license_server.settings import Settings


def _resolve_db_url(target="production"):
    if target == "test":
        url = os.environ.get("LICENSE_TEST_DATABASE_URL")
        if not url:
            env_local = Path(__file__).resolve().parents[1] / ".env.local"
            if env_local.exists():
                for line in env_local.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("LICENSE_TEST_DATABASE_URL="):
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        if not url:
            raise RuntimeError(
                "CRITICAL: Target is 'test', but LICENSE_TEST_DATABASE_URL is not configured. "
                "Refusing to execute: test commands will NEVER fall back to production!"
            )
        # Production isolation guard: ensure test URL never points to production host
        prod_url = os.environ.get("LICENSE_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if prod_url and ("@" in url) and ("@" in prod_url):
            if url.split("@")[-1].split("?")[0] == prod_url.split("@")[-1].split("?")[0]:
                raise RuntimeError(
                    "CRITICAL: LICENSE_TEST_DATABASE_URL points to the production database! "
                    "Aborting immediately to protect production data."
                )
    elif target == "production":
        url = os.environ.get("LICENSE_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not url:
            env_local = Path(__file__).resolve().parents[1] / ".env.local"
            if env_local.exists():
                for line in env_local.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("DATABASE_URL="):
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        if not url:
            raise RuntimeError("LICENSE_DATABASE_URL or DATABASE_URL must be configured")
    else:
        raise ValueError(f"Unknown database target: {target}")

    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", choices=["production", "test"], default=None,
                        help="Database target environment ('production' or 'test'). In test mode, requires LICENSE_TEST_DATABASE_URL and never touches production.")
    sub = parser.add_subparsers(dest="command", required=True)
    keys = sub.add_parser("generate-key")
    keys.add_argument("--private-file", required=True)
    keys.add_argument("--public-file", required=True)
    init_cmd = sub.add_parser("init-db")
    init_cmd.add_argument("--database", dest="sub_database", choices=["production", "test"], default=None)
    admin = sub.add_parser("create-admin")
    admin.add_argument("username")
    admin.add_argument("--database", dest="sub_database", choices=["production", "test"], default=None)
    issue = sub.add_parser("issue-license")
    issue.add_argument("--customer", required=True)
    issue.add_argument("--expires", required=True, help="Timezone-aware ISO 8601 timestamp")
    issue.add_argument("--max-devices", type=int, required=True)
    issue.add_argument("--admin", required=True)
    issue.add_argument("--database", dest="sub_database", choices=["production", "test"], default=None)
    update = sub.add_parser("update-license")
    update.add_argument("license_id")
    update.add_argument("--expires", required=True)
    update.add_argument("--status", choices=["ACTIVE", "DISABLED"], required=True)
    update.add_argument("--admin", required=True)
    update.add_argument("--reason", required=True)
    update.add_argument("--database", dest="sub_database", choices=["production", "test"], default=None)
    args = parser.parse_args()
    if args.command == "generate-key":
        key = Ed25519PrivateKey.generate()
        # Exclusive writes prevent accidental destruction of a signing key.
        with open(args.private_file, "xb") as output:
            output.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        with open(args.public_file, "x", encoding="utf-8") as output:
            json.dump({"primary": public}, output, indent=2)
        print("Signing key created. Restrict private-file permissions to the service account.")
        return

    target = getattr(args, "sub_database", None) or getattr(args, "database", None) or os.environ.get("LICENSE_TARGET_DATABASE") or "production"
    db_url = _resolve_db_url(target)
    engine = create_engine(db_url)

    if args.command == "init-db":
        Base.metadata.create_all(engine)
        print(f"[{target.upper()}] Licensing schema v1 created (idempotent; pharmacy schema is never accessed).")
        return

    if args.command == "create-admin":
        with Session(engine) as session:
            now = datetime.now(timezone.utc)
            if session.get(Administrator, args.username):
                parser.error(f"[{target.upper()}] Administrator '{args.username}' already exists")
            password = getpass.getpass("New developer password (minimum 12 characters): ")
            if len(password) < 12 or password != getpass.getpass("Confirm password: "):
                parser.error("Password too short or confirmation does not match")
            session.add(Administrator(username=args.username, password_hash=PasswordHasher().hash(password), role="DEVELOPER"))
            session.add(Audit(id=str(uuid.uuid4()), event="admin_created", actor="server-cli", reason=args.username, created_at=now))
            session.commit()
            print(f"[{target.upper()}] Administrator '{args.username}' created successfully.")
            return

    # For issue-license and update-license:
    pepper = os.environ.get("LICENSE_TEST_SECRET_PEPPER" if target == "test" else "LICENSE_SECRET_PEPPER")
    if not pepper:
        pepper = os.environ.get("LICENSE_SECRET_PEPPER")
    if not pepper:
        if target == "test":
            pepper = "temporary_test_pepper_for_isolated_branch_32chars"
        else:
            raise RuntimeError("LICENSE_SECRET_PEPPER must be set in environment")

    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        user = session.get(Administrator, args.admin)
        try:
            valid = bool(user and user.active and user.role == "DEVELOPER" and PasswordHasher().verify(user.password_hash, getpass.getpass("Developer password: ")))
        except Exception:
            valid = False
        if not valid:
            parser.error(f"[{target.upper()}] Developer authentication failed for '{args.admin}'")
        expires = datetime.fromisoformat(args.expires)
        if expires.tzinfo is None or expires <= now:
            parser.error("Expiry must be a future timestamp with a timezone")
        if args.command == "issue-license":
            if args.max_devices < 1:
                parser.error("Device limit must be positive")
            customer = Customer(id=str(uuid.uuid4()), name=args.customer)
            session.add(customer)
            session.flush()
            activation = secrets.token_urlsafe(48)
            license_id = str(uuid.uuid4())
            session.add(License(id=license_id, customer_id=customer.id, activation_hash=digest(activation, pepper),
                                expires_at=expires, max_devices=args.max_devices, status="ACTIVE"))
            event, reason = "license_issued", license_id
        else:
            license = session.scalar(select(License).where(License.id == args.license_id).with_for_update())
            if not license:
                parser.error(f"[{target.upper()}] License not found")
            license.expires_at, license.status = expires, args.status
            event, reason = "license_updated", args.license_id + ": " + args.reason
        session.add(Audit(id=str(uuid.uuid4()), event=event, actor=user.username, reason=reason, created_at=now))
        session.commit()
        if args.command == "issue-license":
            print(f"[{target.upper()}] License ID:", license_id)
            print(f"[{target.upper()}] Activation key (deliver securely; shown once):", activation)


if __name__ == "__main__":
    main()
