"""Temporary loopback TLS service for the browser acceptance test."""
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import uvicorn

from license_server.app import patch_proactor_connection_lost
from tests.licensing.conftest import env

patch_proactor_connection_lost()


def main():
    folder = ROOT / "temp/super_admin_validation/browser" / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    # Reuse the isolated fixture: it rejects any production PostgreSQL host/port/database.
    fixture = env.__wrapped__(folder)
    test = next(fixture)
    assert test["client"].validate(activation_key=test["activation"]).allowed
    if os.environ.get("SUPER_ADMIN_BROWSER_FLEET") == "1":
        # Synthetic licensing records only, inside the guarded disposable test schema.
        from license_server.models import Alert, Customer, Device, License
        from license_server.security import digest
        with test["app"].state.sessions() as session:
            for index in range(25):
                device_id, customer_id, license_id = (str(uuid.uuid4()) for _ in range(3))
                session.add(Customer(id=customer_id, name=f"Test installation {index:02d}"))
                session.flush()
                session.add(License(id=license_id, customer_id=customer_id,
                    activation_hash=digest("test-only-" + license_id, test["settings"].pepper),
                    expires_at=test["clock"].now() + timedelta(days=30), max_devices=2,
                    status="DISABLED" if index % 6 == 0 else "ACTIVE"))
                session.flush()
                session.add(Device(id=device_id, secret_hash=digest("test-only-" + device_id, test["settings"].pepper),
                    license_id=license_id, app_version=f"2.0.{index}", status="REVOKED" if index % 7 == 0 else "AUTHORIZED",
                    first_seen=test["clock"].now()-timedelta(minutes=index+1),
                    first_activation=test["clock"].now()-timedelta(minutes=index+1),
                    last_seen=test["clock"].now()-timedelta(seconds=1900 if index % 3 == 0 else 60)))
                session.flush()
                session.add(Alert(id=str(uuid.uuid4()),device_id=device_id,created_at=test["clock"].now(),
                    acknowledged_at=None if index % 4 == 0 else test["clock"].now()))
            session.commit()
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Super Admin loopback test")])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),critical=False)
        .sign(key, hashes.SHA256()))
    cert_path, key_path = folder/"cert.pem", folder/"key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    try:
        uvicorn.run(test["app"], host="127.0.0.1", port=55441, ssl_certfile=str(cert_path), ssl_keyfile=str(key_path), log_level="error", access_log=False)
    finally:
        fixture.close()


if __name__ == "__main__":
    main()
