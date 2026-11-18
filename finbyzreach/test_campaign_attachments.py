"""EM-18: campaign attachments are limited to 12 MB together and go with every email."""
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach import email_marketing


def row(name, size):
	return frappe._dict(name=name, file_name=f"{name}.pdf", file_size=size)


class CampaignAttachmentsTest(TestCase):
	def test_files_within_twelve_megabytes_pass(self):
		self.assertEqual(email_marketing.check_attachment_limit([row("A", 5 * 1048576), row("B", 7 * 1048576)]), 12 * 1048576)

	def test_files_over_twelve_megabytes_together_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			email_marketing.check_attachment_limit([row("A", 8 * 1048576), row("B", 5 * 1048576)])

	def test_too_many_files_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			email_marketing.check_attachment_limit([row(str(i), 1024) for i in range(email_marketing.MAX_ATTACHMENT_FILES + 1)])

	def test_mail_attachments_use_the_file_names_of_the_campaign(self):
		with patch.object(email_marketing, "campaign_attachment_files", return_value=[row("FILE-1", 10), row("FILE-2", 20)]):
			self.assertEqual(email_marketing._mail_attachments("CAMP"), [{"fid": "FILE-1"}, {"fid": "FILE-2"}])
		with patch.object(email_marketing, "campaign_attachment_files", return_value=[]):
			self.assertEqual(email_marketing._mail_attachments("CAMP"), [])

	def test_saving_keeps_listed_files_and_removes_the_others(self):
		campaign = frappe._dict(name="CAMP")
		files = {"NEW": frappe._dict(name="NEW", file_name="new.pdf", file_size=100, attached_to_doctype=None, attached_to_name=None, owner=frappe.session.user, is_folder=0)}
		with patch.object(frappe.db, "get_value", side_effect=lambda doctype, name, *a, **k: files.get(name)), \
				patch.object(email_marketing, "campaign_attachment_files", return_value=[row("OLD", 50)]), \
				patch.object(frappe, "delete_doc") as delete, patch.object(frappe.db, "set_value") as set_value:
			result = email_marketing.set_campaign_attachments(campaign, ["NEW"])
		delete.assert_called_once_with("File", "OLD", ignore_permissions=True)
		self.assertEqual(set_value.call_args.args[:3], ("File", "NEW", {"attached_to_doctype": "Campaign", "attached_to_name": "CAMP"}))
		self.assertEqual(result, [{"name": "NEW", "file_name": "new.pdf", "file_size": 100}])
