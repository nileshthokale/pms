import os

path_memo = "database/duplicate_a6_cash_memo.py"
with open(path_memo, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update docstring
old_doc = """- Typography: Arial ONLY. ALL text is EXTRA BOLD / BLACK (weight 900, toner overdraw).
  Shop name: 11.5 pt, Address: 7.5 pt, Everything else: 8.5 pt, Net Amt: 9.5 pt."""
new_doc = """- Typography: Arial ONLY. ALL text is EXTRA BOLD / BLACK (weight 900, toner overdraw).
  Shop name: 13.5 pt, Address: 9.0 pt, Everything else: 9.5 pt, Net Amt: 12.0 pt."""
assert old_doc in code, "old_doc not found"
code = code.replace(old_doc, new_doc)

# 2. Update default args in _draw_shrink_to_fit_bold and _draw_cut_to_fit_bold
old_def_shrink = "def _draw_shrink_to_fit_bold(\n    painter: QPainter,\n    x: float,\n    y: float,\n    w: float,\n    h: float,\n    text: str,\n    max_pt: float = 8.5,\n    min_pt: float = 6.0,"
new_def_shrink = "def _draw_shrink_to_fit_bold(\n    painter: QPainter,\n    x: float,\n    y: float,\n    w: float,\n    h: float,\n    text: str,\n    max_pt: float = 9.5,\n    min_pt: float = 6.0,"
assert old_def_shrink in code, "old_def_shrink not found"
code = code.replace(old_def_shrink, new_def_shrink)

old_def_cut = "def _draw_cut_to_fit_bold(\n    painter: QPainter,\n    x: float,\n    y: float,\n    w: float,\n    h: float,\n    text: str,\n    pt_size: float = 8.5,"
new_def_cut = "def _draw_cut_to_fit_bold(\n    painter: QPainter,\n    x: float,\n    y: float,\n    w: float,\n    h: float,\n    text: str,\n    pt_size: float = 9.5,"
assert old_def_cut in code, "old_def_cut not found"
code = code.replace(old_def_cut, new_def_cut)

# 3. Update draw_a6_cash_memo_page
old_page_block = '''    # ══════════════════════════════════════════════════════════════════
    # 1. HEADER (Fixed at top, Y = 5.0 to 29.0 mm)
    # ══════════════════════════════════════════════════════════════════
    # Line 1: Shop Name (centered, 11.5 pt heavy bold, from firm master)
    shop_name = store.get("name", "SHREE SAMARTH MEDICAL AND GEN STORE")
    _draw_bold_text(
        painter,
        x=x0,
        y=ry(5.2),
        w=w_content,
        h=rh(4.8),
        text=shop_name,
        pt_size=11.5,
        align="center",
    )

    # Page number at top-right only if multi-page
    if total_pages > 1:
        page_str = f"Page {page_num} of {total_pages}"
        _draw_bold_text(
            painter,
            x=rx(MARGIN_LEFT_MM + CONTENT_WIDTH_MM - 35.0),
            y=ry(5.2),
            w=rw(35.0),
            h=rh(4.0),
            text=page_str,
            pt_size=8.5,
            align="right",
        )

    # Line 2: Shop Address (centered, 7.5 pt bold, from firm master)
    shop_addr = store.get("address", "GHORPADE HOSPITAL, RAHURI")
    _draw_bold_text(
        painter,
        x=x0,
        y=ry(10.4),
        w=w_content,
        h=rh(3.6),
        text=shop_addr,
        pt_size=7.5,
        align="center",
    )

    # Left & Right Block (8.5 pt heavy bold)
    cust_name = str(head.get("patient_name") or head.get("customer_name") or "WALKIN").strip()
    addr = str(head.get("address") or "").strip()
    name_str = f"Name : {cust_name}" + (f", {addr}" if addr else "")

    doc_name = str(head.get("doctor_name") or "").strip()
    doc_str = f"Doctor : {doc_name}"

    v_no = str(head.get("voucher_no") or head.get("bill_no") or "1")
    bill_type = str(head.get("bill_type") or head.get("sale_type") or "Cash").strip()
    memo_label = "Credit Memo" if bill_type.lower() == "credit" else "Cash Memo"
    memo_str = f"{memo_label} : {v_no}"
    if show_duplicate:
        memo_str += "  [ DUPLICATE ]"

    sale_date_raw = head.get("vh_date") or head.get("sale_date")
    dt_str = f"Date : {format_display_date(sale_date_raw)}"

    left_w = rw(CONTENT_WIDTH_MM * 0.58)
    right_w = rw(CONTENT_WIDTH_MM * 0.42)
    right_x = x0 + left_w

    # Meta Row 1 (Y: 14.5 mm)
    _draw_cut_to_fit_bold(painter, x0, ry(14.5), left_w, rh(3.8), name_str, 8.5, "left")
    _draw_cut_to_fit_bold(painter, right_x, ry(14.5), right_w, rh(3.8), memo_str, 8.5, "right")

    # Meta Row 2 (Y: 18.5 mm)
    _draw_cut_to_fit_bold(painter, x0, ry(18.5), left_w, rh(3.8), doc_str, 8.5, "left")
    _draw_cut_to_fit_bold(painter, right_x, ry(18.5), right_w, rh(3.8), dt_str, 8.5, "right")

    # Thin Rule 1 (0.35 mm solid): Above Column Headings (Y = 24.5 mm)
    painter.setPen(pen_rule)
    painter.drawLine(QPointF(x0, ry(24.5)), QPointF(x1, ry(24.5)))

    # Column Headings (8.5 pt heavy bold, Y: 24.9 to 28.7 mm)
    col_x_mm = MARGIN_LEFT_MM
    for key, title, width_mm, align in COLUMN_DEFS:
        cx = rx(col_x_mm)
        cw = rw(width_mm)
        pad = rw(0.6) if align == "left" else 0.0
        r_pad = rw(0.6) if align == "right" else 0.0
        _draw_bold_text(
            painter,
            cx + pad,
            ry(24.9),
            cw - pad - r_pad,
            rh(3.8),
            title,
            8.5,
            align,
        )
        col_x_mm += width_mm

    # Thin Rule 2 (0.35 mm solid): Below Column Headings (Y = 29.0 mm)
    painter.drawLine(QPointF(x0, ry(29.0)), QPointF(x1, ry(29.0)))

    # ══════════════════════════════════════════════════════════════════
    # 2. MIDDLE - RESERVED ITEM AREA (Exactly ITEM_ROWS = 10 rows)
    # ══════════════════════════════════════════════════════════════════
    # Y = 31.0 mm to 71.0 mm (40.0 mm height, 10 rows x 4.0 mm)
    for r_idx in range(ITEM_ROWS):
        curr_y_mm = ITEM_START_Y_MM + r_idx * ROW_HEIGHT_MM
        itm = page["items"][r_idx]

        if itm and (itm.get("item_name") or itm.get("sales_qty") or itm.get("sale_qty") or itm.get("amount") or itm.get("batch_no")):
            qty_val = itm.get("sales_qty") if itm.get("sales_qty") is not None else itm.get("sale_qty")
            qty_str = format_qty_display(qty_val)
            unit_str = str(itm.get("unit") or itm.get("pack_size") or "").strip()
            desc_str = str(itm.get("item_name") or "").strip()
            comp_str = str(itm.get("comp") or itm.get("location") or "").strip()
            batch_str = str(itm.get("batch_no") or "").strip()
            exp_str = format_expiry_display(itm.get("expiry"))
            amt_str = format_amt_display(itm.get("amount"))

            row_map = {
                "qty": qty_str,
                "unit": unit_str,
                "description": desc_str,
                "comp": comp_str,
                "batch": batch_str,
                "expiry": exp_str,
                "amount": amt_str,
            }

            col_x_mm = MARGIN_LEFT_MM
            for key, title, width_mm, align in COLUMN_DEFS:
                val = row_map.get(key, "")
                cx = rx(col_x_mm)
                cw = rw(width_mm)
                pad = rw(0.6) if align == "left" else 0.0
                r_pad = rw(0.6) if align == "right" else 0.0

                if key == "batch":
                    # BATCH: Shrink-to-fit down to 6 pt, NEVER cut, NEVER '...'
                    _draw_shrink_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        max_pt=8.5,
                        min_pt=6.0,
                        align=align,
                    )
                elif key == "description":
                    # DESCRIPTION: Cut at column width without dots
                    _draw_cut_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        pt_size=8.5,
                        align=align,
                    )
                else:
                    _draw_bold_text(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        pt_size=8.5,
                        align=align,
                    )
                col_x_mm += width_mm

    # Thin Rule 3 (0.35 mm solid): Below Items (Y = 71.0 mm)
    painter.setPen(pen_rule)
    painter.drawLine(QPointF(x0, ry(ITEM_END_Y_MM)), QPointF(x1, ry(ITEM_END_Y_MM)))

    # ══════════════════════════════════════════════════════════════════
    # 3. FOOTER (Fixed at Bottom, Y = 75.0 to 100.0 mm)
    # ══════════════════════════════════════════════════════════════════
    # Left Block (8.5 pt bold): Jurisdiction, Licences (wrapped up to 2 lines), GSTIN
    jur = store.get("jurisdiction", "AHMEDNAGAR")
    jur_line = f"E & O E. Subject to {jur} Jurisdiction"
    licence_raw = store.get("licence", "")
    gstin_raw = store.get("gstin", "")

    # Licence line wrapping across up to 2 lines so it is never clipped
    lic_line1 = licence_raw
    lic_line2 = ""
    if len(licence_raw) > 34 and "," in licence_raw:
        split_idx = licence_raw.rfind(",", 0, 34)
        if split_idx != -1:
            lic_line1 = licence_raw[:split_idx + 1].strip()
            lic_line2 = licence_raw[split_idx + 1:].strip()

    foot_left_w = rw(CONTENT_WIDTH_MM * 0.58)

    # Line 1: Jurisdiction
    _draw_bold_text(painter, x0, ry(75.5), foot_left_w, rh(4.0), jur_line, 8.5, "left")

    # Line 2 & 3: Licences (wrapped so never clipped)
    _draw_bold_text(painter, x0, ry(80.0), foot_left_w, rh(4.0), lic_line1, 8.0, "left")
    curr_foot_y_mm = 84.5
    if lic_line2:
        _draw_bold_text(painter, x0, ry(curr_foot_y_mm), foot_left_w, rh(4.0), lic_line2, 8.0, "left")
        curr_foot_y_mm += 4.5

    # Line 4: GSTIN (no debug ID or remarks printed!)
    if gstin_raw:
        _draw_bold_text(painter, x0, ry(curr_foot_y_mm), foot_left_w, rh(4.0), f"GSTIN: {gstin_raw}", 8.0, "left")

    # Right Block: Net Amt (9.5 pt prominent bold), Shop Name, Pharmacist/Sign
    foot_right_w = rw(CONTENT_WIDTH_MM * 0.42)
    foot_right_x = x0 + foot_left_w

    if is_last:
        net_val = float(head.get("net_amount") or 0.0)
        net_str = f"Net Amt : {int(round(net_val))}"
    else:
        net_str = "Continued..."

    # Row 1: Net Amt / Continued... (9.5 pt prominent bold)
    _draw_bold_text(painter, foot_right_x, ry(75.5), foot_right_w, rh(4.8), net_str, 9.5, "right")

    # Row 2: Shop Name (8.5 pt bold)
    _draw_bold_text(painter, foot_right_x, ry(83.5), foot_right_w, rh(4.2), shop_name, 8.5, "right")

    # Row 3: Pharmacist/Sign (8.5 pt bold)
    _draw_bold_text(painter, foot_right_x, ry(92.5), foot_right_w, rh(4.2), "Pharmacist/Sign", 8.5, "right")'''

new_page_block = '''    # ══════════════════════════════════════════════════════════════════
    # 1. HEADER (Fixed at top, Y = 5.0 to 29.0 mm)
    # ══════════════════════════════════════════════════════════════════
    # Line 1: Shop Name (centered, 13.5 pt heavy bold, from firm master)
    shop_name = store.get("name", "SHREE SAMARTH MEDICAL AND GEN STORE")
    _draw_bold_text(
        painter,
        x=x0,
        y=ry(5.0),
        w=w_content,
        h=rh(5.0),
        text=shop_name,
        pt_size=13.5,
        align="center",
    )

    # Page number at top-right only if multi-page (9.5 pt)
    if total_pages > 1:
        page_str = f"Page {page_num} of {total_pages}"
        _draw_bold_text(
            painter,
            x=rx(MARGIN_LEFT_MM + CONTENT_WIDTH_MM - 35.0),
            y=ry(5.0),
            w=rw(35.0),
            h=rh(4.2),
            text=page_str,
            pt_size=9.5,
            align="right",
        )

    # Line 2: Shop Address (centered, 9.0 pt bold, from firm master)
    shop_addr = store.get("address", "GHORPADE HOSPITAL, RAHURI")
    _draw_bold_text(
        painter,
        x=x0,
        y=ry(10.2),
        w=w_content,
        h=rh(3.8),
        text=shop_addr,
        pt_size=9.0,
        align="center",
    )

    # Left & Right Block (9.5 pt heavy bold)
    cust_name = str(head.get("patient_name") or head.get("customer_name") or "WALKIN").strip()
    addr = str(head.get("address") or "").strip()
    name_str = f"Name : {cust_name}" + (f", {addr}" if addr else "")

    doc_name = str(head.get("doctor_name") or "").strip()
    doc_str = f"Doctor : {doc_name}"

    v_no = str(head.get("voucher_no") or head.get("bill_no") or "1")
    bill_type = str(head.get("bill_type") or head.get("sale_type") or "Cash").strip()
    memo_label = "Credit Memo" if bill_type.lower() == "credit" else "Cash Memo"
    memo_str = f"{memo_label} : {v_no}"
    if show_duplicate:
        memo_str += "  [ DUPLICATE ]"

    sale_date_raw = head.get("vh_date") or head.get("sale_date")
    dt_str = f"Date : {format_display_date(sale_date_raw)}"

    left_w = rw(CONTENT_WIDTH_MM * 0.58)
    right_w = rw(CONTENT_WIDTH_MM * 0.42)
    right_x = x0 + left_w

    # Meta Row 1 (Y: 14.3 mm, 9.5 pt)
    _draw_cut_to_fit_bold(painter, x0, ry(14.3), left_w, rh(4.0), name_str, 9.5, "left")
    _draw_cut_to_fit_bold(painter, right_x, ry(14.3), right_w, rh(4.0), memo_str, 9.5, "right")

    # Meta Row 2 (Y: 18.5 mm, 9.5 pt)
    _draw_cut_to_fit_bold(painter, x0, ry(18.5), left_w, rh(4.0), doc_str, 9.5, "left")
    _draw_cut_to_fit_bold(painter, right_x, ry(18.5), right_w, rh(4.0), dt_str, 9.5, "right")

    # Thin Rule 1 (0.35 mm solid): Above Column Headings (Y = 24.5 mm)
    painter.setPen(pen_rule)
    painter.drawLine(QPointF(x0, ry(24.5)), QPointF(x1, ry(24.5)))

    # Column Headings (9.5 pt heavy bold with shrink-to-fit min 8.0, Y: 24.9 to 28.7 mm)
    col_x_mm = MARGIN_LEFT_MM
    for key, title, width_mm, align in COLUMN_DEFS:
        cx = rx(col_x_mm)
        cw = rw(width_mm)
        pad = rw(0.6) if align == "left" else 0.0
        r_pad = rw(0.6) if align == "right" else 0.0
        _draw_shrink_to_fit_bold(
            painter,
            cx + pad,
            ry(24.9),
            cw - pad - r_pad,
            rh(3.8),
            title,
            max_pt=9.5,
            min_pt=8.0,
            align=align,
        )
        col_x_mm += width_mm

    # Thin Rule 2 (0.35 mm solid): Below Column Headings (Y = 29.0 mm)
    painter.drawLine(QPointF(x0, ry(29.0)), QPointF(x1, ry(29.0)))

    # ══════════════════════════════════════════════════════════════════
    # 2. MIDDLE - RESERVED ITEM AREA (Exactly ITEM_ROWS = 10 rows)
    # ══════════════════════════════════════════════════════════════════
    # Y = 31.0 mm to 71.0 mm (40.0 mm height, 10 rows x 4.0 mm)
    for r_idx in range(ITEM_ROWS):
        curr_y_mm = ITEM_START_Y_MM + r_idx * ROW_HEIGHT_MM
        itm = page["items"][r_idx]

        if itm and (itm.get("item_name") or itm.get("sales_qty") or itm.get("sale_qty") or itm.get("amount") or itm.get("batch_no")):
            qty_val = itm.get("sales_qty") if itm.get("sales_qty") is not None else itm.get("sale_qty")
            qty_str = format_qty_display(qty_val)
            unit_str = str(itm.get("unit") or itm.get("pack_size") or "").strip()
            desc_str = str(itm.get("item_name") or "").strip()
            comp_str = str(itm.get("comp") or itm.get("location") or "").strip()
            batch_str = str(itm.get("batch_no") or "").strip()
            exp_str = format_expiry_display(itm.get("expiry"))
            amt_str = format_amt_display(itm.get("amount"))

            row_map = {
                "qty": qty_str,
                "unit": unit_str,
                "description": desc_str,
                "comp": comp_str,
                "batch": batch_str,
                "expiry": exp_str,
                "amount": amt_str,
            }

            col_x_mm = MARGIN_LEFT_MM
            for key, title, width_mm, align in COLUMN_DEFS:
                val = row_map.get(key, "")
                cx = rx(col_x_mm)
                cw = rw(width_mm)
                pad = rw(0.6) if align == "left" else 0.0
                r_pad = rw(0.6) if align == "right" else 0.0

                if key == "batch":
                    # BATCH: 9.5 pt with shrink-to-fit down to 6.5 pt, NEVER cut, NEVER '...'
                    _draw_shrink_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        max_pt=9.5,
                        min_pt=6.5,
                        align=align,
                    )
                elif key == "description":
                    # DESCRIPTION: 9.5 pt, cut at column width without dots
                    _draw_cut_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        pt_size=9.5,
                        align=align,
                    )
                else:
                    # QTY, UNIT, COMP, EXP. DT, AMT: 9.5 pt with shrink-to-fit min 7.5
                    _draw_shrink_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        max_pt=9.5,
                        min_pt=7.5,
                        align=align,
                    )
                col_x_mm += width_mm

    # Thin Rule 3 (0.35 mm solid): Below Items (Y = 71.0 mm)
    painter.setPen(pen_rule)
    painter.drawLine(QPointF(x0, ry(ITEM_END_Y_MM)), QPointF(x1, ry(ITEM_END_Y_MM)))

    # ══════════════════════════════════════════════════════════════════
    # 3. FOOTER (Fixed at Bottom, Y = 75.0 to 100.0 mm)
    # ══════════════════════════════════════════════════════════════════
    # Left Block (9.5 pt / 9.0 pt bold): Jurisdiction, Licences, GSTIN
    jur = store.get("jurisdiction", "AHMEDNAGAR")
    jur_line = f"E & O E. Subject to {jur} Jurisdiction"
    licence_raw = store.get("licence", "")
    gstin_raw = store.get("gstin", "")

    # Licence line wrapping across up to 2 lines so it is never clipped
    lic_line1 = licence_raw
    lic_line2 = ""
    if len(licence_raw) > 34 and "," in licence_raw:
        split_idx = licence_raw.rfind(",", 0, 34)
        if split_idx != -1:
            lic_line1 = licence_raw[:split_idx + 1].strip()
            lic_line2 = licence_raw[split_idx + 1:].strip()

    foot_left_w = rw(CONTENT_WIDTH_MM * 0.62)
    foot_right_w = rw(CONTENT_WIDTH_MM * 0.38)
    foot_right_x = x0 + foot_left_w

    # Line 1: Jurisdiction (9.5 pt with shrink-to-fit min 8.0)
    _draw_shrink_to_fit_bold(painter, x0, ry(75.5), foot_left_w, rh(4.2), jur_line, max_pt=9.5, min_pt=8.0, align="left")

    # Line 2 & 3: Licences (wrapped, 9.0 pt)
    _draw_bold_text(painter, x0, ry(80.0), foot_left_w, rh(4.0), lic_line1, 9.0, "left")
    curr_foot_y_mm = 84.5
    if lic_line2:
        _draw_bold_text(painter, x0, ry(curr_foot_y_mm), foot_left_w, rh(4.0), lic_line2, 9.0, "left")
        curr_foot_y_mm += 4.5

    # Line 4: GSTIN (9.0 pt)
    if gstin_raw:
        _draw_bold_text(painter, x0, ry(curr_foot_y_mm), foot_left_w, rh(4.0), f"GSTIN: {gstin_raw}", 9.0, "left")

    # Right Block: Net Amt (12.0 pt prominent bold), Shop Name (9.5 pt), Pharmacist/Sign (9.5 pt)
    if is_last:
        net_val = float(head.get("net_amount") or 0.0)
        net_str = f"Net Amt : {int(round(net_val))}"
    else:
        net_str = "Continued..."

    # Row 1: Net Amt / Continued... (12.0 pt prominent bold)
    _draw_bold_text(painter, foot_right_x, ry(75.0), foot_right_w, rh(5.5), net_str, 12.0, "right")

    # Row 2: Shop Name (9.5 pt bold)
    _draw_bold_text(painter, foot_right_x, ry(83.5), foot_right_w, rh(4.2), shop_name, 9.5, "right")

    # Row 3: Pharmacist/Sign (9.5 pt bold)
    _draw_bold_text(painter, foot_right_x, ry(92.5), foot_right_w, rh(4.2), "Pharmacist/Sign", 9.5, "right")'''

assert old_page_block in code, "old_page_block not found"
code = code.replace(old_page_block, new_page_block)

# 4. Watermark pt
code = code.replace("f_watermark.setPointSizeF(5.0)", "f_watermark.setPointSizeF(6.0)")

with open(path_memo, "w", encoding="utf-8") as f:
    f.write(code)
print("Updated database/duplicate_a6_cash_memo.py with increased font sizes!")

# 5. Update reports descriptors
for rpt_path in ["reports/DuplicateSalesBill_A6.rpt", "reports/CounterSaleBill_A6.rpt"]:
    with open(rpt_path, "r", encoding="utf-8") as f:
        c = f.read()
    c = c.replace("ShopNamePt=11.5", "ShopNamePt=13.5")
    c = c.replace("AddressPt=7.5", "AddressPt=9.0")
    c = c.replace("BodyPt=8.5", "BodyPt=9.5")
    c = c.replace("NetAmtPt=9.5", "NetAmtPt=12.0")
    c = c.replace("WatermarkPt=5.0", "WatermarkPt=6.0")
    with open(rpt_path, "w", encoding="utf-8") as f:
        f.write(c)
    print(f"Updated {rpt_path}")

