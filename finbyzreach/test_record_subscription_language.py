"""Subscribing from a Lead/Contact sends the confirmation email in the chosen language."""
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach import subscription_preferences as prefs


class RecordSubscriptionLanguageTest(TestCase):
	def test_record_language_prefers_preferred_then_language_then_german(self):
		self.assertEqual(prefs.record_language(frappe._dict(custom_preferred_language="fr", language="de")), "fr")
		self.assertEqual(prefs.record_language(frappe._dict(language="it-CH")), "it")
		self.assertEqual(prefs.record_language(frappe._dict(language="es")), "de")
		self.assertEqual(prefs.record_language(frappe._dict()), "de")

	def _subscribe(self, language):
		doc = frappe._dict(check_permission=lambda *_: None)
		person = {"email": "person@example.com", "emails": ["person@example.com"], "topics": [], "language": "fr"}
		with patch.object(frappe, "get_doc", return_value=doc), \
				patch.object(frappe, "get_roles", return_value=["System Manager"]), \
				patch.object(prefs, "get_person_preferences", return_value=person), \
				patch.object(prefs, "request_subscription", return_value="Pending") as request:
			prefs.set_person_preference("Lead", "LEAD-1", "Marketing E-Mails", 1, "person@example.com", language)
		return request.call_args.kwargs["language"]

	def test_chosen_language_is_used(self):
		self.assertEqual(self._subscribe("it"), "it")

	def test_without_a_choice_the_person_language_is_used(self):
		self.assertEqual(self._subscribe(None), "fr")


class RepeatConfirmationTest(TestCase):
	def test_opening_the_link_again_after_confirming_is_not_an_error(self):
		doc = frappe._dict(status="Subscribed", confirmed_on="2026-11-17 12:00:00", email="person@example.com")
		with patch.object(frappe, "get_doc", return_value=doc):
			self.assertEqual(prefs.confirm("PREF-1", "any-token"), "person@example.com")

	def test_a_wrong_token_is_still_refused_while_pending(self):
		doc = frappe._dict(status="Pending", confirmed_on=None, email="person@example.com", confirmation_hash="x" * 64,
			confirmation_expires_on="2099-01-01 00:00:00")
		with patch.object(frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.PermissionError):
				prefs.confirm("PREF-1", "wrong-token")
