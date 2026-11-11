"""Actual loopback TLS connection with certificate verification and isolated PostgreSQL."""
import base64
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import secrets
import ssl
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
from argon2 import PasswordHasher
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine, text

from license_server.app import create_app, digest
from license_server.models import Administrator, Base, Customer, License
from license_server.settings import Settings
from licensing.client import LicenseClient
from licensing.storage import DPAPIStore


def main():
    output = ROOT / "temp/license_validation/https_smoke"
    output.mkdir(parents=True, exist_ok=True)
    pg_url = "postgresql+psycopg://license_test@127.0.0.1:55439/licensing_isolated_test"
    schema = "smoke_" + uuid.uuid4().hex
    bootstrap = create_engine(pg_url)
    with bootstrap.begin() as conn:
        conn.execute(text('CREATE SCHEMA "' + schema + '"'))
    engine = create_engine(pg_url, connect_args={"options":"-csearch_path=" + schema})
    Base.metadata.create_all(engine)
    signing_key = ed25519.Ed25519PrivateKey.generate()
    settings = Settings(pg_url, signing_key, secrets.token_urlsafe(48))
    app = create_app(settings, engine=engine)
    activation = secrets.token_urlsafe(48)
    password = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    customer_id, license_id = str(uuid.uuid4()), str(uuid.uuid4())
    with app.state.sessions() as session:
        session.add(Customer(id=customer_id,name="Isolated TLS test pharmacy"));session.flush()
        session.add(License(id=license_id,customer_id=customer_id,activation_hash=digest(activation,settings.pepper),expires_at=now+timedelta(days=30),max_devices=1,status="ACTIVE"))
        session.add(Administrator(username="tls-test-developer",password_hash=PasswordHasher().hash(password),role="DEVELOPER"));session.commit()
    tls_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"Loopback licensing test")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),critical=False)
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(tls_key,hashes.SHA256()))
    cert_file,key_file=output/"loopback-cert.pem",output/"loopback-key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(tls_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    server = uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=55440,ssl_certfile=str(cert_file),ssl_keyfile=str(key_file),access_log=False,log_level="error"))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    context=ssl.create_default_context(cafile=str(cert_file))
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    if not server.started:raise RuntimeError("Loopback TLS service did not start")
    url="https://127.0.0.1:55440"
    config={"server_url":url,"public_keys":{"primary":base64.b64encode(signing_key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()}}
    credential_dir=output/uuid.uuid4().hex
    client=LicenseClient(config,DPAPIStore(credential_dir),transport=httpx.HTTPTransport(verify=context))
    results={"database":"PostgreSQL 17.6 isolated loopback cluster","tls":"Verified loopback certificate","public_deployment":False}
    try:
        results["activation"]=client.validate(activation_key=activation).status
        assert results["activation"] == "AUTHORIZED"
        results["heartbeat"]=client.validate(heartbeat=True).status
        assert results["heartbeat"] == "AUTHORIZED"
        with httpx.Client(base_url=url,verify=context) as admin:
            auth=admin.post('/admin/login',json={"username":"tls-test-developer","password":password});assert auth.status_code==200
            headers={"X-CSRF-Token":auth.json()["csrf_token"]}
            results["dashboard_total"]=admin.get('/admin/summary').json()["total"]
            results["dashboard_html"]=admin.get('/admin').status_code
            device=client.state["device_id"]
            action={"confirm":True,"confirmed_device_id":device,"reason":"Loopback TLS verification"}
            assert admin.post(f'/admin/devices/{device}/revoke',headers=headers,json=action).status_code==200
            results["revocation"]=client.validate().status;assert results["revocation"]=="REVOKED"
            restart=LicenseClient(config,DPAPIStore(credential_dir),transport=httpx.HTTPTransport(verify=context))
            results["restart_after_revocation"]=restart.decision().status;assert results["restart_after_revocation"]=="REVOKED"
            assert admin.post(f'/admin/devices/{device}/reactivate',headers=headers,json=action).status_code==200
            results["reactivation"]=restart.validate().status;assert results["reactivation"]=="AUTHORIZED"
        (output/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
        print(json.dumps(results,indent=2))
    finally:
        server.should_exit=True;thread.join(timeout=15)
        engine.dispose()
        with bootstrap.begin() as conn:conn.execute(text('DROP SCHEMA "'+schema+'" CASCADE'))
        bootstrap.dispose()


if __name__ == "__main__":
    main()
