"""Segment dependencies on emails and workflows, and export header language."""
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach import segment_service as service
from finbyzreach import segments


def campaign(name, status, include=None, exclude=None):
	marker = lambda seg: f'[[["Lead","name","in",["#REACH_SEGMENT#","{seg}"]]]]' if seg else "[]"
	return frappe._dict(name=name, campaign_name=name, custom_broadcast_status=status,
		custom_lead_filters_json=marker(include), custom_exclude_filters_json=marker(exclude))


class SegmentUsageTest(TestCase):
	def setUp(self):
		self.segment = frappe._dict(name="Installers CH")
		for item in (patch.object(frappe.db, "has_column", return_value=True),
					 patch.object(service, "workflow_usage", return_value=[])):
			item.start()
			self.addCleanup(item.stop)

	def test_refs_found_in_nested_filters(self):
		value = '[[["Lead","name","in",["#STATIC_SEGMENT#","A"]]],[["Lead","name","in",["#REACH_SEGMENT#","B"]]]]'
		self.assertEqual(service.segment_refs_in_filters(value), {"A", "B"})
		self.assertEqual(service.segment_refs_in_filters("not json"), set())

	def test_campaign_usage_matches_exact_name_and_role(self):
		rows = [campaign("Promo", "Draft", include="Installers CH"),
				campaign("Other", "Scheduled", include="Installers CH 2"),
				campaign("Press", "Sending", exclude="Installers CH")]
		with patch.object(frappe, "get_all", return_value=rows):
			usage = service.campaign_usage(self.segment)
		self.assertEqual([(r["name"], r["role"], r["live"]) for r in usage],
						 [("Promo", "include", False), ("Press", "exclude", True)])

	def test_live_campaign_blocks_delete_and_archive(self):
		with patch.object(frappe, "get_all", return_value=[campaign("Press", "Paused", include="Installers CH")]):
			with self.assertRaises(frappe.ValidationError):
				service.assert_unused(self.segment, blocking=True)

	def test_completed_campaign_does_not_block(self):
		with patch.object(frappe, "get_all", return_value=[campaign("Old", "Completed", include="Installers CH")]), \
				patch.object(frappe, "msgprint") as msgprint:
			service.assert_unused(self.segment, blocking=True)
		msgprint.assert_not_called()

	def test_paused_workflow_counts_as_live(self):
		self.assertIn("PAUSED", service.LIVE_WORKFLOW_STATUSES)
