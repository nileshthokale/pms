"""Visual theme probe — renders the REAL application and reports actual pixels.

This is NOT a stylesheet-string assertion test.  It builds the real
PharmacyMainWindow from the live source tree, switches Day/Night mode, and
renders the real widget tree to PNGs via QWidget.grab().  Every finding is
read back from rendered pixels.

Usage (from the repo root):
    .venv/Scripts/python.exe tools/theme_probe.py --out temp/theme_probe
    .venv/Scripts/python.exe tools/theme_probe.py --platform offscreen

The script never touches the real database or data/theme.json: it runs
against a disposable copy of data/pharmacy.db and a temp theme file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── isolation: never touch the live DB or theme file ──────────────────
def _stage_database() -> Path:
    src = ROOT / "data" / "pharmacy.db"
    fd, name = tempfile.mkstemp(prefix="theme_probe_", suffix=".db")
    os.close(fd)
    dst = Path(name)
    if src.exists():
        source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
    os.environ["PHARMACY_DB"] = str(dst)
    os.environ["PHARMACY_TEST_SAFE_DB"] = str(dst)
    os.environ["PHARMACY_TEST_PROTECTED_DB"] = str(src.resolve())
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "temp" / "theme_probe"))
    ap.add_argument("--platform", default=None,
                    help="offscreen | windows | minimal (default: windows if a "
                         "desktop session is available, else offscreen)")
    ap.add_argument("--width", type=int, default=1366)
    ap.add_argument("--height", type=int, default=760)
    ap.add_argument("--cycles", type=int, default=1)
    args = ap.parse_args()

    staged_db = _stage_database()
    theme_tmp = Path(tempfile.mkdtemp(prefix="theme_probe_")) / "theme.json"

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    platform = args.platform
    if platform:
        os.environ["QT_QPA_PLATFORM"] = platform

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QToolTip, QWidget

    from ui import theme as theme_mod

    # Redirect persistence so we never write data/theme.json.
    theme_mod._THEME_FILE = theme_tmp

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    theme_mod.apply_to_app(app)

    from database import auth, financial_year
    from database.connection import init_database
    from ui.main_window import PharmacyMainWindow

    init_database()
    auth.ensure_auth_schema()
    financial_year.ensure_default_financial_year()
    auth.session.user = {"id": 1, "username": "admin", "role": "ADMIN"}

    report: dict = {
        "platform": QGuiApplication.platformName(),
        "staged_db": str(staged_db),
        "shots": [],
        "tooltips": [],
        "regions": {},
    }

    def pump(n: int = 8):
        for _ in range(n):
            app.processEvents()

    window = PharmacyMainWindow()
    window.resize(args.width, args.height)
    window.show()
    pump(12)

    # Navigate to Counter Sale (Sales > New Bill).
    window._on_menu_action("Sales", "New Bill")
    pump(12)

    # ── widget region-of-interest map (mapped into window coordinates) ──
    def roi(spec):
        """spec: (widget, label). Returns absolute rect in the grab pixmap."""
        w, label = spec
        if w is None:
            return None
        try:
            if not w.isVisible():
                return None
            top_left = w.mapTo(window, QPoint(0, 0))
            return {
                "label": label,
                "cls": type(w).__name__,
                "objectName": w.objectName() or "",
                "x": int(top_left.x()), "y": int(top_left.y()),
                "w": int(w.width()), "h": int(w.height()),
            }
        except Exception as exc:  # pragma: no cover - diagnostic
            return {"label": label, "error": str(exc)}

    page = window._stack.currentWidget()

    def find(name_attr, cls_name=None):
        w = getattr(page, name_attr, None)
        return w

    # Counter Sale specific widgets.
    cs_header = None
    cs_filter = getattr(page, "_history_filter_bar", None)
    cs_billpanel = None
    cs_sale_panel = getattr(page, "_sale_panel", None)
    for child in page.findChildren(QWidget):
        if child.objectName() == "BillPanel":
            cs_billpanel = child
    # The header strip is the first plain QWidget child of the page.
    lay = page.layout()
    if lay is not None and lay.count():
        cs_header = lay.itemAt(0).widget()

    regions = [
        (cs_header, "cs_header_strip"),
        (cs_filter, "cs_history_filter_bar"),
        (cs_billpanel, "cs_bill_panel"),
        (window._nav, "nav_bar"),
        (window._nav.findChild(QWidget, "TitleBar"), "nav_title_strip"),
        (window._nav.findChild(QWidget, "MenuBar"), "nav_menu_strip"),
        (cs_sale_panel, "cs_sale_panel"),
    ]

    def sample(shot_img, rect):
        """Return the most common pixel colour in a rect of a QPixmap."""
        if rect is None or "error" in rect:
            return None
        x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
        # Sample an interior band, avoiding 2px edges (borders).
        xs = range(max(0, x + 3), max(0, x + w - 3), max(1, (w - 6) // 24 or 1))
        ys = range(max(0, y + 3), max(0, y + h - 3), max(1, (h - 6) // 8 or 1))
        counts: dict = {}
        img = shot_img.toImage()
        for yy in ys:
            for xx in xs:
                if xx < 0 or yy < 0 or xx >= img.width() or yy >= img.height():
                    continue
                c = img.pixelColor(xx, yy)
                key = f"#{c.red():02x}{c.green():02x}{c.blue():02x}"
                counts[key] = counts.get(key, 0) + 1
        if not counts:
            return None
        top = sorted(counts.items(), key=lambda kv: -kv[1])
        return {"dominant": top[0][0], "count": top[0][1],
                "total": sum(counts.values()),
                "top3": [k for k, _ in top[:3]]}

    def luminance(hexcol: str) -> float:
        h = hexcol.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0

    def capture(tag: str, mode: str):
        pump(10)
        pix = window.grab()
        path = out_dir / f"{tag}.png"
        pix.save(str(path))
        entry = {"tag": tag, "mode": mode, "path": str(path),
                 "size": [pix.width(), pix.height()], "regions": {}}
        for widget, label in regions:
            r = roi((widget, label))
            s = sample(pix, r) if r else None
            entry["regions"][label] = {"rect": r, "sample": s,
                                       "lum": round(luminance(s["dominant"]), 3) if s else None}
        report["shots"].append(entry)
        return entry

    def tooltip_probe(tag: str, mode: str, owner_label: str):
        """Show the REAL tooltip Qt shows on hover and grab its pixels."""
        owner = (window._nav.user_label if owner_label == "user"
                 else window._nav.theme_btn)
        tip = owner.toolTip()
        pump(4)
        QToolTip.showText(owner.mapToGlobal(QPoint(owner.width() // 2,
                                                   owner.height() + 4)),
                          tip, owner)
        pump(14)
        found = None
        for w in app.topLevelWidgets():
            try:
                if w is window:
                    continue
                if not w.isVisible():
                    continue
                flags = w.windowFlags()
                if (flags & Qt.WindowType.ToolTip) or (
                        "Tip" in type(w).__name__) or (
                        w.metaObject().className() == "QToolTip"):
                    found = w
                    break
            except Exception:
                continue
        entry = {"tag": tag, "mode": mode, "owner": owner_label,
                 "owner_tooltip": tip,
                 "owner_style": owner.styleSheet(),
                 "owner_objectName": owner.objectName(),
                 "owner_cls": type(owner).__name__}
        if found is not None:
            tp = out_dir / f"{tag}.png"
            tpix = found.grab()
            tpix.save(str(tp))
            entry["found"] = type(found).__name__
            entry["className"] = found.metaObject().className()
            entry["path"] = str(tp)
            entry["size"] = [tpix.width(), tpix.height()]
            entry["stylesheet"] = found.styleSheet()
            img = tpix.toImage()
            counts: dict = {}
            for yy in range(2, max(3, img.height() - 2)):
                for xx in range(2, max(3, img.width() - 2)):
                    c = img.pixelColor(xx, yy)
                    k = f"#{c.red():02x}{c.green():02x}{c.blue():02x}"
                    counts[k] = counts.get(k, 0) + 1
            top = sorted(counts.items(), key=lambda kv: -kv[1])[:4]
            entry["pixels"] = [{"color": k, "count": v} for k, v in top]
            entry["dominant"] = top[0][0] if top else None
            entry["dominant_lum"] = round(luminance(top[0][0]), 3) if top else None
            pal = found.palette()
            from PySide6.QtGui import QPalette
            entry["palette_ToolTipBase"] = pal.color(QPalette.ColorRole.ToolTipBase).name()
            entry["palette_Window"] = pal.color(QPalette.ColorRole.Window).name()
        else:
            entry["found"] = None
        QToolTip.hideText()
        pump(6)
        report["tooltips"].append(entry)
        return entry

    # ── main capture cycle ────────────────────────────────────────────
    for cycle in range(args.cycles):
        theme_mod.theme_manager.set_mode("light")
        pump(14)
        capture(f"day_{cycle}", "light")
        tooltip_probe(f"tooltip_day_user_{cycle}", "light", "user")
        tooltip_probe(f"tooltip_day_theme_{cycle}", "light", "theme")

        theme_mod.theme_manager.set_mode("dark")
        pump(14)
        capture(f"night_{cycle}", "dark")
        tooltip_probe(f"tooltip_night_user_{cycle}", "dark", "user")
        tooltip_probe(f"tooltip_night_theme_{cycle}", "dark", "theme")

    theme_mod.theme_manager.set_mode("light")
    pump(10)
    capture("day_final", "light")

    rep = out_dir / "probe_report.json"
    rep.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # ── human summary ─────────────────────────────────────────────────
    print("=" * 72)
    print(f"platform      : {report['platform']}")
    print(f"staged db     : {staged_db}")
    print(f"report        : {rep}")
    print("=" * 72)
    for shot in report["shots"]:
        print(f"\n[{shot['tag']}]  mode={shot['mode']}  size={shot['size']}")
        for label, info in shot["regions"].items():
            s = info.get("sample")
            if not s:
                print(f"   {label:26s} <not found / not visible>")
                continue
            print(f"   {label:26s} dominant={s['dominant']} "
                  f"lum={info['lum']:.3f} ({s['count']}/{s['total']} px) "
                  f"top3={s['top3']}")
    for t in report["tooltips"]:
        print(f"\n[tooltip {t['tag']}] mode={t['mode']} owner={t['owner']}"
              f" obj={t['owner_objectName']}")
        if t.get("dominant"):
            print(f"   dominant={t['dominant']} lum={t['dominant_lum']:.3f}"
                  f"  pixels={t['pixels']}")
            print(f"   palette ToolTipBase={t.get('palette_ToolTipBase')}"
                  f" Window={t.get('palette_Window')}")
        else:
            print(f"   <no tooltip widget found> {t}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
