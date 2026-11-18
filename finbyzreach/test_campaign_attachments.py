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
		self.assertEqual(
			set_value.call_args.args[:3],
			("File", "NEW", {"attached_to_doctype": "Campaign", "attached_to_name": "CAMP", "attached_to_field": email_marketing.MAIL_ATTACHMENT_FIELD}),
		)
		self.assertEqual(result, [{"name": "NEW", "file_name": "new.pdf", "file_size": 100}])

	def _rows_for(self, file_row, campaign_name="CAMP"):
		with patch.object(frappe.db, "get_value", return_value=file_row):
			return email_marketing.studio_attachment_rows([file_row.name], campaign_name)

	def test_a_file_attached_to_another_document_is_refused_even_for_its_owner(self):
		quotation_file = frappe._dict(name="Q", file_name="q.pdf", file_size=10, attached_to_doctype="Quotation", attached_to_name="QTN-1", owner=frappe.session.user, is_folder=0)
		with self.assertRaises(frappe.PermissionError):
			self._rows_for(quotation_file)

	def test_an_unattached_file_of_another_user_is_refused(self):
		foreign = frappe._dict(name="F", file_name="f.pdf", file_size=10, attached_to_doctype=None, attached_to_name=None, owner="someone.else@example.com", is_folder=0)
		with self.assertRaises(frappe.PermissionError):
			self._rows_for(foreign)

	def test_a_campaign_sidebar_file_is_refused(self):
		sidebar = frappe._dict(name="S", file_name="s.pdf", file_size=10, attached_to_doctype="Campaign", attached_to_name="CAMP", attached_to_field=None, owner=frappe.session.user, is_folder=0)
		with self.assertRaises(frappe.PermissionError):
			self._rows_for(sidebar)

	def test_own_upload_and_the_campaign_mail_attachment_pass(self):
		upload = frappe._dict(name="U", file_name="u.pdf", file_size=10, attached_to_doctype=None, attached_to_name=None, owner=frappe.session.user, is_folder=0)
		mail = frappe._dict(name="M", file_name="m.pdf", file_size=10, attached_to_doctype="Campaign", attached_to_name="CAMP", attached_to_field=email_marketing.MAIL_ATTACHMENT_FIELD, owner="other@example.com", is_folder=0)
		self.assertEqual([r.name for r in self._rows_for(upload)], ["U"])
		self.assertEqual([r.name for r in self._rows_for(mail)], ["M"])

	def test_only_marked_files_count_as_mail_attachments(self):
		with patch.object(frappe, "get_all", return_value=[]) as get_all:
			email_marketing.campaign_attachment_files("CAMP")
		self.assertEqual(get_all.call_args.kwargs["filters"]["attached_to_field"], email_marketing.MAIL_ATTACHMENT_FIELD)
