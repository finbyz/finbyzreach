# Copyright (c) 2026, Finbyz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class OptinImportLog(Document):
	def validate(self):
		if self.is_new() or self.status == "Draft":
			return
		before = self.get_doc_before_save()
		if before and any(before.get(field) != self.get(field) for field in ("import_file", "leads", "contacts", "customers", "filter_doctype", "record_filters", "customer_contacts", "consent_source", "default_topics", "default_language", "default_opted_in_on")):
			frappe.throw(_("A started opt-in import cannot be changed. Start a new import instead."))

	def on_trash(self):
		if self.status in ("Queued", "Running"):
			frappe.throw(_("Wait until the import has finished"))
