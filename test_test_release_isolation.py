"""Isolation guards for the packaged TEST release.

These tests cover the safety contract added for the test build:

* the release never falls back to a normal database when its own
  configuration is missing;
* it never silently creates an empty database;
* the normal per-user database path is remapped to the isolated test path;
* the UI/version branding names the test build;
* the development seed path points at the verified staging snapshot.

They do not modify any real database: every path used here is either a
nonexistent temp path or an environment-only remapping.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import release_test_main as release
from database.connection import get_db_path, get_connection

_MANAGED = (
    "PHARMACY_DB",
    "PHARMACY_DB_PATH",
    "PHARMACY_TEST_RELEASE",
    "PHARMACY_REQUIRE_EXISTING_DB",
    "PHARMACY_TEST_PROTECTED_DB",
    "PHARMACY_TEST_SAFE_DB",
)


class TestReleaseIsolationTests(unittest.TestCase):
    def setUp(self):
        self._saved = {name: os.environ.get(name) for name in _MANAGED}
        for name in _MANAGED:
            os.environ.pop(name, None)

    def tearDown(self):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_01_refuses_to_resolve_without_test_db_configuration(self):
        os.environ["PHARMACY_TEST_RELEASE"] = "1"
        with self.assertRaises(RuntimeError):
            get_db_path()

    def test_02_refuses_to_create_an_empty_database(self):
        missing = Path(tempfile.gettempdir()) / "pharmacy_test_release_missing.db"
        if missing.exists():
            missing.unlink()
        os.environ["PHARMACY_DB"] = str(missing)
        os.environ["PHARMACY_TEST_RELEASE"] = "1"
        os.environ["PHARMACY_REQUIRE_EXISTING_DB"] = "1"
        with self.assertRaises(RuntimeError):
            get_connection()
        self.assertFalse(missing.exists())

    def test_03_normal_per_user_database_is_remapped_to_test_database(self):
        normal = str(release.normal_app_data_dir() / release.DB_FILE_NAME)
        safe = str(Path(tempfile.gettempdir()) / "pharmacy_test_release_safe.db")
        os.environ["PHARMACY_DB"] = normal
        os.environ["PHARMACY_TEST_PROTECTED_DB"] = normal
        os.environ["PHARMACY_TEST_SAFE_DB"] = safe
        self.assertEqual(get_db_path(), safe)
        self.assertNotEqual(
            os.path.normcase(get_db_path()), os.path.normcase(normal)
        )

    def test_04_branding_names_the_test_build(self):
        import version

        original = version.APP_TITLE
        try:
            release.apply_test_branding()
            self.assertIn("Test Build", version.APP_TITLE)
            self.assertNotIn("STAGING", version.APP_TITLE)
        finally:
            version.APP_TITLE = original

    def test_05_development_seed_is_the_verified_staging_snapshot(self):
        expected = (
            Path(release.__file__).resolve().parent
            / "staging"
            / "pharmacy_staging.db"
        )
        self.assertEqual(release.bundled_seed_path(), expected)
        self.assertTrue(expected.is_file())

    def test_06_test_data_directory_is_distinct_from_normal_app_directory(self):
        self.assertNotEqual(
            release.test_app_data_dir().name,
            release.normal_app_data_dir().name,
        )
        self.assertEqual(release.test_app_data_dir().name, "PharmacyManagementSystem-Test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
