"""Approval releases only the selected held rows after authorization."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach.ai_email_outreach import approval


class TestApproval(unittest.TestCase):
	def test_selected_held_rows_preserve_branch_scheduling(self):
		rows = [
			SimpleNamespace(name="first", idx=1, status="Awaiting Approval"),
			SimpleNamespace(name="later", idx=2, status="Awaiting Approval"),
			SimpleNamespace(name="sent", idx=3, status="Sent"),
		]
		with patch.object(approval, "frappe", MagicMock()) as framework:
			framework.get_doc.return_value.communication_email = rows
			result = approval.approve_emails("OUT-1", rows=["later", "sent"])
			self.assertEqual(result["released"], 1)
			framework.only_for.assert_called_once_with("System Manager")
			framework.get_doc.return_value.check_permission.assert_called_once_with("write")
			framework.db.set_value.assert_called_once_with(
				"Communication Email", "later", "status", "Pending", update_modified=False
			)
			framework.db.commit.assert_not_called()

	def test_first_step_is_queued(self):
		with patch.object(approval, "frappe", MagicMock()) as framework:
			framework.get_doc.return_value.communication_email = [
				SimpleNamespace(name="first", idx=1, status="Awaiting Approval")
			]
			approval.approve_emails("OUT-1")
			framework.db.set_value.assert_called_once_with(
				"Communication Email", "first", "status", "Queued", update_modified=False
			)

	def test_empty_selection_releases_nothing(self):
		with patch.object(approval, "frappe", MagicMock()) as framework:
			framework.get_doc.return_value.communication_email = [
				SimpleNamespace(name="first", idx=1, status="Awaiting Approval")
			]
			self.assertEqual(approval.approve_emails("OUT-1", rows=[])["released"], 0)
			framework.db.set_value.assert_not_called()

	def test_permission_failure_cannot_release_rows(self):
		with patch.object(approval, "frappe", MagicMock()) as framework:
			framework.get_doc.return_value.check_permission.side_effect = frappe.PermissionError
			with self.assertRaises(frappe.PermissionError):
				approval.approve_emails("OUT-1")
			framework.db.set_value.assert_not_called()

	def test_invalid_row_selection_is_rejected(self):
		for rows in ({"first": True}, [1]):
			with self.subTest(rows=rows), patch.object(approval, "frappe", MagicMock()) as framework:
				framework.throw.side_effect = frappe.ValidationError
				with self.assertRaises(frappe.ValidationError):
					approval.approve_emails("OUT-1", rows=rows)
				framework.get_doc.assert_not_called()
