"""EM-14: saved themes."""
from frappe.tests import IntegrationTestCase


class TestSavedThemes(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		import frappe

		frappe.set_user("Administrator")

	def test_theme_can_be_saved_listed_updated_and_deleted(self):
		import frappe

		from finbyzreach.email_template_builder import api

		name = f"ZZTEST Theme {frappe.generate_hash(length=5)}"
		saved = api.save_theme(name, {"body_background": "#101010", "text_color": "#fafafa", "dark_mode": "off", "evil_key": "x", "link_color": "not a colour"})
		self.assertEqual(saved["settings"]["body_background"], "#101010")
		self.assertNotIn("evil_key", saved["settings"])
		self.assertNotEqual(saved["settings"]["link_color"], "not a colour")  # replaced by the default, not stored as typed
		again = api.save_theme(name, {"body_background": "#202020"})
		self.assertEqual(again["settings"], {"body_background": "#202020"})
		listed = {row["theme_name"]: row["settings"] for row in api.list_themes()}
		self.assertEqual(listed[name], {"body_background": "#202020"})
		self.assertEqual(api.delete_theme(name), {"deleted": name})
		self.assertNotIn(name, {row["theme_name"] for row in api.list_themes()})

	def test_theme_needs_a_name(self):
		import frappe

		from finbyzreach.email_template_builder import api

		with self.assertRaises(frappe.ValidationError):
			api.save_theme("  ", {"body_background": "#101010"})
