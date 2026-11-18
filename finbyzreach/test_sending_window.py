"""Rule 4.5 / EM-24: daily sending windows, including windows across midnight."""
from datetime import datetime, time
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe

from finbyzreach import email_marketing as em

ZURICH = ZoneInfo("Europe/Zurich")
WEEKDAYS = {0, 1, 2, 3, 4}  # Mon-Fri


def campaign(start, end, days=("monday", "tuesday", "wednesday", "thursday", "friday")):
	values = {f"custom_send_{day}": 1 for day in days}
	return frappe._dict(custom_restrict_sending_window=1, custom_window_start=start, custom_window_end=end, **values)


class SendingWindowTest(TestCase):
	def test_same_day_window(self):
		allows = lambda h: em.window_allows(datetime(2026, 11, 18, h, 0), WEEKDAYS, time(8), time(17))
		self.assertTrue(allows(8)); self.assertTrue(allows(12)); self.assertFalse(allows(7)); self.assertFalse(allows(18))

	def test_overnight_window_belongs_to_the_evening_it_opened(self):
		allows = lambda d, h: em.window_allows(datetime(2026, 11, d, h, 0), WEEKDAYS, time(22), time(6))
		self.assertTrue(allows(20, 23))   # Friday 23:00
		self.assertTrue(allows(21, 3))    # Saturday 03:00, opened Friday evening
		self.assertFalse(allows(22, 3))   # Sunday 03:00, opened Saturday (not allowed)
		self.assertFalse(allows(18, 12))  # Wednesday noon, outside the window

	def test_next_slot_moves_to_the_next_opening(self):
		c = campaign("22:00:00", "06:00:00")
		slot = em._next_valid_slot(datetime(2026, 11, 18, 12, 0, tzinfo=ZURICH), c, ZURICH)
		self.assertEqual((slot.day, slot.hour), (18, 22))
		# Saturday noon: the next allowed evening is Monday 22:00.
		slot = em._next_valid_slot(datetime(2026, 11, 21, 12, 0, tzinfo=ZURICH), c, ZURICH)
		self.assertEqual((slot.day, slot.hour), (23, 22))

	def test_slot_inside_overnight_window_is_kept(self):
		c = campaign("22:00:00", "06:00:00")
		slot = em._next_valid_slot(datetime(2026, 11, 19, 2, 30, tzinfo=ZURICH), c, ZURICH)
		self.assertEqual((slot.day, slot.hour, slot.minute), (19, 2, 30))


class DefaultWindowSettingTest(TestCase):
	def _window(self, values):
		with patch.object(frappe.db, "get_single_value", side_effect=lambda doctype, field: values.get(field)):
			return em.default_sending_window()

	def test_unsaved_settings_fall_back_to_office_hours_off(self):
		window = self._window({})
		self.assertEqual((window["enabled"], window["start"], window["end"], window["weekdays"]), (0, "08:00:00", "17:00:00", [0, 1, 2, 3, 4]))
		self.assertEqual(window["timezone"], "Europe/Zurich")

	def test_saved_settings_are_used_including_an_overnight_window(self):
		values = {"default_window_enabled": 1, "default_window_start": "22:00:00", "default_window_end": "06:00:00",
			**{f"default_send_{d}": 1 for d in ("monday", "tuesday", "wednesday", "thursday", "friday")},
			"default_send_saturday": 0, "default_send_sunday": 0}
		window = self._window(values)
		self.assertEqual((window["enabled"], window["start"], window["end"], window["weekdays"]), (1, "22:00:00", "06:00:00", [0, 1, 2, 3, 4]))
