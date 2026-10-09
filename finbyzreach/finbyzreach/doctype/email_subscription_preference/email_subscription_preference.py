import hashlib

import frappe
from frappe.model.document import Document
from frappe.utils import validate_email_address


class EmailSubscriptionPreference(Document):
	def autoname(self):
		email = (self.email or "").strip().lower()
		validate_email_address(email, throw=True)
		self.email = email
		self.name = hashlib.sha256(f"{email}\0{self.subscription_topic}".encode()).hexdigest()

	def validate(self):
		self.email = (self.email or "").strip().lower()
		validate_email_address(self.email, throw=True)
		if self.status not in ("Pending", "Subscribed", "Unsubscribed"):
			frappe.throw("Invalid subscription status")
		