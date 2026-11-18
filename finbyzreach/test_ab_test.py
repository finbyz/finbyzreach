"""EM-30: A/B test split, winner rule and release of the rest."""
from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach import ab_test, email_marketing


def rows(count):
	return [frappe._dict(email=f"p{i}@example.com", normalized_email=f"p{i}@example.com") for i in range(count)]


def stats(a_sent, a_hit, b_sent, b_hit, key="opened"):
	return {"A": {"sent": a_sent, "opened": 0, "clicked": 0, **{key: a_hit}}, "B": {"sent": b_sent, "opened": 0, "clicked": 0, **{key: b_hit}}}


class AbSplitTest(TestCase):
	def test_test_group_is_the_share_split_equally_and_the_rest_waits(self):
		plan = ab_test.plan("CAMP", rows(100), 20)
		self.assertEqual([phase for _r, _v, phase in plan].count("Test"), 20)
		self.assertEqual([v for _r, v, _p in plan].count("A"), 10)
		self.assertEqual([v for _r, v, _p in plan].count("B"), 10)
		self.assertTrue(all(v == "" for _r, v, p in plan if p == "Rest"))
		self.assertTrue(all(p == "Test" for _r, _v, p in plan[:20]), "the test group goes first")

	def test_split_is_stable_for_the_same_campaign(self):
		first = [(r.email, v) for r, v, _p in ab_test.plan("CAMP", rows(40), 25)]
		second = [(r.email, v) for r, v, _p in ab_test.plan("CAMP", rows(40), 25)]
		self.assertEqual(first, second)

	def test_test_size_is_even_at_least_two_and_never_above_the_audience(self):
		self.assertEqual(ab_test.test_size(100, 15), 14)
		self.assertEqual(ab_test.test_size(10, 5), 2)
		self.assertEqual(ab_test.test_size(3, 50), 2)
		self.assertEqual(ab_test.test_size(1, 50), 1)


class AbWinnerTest(TestCase):
	def test_higher_open_rate_wins(self):
		self.assertEqual(ab_test.choose_winner(stats(10, 2, 10, 5), "Opens"), "B")
		self.assertEqual(ab_test.choose_winner(stats(10, 6, 10, 5), "Opens"), "A")

	def test_rates_not_counts_decide_when_groups_differ_in_size(self):
		self.assertEqual(ab_test.choose_winner(stats(20, 8, 10, 5), "Opens"), "B")

	def test_clicks_decide_when_chosen(self):
		self.assertEqual(ab_test.choose_winner(stats(10, 3, 10, 4, key="clicked"), "Clicks"), "B")

	def test_a_tie_and_no_data_go_to_a(self):
		self.assertEqual(ab_test.choose_winner(stats(10, 4, 10, 4), "Opens"), "A")
		self.assertEqual(ab_test.choose_winner(stats(0, 0, 0, 0), "Opens"), "A")


class AbValidateTest(TestCase):
	def _campaign(self, **values):
		base = dict(custom_ab_enabled=1, custom_ab_subject_b="Other subject", custom_ab_share=20, custom_ab_hours=24, custom_ab_metric="Opens")
		return frappe._dict({**base, **values})

	def test_a_valid_test_passes_and_a_disabled_test_is_ignored(self):
		ab_test.validate(self._campaign())
		ab_test.validate(frappe._dict(custom_ab_enabled=0))

	def test_variant_b_must_differ(self):
		with self.assertRaises(frappe.ValidationError):
			ab_test.validate(self._campaign(custom_ab_subject_b="", custom_ab_template_b=None))

	def test_share_and_duration_are_limited(self):
		for values in ({"custom_ab_share": 4}, {"custom_ab_share": 51}, {"custom_ab_hours": 0}, {"custom_ab_metric": "Revenue"}):
			with self.assertRaises(frappe.ValidationError):
				ab_test.validate(self._campaign(**values))


class AbDecisionTest(TestCase):
	def _decide(self, status="Testing", broadcast="Sending", winner_stats=None, rest=3):
		campaign = frappe._dict(custom_ab_status=status, custom_broadcast_status=broadcast, custom_ab_metric="Opens")
		batches = [frappe._dict(scheduled_at=datetime(2026, 11, 20, 9), size=rest, number=1)]
		with patch.object(frappe, "get_doc", return_value=campaign), \
				patch.object(ab_test, "results", return_value=winner_stats or stats(10, 2, 10, 6)), \
				patch.object(frappe, "get_all", return_value=[frappe._dict(name=f"R{i}") for i in range(rest)]), \
				patch.object(email_marketing, "calculate_delivery_batches", return_value=batches), \
				patch.object(email_marketing, "_reschedule_recipient_batches") as reschedule, \
				patch.object(frappe.db, "set_value") as set_value:
			return ab_test.decide("CAMP"), reschedule, set_value

	def test_winner_is_sent_to_the_rest_and_recorded(self):
		result, reschedule, set_value = self._decide()
		self.assertEqual(result["winner"], "B")
		self.assertEqual(result["released"], 3)
		reschedule.assert_called_once()
		final = set_value.call_args_list[-1]
		self.assertEqual(final.args[:3], ("Campaign", "CAMP", {"custom_ab_status": "Decided", "custom_ab_winner": "B"}))
		variant_call = next(call for call in set_value.call_args_list if call.args[2] == "custom_ab_variant")
		self.assertEqual(variant_call.args[3], "B")

	def test_nothing_happens_for_a_paused_or_already_decided_campaign(self):
		for status, broadcast in (("Decided", "Sending"), ("Testing", "Paused")):
			result, reschedule, _set = self._decide(status=status, broadcast=broadcast)
			self.assertIsNone(result)
			reschedule.assert_not_called()


class AbVariantContentTest(TestCase):
	def test_variant_b_gets_its_own_frozen_copy_and_others_get_the_main_one(self):
		campaign = frappe._dict(custom_ab_enabled=1, custom_snapshot_subject="Subject A", custom_snapshot_html="<p>A</p>",
			custom_ab_snapshot_subject="Subject B", custom_ab_snapshot_html="<p>B</p>")
		self.assertEqual(ab_test.variant_content(campaign, frappe._dict(custom_ab_variant="B")), ("Subject B", "<p>B</p>"))
		self.assertEqual(ab_test.variant_content(campaign, frappe._dict(custom_ab_variant="A")), ("Subject A", "<p>A</p>"))
		self.assertEqual(ab_test.variant_content(campaign, frappe._dict()), ("Subject A", "<p>A</p>"))
		off = frappe._dict(campaign, custom_ab_enabled=0)
		self.assertEqual(ab_test.variant_content(off, frappe._dict(custom_ab_variant="B")), ("Subject A", "<p>A</p>"))
