"""EM-40: sending status per e-mail."""
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
