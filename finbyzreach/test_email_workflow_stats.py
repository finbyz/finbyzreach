"""EM-27: workflow e-mails are counted separately from campaigns."""
import frappe
from frappe.tests import IntegrationTestCase

from finbyzreach.finbyzreach.page.email_campaign_report import email_campaign_report as report


class TestWorkflowEmailStatistics(IntegrationTestCase):
	def test_workflow_summary_has_its_own_counts_and_does_not_change_campaign_totals(self):
		frappe.set_user("Administrator")
		campaigns_before = report.get_overview("90")["summary"]["sent"]
		result = report.get_workflow_overview("90")
		self.assertEqual(set(result["summary"]), {"sent", "opened", "clicked", "hard_bounce", "soft_bounce", "spam", "unsubscribed", "open_rate", "click_rate"})
		self.assertGreaterEqual(result["summary"]["sent"], 0)
		self.assertIn("label", result["range"])
		self.assertEqual(report.get_overview("90")["summary"]["sent"], campaigns_before)

	def test_workflow_email_with_an_open_is_counted_once_in_its_own_row(self):
		frappe.set_user("Administrator")
		before = report.get_workflow_overview("90")["summary"]
		now = frappe.utils.now_datetime()
		frappe.get_doc({
			"doctype": "Automation Effect Ledger", "effect_key": f"zztest-{frappe.generate_hash(length=8)}", "status": "COMPLETED",
			"result_json": frappe.as_json({"email_queue": "Q-ZZ", "communication": "COMM-ZZ-NOPE", "email_template": "ZZ Template"}),
			"completed_at": now, "request_hash": frappe.generate_hash(length=16),
		}).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
		after = report.get_workflow_overview("90")["summary"]
		self.assertEqual(after["sent"], before["sent"] + 1)
