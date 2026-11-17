"""EM-28: test emails to several addresses; the send guard still applies."""
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach.finbyzreach.page.email_campaign_studio import email_campaign_studio as studio


class StudioTestSendTest(TestCase):
	def test_recipient_list_merges_json_text_and_dedupes(self):
		emails = studio._test_recipient_list('["Lena@Megasol.ch", "team@megasol.ch"]', "lena@megasol.ch, other@example.com\nthird@example.com")
		self.assertEqual(emails, ["lena@megasol.ch", "team@megasol.ch", "other@example.com", "third@example.com"])

	def test_recipient_list_limits_and_validates(self):
		with self.assertRaises(frappe.ValidationError):
			studio._test_recipient_list([], "")
		with self.assertRaises(frappe.ValidationError):
			studio._test_recipient_list([f"user{i}@example.com" for i in range(11)])
		with self.assertRaises(frappe.ValidationError):
			studio._test_recipient_list(["not-an-address"])

	def test_blocked_addresses_are_skipped_and_others_still_receive_the_test(self):
		reasons = {"bounced@example.com": "Hard bounce"}
		sent = {}
		def fake_sendmail(**kwargs):
			sent.update(kwargs)
			return frappe._dict(name="EQ-1")
		account = frappe._dict(email_id="marketing@megasol.ch", enable_outgoing=1, check_permission=lambda *_: None)
		lead = frappe._dict(doctype="Lead", name="LEAD-1")
		with patch.object(studio, "_check_permission"), \
				patch.object(studio.email_marketing, "test_recipient_exclusion", side_effect=lambda email, *_: reasons.get(email)), \
				patch.object(studio, "_check_test_email_rate_limit"), \
				patch.object(frappe, "get_doc", return_value=account), \
				patch.object(studio, "_sample_document", return_value=(lead, {})), \
				patch.object(studio, "get_campaign_snapshot", return_value=frappe._dict(mode="Visual", subject="S", html="<p>x</p>", reference_doctype=None)), \
				patch.object(studio, "render_campaign_snapshot", return_value=frappe._dict(subject="S", html="<p>x</p>")), \
				patch.object(studio.email_marketing, "decorate_campaign_links", side_effect=lambda html, *a, **k: html), \
				patch.object(studio, "get_url", return_value="https://example.com/view"), \
				patch.object(frappe, "sendmail", side_effect=fake_sendmail):
			result = studio.send_test(
				payload={"email_account": "Marketing", "email_template": "T", "campaign_title": "Test", "audience_doctype": "Lead"},
				recipients='["ok@example.com", "bounced@example.com"]', sample_lead="LEAD-1",
			)
		self.assertEqual(sent["recipients"], ["ok@example.com"])
		self.assertEqual(result["recipients"], ["ok@example.com"])
		self.assertEqual(result["blocked"], [{"email": "bounced@example.com", "reason": "Hard bounce"}])
