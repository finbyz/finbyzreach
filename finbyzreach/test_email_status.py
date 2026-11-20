"""EM-40: sending status per e-mail."""
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from finbyzreach import email_status


class TestEmailStatus(IntegrationTestCase):
	def test_campaign_status_is_shown_in_list_words_and_latest_campaign_wins(self):
		self.assertEqual(email_status.STATUS_OF_CAMPAIGN["Completed"], "Completed")
		self.assertEqual(email_status.STATUS_OF_CAMPAIGN["Preparing Audience"], "Sending")
		frappe.set_user("Administrator")
		statuses = email_status.sending_statuses()
		self.assertIsInstance(statuses, dict)
		self.assertTrue(set(statuses.values()) <= set(email_status.STATUSES))

	def test_filter_returns_drafts_for_emails_never_sent_and_rejects_unknown_status(self):
		frappe.set_user("Administrator")
		used = set(email_status.sending_statuses())
		drafts = set(email_status.emails_by_sending_status("Draft"))
		self.assertFalse(drafts & {name for name, value in email_status.sending_statuses().items() if value != "Draft"})
		self.assertTrue(drafts.isdisjoint({n for n in used if email_status.sending_statuses()[n] != "Draft"}))
		with self.assertRaises(frappe.ValidationError):
			email_status.emails_by_sending_status("Nonsense")


# Deterministic regression cases; no campaigns or emails need to be created.
class TestEmailStatusRegression(TestCase):
	def test_filter_and_badges_choose_the_same_most_recently_modified_campaign(self):
		from finbyzreach.email_template_builder.languages import email_usage

		rows = [
			frappe._dict(name="older-edited", campaign_name="Edited campaign", custom_email_template="Email",
				custom_broadcast_status="Preparing Audience", custom_start_on=None),
			frappe._dict(name="newer-created", campaign_name="New campaign", custom_email_template="Email",
				custom_broadcast_status="Completed", custom_start_on=None),
		]
		with patch.object(frappe, "get_all", return_value=rows) as get_all, \
			patch.object(frappe, "has_permission", side_effect=lambda dt, *a, **kw: dt != "Automation Workflow"):
			self.assertEqual(email_status.emails_by_sending_status("Sending"), ["Email"])
			self.assertEqual(email_status.emails_by_sending_status("Completed"), [])
			self.assertEqual(email_usage('["Email"]')["Email"]["status"], "Sending")
			for call in get_all.call_args_list:
				self.assertEqual(call.kwargs["order_by"], "modified desc, name desc")
				self.assertEqual(call.kwargs["limit_page_length"], 0)

	def test_draft_includes_unused_emails_and_campaign_drafts(self):
		def get_all(doctype, **kwargs):
			if doctype == "Email Template":
				return ["Unused", "Campaign draft", "Sent"]
			return [
				frappe._dict(custom_email_template="Campaign draft", custom_broadcast_status="Draft"),
				frappe._dict(custom_email_template="Sent", custom_broadcast_status="Completed"),
			]

		with patch.object(frappe, "get_all", side_effect=get_all), patch.object(frappe, "has_permission", return_value=True):
			self.assertEqual(email_status.emails_by_sending_status("Draft"), ["Unused", "Campaign draft"])
