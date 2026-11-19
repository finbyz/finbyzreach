"""EM-36: opens and clicks reach the record timeline."""
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach import record_timeline


def event(event_type, **values):
	return frappe._dict(event_type=event_type, lead="LEAD-1", contact=None, marketing_campaign_recipient=None,
		marketing_email_campaign="CAMP", communication="COMM", url=None, **values)


class RecordTimelineTest(TestCase):
	def _run(self, doc, exists=True):
		values = {("Campaign", "CAMP", "campaign_name"): "Autumn offer", ("Communication", "COMM", "subject"): "Our new panels"}
		added = []
		with patch.object(frappe.db, "get_value", side_effect=lambda dt, name, field, **k: values.get((dt, name, field))), \
				patch.object(frappe.db, "exists", return_value=exists), \
				patch.object(frappe, "get_doc", side_effect=lambda d: added.append(d) or frappe._dict(insert=lambda **k: None)):
			record_timeline.log_email_event(doc)
		return added

	def test_an_open_adds_a_line_to_the_lead_timeline(self):
		added = self._run(event("Opened"))
		self.assertEqual(len(added), 1)
		self.assertEqual((added[0]["reference_doctype"], added[0]["reference_name"], added[0]["comment_type"]), ("Lead", "LEAD-1", "Info"))
		self.assertIn("Opened the email “Our new panels” (Autumn offer).", added[0]["content"])

	def test_a_click_names_the_link(self):
		doc = event("Clicked")
		doc.url = "https://megasol.ch/offer"
		added = self._run(doc)
		self.assertIn("Clicked a link in the email", added[0]["content"])
		self.assertIn("https://megasol.ch/offer", added[0]["content"])

	def test_bounces_and_unsubscribes_are_on_the_timeline_too(self):
		for event_type, words in (("Bounced", "hard bounce"), ("Soft-Bounced", "soft bounce"), ("Unsubscribed", "Unsubscribed through the email")):
			with self.subTest(event_type):
				added = self._run(event(event_type))
				self.assertEqual(len(added), 1)
				self.assertIn(words, added[0]["content"])

	def test_other_events_and_missing_records_add_nothing(self):
		self.assertEqual(self._run(event("Sent")), [])
		self.assertEqual(self._run(event("Opened"), exists=False), [])
