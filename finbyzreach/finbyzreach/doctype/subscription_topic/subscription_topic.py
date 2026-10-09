# Copyright (c) 2026, Finbyz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SubscriptionTopic(Document):
	def validate(self):
		languages = [row.language for row in self.translations or []]
		if len(languages) != len(set(languages)):
			frappe.throw(_("Add only one translation per language"))
