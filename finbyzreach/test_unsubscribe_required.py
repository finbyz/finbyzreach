"""EM-11: a marketing email without an unsubscribe link cannot be scheduled."""
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach import consent, email_marketing


class UnsubscribeRequiredTest(TestCase):
	def test_detects_the_unsubscribe_variable_in_template_source(self):
		self.assertTrue(consent.email_has_unsubscribe('<a href="{{ unsubscribe_url | e }}">Unsubscribe</a>'))
		self.assertTrue(consent.email_has_unsubscribe("{% if unsubscribe_url is defined %}x{% endif %}"))
		self.assertFalse(consent.email_has_unsubscribe("<p>Hello</p>"))
		self.assertFalse(consent.email_has_unsubscribe(None))

	def _preflight(self, topic, html):
		campaign = frappe._dict(custom_subscription_topic=topic, custom_email_template="T", custom_subject_override=None,
			custom_broadcast_status="Draft", custom_audience_doctype="Lead", custom_personalization_doctype="Lead",
			custom_lead_filters_json="[]", custom_exclude_filters_json="[]", custom_exclude_email_groups_json="[]",
			check_permission=lambda *_: None, name="C-1")
		snapshot = frappe._dict(html=html, reference_doctype="")
		with patch.object(frappe.db, "exists", return_value=False), \
				patch.object(email_marketing, "validate_campaign"), \
				patch.object(email_marketing, "validate_lead_filter_groups"), \
				patch.object(email_marketing, "validate_excluded_email_groups"), \
				patch.object(email_marketing, "calculate_batch_slots"), \
				patch.object(email_marketing, "get_campaign_snapshot", return_value=snapshot):
			return email_marketing.validate_schedule_preflight(campaign)

	def test_marketing_email_without_link_is_refused_with_a_clear_message(self):
		with self.assertRaises(frappe.ValidationError):
			self._preflight("Marketing E-Mails", "<p>Hello</p>")

	def test_marketing_email_with_link_and_transactional_email_pass(self):
		self.assertTrue(self._preflight("Marketing E-Mails", '<a href="{{ unsubscribe_url }}">x</a>'))
		self.assertTrue(self._preflight("Transactional", "<p>Order confirmed</p>"))


class EmailSetupUnsubscribeTest(TestCase):
	def test_email_setup_reports_whether_the_email_has_an_unsubscribe_link(self):
		from unittest.mock import patch
		from finbyzreach.email_template_builder import languages
		with patch.object(languages, "get_campaign_snapshot", create=True), \
				patch("finbyzreach.email_template_builder.services.get_campaign_snapshot", return_value=frappe._dict(html='<a href="{{ unsubscribe_url }}">x</a>')):
			self.assertTrue(languages._has_unsubscribe("Mail"))
		with patch("finbyzreach.email_template_builder.services.get_campaign_snapshot", return_value=frappe._dict(html="<p>Hello</p>")):
			self.assertFalse(languages._has_unsubscribe("Mail"))
		with patch("finbyzreach.email_template_builder.services.get_campaign_snapshot", side_effect=Exception("broken")):
			self.assertIsNone(languages._has_unsubscribe("Mail"))
