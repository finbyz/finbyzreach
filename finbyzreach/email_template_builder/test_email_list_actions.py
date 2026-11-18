"""EM-40 / EM-41: usage shown on the Emails list, duplicate and bulk move."""
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach.email_template_builder import languages


class EmailListActionsTest(TestCase):
	def test_usage_reports_the_latest_campaign_status_and_workflows(self):
		campaigns = [
			frappe._dict(name="C-2", campaign_name="Winter promo", custom_email_template="Mail A", custom_broadcast_status="Sending", custom_start_on="2026-11-16 08:00:00", modified="2026-11-17"),
			frappe._dict(name="C-1", campaign_name="Old", custom_email_template="Mail A", custom_broadcast_status="Completed", custom_start_on="2026-10-01 08:00:00", modified="2026-10-02"),
		]
		def get_all(doctype, **kwargs):
			return campaigns if doctype == "Campaign" else [frappe._dict(workflow="WF-1")]
		with patch.object(frappe, "has_permission", return_value=True), patch.object(frappe, "get_all", side_effect=get_all), \
				patch.object(frappe.db, "exists", return_value=True), patch.object(frappe.db, "get_value", return_value="Trade fair follow-up"):
			result = languages.email_usage('["Mail A", "Mail B"]')
		self.assertEqual(result["Mail A"]["status"], "Sending")
		self.assertEqual(result["Mail A"]["send_time"], "2026-11-16 08:00:00")
		self.assertEqual({u["kind"] for u in result["Mail A"]["used_in"]}, {"campaign", "workflow"})

	def test_usage_rejects_a_bad_payload(self):
		with self.assertRaises(frappe.ValidationError):
			languages.email_usage('"not a list"')

	def test_bulk_move_is_limited_and_checks_each_email(self):
		with self.assertRaises(frappe.ValidationError):
			languages.move_emails_to_folder("[]")
		with self.assertRaises(frappe.ValidationError):
			languages.move_emails_to_folder([f"E{i}" for i in range(201)])
