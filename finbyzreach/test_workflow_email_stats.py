"""EM-27: workflow e-mail statistics are counted per workflow and e-mail."""
import json

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


class TestWorkflowEmailHandoff(IntegrationTestCase):
	def _ledger(self, *, recipient_status="Not Sent", queue_status="Not Sent", delivery_status="Not Sent",
			other_recipient_sent=False, result_recipient="person@example.com", result_communication=None):
		key = frappe.generate_hash(length=12)
		communication = "ZZTEST-WF-COMM-" + key
		queue = "ZZTEST-WF-QUEUE-" + key
		# Raw insertion avoids outgoing-mail hooks; no message is enqueued or sent.
		frappe.get_doc({"doctype": "Communication", "name": communication,
			"subject": "ZZTEST workflow handoff", "delivery_status": delivery_status,
			"communication_type": "Automated Message", "communication_medium": "Email",
			"sent_or_received": "Sent"}).db_insert()
		frappe.get_doc({"doctype": "Email Queue", "name": queue, "communication": communication,
			"status": queue_status, "sender": "sender@example.com", "message": "ZZTEST"}).db_insert()
		frappe.get_doc({"doctype": "Email Queue Recipient", "name": "ZZTEST-WF-R-" + key,
			"parent": queue, "parenttype": "Email Queue", "parentfield": "recipients",
			"recipient": "person@example.com", "status": recipient_status}).db_insert()
		if other_recipient_sent:
			frappe.get_doc({"doctype": "Email Queue Recipient", "name": "ZZTEST-WF-OTHER-" + key,
				"parent": queue, "parenttype": "Email Queue", "parentfield": "recipients",
				"recipient": "other@example.com", "status": "Sent"}).db_insert()
		return frappe._dict(workflow="ZZTEST Workflow", title="ZZTEST", result_json=json.dumps({
			"communication": result_communication or communication, "email_queue": queue,
			"recipient": result_recipient, "email_template": "ZZTEST Template"}))

	def test_queued_sending_and_suppressed_messages_are_not_sent(self):
		rows = [self._ledger(queue_status=status) for status in ("Not Sent", "Sending", "Error", "Sent")]
		self.assertEqual(stats._sent_workflow_rows(rows), [])

	def test_another_sent_recipient_does_not_qualify_the_workflow_target(self):
		row = self._ledger(queue_status="Partially Sent", other_recipient_sent=True)
		self.assertEqual(stats._sent_workflow_rows([row]), [])

	def test_successful_handoff_survives_later_bounce_or_unsubscribe(self):
		rows = [self._ledger(recipient_status="Sent", queue_status="Sent", delivery_status=status)
			for status in ("Sent", "Bounced", "Soft-Bounced", "Recipient Unsubscribed")]
		sent = stats._sent_workflow_rows(rows)
		self.assertEqual(len(sent), 4)
		self.assertEqual(stats.aggregate(sent, [])[0]["sent"], 4)

	def test_sent_target_counts_even_when_the_overall_queue_is_partial_or_error(self):
		rows = [self._ledger(recipient_status="Sent", queue_status=status)
			for status in ("Partially Sent", "Error")]
		self.assertEqual(len(stats._sent_workflow_rows(rows)), 2)

	def test_handoff_must_match_both_communication_and_normalized_recipient(self):
		valid = self._ledger(recipient_status="Sent", result_recipient=" PERSON@EXAMPLE.COM ")
		display_name = self._ledger(recipient_status="Sent", result_recipient='"A Person" <PERSON@EXAMPLE.COM>')
		wrong_address = self._ledger(recipient_status="Sent", result_recipient="other@example.com")
		wrong_communication = self._ledger(recipient_status="Sent", result_communication="UNRELATED")
		self.assertEqual(len(stats._sent_workflow_rows([valid, display_name, wrong_address, wrong_communication])), 2)

	def test_malformed_or_incomplete_legacy_results_are_not_assumed_sent(self):
		rows = [frappe._dict(result_json=value) for value in (None, "invalid", "[]", "null", "{}",
			json.dumps({"communication": "C"}))]
		self.assertEqual(stats._sent_workflow_rows(rows), [])

	def test_purged_queue_falls_back_to_the_communication_delivery_status(self):
		rows = [self._ledger(recipient_status="Sent", queue_status="Sent", delivery_status=status)
			for status in ("Sent", "Opened", "Bounced", "Sending", "Error")]
		for row in rows:
			queue = json.loads(row.result_json)["email_queue"]
			frappe.db.delete("Email Queue Recipient", {"parent": queue})
			frappe.db.delete("Email Queue", {"name": queue})
		self.assertEqual(len(stats._sent_workflow_rows(rows)), 3)

	def test_report_overview_counts_actual_handoffs_within_selected_period(self):
		from finbyzreach.finbyzreach.page.email_campaign_report import email_campaign_report as report

		pending = self._ledger(queue_status="Sending")
		failed = self._ledger(queue_status="Error")
		partial = self._ledger(recipient_status="Sent", queue_status="Partially Sent")
		purged = self._ledger(recipient_status="Sent", queue_status="Sent", delivery_status="Sent")
		queue = json.loads(purged.result_json)["email_queue"]
		frappe.db.delete("Email Queue Recipient", {"parent": queue})
		frappe.db.delete("Email Queue", {"name": queue})
		# A future test-only period isolates these uncommitted rows from site data.
		for row, completed_at in [(pending, "2099-01-01"), (failed, "2099-01-01"),
				(partial, "2099-01-01"), (partial, "2099-01-01"), (purged, "2099-01-01"),
				(self._ledger(recipient_status="Sent"), "2099-01-02"),
				(frappe._dict(result_json="{}"), "2099-01-01")]:
			key = "ZZTEST-WF-EFFECT-" + frappe.generate_hash(length=12)
			frappe.get_doc({"doctype": "Automation Effect Ledger", "name": key,
				"effect_key": key, "request_hash": key, "run": "ZZTEST", "node_id": "ZZTEST",
				"status": "COMPLETED", "completed_at": completed_at,
				"result_json": row.result_json}).db_insert()
		result = report.get_workflow_overview("custom", "2099-01-01", "2099-01-01")
		self.assertEqual(result["summary"]["sent"], 2)
		self.assertEqual(result["email_count"], 1)
