"""Studio title validation; no records, emails or background jobs are created."""
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from finbyzreach.finbyzreach.page.email_campaign_studio import email_campaign_studio as studio


class TestStudioCampaignTitle(TestCase):
	def test_title_normalization_and_length_do_not_silently_truncate(self):
		self.assertEqual(studio._normalized_campaign_title("  Newsletter  "), "Newsletter")
		for title in ("", "   ", "a" * 141):
			with self.subTest(title=title), self.assertRaises(frappe.ValidationError):
				studio._normalized_campaign_title(title)

	def test_availability_excludes_only_the_document_being_edited(self):
		with patch.object(frappe.db, "exists", return_value=False) as exists:
			self.assertTrue(studio._campaign_title_available("Newsletter", "CAM-1"))
		exists.assert_called_once_with("Campaign", {"campaign_name": "Newsletter", "name": ["!=", "CAM-1"]})

	def test_endpoint_checks_source_permission_and_returns_no_other_campaign_details(self):
		doc = Mock()
		with patch.object(frappe, "has_permission") as permission, patch.object(frappe, "get_doc", return_value=doc), patch.object(frappe.db, "exists", return_value=True):
			self.assertEqual(studio.check_campaign_title("Newsletter", "CAM-1"), {"available": False})
		permission.assert_called_once_with("Campaign", "write", throw=True)
		doc.check_permission.assert_called_once_with("write")

	def test_direct_save_rejects_duplicate_before_creating_utm_or_campaign(self):
		with patch.object(studio, "_check_permission"), patch.object(studio, "_audience_context"), patch.object(studio, "_campaign_values", return_value={"campaign_name": "Taken"}), patch.object(frappe.db, "exists", return_value=True), patch.object(studio, "_ensure_utm_campaign") as utm, patch.object(frappe, "get_doc") as get_doc:
			with self.assertRaises(frappe.ValidationError):
				studio.create_campaign({"campaign_title": "Taken"}, launch="draft")
		utm.assert_not_called()
		get_doc.assert_not_called()
