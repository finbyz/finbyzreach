# Copyright (c) 2026, Finbyz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class UnsubscribeTopicMultiSelect(Document):
	def on_trash(self):
		frappe.throw(
			_(
				"Unsubscribe Topics cannot be deleted directly. "
				"A verified resubscribe process is required."
			),
			frappe.ValidationError,
		)
