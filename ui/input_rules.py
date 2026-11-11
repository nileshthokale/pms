"""Automatic UPPERCASE conversion for business-data text inputs.

Why this module exists
----------------------
Pharmacy data is entered the same way it is printed on a bill: an item, a
company, a supplier, a patient or a batch number is a business identifier,
and the shop standard is that those identifiers are stored and shown in
capitals.  Rather than pushing the same ``text().upper()`` through the 200-odd
text fields in 37 screens — where one forgotten line is an inconsistency
nobody notices until a report groups "Cipla" and "CIPLA" separately — the rule
lives here once and is applied by the application at start-up.

How it works
------------
* :func:`attach_uppercase` hooks ONE ``QLineEdit`` with a small event filter
  that rewrites lower-case **key text before Qt inserts it**.  The user's
  single keystroke therefore produces exactly one ``textChanged``, one undo
  step and a natural caret/selection result: there is no second rewrite of
  the whole field to replay or to fight with selection replacement.  Paste
  (Ctrl+V) is converted from the clipboard and inserted the same way.
  Drag-and-drop and IME edits are converted just after the edit completes.

* There is deliberately **no** value-watching hook on ``textEdited`` /
  ``textChanged``.  ``QLineEdit.setText()``, ``QComboBox.setEditText()`` and
  a programmatic ``insert("")`` therefore never rewrite a record loaded from
  the database.

* :func:`apply_uppercase` remains the explicit, whole-text conversion used by
  the fallback.  It preserves caret and selection.

* :func:`install_uppercase_input` attaches the hook application-wide: a
  ``QApplication`` event filter watches every widget as it is shown or
  focused, and an initial sweep covers whatever already existed.  A screen
  therefore does not have to remember to opt in.

* Editable ``QComboBox`` fields also get a case-insensitive completer, so
  upper-casing the typed prefix never costs the operator their suggestions.

What is deliberately NOT converted
----------------------------------
Upper-casing only affects letters — digits, ``.``, ``-``, ``/`` and spaces are
unchanged — so quantity, rate, discount and currency fields need no special
handling: converting them is a no-op.  The fields that genuinely must keep
their exact case are excluded by :func:`uppercase_enabled`:

* password / secret fields (``echoMode() != QLineEdit.Normal``),
* read-only and disabled fields (they cannot be typed into at all),
* anything inside a ``QFileDialog`` (a filesystem path),
* anything inside a ``QAbstractSpinBox`` (its internal editor is numeric),
* any widget explicitly opted out with ``set_uppercase(widget, False)``.

A screen with a genuinely case-significant field opts out once::

    from ui.input_rules import set_uppercase
    set_uppercase(self._technical_field, False)
"""

from __future__ import annotations

import ctypes
import re
import sys

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)

#: Widget property naming the per-widget override.  ``True`` forces the
#: conversion, ``False`` opts the widget out, and an unset property means
#: "follow the default policy in :func:`uppercase_enabled`".
UPPERCASE_PROPERTY = "upper_case"

#: Widget property recording that the ``textEdited`` hook is already attached,
#: so a widget that is shown many times is never connected twice.
_ATTACHED_PROPERTY = "_uppercase_attached"

#: Guard property preventing any re-entrant conversion of the same widget.
_BUSY_PROPERTY = "_uppercase_busy"

#: Application-wide default.  Business-data entry is the normal case, so a
#: field is converted unless something excludes it.  A deployment that wants
#: the conversion only where a field explicitly asks for it can flip this.
DEFAULT_UPPERCASE = True


# ── Windows Caps Lock Synchronization ──────────────────────────────────

def is_caps_lock_on() -> bool:
    """Return True if Windows Caps Lock is currently ON."""
    if sys.platform != "win32":
        return True
    try:
        user32 = ctypes.windll.user32
        return bool(user32.GetKeyState(0x14) & 1)
    except Exception:
        return True


def ensure_caps_lock_on() -> bool:
    """Ensure Windows Caps Lock is turned ON when working in the software.

    If Caps Lock is currently OFF on Windows, enables it both in the
    application thread's virtual keyboard state and system-wide on the
    keyboard. Returns True if Caps Lock is ON.
    """
    if sys.platform != "win32":
        return True
    try:
        user32 = ctypes.windll.user32
        VK_CAPITAL = 0x14

        # 1. Update the application thread's keyboard state table
        buf = (ctypes.c_byte * 256)()
        if user32.GetKeyboardState(buf):
            if not (buf[VK_CAPITAL] & 1):
                buf[VK_CAPITAL] |= 1
                user32.SetKeyboardState(buf)

        # 2. Simulate Caps Lock toggle key event if system state is OFF
        if not (user32.GetKeyState(VK_CAPITAL) & 1):
            scan = user32.MapVirtualKeyW(VK_CAPITAL, 0) or 0x3A
            KEYEVENTF_KEYUP = 0x2
            user32.keybd_event(VK_CAPITAL, scan, 0, 0)
            user32.keybd_event(VK_CAPITAL, scan, KEYEVENTF_KEYUP, 0)

        return bool(user32.GetKeyState(VK_CAPITAL) & 1)
    except Exception:
        return True


# ── Pure text logic ───────────────────────────────────────────────────

#: A complete pack-size expression such as ``10x10``, ``10*10`` or ``1X10``.
#: The ``x``/``X``/``*`` is a multiplication sign, not a word letter, so the
#: string is formatting-sensitive and must keep the case the operator typed.
_PACK_EXPRESSION = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*[*xX]\s*\d+(?:\.\d+)?\s*$"
)

#: The same expression while it is still being typed (e.g. ``10x`` after the
#: operator has typed the multiplication sign but no second factor yet).
_PACK_EXPRESSION_PARTIAL = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*[*xX]\s*\d*\s*$"
)


def coerce_upper(text: str) -> str:
    """Return ``text`` upper-cased, except for formatting-sensitive values.

    Pack sizes such as ``10x10`` use ``x`` as a multiplication sign; changing
    it to ``10X10`` would alter a stored/printed pack format, so those exact
    expressions are returned unchanged.  Everything else follows
    ``str.upper()``.

    Kept as a separate function so the rule is unit-testable on its own and
    so callers can reuse the exact same conversion (e.g. to upper-case a
    value loaded into a dialog before it is shown).
    """
    if not text:
        return text
    if _PACK_EXPRESSION.match(text):
        return text
    return text.upper()


def needs_conversion(text: str) -> bool:
    """True when :func:`coerce_upper` would change ``text``."""
    return bool(text) and coerce_upper(text) != text


# ── Policy ────────────────────────────────────────────────────────────

def _ancestor_blocks(widget) -> bool:
    """True when an ancestor makes the field case-significant or non-text.

    A ``QFileDialog``'s file-name box is a filesystem path and a spin box's
    internal editor is a number: neither may be rewritten, and neither can be
    recognised from the widget itself — only from where it lives.
    """
    node = widget
    for _ in range(64):
        if node is None:
            return False
        if isinstance(node, (QFileDialog, QAbstractSpinBox)):
            return True
        try:
            node = node.parent()
        except Exception:
            return False
    return False


def _explicit_override(widget) -> bool | None:
    """The nearest explicit ``upper_case`` property, or None when unset.

    An editable ``QComboBox`` owns its text through the inner ``QLineEdit``,
    so the marker is usually set on the combo; the widget's own property wins
    over its parent's.
    """
    node = widget
    for _ in range(4):
        if node is None:
            return None
        try:
            state = node.property(UPPERCASE_PROPERTY)
        except Exception:
            state = None
        if state is not None:
            return bool(state)
        try:
            node = node.parent()
        except Exception:
            return None
    return None


def editable_text_widget_for(widget):
    """The editable text widget (QLineEdit, QTextEdit, QPlainTextEdit) or None."""
    if widget is None:
        return None
    if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
        return widget
    if isinstance(widget, QComboBox):
        try:
            if widget.isEditable():
                return widget.lineEdit()
        except Exception:
            return None
    return None


def line_edit_for(widget):
    """The editable text widget a typeable widget edits, or None.

    Handles a plain ``QLineEdit``, ``QTextEdit``, ``QPlainTextEdit`` and the inner
    editor of an editable ``QComboBox``; a non-editable combo has no text field and is skipped.
    """
    return editable_text_widget_for(widget)


def uppercase_enabled(widget) -> bool:
    """Resolve the policy for one text widget at the moment of an edit.

    The decision is deliberately dynamic — echo mode, read-only state and the
    override property are all re-read on every keystroke — so a screen may
    make a field read-only or opt it out at any time and the behaviour follows
    without re-attaching anything.
    """
    if widget is None:
        return False
    override = _explicit_override(widget)
    if override is not None:
        return override
    if isinstance(widget, QLineEdit):
        try:
            if widget.echoMode() != QLineEdit.EchoMode.Normal:
                return False
        except Exception:
            return False
        try:
            if widget.isReadOnly() or not widget.isEnabled():
                return False
        except Exception:
            return False
        if _ancestor_blocks(widget):
            return False
        return DEFAULT_UPPERCASE
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        try:
            if widget.isReadOnly() or not widget.isEnabled():
                return False
        except Exception:
            return False
        if _ancestor_blocks(widget):
            return False
        return DEFAULT_UPPERCASE
    return False


def set_uppercase(widget, enabled: bool | None) -> None:
    """Opt a widget in (``True``), out (``False``) or back to default (None).

    The marker may be placed on an editable ``QComboBox`` as well as on a
    plain ``QLineEdit``.  Setting it does not by itself attach the hook —
    :func:`attach_uppercase` (or the application-wide installer) does that.
    """
    if widget is None:
        return
    try:
        widget.setProperty(UPPERCASE_PROPERTY, enabled)
    except Exception:
        return
    target = line_edit_for(widget)
    if target is not None:
        attach_uppercase(target)


# ── The conversion itself ─────────────────────────────────────────────

def apply_uppercase(edit) -> bool:
    """Upper-case ``edit``'s text in place, preserving caret and selection.

    Returns True when the text actually changed.  The rewrite goes through
    ``QLineEdit.insert()`` — the same path as typing — so the field keeps a
    single undo step; if a validator refuses that route the plain
    ``setText()`` is used as a fallback so the rule still holds.

    Only positions are carried over, never recomputed: ``str.upper()`` is
    length-preserving for every character with a single-character upper form,
    which covers all Latin input.  The few multi-character expansions
    (``ß`` -> ``SS``) do lengthen the text, so every position is clamped to
    the new length rather than trusted blindly.
    """
    if edit is None:
        return False
    if isinstance(edit, (QTextEdit, QPlainTextEdit)):
        try:
            original = edit.toPlainText()
        except Exception:
            return False
        upper = coerce_upper(original)
        if upper == original:
            return False
        if edit.property(_BUSY_PROPERTY):
            return False
        try:
            edit.setProperty(_BUSY_PROPERTY, True)
            cursor = edit.textCursor()
            pos = cursor.position()
            edit.setPlainText(upper)
            cursor.setPosition(min(pos, len(upper)))
            edit.setTextCursor(cursor)
            return True
        finally:
            try:
                edit.setProperty(_BUSY_PROPERTY, False)
            except Exception:
                pass

    try:
        original = edit.text()
    except Exception:
        return False
    upper = coerce_upper(original)
    if upper == original:
        return False
    if edit.property(_BUSY_PROPERTY):
        return False

    had_selection = False
    selection_start = 0
    selection_length = 0
    caret = 0
    try:
        caret = edit.cursorPosition()
        if edit.hasSelectedText():
            had_selection = True
            selection_start = edit.selectionStart()
            selection_length = len(edit.selectedText())
    except Exception:
        had_selection = False

    try:
        edit.setProperty(_BUSY_PROPERTY, True)
    except Exception:
        pass
    try:
        # Prefer the undo-aware path: select everything, then insert over it.
        try:
            edit.selectAll()
            edit.insert(upper)
        except Exception:
            pass
        if edit.text() != upper:
            try:
                edit.setText(upper)
            except Exception:
                return False
    finally:
        try:
            edit.setProperty(_BUSY_PROPERTY, False)
        except Exception:
            pass

    length = len(upper)
    try:
        if had_selection:
            start = max(0, min(selection_start, length))
            edit.setSelection(start, max(0, min(selection_length, length - start)))
        edit.setCursorPosition(max(0, min(caret, length)))
    except Exception:
        pass
    return True


# ── Attaching the hook ────────────────────────────────────────────────

def _convert_after_nonkey_edit(edit) -> None:
    """Convert after a drop/IME edit that did not arrive as key text.

    Scheduled with ``QTimer.singleShot(0, ...)`` so it runs after Qt has
    applied the user's edit.  Programmatic ``setText``/``insert`` never
    schedules this, so loaded records are untouched.
    """
    try:
        if not uppercase_enabled(edit) or edit.property(_BUSY_PROPERTY):
            return
    except Exception:
        return
    apply_uppercase(edit)


def _handle_paste(watched, event) -> bool:
    """Convert clipboard text for Ctrl+V before Qt inserts it.

    Returning True consumes the key event after inserting the converted
    text, so the paste is one normal edit (one textChanged / undo step).
    """
    edit = editable_text_widget_for(watched)
    if edit is None:
        return False
    try:
        if event.key() != Qt.Key.Key_V:
            return False
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            return False
        if edit.property(_BUSY_PROPERTY) or not uppercase_enabled(edit):
            return False
        clipboard = QApplication.clipboard()
        text = clipboard.text() if clipboard is not None else ""
    except Exception:
        return False
    if not text:
        return False
    if isinstance(edit, QLineEdit):
        # QLineEdit's own paste drops line breaks; mirror that.
        text = " ".join(text.splitlines()) or text
    upper = coerce_upper(text)
    if upper == text:
        return False
    try:
        if isinstance(edit, QLineEdit):
            edit.insert(upper)
        elif isinstance(edit, (QTextEdit, QPlainTextEdit)):
            edit.insertPlainText(upper)
        else:
            return False
    except Exception:
        return False
    return True


def _owning_combo(widget):
    """The editable combo that owns ``widget`` (or ``widget`` itself)."""
    if isinstance(widget, QComboBox):
        return widget
    try:
        parent = widget.parent()
    except Exception:
        return None
    return parent if isinstance(parent, QComboBox) else None


def _make_completion_case_insensitive(combo) -> None:
    """Upper-cased typing must not hide the operator's suggestions."""
    try:
        completer = combo.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    except Exception:
        pass


def _prospective_text(edit, inserted: str) -> str | None:
    """The text ``edit`` would hold if ``inserted`` replaced its selection."""
    try:
        text = edit.text()
        if edit.hasSelectedText():
            start = edit.selectionStart()
            end = start + len(edit.selectedText())
        else:
            start = end = edit.cursorPosition()
        return text[:start] + inserted + text[end:]
    except Exception:
        return None


def _keeps_pack_format(edit, inserted: str) -> bool:
    """True when this keystroke keeps a pack expression (``10x10``) exact."""
    prospective = _prospective_text(edit, inserted)
    if prospective is None:
        return False
    return bool(_PACK_EXPRESSION_PARTIAL.match(prospective))


def _handle_key_press(watched, event) -> bool:
    """Rewrite lower-case key text before Qt inserts it and enforce Caps Lock.

    Returns True when the original event was consumed and an upper-case
    replacement delivered.  One keystroke therefore produces exactly one
    ``textChanged``, one undo step and the natural caret/selection outcome.
    """
    ensure_caps_lock_on()

    if _handle_paste(watched, event):
        return True
    edit = editable_text_widget_for(watched)
    if edit is None:
        return False
    try:
        if edit.property(_BUSY_PROPERTY) or not uppercase_enabled(edit):
            return False
    except Exception:
        return False
    try:
        text = event.text()
    except Exception:
        return False
    if not text:
        return False
    if isinstance(edit, QLineEdit) and _keeps_pack_format(edit, text):
        return False
    upper = coerce_upper(text)
    if upper == text:
        return False
    try:
        replacement = QKeyEvent(
            event.type(),
            event.key(),
            event.modifiers(),
            upper,
            event.isAutoRepeat(),
            event.count(),
        )
        QApplication.sendEvent(watched, replacement)
    except Exception:
        return False
    return True


class _UppercaseKeyFilter(QObject):
    """Per-field filter that upper-cases key text before insertion."""

    def eventFilter(self, watched, event):
        try:
            if event.type() == QEvent.Type.KeyPress:
                return _handle_key_press(watched, event)
        except Exception:
            pass
        return False


def attach_uppercase(widget) -> bool:
    """Hook one widget (or an editable combo) for automatic upper-casing.

    Idempotent: the marker property makes a repeat call a no-op, so the
    application-wide watcher may re-examine a widget as often as it likes.
    Returns True when the widget carries a hook.
    """
    target = editable_text_widget_for(widget)
    if target is None:
        return False
    try:
        if target.property(_ATTACHED_PROPERTY):
            return True
        # Convert key text before Qt inserts it: one textChanged, one undo
        # step, and the natural selection/caret result.
        key_filter = _UppercaseKeyFilter(target)
        target.installEventFilter(key_filter)
        combo = _owning_combo(widget) or _owning_combo(target)
        if combo is not None:
            _make_completion_case_insensitive(combo)
        target.setProperty(_ATTACHED_PROPERTY, True)
    except Exception:
        return False
    return True


class UppercaseInputFilter(QObject):
    """Attaches the hook to every text field as the UI appears and keeps Caps Lock ON.

    Installed on the ``QApplication``, so it sees the events of every widget
    in every window — including dialogs that do not exist yet when the
    application starts.  ``Show`` covers a field the first time it appears
    anywhere (a page, a popup, a modal dialog); ``FocusIn`` covers a field
    that is focused without a fresh show, for example after a page swap in
    the main window's ``QStackedWidget``.  ``KeyPress`` is a safety net for a
    field that was never attached; an attached field's own filter consumes
    the event first.
    """

    def eventFilter(self, watched, event):
        try:
            kind = event.type()
            if kind == QEvent.Type.KeyPress:
                return _handle_key_press(watched, event)
            if kind in (QEvent.Type.WindowActivate, QEvent.Type.ApplicationActivate):
                ensure_caps_lock_on()
            if kind == QEvent.Type.Drop or kind == QEvent.Type.InputMethod:
                edit = editable_text_widget_for(watched)
                if edit is not None and isinstance(edit, QLineEdit):
                    QTimer.singleShot(
                        0, lambda _edit=edit: _convert_after_nonkey_edit(_edit)
                    )
                return False
            if kind == QEvent.Type.Show or kind == QEvent.Type.FocusIn:
                ensure_caps_lock_on()
                attach_uppercase(watched)
        except Exception:
            pass
        return False


_filter: "UppercaseInputFilter | None" = None
_filter_app = None
_focus_hooked = False


def _app_instance() -> "QApplication | None":
    """The live ``QApplication``, or None when there is none.

    ``QApplication.instance()`` is declared to return the base
    ``QCoreApplication``, which has neither ``focusChanged`` nor
    ``allWidgets``; narrowing here keeps those calls honest (and checkable)
    instead of scattering suppressions at every use.
    """
    try:
        instance = QApplication.instance()
    except Exception:
        return None
    return instance if isinstance(instance, QApplication) else None


def install_uppercase_input(app=None) -> "UppercaseInputFilter | None":
    """Attach the app-wide upper-casing watcher and ensure Caps Lock is ON (idempotent).

    Safe to call more than once and at any point in start-up: whatever
    already exists is swept immediately, and everything created later is
    caught as it is shown or focused.  If the application object itself has
    been replaced, the watcher is rebuilt on the new one rather than left
    pointing at a dead application.
    """
    global _filter, _filter_app, _focus_hooked
    if app is None:
        app = _app_instance()
    if app is None:
        return None
    ensure_caps_lock_on()
    if _filter is None or _filter_app is not app:
        candidate = UppercaseInputFilter(app)
        try:
            app.installEventFilter(candidate)
        except Exception:
            return None
        _filter, _filter_app, _focus_hooked = candidate, app, False
    if not _focus_hooked:
        try:
            app.focusChanged.connect(lambda _old, now: (ensure_caps_lock_on(), attach_uppercase(now)))
        except Exception:
            pass
        else:
            _focus_hooked = True
    sweep_uppercase_input(app)
    return _filter


def sweep_uppercase_input(root=None) -> int:
    """Attach the hook to every text field currently in the tree.

    The event filter covers fields that appear later; this covers fields that
    already exist (and were already visible) at install time, which is the
    case for a page built before the watcher was installed.
    """
    if root is None:
        root = _app_instance()
    if root is None:
        return 0
    try:
        if hasattr(root, "allWidgets"):
            widgets = list(root.allWidgets())
        else:
            widgets = (
                [root]
                + list(root.findChildren(QLineEdit))
                + list(root.findChildren(QComboBox))
                + list(root.findChildren(QTextEdit))
                + list(root.findChildren(QPlainTextEdit))
            )
    except Exception:
        return 0
    attached = 0
    for widget in widgets:
        try:
            if attach_uppercase(widget):
                attached += 1
        except Exception:
            continue
    return attached


def uppercase_filter() -> "UppercaseInputFilter | None":
    """The installed watcher, for tests and diagnostics."""
    return _filter


__all__ = [
    "UPPERCASE_PROPERTY",
    "DEFAULT_UPPERCASE",
    "is_caps_lock_on",
    "ensure_caps_lock_on",
    "coerce_upper",
    "needs_conversion",
    "uppercase_enabled",
    "set_uppercase",
    "apply_uppercase",
    "attach_uppercase",
    "editable_text_widget_for",
    "line_edit_for",
    "install_uppercase_input",
    "sweep_uppercase_input",
    "uppercase_filter",
    "UppercaseInputFilter",
]
