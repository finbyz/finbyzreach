import unittest
from unittest.mock import patch

import frappe

from finbyzreach.finbyzreach.page.megasol_marketing_start import megasol_marketing_start as start


class TestMarketingStart(unittest.TestCase):
    def test_no_campaign_access_does_not_query_activity_or_metrics(self):
        with patch.object(start, "_allowed", return_value=False), patch.object(start, "_form_teams", return_value=[]), \
                patch.object(frappe, "get_cached_value", return_value="Aman"), patch.object(frappe, "get_list") as query, \
                patch.object(start, "_summary") as summary:
            data = start.get_start_data()
        query.assert_not_called()
        summary.assert_not_called()
        self.assertEqual(data["upcoming"], [])
        self.assertEqual(data["recent"], [])
        self.assertFalse(data["can_read_statistics"])

    def test_campaign_queries_are_permission_aware_and_bounded(self):
        campaign = frappe._dict(name="Campaign A", campaign_name="Newsletter", custom_start_on=None,
                                custom_broadcast_status="Scheduled", custom_queued=0, custom_email_template="Email A")
        def query(doctype, **kwargs):
            if doctype == "Email Campaign":
                return [frappe._dict(campaign_name="Campaign A", skipped=4)]
            return [campaign]
        counts = {"sent": 10, "delivered": None, "clicked": 2, "unsubscribed": 1}
        with patch.object(start, "_allowed", return_value=True), patch.object(start, "_form_teams", return_value=[]), \
                patch.object(frappe, "get_cached_value", return_value="Aman"), \
                patch.object(frappe, "get_roles", return_value=["System Manager"]), \
                patch.object(frappe, "get_list", side_effect=query) as queries, patch.object(start, "_summary", return_value=counts):
            data = start.get_start_data()
        self.assertEqual([call.kwargs["limit_page_length"] for call in queries.call_args_list], [8, 3, 3])
        self.assertEqual(queries.call_args_list[0].kwargs["filters"]["custom_email_template"], ["is", "set"])
        self.assertEqual(data["recent"][0]["click_rate"], 20.0)
        self.assertEqual(data["recent"][0]["skipped"], 4)
        self.assertIsNone(data["recent"][0]["delivered"])

    def test_campaign_readers_without_recipient_access_do_not_get_metrics(self):
        with patch.object(start, "_allowed", side_effect=lambda dt, ptype="read": dt == "Campaign" and ptype == "read"), \
                patch.object(start, "_form_teams", return_value=[]), patch.object(frappe, "get_cached_value", return_value="Aman"), \
                patch.object(frappe, "get_list", return_value=[]) as query, patch.object(start, "_summary") as summary:
            data = start.get_start_data()
        self.assertEqual(query.call_count, 1)
        summary.assert_not_called()
        self.assertFalse(data["can_read_statistics"])

    def test_opening_start_never_creates_a_forms_team(self):
        with patch.object(frappe, "get_installed_apps", return_value=["forms_pro"]), \
                patch.object(frappe, "get_roles", return_value=["Forms Pro User"]), \
                patch("forms_pro.utils.teams.get_user_teams", return_value=[]) as teams:
            self.assertEqual(start._form_teams(), [])
        teams.assert_called_once_with(create_if_empty=False)
