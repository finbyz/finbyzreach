# Copyright (c) 2026, Finbyz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SubscriptionTopic(Document):
	def validate(self):
		if self.category == "System" or self.topic_name == "Transactional":
			if self.topic_name != "Transactional" or self.category != "System" or self.disabled or self.consent_required or self.double_opt_in or self.deliver_while_pending:
				frappe.throw(_("Transactional is a protected system email type"))
		if self.category == "Topic":
			self.consent_required = self.double_opt_in = self.deliver_while_pending = 0
		if not self.consent_required or not self.double_opt_in:
			self.deliver_while_pending = 0
		languages = [row.language for row in self.translations or []]
		if len(languages) != len(set(languages)):
			frappe.throw(_("Add only one translation per language"))

	def on_trash(self):
		if self.name == "Transactional":
			frappe.throw(_("The system Transactional email type cannot be deleted"))
