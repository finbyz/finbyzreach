"""EM-42: who may read, edit, send and delete e-mails.

Email Viewer    reads e-mails, campaigns and statistics, changes nothing
Email Designer  edits e-mails in the builder (role from the builder module)
Email Sender    schedules, pauses, resumes and cancels campaigns; needs read access to e-mails
Email Manager   deletes e-mails and campaigns; give it together with Designer or Sender
"""
import frappe
from frappe.permissions import add_permission, update_permission_property

MATRIX = {
	"Email Viewer": {
		"Email Template": ("read",),
		"Campaign": ("read",),
		"Email Campaign": ("read",),
	},
	"Email Sender": {
		"Email Template": ("read",),
		"Campaign": ("read", "write", "create", "email"),
		"Email Campaign": ("read",),
	},
	"Email Manager": {
		"Email Template": ("read", "delete"),
		"Campaign": ("read", "delete"),
	},
}


def ensure_email_roles():
	"""Create the roles and their permissions; safe to run on every migrate."""
	for role, doctypes in MATRIX.items():
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
		for doctype, rights in doctypes.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			for right in rights:
				add_permission(doctype, role, 0)
				update_permission_property(doctype, role, 0, right, 1)
