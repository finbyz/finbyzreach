import frappe
from frappe import _
from frappe.model.document import Document


class EmailBuilderRevision(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("Email Builder revisions are immutable"))

	def on_trash(self):
		if self.flags.get("email_builder_retention"):
			return
		if "System Manager" not in frappe.get_roles():
			frappe.throw(_("Only a System Manager can delete builder revisions"), frappe.PermissionError)
