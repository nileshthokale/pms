"""Item Master New/Edit dialog — drug selector and Category removal.

Two changes are covered here:

* the dialog's drug selector is compact, searchable and keyboard friendly
  instead of a 137-entry dropdown tall enough to cover the dialog, and
* Category is gone from the New/Edit Item dialog, while the stored
  ``items.category_id`` of an existing item survives an unrelated edit
  untouched (``ItemDAO.update`` always writes that column, so the dialog
  has to carry the stored value through).

Data safety: every test runs against a disposable temporary database.
``data/pharmacy.db`` is never opened, and no drug row is ever renamed,
merged, deleted or re-imported — the selector is a presentation layer over
``DrugDAO.get_all()``.
"""

import os
import re
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HAS_PYSIDE6 = False
_PYSIDE_SKIP_REASON = "PySide6 not available"
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    pass


DRUGS = (
    "AMOXICILLIN",
    "ATORVASTATIN",
    "AZITHROMYCIN",
    "CETIRIZINE",
    "CIPROFLOXACIN",
    "DICLOFENAC",
    "ESOMEPRAZOLE MAG TRIHY & RELEASE NAPROXEN TAB",
    "GABAPENTIN",
    "IBUPROFEN",
    "LOSARTAN",
    "METFORMIN",
    "OMEPRAZOLE",
    "PARACETAMOL",
    "PARACETAMOL & TRAMADOL",
)

_APP = None


def _ensure_app():
    """One QApplication for the whole module."""
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def _fresh_db(tag: str) -> str:
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_itemdialog_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            os.remove(stale)
    os.environ["PHARMACY_DB"] = db_path
    return db_path


class _DBBase(unittest.TestCase):
    """Disposable database plus the small drug master the tests rely on."""

    @classmethod
    def setUpClass(cls):
        cls._app = _ensure_app()
        cls.db_path = _fresh_db(cls.__name__)
        from database import auth
        from database.connection import init_database

        init_database()
        auth.ensure_auth_schema()

    def setUp(self):
        from database.connection import get_connection

        conn = get_connection()
        for table in ("item_ingredients", "items", "drugs", "units",
                      "companies", "categories"):
            conn.execute(f'DELETE FROM "{table}"')
        conn.commit()
        conn.close()

        from database.drug_dao import DrugDAO

        self.drug_ids = {name: DrugDAO.insert(name) for name in DRUGS}

    # -- helpers ------------------------------------------------------

    def _all_drugs(self) -> list[dict]:
        from database.drug_dao import DrugDAO

        return DrugDAO.get_all()

    def _combo(self):
        from screens.item_master import _DrugComboBox

        combo = _DrugComboBox(self._all_drugs())
        self.addCleanup(combo.deleteLater)
        return combo

    def _dialog(self, item=None):
        from screens.item_master import _ItemDialog

        dialog = _ItemDialog(item=item)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _completions(self, combo) -> list[str]:
        model = combo.completer().completionModel()
        return [model.index(row, 0).data() for row in range(model.rowCount())]

    def _assert_no_category_control(self, dialog):
        self.assertFalse(
            hasattr(dialog, "_category_combo"),
            "the dialog must not keep a Category combo box",
        )
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        offenders = [text for text in labels if "categor" in text.lower()]
        self.assertEqual(
            offenders, [], f"Category label still shown in the dialog: {offenders}"
        )


class DrugSelectorTests(_DBBase):
    """A. popup height, B. type-to-search, C. keyboard, D. mouse, E. width."""

    def test_a_popup_is_capped_to_a_compact_list(self):
        from screens.item_master import _DRUG_POPUP_MAX_ROWS

        combo = self._combo()
        self.assertEqual(_DRUG_POPUP_MAX_ROWS, 12)
        # Both popups the selector can open — its own and the completer's —
        # obey the cap, so neither can open the old full-height list.
        self.assertEqual(combo.maxVisibleItems(), _DRUG_POPUP_MAX_ROWS)
        self.assertEqual(combo.completer().maxVisibleItems(), _DRUG_POPUP_MAX_ROWS)
        self.assertLess(
            _DRUG_POPUP_MAX_ROWS,
            len(self._all_drugs()),
            "the cap must actually bite for a drug master this size",
        )
        row_height = combo.completer().popup().sizeHintForRow(0)
        if row_height > 0:
            self.assertLessEqual(row_height * _DRUG_POPUP_MAX_ROWS, 340)

    def test_b_typing_filters_the_drug_list(self):
        combo = self._combo()
        combo.lineEdit().textEdited.emit("PARACET")
        self._app.processEvents()

        shown = self._completions(combo)
        self.assertTrue(shown, "typing PARACET must still offer matches")
        self.assertLess(len(shown), len(self._all_drugs()))
        for name in shown:
            self.assertIn("PARACET", name.upper())

    def test_b2_filtering_ignores_case(self):
        combo = self._combo()
        combo.lineEdit().textEdited.emit("PARACET")
        self._app.processEvents()
        upper = self._completions(combo)

        combo.lineEdit().textEdited.emit("paracet")
        self._app.processEvents()
        self.assertEqual(self._completions(combo), upper)

    def test_b3_filtering_matches_inside_a_name_not_only_the_start(self):
        combo = self._combo()
        combo.lineEdit().textEdited.emit("TRAMADOL")
        self._app.processEvents()
        self.assertIn(
            "PARACETAMOL & TRAMADOL",
            self._completions(combo),
            "a drug whose match is not at the start must still be offered",
        )

    def test_c_keyboard_selects_the_filtered_drug(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        combo = dialog._ingredient_rows[0].drug_combo

        combo.show()
        combo.setFocus()
        QTest.keyClicks(combo.lineEdit(), "PARACET")
        self._app.processEvents()
        QTest.keyClick(combo.lineEdit(), Qt.Key.Key_Down)
        QTest.keyClick(combo.lineEdit(), Qt.Key.Key_Return)
        self._app.processEvents()

        self.assertIsNotNone(combo.drug_id(), "Enter must commit a drug")
        self.assertIn("PARACET", combo.chosen_name().upper())
        # The chosen drug stays on screen after the popup closes.
        self.assertEqual(combo.currentText(), combo.chosen_name())

    def test_c2_typing_a_full_drug_name_commits_it(self):
        """Enter on an exactly-typed name selects it, popup or no popup."""
        dialog = self._dialog()
        dialog._add_ingredient_row()
        combo = dialog._ingredient_rows[0].drug_combo

        combo.show()
        combo.setFocus()
        QTest.keyClicks(combo.lineEdit(), "CETIRIZINE")
        QTest.keyClick(combo.lineEdit(), Qt.Key.Key_Return)
        self._app.processEvents()
        combo.lineEdit().editingFinished.emit()
        self._app.processEvents()

        self.assertEqual(combo.drug_id(), self.drug_ids["CETIRIZINE"])
        self.assertEqual(combo.chosen_name(), "CETIRIZINE")

    def test_c3_typed_rubbish_leaves_no_selection(self):
        """A half-typed name must never masquerade as a chosen drug."""
        dialog = self._dialog()
        dialog._add_ingredient_row()
        combo = dialog._ingredient_rows[0].drug_combo

        combo.lineEdit().textEdited.emit("ZZZNOTADRUG")
        combo.lineEdit().editingFinished.emit()
        self._app.processEvents()

        self.assertIsNone(combo.drug_id())
        self.assertEqual(combo.chosen_name(), "")

    def test_d_mouse_selects_a_drug_from_the_popup(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        combo = dialog._ingredient_rows[0].drug_combo

        combo.lineEdit().textEdited.emit("CETIRIZINE")
        self._app.processEvents()
        popup = combo.completer().popup()
        target = popup.model().index(0, 0)
        popup.setCurrentIndex(target)
        QTest.mouseClick(
            popup.viewport(), Qt.MouseButton.LeftButton,
            pos=popup.visualRect(target).center(),
        )
        self._app.processEvents()

        self.assertEqual(combo.drug_id(), self.drug_ids["CETIRIZINE"])

    def test_e_popup_fits_the_longest_drug_name(self):
        from screens.item_master import _DRUG_POPUP_MAX_WIDTH

        drugs = self._all_drugs()
        longest = max(drugs, key=lambda d: len(d["drug_name"]))["drug_name"]
        combo = self._combo()

        needed = combo.fontMetrics().horizontalAdvance(longest)
        width = combo.completer().popup().minimumWidth()
        self.assertGreaterEqual(
            width, needed, "a long drug name must not be cut off"
        )
        self.assertLessEqual(
            width, _DRUG_POPUP_MAX_WIDTH, "the popup must not span the screen"
        )

    def test_f_escape_keeps_the_chosen_drug(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        combo = dialog._ingredient_rows[0].drug_combo
        combo.select_drug(self.drug_ids["IBUPROFEN"])

        combo.lineEdit().textEdited.emit("AMOX")
        self._app.processEvents()
        QTest.keyClick(combo.lineEdit(), Qt.Key.Key_Escape)
        self._app.processEvents()
        combo.lineEdit().editingFinished.emit()
        self._app.processEvents()

        # A half-typed name must never leave a bogus selection behind.
        self.assertIn(combo.drug_id(), (None, self.drug_ids["IBUPROFEN"]))


class DuplicateDrugTests(_DBBase):
    """H. One drug can only be added to an item once."""

    def test_a_taken_drug_disappears_from_the_other_rows(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        dialog._add_ingredient_row()
        first, second = dialog._ingredient_rows

        first.drug_combo.select_drug(self.drug_ids["AMOXICILLIN"])
        first.drug_changed.emit()  # what a real pick emits
        self._app.processEvents()

        offered = [
            second.drug_combo.itemData(i) for i in range(second.drug_combo.count())
        ]
        self.assertNotIn(self.drug_ids["AMOXICILLIN"], offered)
        self.assertIn(self.drug_ids["CETIRIZINE"], offered)

    def test_releasing_a_drug_offers_it_again(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        dialog._add_ingredient_row()
        first, second = dialog._ingredient_rows
        amox = self.drug_ids["AMOXICILLIN"]

        first.drug_combo.select_drug(amox)
        first.drug_changed.emit()
        self._app.processEvents()
        second.drug_combo.select_drug(self.drug_ids["IBUPROFEN"])

        first.drug_combo.select_drug(None)
        first.drug_changed.emit()
        self._app.processEvents()

        offered = [
            second.drug_combo.itemData(i) for i in range(second.drug_combo.count())
        ]
        self.assertIn(amox, offered)

    def test_stored_duplicate_ingredients_survive_an_unrelated_edit(self):
        """The database permits a stored duplicate; an edit must not drop it."""
        from database.item_dao import ItemDAO

        amox = self.drug_ids["AMOXICILLIN"]
        item_id = ItemDAO.insert(item_name="Stored Duplicate")
        ItemDAO.save_ingredients(item_id, [
            {"drug_id": amox, "power": "1g"},
            {"drug_id": amox, "power": "2g"},
        ])

        dialog = self._dialog(item=ItemDAO.get_by_id(item_id))
        dialog._on_save()

        self.assertTrue(dialog.was_saved)
        stored = ItemDAO.get_ingredients(item_id)
        self.assertEqual(len(stored), 2)
        self.assertEqual([row["power"] for row in stored], ["1g", "2g"])


class IngredientPersistenceTests(_DBBase):
    """F. multiple drugs, G. Power, and the drug links themselves."""

    def test_multiple_drugs_and_power_round_trip(self):
        from database.item_dao import ItemDAO

        dialog = self._dialog()
        dialog._item_name_edit.setText("Multi Drug Item")
        dialog._add_ingredient_row()
        dialog._add_ingredient_row()
        first, second = dialog._ingredient_rows

        first.drug_combo.select_drug(self.drug_ids["AMOXICILLIN"])
        first.power_edit.setText("500mg")
        second.drug_combo.select_drug(self.drug_ids["CETIRIZINE"])
        second.power_edit.setText("10mg")
        dialog._on_save()

        self.assertTrue(dialog.was_saved)
        item_id = ItemDAO.search("Multi Drug Item")[0]["id"]
        stored = ItemDAO.get_ingredients(item_id)
        self.assertEqual(
            [(row["drug_name"], row["power"]) for row in stored],
            [("AMOXICILLIN", "500mg"), ("CETIRIZINE", "10mg")],
        )

    def test_adding_a_row_does_not_disturb_the_existing_one(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        first = dialog._ingredient_rows[0]
        first.drug_combo.select_drug(self.drug_ids["IBUPROFEN"])
        first.power_edit.setText("400mg")

        dialog._add_ingredient_row()
        self.assertEqual(first.drug_combo.drug_id(), self.drug_ids["IBUPROFEN"])
        self.assertEqual(first.power_edit.text(), "400mg")
        self.assertEqual(len(dialog._ingredient_rows), 2)

    def test_removing_a_row_keeps_the_rest(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        dialog._add_ingredient_row()
        first, second = dialog._ingredient_rows
        first.drug_combo.select_drug(self.drug_ids["AMOXICILLIN"])
        second.drug_combo.select_drug(self.drug_ids["IBUPROFEN"])

        dialog._remove_ingredient_row(first)

        self.assertEqual(len(dialog._ingredient_rows), 1)
        self.assertEqual(
            dialog._ingredient_rows[0].drug_combo.drug_id(),
            self.drug_ids["IBUPROFEN"],
        )


class IngredientRemoveButtonTests(_DBBase):
    """K. the red ✕ beside an ingredient row must actually show a ✕.

    Regression guard: the button is a 30 px square, but the application
    stylesheet gives *every* ``QPushButton`` ``padding: 6px 14px``.  The old
    caption-based button therefore had a zero-width contents rect, so it
    rendered as a plain red square with an invisible "X".  These assertions
    read the rendered pixels rather than the stylesheet alone, so a caption
    that does not fit cannot quietly come back.
    """

    TOOLTIP = "Remove ingredient"

    def _row(self, dialog):
        dialog._add_ingredient_row()
        return dialog._ingredient_rows[-1]

    def _click(self, button):
        """Click a row button the way a user would.

        ``QAbstractButton.click()`` emits exactly the pressed/released/clicked
        sequence a real mouse click does, and is used here on purpose:
        ``QTest.mouseClick`` routes the event through the widget's *window*,
        and these dialogs are deliberately never shown, so the synthetic
        event would have no window to be delivered to.
        """
        button.click()
        self._app.processEvents()

    @staticmethod
    def _ink(button):
        """Grab the button and return (image, [(x, y)] of glyph pixels).

        The fill is ``#c0392b`` (green 57, blue 43); the glyph is white, so
        "green and blue both bright" isolates the drawn ✕ from the red.
        """
        button.clearFocus()  # a focus ring would add non-glyph ink
        image = button.grab().toImage()
        ink = []
        for y in range(image.height()):
            for x in range(image.width()):
                colour = image.pixelColor(x, y)
                if colour.green() > 130 and colour.blue() > 130 and colour.red() > 150:
                    ink.append((x, y))
        return image, ink

    # -- the rendered control -----------------------------------------

    def test_a_the_button_is_a_compact_square(self):
        btn = self._row(self._dialog()).delete_btn
        self.assertEqual(btn.width(), btn.height(), "the control must be square")
        self.assertGreaterEqual(btn.width(), 28)
        self.assertLessEqual(btn.width(), 32)

    def test_b_the_button_renders_a_visible_cross(self):
        btn = self._row(self._dialog()).delete_btn
        self.assertFalse(btn.icon().isNull(),
                         "the remove button must carry a real icon")
        image, ink = self._ink(btn)
        self.assertGreaterEqual(
            len(ink), 25, "the remove button drew no visible ✕ symbol")

        xs = [x for x, _ in ink]
        ys = [y for _, y in ink]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        span_x, span_y = x1 - x0, y1 - y0
        self.assertGreater(span_x, 6, "the symbol is too small to read")
        self.assertGreater(span_y, 6, "the symbol is too small to read")

        # Every corner of the ink box is drawn, so the two strokes cross:
        # that is what makes it an X rather than a dash or a blob.
        tol = max(2, min(span_x, span_y) // 4)

        def inked_near(px, py):
            return any(abs(x - px) <= tol and abs(y - py) <= tol for x, y in ink)

        for px, py, corner in ((x0, y0, "top-left"), (x1, y1, "bottom-right"),
                               (x1, y0, "top-right"), (x0, y1, "bottom-left")):
            self.assertTrue(inked_near(px, py),
                            f"the ✕ is missing its {corner} arm")

        # ...and it is a drawn glyph, not a filled block.
        box = (span_x + 1) * (span_y + 1)
        self.assertLess(len(ink), 0.8 * box,
                        "the button looks filled rather than drawn")

        # ...centred in the button, not shoved into a corner by padding.
        self.assertLessEqual(abs((x0 + x1) / 2 - (image.width() - 1) / 2), 2,
                             "the ✕ is not horizontally centred")
        self.assertLessEqual(abs((y0 + y1) / 2 - (image.height() - 1) / 2), 2,
                             "the ✕ is not vertically centred")

    def test_c_the_button_is_labelled_and_hinted(self):
        btn = self._row(self._dialog()).delete_btn
        self.assertEqual(btn.toolTip(), self.TOOLTIP)
        self.assertEqual(btn.accessibleName(), self.TOOLTIP)

    def test_d_no_caption_padding_can_eat_the_square(self):
        """The global ``padding: 6px 14px`` must not squeeze the glyph out."""
        btn = self._row(self._dialog()).delete_btn
        style = btn.styleSheet()
        self.assertRegex(style, r"padding:\s*0px",
                         "the button must pin its own padding")
        self.assertRegex(style, r"margin:\s*0px",
                         "the button must pin its own margin")

    # -- the visual states --------------------------------------------

    @staticmethod
    def _background(style, state):
        match = re.search(
            r"QPushButton" + state
            + r"\s*\{[^}]*background-color:\s*(#[0-9a-fA-F]{6})",
            style,
        )
        return None if match is None else QColor(match.group(1))

    def test_e_hover_and_press_darken_the_red(self):
        btn = self._row(self._dialog()).delete_btn
        style = btn.styleSheet()

        resting = self._background(style, "")
        hover = self._background(style, ":hover")
        pressed = self._background(style, ":pressed")
        for name, colour in (("resting", resting), ("hover", hover),
                             ("pressed", pressed)):
            self.assertIsNotNone(colour, f"no {name} background declared")

        def luminance(colour):
            return 0.299 * colour.red() + 0.587 * colour.green() + 0.114 * colour.blue()

        self.assertLess(luminance(hover), luminance(resting),
                        "hover must be a *darker* red, not a lighter one")
        self.assertLessEqual(luminance(pressed), luminance(hover),
                             "pressed must be at least as dark as hover")
        self.assertNotEqual(
            hover.name(), "#d32f2f",
            "the old lighter hover red was a state change in the wrong direction")

    def test_f_the_button_can_be_reached_and_shows_focus(self):
        btn = self._row(self._dialog()).delete_btn
        style = btn.styleSheet()
        self.assertNotEqual(btn.focusPolicy(), Qt.NoFocus,
                            "the remove button must be reachable by Tab")
        self.assertTrue(btn.isEnabled(), "the remove button must be clickable")
        self.assertRegex(style, r"QPushButton:focus\s*\{[^}]*border:",
                         "the focused button must be visibly outlined")
        # The dialog behind the button is white, so a white ring on its own is
        # all but invisible: the fill has to change as well.
        focus = self._background(style, ":focus")
        resting = self._background(style, "")
        self.assertIsNotNone(focus, "no focus background declared")
        self.assertNotEqual(focus.name(), resting.name(),
                            "focus must change more than a white-on-white ring")

    # -- behaviour -----------------------------------------------------

    def test_g_clicking_the_button_removes_only_its_own_row(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        dialog._add_ingredient_row()
        first, second = dialog._ingredient_rows
        first.drug_combo.select_drug(self.drug_ids["AMOXICILLIN"])
        first.power_edit.setText("500mg")
        second.drug_combo.select_drug(self.drug_ids["IBUPROFEN"])

        self._click(second.delete_btn)

        self.assertEqual(dialog._ingredient_rows, [first])
        self.assertEqual(first.drug_combo.drug_id(), self.drug_ids["AMOXICILLIN"])
        self.assertEqual(first.power_edit.text(), "500mg")

    def test_h_removing_a_row_offers_its_drug_to_the_other_rows_again(self):
        dialog = self._dialog()
        dialog._add_ingredient_row()
        dialog._add_ingredient_row()
        first, second = dialog._ingredient_rows
        amox = self.drug_ids["AMOXICILLIN"]

        first.drug_combo.select_drug(amox)
        first.drug_changed.emit()
        self._app.processEvents()

        def offered():
            return [second.drug_combo.itemData(i)
                    for i in range(second.drug_combo.count())]

        self.assertNotIn(amox, offered(), "a taken drug must be hidden")

        self._click(first.delete_btn)

        self.assertEqual(dialog._ingredient_rows, [second])
        self.assertIn(amox, offered(), "the released drug must be offered again")

    def test_i_three_rows_survive_removing_the_middle_one(self):
        dialog = self._dialog()
        for _ in range(3):
            dialog._add_ingredient_row()
        first, middle, last = dialog._ingredient_rows
        first.drug_combo.select_drug(self.drug_ids["AMOXICILLIN"])
        first.power_edit.setText("500mg")
        middle.drug_combo.select_drug(self.drug_ids["CETIRIZINE"])
        middle.power_edit.setText("10mg")
        last.drug_combo.select_drug(self.drug_ids["IBUPROFEN"])
        last.power_edit.setText("400mg")

        self._click(middle.delete_btn)

        self.assertEqual(dialog._ingredient_rows, [first, last])
        self.assertEqual(
            [(r.drug_combo.chosen_name(), r.power_edit.text())
             for r in dialog._ingredient_rows],
            [("AMOXICILLIN", "500mg"), ("IBUPROFEN", "400mg")])

    def test_j_editing_an_item_removes_only_the_clicked_ingredient(self):
        from database.item_dao import ItemDAO

        item_id = ItemDAO.insert(item_name="Two Ingredients")
        ItemDAO.save_ingredients(item_id, [
            {"drug_id": self.drug_ids["AMOXICILLIN"], "power": "500mg"},
            {"drug_id": self.drug_ids["CETIRIZINE"], "power": "10mg"},
        ])

        dialog = self._dialog(item=ItemDAO.get_by_id(item_id))
        self.assertEqual(len(dialog._ingredient_rows), 2,
                         "both stored ingredients must load")

        self._click(dialog._ingredient_rows[1].delete_btn)
        dialog._on_save()

        self.assertTrue(dialog.was_saved)
        self.assertEqual(
            [(row["drug_name"], row["power"])
             for row in ItemDAO.get_ingredients(item_id)],
            [("AMOXICILLIN", "500mg")])


class CategoryRemovedTests(_DBBase):
    """H/I. no Category control, J. stored data unchanged."""

    def test_a_new_item_dialog_has_no_category_control(self):
        self._assert_no_category_control(self._dialog())

    def test_b_edit_item_dialog_has_no_category_control(self):
        from database.item_dao import ItemDAO

        item_id = ItemDAO.insert(item_name="Plain Item")
        self._assert_no_category_control(
            self._dialog(item=ItemDAO.get_by_id(item_id))
        )

    def test_c_editing_an_item_keeps_its_stored_category(self):
        """The regression this guards: update() always writes category_id."""
        from database.category_dao import CategoryDAO
        from database.item_dao import ItemDAO

        category_id = CategoryDAO.create_category("Kept Category")
        item_id = ItemDAO.insert(
            item_name="Categorised Item",
            tax_structure="6",
            legacy_tax_id=6,
            category_id=category_id,
            pack_size="10x10",
            pathy="ALLOPATHIC MEDICINES",
        )
        ItemDAO.save_ingredients(item_id, [
            {"drug_id": self.drug_ids["AMOXICILLIN"], "power": "500mg"},
        ])
        before = ItemDAO.get_by_id(item_id)

        dialog = self._dialog(item=before)
        dialog._on_save()

        self.assertTrue(dialog.was_saved)
        after = ItemDAO.get_by_id(item_id)
        self.assertEqual(after["category_id"], category_id)
        for field in ("item_name", "unit_id", "company_id", "pack_size",
                      "tax_structure", "discount", "mrp", "rate",
                      "reorder_stock_level", "scheduled", "location", "pathy",
                      "dpco", "legacy_tax_id"):
            self.assertEqual(after[field], before[field], f"{field} changed")
        self.assertEqual(
            [(row["drug_name"], row["power"])
             for row in ItemDAO.get_ingredients(item_id)],
            [("AMOXICILLIN", "500mg")],
        )

    def test_d_a_new_item_is_stored_without_a_category(self):
        from database.item_dao import ItemDAO

        dialog = self._dialog()
        dialog._item_name_edit.setText("Fresh Item")
        dialog._on_save()

        self.assertTrue(dialog.was_saved)
        self.assertIsNone(ItemDAO.search("Fresh Item")[0]["category_id"])

    def test_e_category_master_still_works_for_other_screens(self):
        """Item Master dropped Category; the table and DAO stay usable."""
        from database.category_dao import CategoryDAO

        category_id = CategoryDAO.create_category("Untouched Category")
        self.assertEqual(
            CategoryDAO.get_category(category_id)["category_name"],
            "Untouched Category",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
