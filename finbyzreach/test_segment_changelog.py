"""SEG-51: filters and exclusions appear as sentences, not JSON."""
import json

import frappe
from frappe.tests import IntegrationTestCase

from finbyzreach import segment_changelog as changelog


class TestSegmentChangelog(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_describe_turns_conditions_into_sentences(self):
		expression = {"operator": "AND", "conditions": [
			[["Lead", "status", "=", "Open"]],
			{"kind": "relative_date", "field": "creation", "comparison": "older_than", "amount": 6, "unit": "months"},
			{"kind": "multiselect", "field": "custom_subscriptions", "mode": "any", "values": ["A", "B"]},
			{"kind": "segment", "segment": "Other", "operator": "not in"},
		]}
		lines = changelog.describe("Lead", {"filter_expression_json": json.dumps(expression),
			"exclude_filters_json": json.dumps([[["Lead", "email_id", "is", "not set"]]]),
			"exclude_segments_json": json.dumps(["Blocked"])})
		text = "\n".join(lines)
		self.assertIn("is Open", text)
		self.assertIn("more than 6", text)
		self.assertIn("A, B", text)
		self.assertIn("Other", text)
		self.assertIn("Exclude: ", text)
		self.assertIn("Blocked", text)
		self.assertNotIn("{", text)

	def test_edit_is_logged_with_added_and_removed_conditions(self):
		name = f"ZZTEST Changelog {frappe.generate_hash(length=5)}"
		segment = frappe.get_doc({"doctype": "Reach Segment", "segment_name": name, "audience_doctype": "Lead",
			"segment_type": "Active", "filter_groups_json": json.dumps([[["Lead", "status", "=", "Open"]]])}).insert()
		segment.reload()
		segment.filter_groups_json = json.dumps([[["Lead", "status", "=", "Replied"]]])
		segment.save(ignore_version=False)
		entries = changelog.definition_changes(name)["entries"]
		self.assertTrue(entries)
		newest = entries[0]
		self.assertEqual(newest["by"], "Administrator")
		kinds = {(c["type"], c["text"]) for c in newest["changes"]}
		self.assertTrue(any(t == "removed" and "Open" in x for t, x in kinds), kinds)
		self.assertTrue(any(t == "added" and "Replied" in x for t, x in kinds), kinds)

	def test_changes_that_do_not_touch_the_definition_are_skipped(self):
		name = f"ZZTEST Changelog Quiet {frappe.generate_hash(length=5)}"
		segment = frappe.get_doc({"doctype": "Reach Segment", "segment_name": name, "audience_doctype": "Lead",
			"segment_type": "Active", "filter_groups_json": json.dumps([[["Lead", "status", "=", "Open"]]])}).insert()
		segment.reload()
		segment.member_count = 99
		segment.save(ignore_version=False)
		# The size changed but no filter did, so the log has nothing to report.
		self.assertEqual(changelog.definition_changes(name)["entries"], [])
