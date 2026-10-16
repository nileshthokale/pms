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
* :func:`attach_uppercase` hooks ONE ``QLineEdit``.  The hook is connected to
  ``textEdited``, which Qt emits **only for a user edit** — typing, pasting,
  dropping text or IME input.  ``QLineEdit.setText()`` and
  ``QComboBox.setEditText()`` emit ``textChanged`` but *not* ``textEdited``,
  so:

    - a record loaded from the database is never rewritten, and
    - the conversion can never recurse into itself.

* :func:`apply_uppercase` rewrites the field in place and restores the caret
  and the selection afterwards, so editing in the middle of a word keeps the
  caret where the user left it.

* :func:`install_uppercase_input` attaches the hook application-wide: a
  ``QApplication`` event filter watches every widget as it is shown or
  focused, and an initial sweep covers whatever already existed.  A screen
  therefore does not have to remember to opt in.

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

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFileDialog,
    QLineEdit,
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


# ── Pure text logic ───────────────────────────────────────────────────

def coerce_upper(text: str) -> str:
    """Return ``text`` upper-cased.

    Kept as a separate function so the rule is unit-testable on its own and
    so callers can reuse the exact same conversion (e.g. to upper-case a
    value loaded into a dialog before it is shown).
    """
    return text.upper() if text else text


def needs_conversion(text: str) -> bool:
    """True when ``text`` contains a letter that upper-casing would change."""
    return bool(text) and text.upper() != text


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


def line_edit_for(widget):
    """The ``QLineEdit`` a typeable widget edits, or None.

    Handles a plain ``QLineEdit`` and the inner editor of an editable
    ``QComboBox``; a non-editable combo has no text field and is skipped.
    """
    if widget is None:
        return None
    if isinstance(widget, QLineEdit):
        return widget
    if isinstance(widget, QComboBox):
        try:
            if widget.isEditable():
                return widget.lineEdit()
        except Exception:
            return None
    return None


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
    if not isinstance(widget, QLineEdit):
        return False
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

def _on_text_edited(edit) -> None:
    """``textEdited`` receiver: convert when the policy allows it."""
    try:
        if not uppercase_enabled(edit):
            return
    except Exception:
        return
    if edit.property(_BUSY_PROPERTY):
        return
    apply_uppercase(edit)


def attach_uppercase(widget) -> bool:
    """Hook one widget (or an editable combo) for automatic upper-casing.

    Idempotent: the marker property makes a repeat call a no-op, so the
    application-wide watcher may re-examine a widget as often as it likes.
    Returns True when the widget carries a hook.
    """
    target = line_edit_for(widget)
    if target is None:
        return False
    try:
        if target.property(_ATTACHED_PROPERTY):
            return True
        target.setProperty(_ATTACHED_PROPERTY, True)
        target.textEdited.connect(lambda _text, _edit=target: _on_text_edited(_edit))
    except Exception:
        return False
    return True


class UppercaseInputFilter(QObject):
    """Attaches the hook to every text field as the UI appears.

    Installed on the ``QApplication``, so it sees the events of every widget
    in every window — including dialogs that do not exist yet when the
    application starts.  ``Show`` covers a field the first time it appears
    anywhere (a page, a popup, a modal dialog); ``FocusIn`` covers a field
    that is focused without a fresh show, for example after a page swap in
    the main window's ``QStackedWidget``.
    """

    def eventFilter(self, watched, event):
        try:
            kind = event.type()
            if kind == QEvent.Type.Show or kind == QEvent.Type.FocusIn:
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
    """Attach the app-wide upper-casing watcher (idempotent).

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
    if _filter is None or _filter_app is not app:
        candidate = UppercaseInputFilter(app)
        try:
            app.installEventFilter(candidate)
        except Exception:
            return None
        _filter, _filter_app, _focus_hooked = candidate, app, False
    if not _focus_hooked:
        try:
            app.focusChanged.connect(lambda _old, now: attach_uppercase(now))
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
            widgets = ([root] + list(root.findChildren(QLineEdit))
                       + list(root.findChildren(QComboBox)))
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
    "coerce_upper",
    "needs_conversion",
    "uppercase_enabled",
    "set_uppercase",
    "apply_uppercase",
    "attach_uppercase",
    "line_edit_for",
    "install_uppercase_input",
    "sweep_uppercase_input",
    "uppercase_filter",
    "UppercaseInputFilter",
]
