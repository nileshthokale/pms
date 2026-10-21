"""Regression tests for automatic UPPERCASE business-data entry.

The feature has three layers, and each is tested here:

1. the pure text rule (:func:`ui.input_rules.coerce_upper`),
2. the per-widget policy (what must NOT be converted — passwords, read-only,
   paths, numbers, explicit opt-outs) and the conversion itself (caret and
   selection preserved, no re-entrant loop, no rewriting of loaded records),
3. the application-wide installer, which is what actually makes every screen
   consistent without touching 200 call sites.

GUI tests skip only when PySide6 is unavailable.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtCore import QObject, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QDoubleSpinBox,
        QLineEdit,
        QVBoxLayout,
        QWidget,
    )

    from ui import input_rules

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover - headless
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


# ── 1. Pure text rule ─────────────────────────────────────────────────

class UpperCaseTextRuleTests(unittest.TestCase):
    """The conversion rule itself, with no Qt involved."""

    def test_01_letters_become_capitals(self):
        self.assertEqual(input_rules.coerce_upper("nilesh"), "NILESH")
        self.assertEqual(input_rules.coerce_upper("bio d3 plus"), "BIO D3 PLUS")
        self.assertEqual(input_rules.coerce_upper("care pharma"), "CARE PHARMA")

    def test_02_digits_symbols_and_spacing_are_untouched(self):
        for value in ("10x10", "12/27", "1,234.50", "  ", "-", ""):
            self.assertEqual(input_rules.coerce_upper(value), value,
                             f"{value!r} must not change")

    def test_03_already_upper_is_a_no_op(self):
        self.assertEqual(input_rules.coerce_upper("CIPLA"), "CIPLA")
        self.assertFalse(input_rules.needs_conversion("CIPLA"))
        self.assertFalse(input_rules.needs_conversion("123.45"))
        self.assertTrue(input_rules.needs_conversion("Cipla"))


# ── 2a. Policy: what must never be converted ──────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class UpperCasePolicyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_01_plain_editable_field_is_enabled(self):
        edit = QLineEdit()
        self.addCleanup(edit.deleteLater)
        self.assertTrue(input_rules.uppercase_enabled(edit))

    def test_02_password_field_is_never_converted(self):
        for mode in (QLineEdit.EchoMode.Password, QLineEdit.EchoMode.NoEcho,
                     QLineEdit.EchoMode.PasswordEchoOnEdit):
            edit = QLineEdit()
            edit.setEchoMode(mode)
            self.addCleanup(edit.deleteLater)
            self.assertFalse(input_rules.uppercase_enabled(edit),
                             f"{mode} must keep the typed case")

    def test_03_read_only_and_disabled_fields_are_skipped(self):
        read_only = QLineEdit()
        read_only.setReadOnly(True)
        disabled = QLineEdit()
        disabled.setEnabled(False)
        self.addCleanup(read_only.deleteLater)
        self.addCleanup(disabled.deleteLater)
        self.assertFalse(input_rules.uppercase_enabled(read_only))
        self.assertFalse(input_rules.uppercase_enabled(disabled))

    def test_04_explicit_opt_out_wins(self):
        edit = QLineEdit()
        self.addCleanup(edit.deleteLater)
        input_rules.set_uppercase(edit, False)
        self.assertFalse(input_rules.uppercase_enabled(edit))

    def test_05_explicit_opt_in_overrides_a_blocking_default(self):
        """An opt-in still wins, so a site can force the rule if it must."""
        edit = QLineEdit()
        edit.setReadOnly(True)
        self.addCleanup(edit.deleteLater)
        input_rules.set_uppercase(edit, True)
        self.assertTrue(input_rules.uppercase_enabled(edit))

    def test_06_setting_back_to_none_restores_the_default(self):
        edit = QLineEdit()
        self.addCleanup(edit.deleteLater)
        input_rules.set_uppercase(edit, False)
        self.assertFalse(input_rules.uppercase_enabled(edit))
        input_rules.set_uppercase(edit, None)
        self.assertTrue(input_rules.uppercase_enabled(edit))

    def test_07_spin_box_internal_editor_is_skipped(self):
        """Numeric controls are a no-op, but they are excluded outright."""
        spin = QDoubleSpinBox()
        self.addCleanup(spin.deleteLater)
        self.assertIsNotNone(spin.lineEdit())
        self.assertFalse(input_rules.uppercase_enabled(spin.lineEdit()))

    def test_08_file_dialog_filename_box_is_skipped(self):
        """A filesystem path is case-significant and must be left alone."""
        from PySide6.QtWidgets import QFileDialog

        dialog = QFileDialog()
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        try:
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            names = dialog.findChildren(QLineEdit)
            self.assertTrue(names, "the non-native dialog should own a file-name box")
            for name in names:
                self.assertFalse(input_rules.uppercase_enabled(name),
                                 "a path box must never be upper-cased")
        finally:
            dialog.deleteLater()

    def test_09_non_editable_combo_is_not_a_text_field(self):
        combo = QComboBox()
        combo.addItems(["Cash", "Card"])
        self.addCleanup(combo.deleteLater)
        self.assertIsNone(input_rules.line_edit_for(combo))

    def test_10_editable_combo_exposes_its_line_edit(self):
        combo = QComboBox()
        combo.setEditable(True)
        self.addCleanup(combo.deleteLater)
        self.assertIs(input_rules.line_edit_for(combo), combo.lineEdit())

    def test_11_combo_opt_out_is_honoured(self):
        combo = QComboBox()
        combo.setEditable(True)
        self.addCleanup(combo.deleteLater)
        input_rules.set_uppercase(combo, False)
        self.assertFalse(input_rules.uppercase_enabled(combo.lineEdit()))


# ── 2b. The conversion: caret, selection, no loop, no rewriting ───────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class UpperCaseConversionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _hooked(self, text: str = "") -> QLineEdit:
        edit = QLineEdit()
        edit.setWindowTitle("uppercase-test")
        self.addCleanup(edit.deleteLater)
        input_rules.attach_uppercase(edit)
        if text:
            edit.setText(text)
        return edit

    def test_01_typing_lowercase_lands_upper_case(self):
        edit = self._hooked()
        QTest.keyClicks(edit, "nilesh")
        self.assertEqual(edit.text(), "NILESH")

    def test_02_typing_includes_spaces_and_digits(self):
        edit = self._hooked()
        QTest.keyClicks(edit, "bio d3 plus")
        self.assertEqual(edit.text(), "BIO D3 PLUS")

    def test_03_caret_is_preserved_when_editing_in_the_middle(self):
        edit = self._hooked("ABCD")
        edit.setCursorPosition(2)
        QTest.keyClicks(edit, "x")
        self.assertEqual(edit.text(), "ABXCD")
        self.assertEqual(edit.cursorPosition(), 3,
                         "the caret must stay right after the typed character")

    def test_04_caret_is_preserved_at_the_start(self):
        edit = self._hooked("BIO")
        edit.setCursorPosition(0)
        QTest.keyClicks(edit, "a")
        self.assertEqual(edit.text(), "ABIO")
        self.assertEqual(edit.cursorPosition(), 1)

    def test_05_typing_over_a_selection_replaces_it(self):
        edit = self._hooked("bio d3")
        edit.setSelection(0, 3)          # the leading "bio"
        QTest.keyClicks(edit, "x")
        self.assertEqual(edit.text(), "X d3")
        self.assertEqual(edit.cursorPosition(), 1)

    def test_06_typing_over_a_selection_keeps_the_caret_after_it(self):
        edit = self._hooked("ABCDEF")
        edit.setSelection(2, 2)          # "CD"
        QTest.keyClicks(edit, "z")
        self.assertEqual(edit.text(), "ABZEF")
        self.assertEqual(edit.cursorPosition(), 3)

    def test_07_no_recursion_and_no_lost_characters(self):
        """Every keystroke survives exactly once; the loop cannot run away."""
        edit = self._hooked()
        edits = []
        edit.textEdited.connect(lambda t: edits.append(t))
        changes = []
        edit.textChanged.connect(lambda t: changes.append(t))
        QTest.keyClicks(edit, "abcdef")
        self.assertEqual(edit.text(), "ABCDEF",
                         "characters must not be dropped or duplicated")
        self.assertEqual(len(changes), 6,
                         "each keystroke must produce one textChanged, not a storm")
        self.assertLessEqual(len(edits), 6)

    def test_08_programmatic_load_is_never_rewritten(self):
        """A record read from the database keeps its stored case."""
        edit = self._hooked()
        edit.setText("Cipla Ltd")
        self.assertEqual(edit.text(), "Cipla Ltd",
                         "loading a record must not change stored letter case")
        edit.insert("")                  # a no-op programmatic call
        self.assertEqual(edit.text(), "Cipla Ltd")

    def test_09_paste_is_converted(self):
        edit = self._hooked()
        edit.setFocus()
        QApplication.clipboard().setText("care pharma")
        QTest.keyClick(edit, Qt.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(edit.text(), "CARE PHARMA")

    def test_10_apply_uppercase_reports_whether_it_changed(self):
        edit = self._hooked("CIPLA")
        self.assertFalse(input_rules.apply_uppercase(edit))
        edit.setText("Cipla")
        self.assertTrue(input_rules.apply_uppercase(edit))
        self.assertEqual(edit.text(), "CIPLA")

    def test_11_undo_stays_a_single_step_per_edit(self):
        edit = self._hooked()
        QTest.keyClicks(edit, "ab")
        self.assertEqual(edit.text(), "AB")
        edit.undo()
        self.assertIn(edit.text(), ("A", ""),
                         "undo must step back through the typed text, "
                         "not replay the internal upper-casing rewrite")

    def test_12_opt_out_field_keeps_its_case(self):
        edit = self._hooked()
        input_rules.set_uppercase(edit, False)
        QTest.keyClicks(edit, "MixedCase")
        self.assertEqual(edit.text(), "MixedCase")

    def test_13_attach_is_idempotent(self):
        edit = self._hooked()
        for _ in range(3):
            self.assertTrue(input_rules.attach_uppercase(edit))
        QTest.keyClicks(edit, "ab")
        self.assertEqual(edit.text(), "AB",
                         "a double attachment would duplicate characters or "
                         "emit a second textChanged")

    def test_14_combo_line_edit_is_converted(self):
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(["Cipla", "Sun Pharma"])
        combo.lineEdit().clear()
        self.addCleanup(combo.deleteLater)
        input_rules.attach_uppercase(combo)
        QTest.keyClicks(combo.lineEdit(), "cipla")
        self.assertEqual(combo.lineEdit().text(), "CIPLA")

    def test_15_completion_still_matches_after_conversion(self):
        """Upper-casing must not cost the user their suggestions."""
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(["Cipla", "Sun Pharma", "Cipla D3"])
        combo.lineEdit().clear()
        self.addCleanup(combo.deleteLater)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        input_rules.attach_uppercase(combo)
        QTest.keyClicks(combo.lineEdit(), "cipla")
        completer = combo.completer()
        completer.setCompletionPrefix(combo.lineEdit().text())
        matches = [completer.completionModel().index(i, 0).data()
                   for i in range(completer.completionCount())]
        self.assertIn("Cipla", matches,
                      "a case-insensitive completer must still match")
        self.assertIn("Cipla D3", matches)

    def test_16_selection_helper_style_edit_can_opt_in(self):
        """ui.components.style_edit exposes the same switch."""
        from ui import components as ui

        edit = QLineEdit()
        self.addCleanup(edit.deleteLater)
        ui.style_edit(edit, upper=True)
        QTest.keyClicks(edit, "cipla")
        self.assertEqual(edit.text(), "CIPLA")

        other = QLineEdit()
        self.addCleanup(other.deleteLater)
        ui.style_edit(other, upper=False)
        QTest.keyClicks(other, "cipla")
        self.assertEqual(other.text(), "cipla")

    def test_17_pack_size_expression_keeps_its_exact_format(self):
        """``x`` in ``10x10`` is a multiplication sign, not a word letter."""
        edit = self._hooked()
        QTest.keyClicks(edit, "10x10")
        self.assertEqual(edit.text(), "10x10",
                         "typing a pack size must not rewrite it to 10X10")

    def test_18_combo_typing_produces_one_change_per_key(self):
        """The conversion happens before insertion, so nothing doubles."""
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(["Cipla", "Sun Pharma"])
        combo.lineEdit().clear()
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addCleanup(combo.deleteLater)
        input_rules.attach_uppercase(combo)
        changes = []
        combo.lineEdit().textChanged.connect(lambda t: changes.append(t))
        QTest.keyClicks(combo.lineEdit(), "cipla")
        self.assertEqual(combo.lineEdit().text(), "CIPLA")
        self.assertEqual(len(changes), 5,
                         "each key must produce exactly one textChanged")


# ── 3. Application-wide installer ─────────────────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class UpperCaseInstallerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_01_installer_is_idempotent_and_returns_the_watcher(self):
        first = input_rules.install_uppercase_input(self.app)
        second = input_rules.install_uppercase_input(self.app)
        self.assertIsNotNone(first)
        self.assertIs(first, second,
                      "a second install must reuse the watcher, not stack filters")

    def test_02_a_field_created_later_is_caught_when_it_is_shown(self):
        input_rules.install_uppercase_input(self.app)
        window = QWidget()
        self.addCleanup(window.deleteLater)
        layout = QVBoxLayout(window)
        edit = QLineEdit()
        layout.addWidget(edit)
        window.show()
        self.app.processEvents()
        QTest.keyClicks(edit, "nilesh")
        self.assertEqual(edit.text(), "NILESH",
                         "the app-wide watcher must hook fields created after start-up")

    def test_03_a_field_that_already_existed_is_caught_by_the_sweep(self):
        window = QWidget()
        self.addCleanup(window.deleteLater)
        layout = QVBoxLayout(window)
        edit = QLineEdit()
        layout.addWidget(edit)
        window.show()
        self.app.processEvents()
        # Sweep as the installer does at start-up.
        input_rules.sweep_uppercase_input(self.app)
        QTest.keyClicks(edit, "care")
        self.assertEqual(edit.text(), "CARE")

    def test_04_a_password_field_in_a_live_window_is_left_alone(self):
        input_rules.install_uppercase_input(self.app)
        window = QWidget()
        self.addCleanup(window.deleteLater)
        layout = QVBoxLayout(window)
        secret = QLineEdit()
        secret.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(secret)
        window.show()
        self.app.processEvents()
        QTest.keyClicks(secret, "Secret123")
        self.assertEqual(secret.text(), "Secret123")

    def test_05_main_entry_installs_the_watcher(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "main.py"), "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("install_uppercase_input", source,
                      "the application entry point must install the watcher "
                      "so every screen is covered")


# ── 4. The real screens' own fields ───────────────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class RealScreenUpperCaseTests(unittest.TestCase):
    """End-to-end checks on genuine application fields."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        input_rules.install_uppercase_input(cls.app)

    def test_01_company_master_name_field_is_converted(self):
        from screens.company_master import _CompanyDialog

        dialog = _CompanyDialog()
        try:
            dialog.show()
            self.app.processEvents()
            QTest.keyClicks(dialog._name_edit, "care pharma")
            self.assertEqual(dialog._name_edit.text(), "CARE PHARMA")
            QTest.keyClicks(dialog._short_edit, "cp")
            self.assertEqual(dialog._short_edit.text(), "CP")
        finally:
            dialog.deleteLater()

    def test_02_searchable_filter_edit_is_converted(self):
        from ui.searchable_filter import SearchableFilterEdit

        field = SearchableFilterEdit("Patient")
        try:
            field.show()
            self.app.processEvents()
            QTest.keyClicks(field, "nilesh")
            self.assertEqual(field.text(), "NILESH")
            self.assertIsNone(field.selected_id,
                              "typing must never leave a stale record id behind")
        finally:
            field.deleteLater()

    def test_03_login_password_field_keeps_its_case(self):
        """The authentication secret is never touched."""
        from screens.login import LoginDialog

        dialog = LoginDialog()
        try:
            dialog.show()
            self.app.processEvents()
            QTest.keyClicks(dialog._password, "MixedCase1")
            self.assertEqual(dialog._password.text(), "MixedCase1")
        finally:
            dialog.deleteLater()

    def test_04_login_username_is_not_uppercased(self):
        """The account identifier is an authentication name, not business data."""
        from screens.login import LoginDialog

        dialog = LoginDialog()
        try:
            dialog.show()
            self.app.processEvents()
            QTest.keyClicks(dialog._username, "admin")
            self.assertEqual(dialog._username.text(), "admin")
        finally:
            dialog.deleteLater()

    def test_05_user_master_username_is_not_uppercased(self):
        from screens.user_management import _CreateUserDialog

        dialog = _CreateUserDialog()
        try:
            dialog.show()
            self.app.processEvents()
            QTest.keyClicks(dialog.username, "savan")
            self.assertEqual(dialog.username.text(), "savan")
            QTest.keyClicks(dialog.password, "pw")
            self.assertEqual(dialog.password.text(), "pw")
        finally:
            dialog.deleteLater()

    def test_06_company_master_dialog_spacing_layout_is_intact(self):
        """The conversion must not disturb the form the dialog builds."""
        from screens.company_master import _CompanyDialog

        dialog = _CompanyDialog()
        try:
            self.assertIsInstance(dialog, QDialog)
            self.assertGreaterEqual(dialog.minimumWidth(), 300)
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
