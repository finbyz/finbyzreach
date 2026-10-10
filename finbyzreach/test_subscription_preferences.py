import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
