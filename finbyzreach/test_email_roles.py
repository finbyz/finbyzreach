"""EM-42: the e-mail roles and what each may do."""
import frappe
from frappe.tests import IntegrationTestCase

from finbyzreach import email_roles


class TestEmailRoles(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		email_roles.ensure_email_roles()

	def _rights(self, doctype, role):
		return {
			right for right in ("read", "write", "create", "delete", "email")
			if frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}, right)
		}

	def test_viewer_only_reads(self):
		self.assertEqual(self._rights("Campaign", "Email Viewer"), {"read"})
		self.assertEqual(self._rights("Email Template", "Email Viewer"), {"read"})

	def test_sender_can_send_campaigns_but_not_edit_or_delete_emails(self):
		self.assertEqual(self._rights("Campaign", "Email Sender"), {"read", "write", "create", "email"})
		self.assertEqual(self._rights("Email Template", "Email Sender"), {"read"})

	def test_manager_deletes(self):
		self.assertIn("delete", self._rights("Email Template", "Email Manager"))
		self.assertIn("delete", self._rights("Campaign", "Email Manager"))

	def test_running_it_again_changes_nothing(self):
		before = frappe.db.count("Custom DocPerm", {"role": ["in", list(email_roles.MATRIX)]})
		email_roles.ensure_email_roles()
		self.assertEqual(frappe.db.count("Custom DocPerm", {"role": ["in", list(email_roles.MATRIX)]}), before)
