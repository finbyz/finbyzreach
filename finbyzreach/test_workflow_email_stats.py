"""EM-27: workflow e-mail statistics are counted per workflow and e-mail."""
import frappe
from frappe.tests import IntegrationTestCase

from finbyzreach import workflow_email_stats as stats


class TestWorkflowEmailStats(IntegrationTestCase):
	def test_aggregate_counts_each_email_once_per_event_kind(self):
		sent = [
			{"workflow": "W1", "workflow_title": "Welcome", "email_template": "Hello", "communication": "C1"},
			{"workflow": "W1", "workflow_title": "Welcome", "email_template": "Hello", "communication": "C2"},
			{"workflow": "W2", "workflow_title": "Nurture", "email_template": "Tips", "communication": "C3"},
		]
		events = [
			{"communication": "C1", "event_type": "Opened"},
			{"communication": "C1", "event_type": "Opened"},  # opened twice, counted once
			{"communication": "C1", "event_type": "Clicked"},
			{"communication": "C2", "event_type": "Soft-Bounced"},
			{"communication": "C3", "event_type": "Unsubscribed"},
			{"communication": "OTHER-CAMPAIGN", "event_type": "Opened"},  # not sent by a workflow
		]
		rows = {row["workflow"]: row for row in stats.aggregate(sent, events)}
		self.assertEqual((rows["W1"]["sent"], rows["W1"]["opened"], rows["W1"]["clicked"], rows["W1"]["bounced"]), (2, 1, 1, 1))
		self.assertEqual((rows["W2"]["sent"], rows["W2"]["unsubscribed"], rows["W2"]["opened"]), (1, 1, 0))

	def test_busiest_workflow_first_and_empty_input_is_empty(self):
		self.assertEqual(stats.aggregate([], []), [])
		rows = stats.aggregate(
			[{"workflow": "A", "workflow_title": "A", "email_template": "", "communication": "1"},
			 {"workflow": "B", "workflow_title": "B", "email_template": "", "communication": "2"},
			 {"workflow": "B", "workflow_title": "B", "email_template": "", "communication": "3"}], [])
		self.assertEqual([row["workflow"] for row in rows], ["B", "A"])

	def test_endpoint_runs_on_the_real_site(self):
		frappe.set_user("Administrator")
		result = stats.workflow_email_usage(30)
		self.assertIn("rows", result)
		self.assertTrue(all(row["sent"] >= 1 for row in result["rows"]))
