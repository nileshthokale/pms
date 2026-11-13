"""Tests for the License Validity UI panel and client validity reporting."""
import base64
import time
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtWidgets import QApplication

from licensing.client import LicenseClient
from licensing.protocol import sign_license
from licensing.qt import LicenseController
from screens.user_management import LicenseValidityPanel, _ActivateLicenseDialog
from tests.licensing.conftest import MemoryStore


class LicenseValidityUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.priv = Ed25519PrivateKey.generate()
        cls.pub = base64.b64encode(
            cls.priv.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode()
        cls.key_id = "primary"
        cls.config = {
            "server_url": "https://license.test",
            "activation_mode": "ALERT",
            "offline_grace_hours": 48,
            "public_keys": {cls.key_id: cls.pub},
        }

    def _make_client(self, days_left=100, status="AUTHORIZED"):
        store = MemoryStore()
        now = time.time()
        expires = now + (days_left * 86400)
        payload = {
            "schema": 1,
            "issuer": "pharmacy-license-service",
            "audience": "pharmacy-desktop",
            "device_id": "test-device-uuid-1234",
            "license_id": "test-license-uuid-5678",
            "customer_id": "test-customer-uuid-9999",
            "status": status,
            "issued_at": now,
            "offline_until": min(now + 172800, expires),
            "license_expires_at": expires,
            "revision": 1,
            "nonce": "test-nonce",
        }
        envelope = sign_license(self.priv, self.key_id, payload)
        store.write({
            "device_id": "test-device-uuid-1234",
            "device_secret": "test-secret",
            "registered": True,
            "license": envelope,
            "trusted_time": now,
            "wall_high": now,
        })
        client = LicenseClient(self.config, store)
        client.connectivity = "ONLINE"
        return client

    def test_get_license_details_green(self):
        client = self._make_client(days_left=90)
        details = client.get_license_details()
        self.assertTrue(details["has_license"])
        self.assertEqual(details["status"], "AUTHORIZED")
        self.assertEqual(details["days_remaining"], 90)
        self.assertIn("90 Days Remaining", details["days_label"])
        self.assertEqual(details["alert_level"], "success")
        self.assertEqual(details["license_id"], "test-license-uuid-5678")
        self.assertEqual(details["device_id"], "test-device-uuid-1234")

    def test_get_license_details_warning(self):
        client = self._make_client(days_left=15)
        details = client.get_license_details()
        self.assertEqual(details["days_remaining"], 15)
        self.assertEqual(details["alert_level"], "warning")

    def test_get_license_details_expired(self):
        client = self._make_client(days_left=-2, status="EXPIRED")
        details = client.get_license_details()
        self.assertEqual(details["days_remaining"], 0)
        self.assertEqual(details["alert_level"], "danger")

    def test_panel_widget_render(self):
        client = self._make_client(days_left=45)
        ctrl = LicenseController(client, self.app)

        panel = LicenseValidityPanel()
        self.assertIn("45 Days", panel._days_label.text())
        self.assertEqual(panel._license_id.text(), "test-license-uuid-5678")
        self.assertEqual(panel._device_id.text(), "test-device-uuid-1234")

        # Test copy buttons without crashing
        panel._copy_license_id()
        panel._copy_device_id()

        # Test activation dialog instantiation
        dlg = _ActivateLicenseDialog(panel)
        self.assertIsNotNone(dlg.key_field)
