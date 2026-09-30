from datetime import datetime
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe

from finbyzreach import email_marketing
from finbyzreach.finbyzreach.page.email_campaign_studio import email_campaign_studio as studio


class TestEmailCampaignTimezone(TestCase):
    @patch.object(studio, "get_system_timezone", return_value="Asia/Kolkata")
    @patch.object(studio, "_studio_timezone", return_value=ZoneInfo("Europe/Zurich"))
    def test_studio_round_trip_matches_frappe_datetime_display(self, zone, system):
        stored = studio._studio_to_system_datetime("2026-09-30 10:02:22")

        self.assertEqual(stored, datetime(2026, 9, 30, 13, 32, 22))
        self.assertEqual(studio._system_to_studio_datetime(stored).replace(tzinfo=None), datetime(2026, 9, 30, 10, 2, 22))

    @patch.object(studio, "get_system_timezone", return_value="Asia/Kolkata")
    @patch.object(studio, "_studio_timezone", return_value=ZoneInfo("Europe/Zurich"))
    def test_studio_rejects_nonexistent_and_ambiguous_local_times(self, zone, system):
        with patch.object(studio.frappe, "throw", side_effect=frappe.ValidationError):
            for value in ("2026-03-29 02:30:00", "2026-10-25 02:30:00"):
                with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
                    studio._studio_to_system_datetime(value)

    @patch.object(studio, "get_system_timezone", return_value="Asia/Kolkata")
    @patch.object(studio, "_studio_timezone", return_value=ZoneInfo("Europe/Zurich"))
    def test_campaign_values_store_system_time_and_campaign_zone(self, zone, system):
        context = frappe._dict(include_filters_json="[]", exclude_filters_json="[]", email_groups=[])
        values = studio._campaign_values(
            frappe._dict(campaign_title="Launch", start_date="2026-09-30", start_time="10:02:22"),
            context, require_ready=False,
        )

        self.assertEqual(values["custom_start_on"], datetime(2026, 9, 30, 13, 32, 22))
        self.assertEqual(values["custom_schedule_timezone"], "Europe/Zurich")

    @patch.object(email_marketing, "get_system_timezone", return_value="Asia/Kolkata")
    def test_batch_slots_keep_zurich_wall_time_across_dst(self, system):
        campaign = frappe._dict(
            custom_start_on="2026-10-24 13:30:00",
            custom_schedule_timezone="Europe/Zurich",
            custom_batch_size=1,
            custom_repeat_every=1,
            custom_repeat_unit="Days",
            custom_restrict_sending_window=0,
            custom_send_monday=1, custom_send_tuesday=1, custom_send_wednesday=1,
            custom_send_thursday=1, custom_send_friday=1, custom_send_saturday=1,
            custom_send_sunday=1,
        )

        self.assertEqual(
            email_marketing.calculate_batch_slots(campaign, 2),
            [datetime(2026, 10, 24, 13, 30), datetime(2026, 10, 25, 14, 30)],
        )
