import frappe
from frappe.utils.nestedset import NestedSet


ROOT_FOLDER = "All Email Template Folders"


class EmailTemplateFolder(NestedSet):
	nsm_parent_field = "parent_email_template_folder"

	def validate(self):
		self.is_group = 1
		if self.folder_name != ROOT_FOLDER and not self.parent_email_template_folder:
			self.parent_email_template_folder = ROOT_FOLDER

	def on_update(self):
		super().on_update()
		self.validate_one_root()


def on_doctype_update():
	frappe.db.add_index("Email Template Folder", ["lft", "rgt"])
