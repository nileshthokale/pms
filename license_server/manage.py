"""Developer CLI. Schema/credentials never flow into the desktop package."""
import argparse
import base64
from datetime import datetime, timezone
import getpass
import json
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    keys = sub.add_parser("generate-key")
    keys.add_argument("--private-file", required=True)
    keys.add_argument("--public-file", required=True)
    sub.add_parser("init-db")
    admin = sub.add_parser("create-admin")
    admin.add_argument("username")
    issue = sub.add_parser("issue-license")
    issue.add_argument("--customer", required=True)
    issue.add_argument("--expires", required=True, help="Timezone-aware ISO 8601 timestamp")
    issue.add_argument("--max-devices", type=int, required=True)
    issue.add_argument("--admin", required=True)
    update = sub.add_parser("update-license")
    update.add_argument("license_id")
    update.add_argument("--expires", required=True)
    update.add_argument("--status", choices=["ACTIVE", "DISABLED"], required=True)
    update.add_argument("--admin", required=True)
    update.add_argument("--reason", required=True)
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
    settings = Settings.from_env()
    engine = create_engine(settings.database_url)
    if args.command == "init-db":
        Base.metadata.create_all(engine)
        print("Licensing schema v1 created (idempotent; pharmacy schema is never accessed).")
        return
    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        if args.command == "create-admin":
            if session.get(Administrator, args.username):
                parser.error("Administrator already exists")
            password = getpass.getpass("New developer password (minimum 12 characters): ")
            if len(password) < 12 or password != getpass.getpass("Confirm password: "):
                parser.error("Password too short or confirmation does not match")
            session.add(Administrator(username=args.username, password_hash=PasswordHasher().hash(password), role="DEVELOPER"))
            session.add(Audit(id=str(uuid.uuid4()), event="admin_created", actor="server-cli", reason=args.username, created_at=now))
        else:
            user = session.get(Administrator, args.admin)
            try:
                valid = bool(user and user.active and user.role == "DEVELOPER" and PasswordHasher().verify(user.password_hash, getpass.getpass("Developer password: ")))
            except Exception:
                valid = False
            if not valid:
                parser.error("Developer authentication failed")
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
                session.add(License(id=license_id, customer_id=customer.id, activation_hash=digest(activation, settings.pepper),
                                    expires_at=expires, max_devices=args.max_devices, status="ACTIVE"))
                event, reason = "license_issued", license_id
            else:
                license = session.scalar(select(License).where(License.id == args.license_id).with_for_update())
                if not license:
                    parser.error("License not found")
                license.expires_at, license.status = expires, args.status
                event, reason = "license_updated", args.license_id + ": " + args.reason
            session.add(Audit(id=str(uuid.uuid4()), event=event, actor=user.username, reason=reason, created_at=now))
        session.commit()
        if args.command == "issue-license":
            print("License ID:", license_id)
            print("Activation key (deliver securely; shown once):", activation)


if __name__ == "__main__":
    main()
