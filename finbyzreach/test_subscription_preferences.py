import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach import subscription_preferences as preferences
from finbyzreach import email_marketing
from finbyzreach import legacy_subscription_reconfirmation as legacy


class TestSubscriptionPreferences(unittest.TestCase):
	def test_compliance_footer_stays_inside_visual_email(self):
		html = email_marketing._insert_email_footer("<html><body>Hello</body></html>", "<a>Preferences</a>")
		self.assertIn("Hello<a>Preferences</a></body>", html)
		self.assertEqual(html.count("Preferences"), 1)

	def test_preference_center_link_keeps_its_signature(self):
		url = "https://example.com/manage_subscriptions?campaign_recipient=one&_signature=signed"
		campaign = SimpleNamespace(
			custom_enable_click_tracking=1,
			custom_utm_source="campaign",
			custom_utm_medium="email",
			custom_utm_campaign="test",
		)
		html = email_marketing.decorate_campaign_links(f'<a href="{url}">Preferences</a>', campaign, "one")
		self.assertIn(url.replace("&", "&amp;"), html)
		self.assertNotIn("utm_source", html)

	@patch.object(preferences, "request_subscription", return_value="Pending")
	@patch.object(preferences, "unsubscribe")
	@patch.object(preferences, "statuses")
	@patch.object(preferences.frappe, "get_all")
	def test_saving_visible_options_preserves_hidden_opt_outs(self, get_all, statuses, unsubscribe, request):
		get_all.return_value = ["Marketing E-Mails", "News"]
		statuses.return_value = {
			"Marketing E-Mails": "Subscribed",
			"Old disabled topic": "Unsubscribed",
		}
		result = preferences.save_selection(
			"person@example.com", ["News"], ["Marketing E-Mails", "News"]
		)
		unsubscribe.assert_called_once_with("person@example.com", "Marketing E-Mails", "Preference center")
		request.assert_called_once_with("person@example.com", "News", "Preference center")
		self.assertEqual(result, {"Marketing E-Mails": "Unsubscribed", "News": "Pending"})

	@patch.object(preferences, "_sign_message", return_value="signed")
	@patch.object(preferences.frappe, "get_doc")
	@patch.object(preferences.frappe, "db", new=SimpleNamespace(exists=lambda *args: True))
	def test_signed_link_uses_actual_recipient_email(self, get_doc, sign):
		get_doc.return_value = SimpleNamespace(custom_normalized_email="Person@Example.com", custom_recipient_email=None)
		recipient, email = preferences.signed_recipient(
			"recipient-1", "campaign_recipient=recipient-1&email=person%40example.com&_signature=signed"
		)
		self.assertEqual(email, "person@example.com")
		self.assertIs(recipient, get_doc.return_value)

	@patch.object(preferences.frappe, "throw", side_effect=PermissionError("bad signature"))
	@patch.object(preferences, "_sign_message", return_value="signed")
	def test_tampered_preference_link_is_rejected(self, sign, throw):
		with self.assertRaises(PermissionError):
			preferences.signed_recipient("recipient-1", "campaign_recipient=recipient-1&_signature=changed")

	@patch.object(preferences, "statuses", return_value={"News": "Pending"})
	def test_pending_doi_is_not_a_sendable_subscription(self, statuses):
		self.assertFalse(preferences.is_subscribed("person@example.com", "News"))

	@patch.object(preferences, "request_subscription")
	@patch.object(preferences, "unsubscribe")
	@patch.object(preferences, "statuses", return_value={"News": "Pending"})
	@patch.object(preferences.frappe, "get_all", return_value=["News"])
	def test_deselecting_pending_subscription_revokes_token(self, get_all, statuses, unsubscribe, request):
		result = preferences.save_selection("person@example.com", [], ["News"])
		unsubscribe.assert_called_once_with("person@example.com", "News", "Preference center")
		request.assert_not_called()
		self.assertEqual(result, {"News": "Unsubscribed"})

	@patch.object(preferences, "now_datetime", return_value=datetime(2026, 10, 13, 12, 0))
	@patch.object(preferences, "_topic")
	@patch.object(preferences, "statuses", return_value={"News": "Pending"})
	@patch.object(preferences.frappe, "get_all", return_value=["News"])
	@patch.object(preferences.frappe, "db", new=SimpleNamespace(exists=lambda *args: True))
	def test_deselection_invalidates_original_confirmation_token(self, get_all, statuses, topic, now):
		import hashlib

		token = "old-confirmation-token"
		preference = SimpleNamespace(
			status="Pending", confirmation_hash=hashlib.sha256(token.encode()).hexdigest(),
			confirmation_expires_on=now.return_value + timedelta(days=1),
			email="person@example.com", subscription_topic="News", consent_source="Preference center",
			is_new=lambda: False, save=MagicMock(),
		)
		event = MagicMock()
		with (
			patch.object(preferences, "preference_name", return_value="pref-1"),
			patch.object(preferences.frappe, "get_doc", side_effect=lambda *args, **kwargs: preference if args[0] == preferences.PREFERENCE_DOCTYPE else event),
			patch.object(preferences.frappe, "throw", side_effect=PermissionError("revoked")),
		):
			preferences.save_selection("person@example.com", [], ["News"])
			self.assertEqual(preference.status, "Unsubscribed")
			self.assertIsNone(preference.confirmation_hash)
			self.assertIsNone(preference.confirmation_expires_on)
			with self.assertRaises(PermissionError):
				preferences.confirm("pref-1", token)
		preference.save.assert_called_once_with(ignore_permissions=True)

	@patch.object(preferences, "_ensure_public_subscriber_lead")
	@patch.object(preferences, "_save")
	@patch.object(preferences, "now_datetime", return_value=datetime(2026, 10, 12, 12, 0))
	@patch.object(preferences.frappe, "get_doc")
	def test_public_confirmation_creates_a_lead_after_consent(self, get_doc, now, save, ensure_lead):
		import hashlib
		token = "valid-token"
		get_doc.return_value = SimpleNamespace(
			status="Pending", confirmation_hash=hashlib.sha256(token.encode()).hexdigest(),
			confirmation_expires_on=now.return_value + timedelta(days=1),
			email="person@example.com", subscription_topic="News", consent_source="Public registration",
		)
		self.assertEqual(preferences.confirm("preference", token), "person@example.com")
		save.assert_called_once_with("person@example.com", "News", "Subscribed", "Double opt-in confirmation")
		ensure_lead.assert_called_once_with("person@example.com")

	@patch.object(preferences.frappe, "get_doc")
	@patch.object(preferences.frappe, "db", new=MagicMock())
	def test_public_subscriber_lead_is_created_only_when_missing(self, get_doc):
		db = preferences.frappe.db
		db.exists.return_value = None
		lead = MagicMock()
		get_doc.return_value = lead
		preferences._ensure_public_subscriber_lead("person@example.com")
		get_doc.assert_called_once_with({"doctype": "Lead", "email_id": "person@example.com", "status": "Lead"})
		lead.insert.assert_called_once_with(ignore_permissions=True)
		db.exists.return_value = "CRM-LEAD-1"
		preferences._ensure_public_subscriber_lead("person@example.com")
		self.assertEqual(get_doc.call_count, 1)

	@patch.object(email_marketing.frappe, "db", new=MagicMock())
	def test_disabled_content_topic_blocks_scheduled_delivery(self):
		db = email_marketing.frappe.db
		db.get_value.side_effect = [0, 1]
		recipient = SimpleNamespace(custom_unsubscribed=0)
		campaign = frappe._dict(custom_subscription_topic="Marketing E-Mails", custom_content_topic="News")
		self.assertEqual(
			email_marketing._current_recipient_exclusion(recipient, campaign),
			"Content topic unavailable or disabled",
		)
		db.get_value.assert_any_call("Subscription Topic", "News", "disabled")

	@patch.object(email_marketing, "_mark_campaign_recipient_unsubscribed")
	@patch.object(preferences, "signed_recipient", return_value=(SimpleNamespace(campaign_name="Campaign-1"), "person@example.com"))
	@patch.object(preferences, "unsubscribe")
	@patch.object(email_marketing.frappe, "respond_as_web_page")
	@patch.object(email_marketing.frappe, "db", new=MagicMock())
	@patch.object(email_marketing.frappe, "request", new=SimpleNamespace(query_string=b"campaign_recipient=EC-1&_signature=valid"), create=True)
	@patch.object(email_marketing.frappe, "form_dict", new=SimpleNamespace(campaign_recipient="EC-1", get=lambda key: "EC-1"))
	def test_get_unsubscribe_commits_preference_and_campaign_update(
		self, respond, unsubscribe, signed_recipient, mark
	):
		db = email_marketing.frappe.db
		db.get_value.return_value = "Marketing E-Mails"
		email_marketing.unsubscribe_marketing()
		unsubscribe.assert_called_once_with("person@example.com", "Marketing E-Mails")
		mark.assert_called_once_with(signed_recipient.return_value[0])
		db.commit.assert_called_once_with()
		respond.assert_called_once()

	@patch.object(legacy, "request_subscription")
	@patch.object(legacy, "test_recipient_exclusion", return_value=None)
	@patch.object(legacy, "statuses", return_value={})
	@patch.object(legacy.frappe, "get_all")
	@patch.object(legacy.frappe, "db", new=SimpleNamespace(
		get_value=lambda *args, **kwargs: SimpleNamespace(
			email_id="PERSON@example.com", unsubscribed=0, disabled=0, status="Open"
		),
		exists=lambda *args, **kwargs: False,
	))
	def test_legacy_preview_requires_reconfirmation(self, get_all, statuses, exclusion, request):
		get_all.side_effect = [["News"], [SimpleNamespace(parent="LEAD-1", subscription="Old News")]]
		result = legacy.reconfirm_legacy_leads(topic_mapping={"Old News": "News"})
		self.assertEqual(result["eligible"], 1)
		self.assertEqual(result["confirmation_requested"], 0)
		request.assert_not_called()


if __name__ == "__main__":
	unittest.main()
