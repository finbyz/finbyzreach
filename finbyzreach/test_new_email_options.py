"""EM-16: creating an email from the list sets its type, language and folder."""
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach.email_template_builder import api


class NewEmailOptionsTest(TestCase):
	def _create(self, **options):
		inserted = []
		class Doc(dict):
			name = "Autumn"
			modified = "now"
			def insert(self, *a, **k):
				inserted.append(dict(self))
			def __setattr__(self, key, value):
				self[key] = value
		with patch.object(api, "_require_designer"), patch.object(frappe, "has_permission", return_value=True), \
				patch.object(frappe.db, "exists", side_effect=lambda dt, name=None: dt == "Email Folder" and name == "Campaigns"), \
				patch.object(frappe, "get_doc", side_effect=lambda *a: Doc(a[0]) if isinstance(a[0], dict) else frappe._dict()), \
				patch.object(api, "builder_route", return_value=["x"]), \
				patch("finbyzreach.consent.email_policy", return_value=frappe._dict(available=options.pop("available", True))):
			api.create_visual_template("Autumn", "Autumn offer", **options)
		return inserted[0]

	def test_type_language_and_folder_are_saved_on_the_new_email(self):
		doc = self._create(email_type="Newsletter", language="fr", folder="Campaigns")
		self.assertEqual((doc["custom_email_type"], doc["custom_language"], doc["custom_folder"]), ("Newsletter", "fr", "Campaigns"))

	def test_all_three_are_optional(self):
		doc = self._create()
		self.assertNotIn("custom_email_type", doc)
		self.assertNotIn("custom_language", doc)

	def test_unknown_language_unavailable_type_and_missing_folder_are_refused(self):
		for options in ({"language": "xx"}, {"email_type": "Gone", "available": False}, {"folder": "Nope"}):
			with self.assertRaises(frappe.ValidationError):
				self._create(**options)
