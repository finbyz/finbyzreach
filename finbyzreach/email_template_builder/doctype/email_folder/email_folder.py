import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet

ROOT_FOLDER = "All Email Folders"


class EmailFolder(NestedSet):
    nsm_parent_field = "parent_email_folder"
    allow_root_deletion = False

    def validate(self):
        before = self.get_doc_before_save()
        if before:
            for field in ("lft", "rgt", "old_parent"):
                self.set(field, before.get(field))
        self.is_group = 1
        if self.name == ROOT_FOLDER or self.folder_name == ROOT_FOLDER:
            if self.parent_email_folder:
                frappe.throw(_("The root email folder cannot have a parent"))
        elif not self.parent_email_folder:
            self.parent_email_folder = ROOT_FOLDER

    def on_update(self):
        super().on_update()
        self.validate_one_root()

    def before_rename(self, olddn, newdn, merge=False):
        if olddn == ROOT_FOLDER:
            frappe.throw(_("The root email folder cannot be renamed"))
        super().before_rename(olddn, newdn, merge=merge)


def on_doctype_update():
    frappe.db.add_index("Email Folder", ["lft", "rgt"])
