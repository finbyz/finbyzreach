import frappe
from frappe.model.document import Document
from frappe.utils.jinja import validate_template


class EmailTemplateMaster(Document):
	@property
	def response_(self):
		return self.response_html if self.use_html else self.response

	def validate(self):
		from finbyzreach.email_template_builder.languages import validate_metadata
		validate_metadata(self)
		validate_template(self.subject)
		validate_template(self.response_)
		if self.folder and not frappe.db.exists("Email Template Folder", self.folder):
			frappe.throw(f"Email Template Folder {self.folder} does not exist")
