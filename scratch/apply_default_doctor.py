with open('screens/counter_sale.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Add _select_default_doctor method right above _load_doctors
old_load_doctors = '''    def _load_doctors(self):
        doctors = DoctorDAO.get_all()
        self.doctor_combo.addItem("-- None --", None)
        for d in doctors:
            self.doctor_combo.addItem(d["doctor_name"], d["id"])'''

new_load_doctors = '''    def _select_default_doctor(self):
        """Default to DR.K.N.GHORPADE if available in the doctors list,
        otherwise fall back to index 0 (-- None --).
        """
        for i in range(self.doctor_combo.count()):
            text = self.doctor_combo.itemText(i).upper()
            if "GHORPADE" in text:
                self.doctor_combo.setCurrentIndex(i)
                return
        if self.doctor_combo.count() > 0:
            self.doctor_combo.setCurrentIndex(0)

    def _load_doctors(self):
        doctors = DoctorDAO.get_all()
        self.doctor_combo.addItem("-- None --", None)
        for d in doctors:
            self.doctor_combo.addItem(d["doctor_name"], d["id"])
        self._select_default_doctor()'''

assert old_load_doctors in text, "old_load_doctors not found"
text = text.replace(old_load_doctors, new_load_doctors)

# 2. Update clear_form to use _select_default_doctor
old_clear_doctor = '''        if self.doctor_combo.count():
            self.doctor_combo.setCurrentIndex(0)'''

new_clear_doctor = '''        if self.doctor_combo.count():
            self._select_default_doctor()'''

assert old_clear_doctor in text, "old_clear_doctor not found"
text = text.replace(old_clear_doctor, new_clear_doctor, 1)

# 3. Update load_draft_state
old_load_draft_doctor = '''        doctor_index = self.doctor_combo.findData(state.get("doctor_id"))
        if doctor_index >= 0:
            self.doctor_combo.setCurrentIndex(doctor_index)'''

new_load_draft_doctor = '''        did = state.get("doctor_id")
        if did is not None:
            doctor_index = self.doctor_combo.findData(did)
            if doctor_index >= 0:
                self.doctor_combo.setCurrentIndex(doctor_index)
            else:
                self._select_default_doctor()
        else:
            self._select_default_doctor()'''

assert old_load_draft_doctor in text, "old_load_draft_doctor not found"
text = text.replace(old_load_draft_doctor, new_load_draft_doctor, 1)

# 4. In SalesBillReviewDialog.__init__
old_dialog_init = '''        if self._is_editing:
            self._panel.load_invoice(invoice)
        else:
            self._panel.load_draft_state(panel.draft_state())'''

new_dialog_init = '''        if self._is_editing:
            self._panel.load_invoice(invoice)
        else:
            self._panel.load_draft_state(panel.draft_state())
            if self._panel.doctor_combo.currentData() is None:
                self._panel._select_default_doctor()'''

assert old_dialog_init in text, "old_dialog_init not found"
text = text.replace(old_dialog_init, new_dialog_init, 1)

with open('screens/counter_sale.py', 'w', encoding='utf-8', newline='') as f:
    f.write(text)

print("screens/counter_sale.py updated successfully!")
