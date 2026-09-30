from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach import email_marketing
from finbyzreach.finbyzreach.page.email_campaign_studio import email_campaign_studio as studio


class TestEmailCampaignPreflight(TestCase):
    @patch.object(email_marketing, "get_campaign_snapshot", side_effect=ValueError("Invalid template"))
    @patch.object(email_marketing, "calculate_batch_slots", return_value=["slot"])
    @patch.object(email_marketing, "validate_excluded_email_groups")
    @patch.object(email_marketing, "validate_lead_filter_groups")
    @patch.object(email_marketing, "validate_campaign")
    @patch.object(email_marketing.frappe, "db", new=MagicMock())
    def test_template_error_is_found_before_enqueue(self, validate, groups, excluded, slots, snapshot):
        campaign = MagicMock(
            name="Campaign-1", custom_broadcast_status="Draft",
            custom_lead_filters_json="[]", custom_exclude_filters_json="[]",
            custom_exclude_email_groups_json="[]", custom_email_template="Template-1",
            custom_subject_override="",
        )
        campaign.name = "Campaign-1"
        email_marketing.frappe.db.exists.return_value = False

        with self.assertRaisesRegex(ValueError, "Invalid template"):
            email_marketing.validate_schedule_preflight(campaign, 12)

        campaign.check_permission.assert_any_call("email")
        slots.assert_called_once_with(campaign, 1)
        snapshot.assert_called_once_with("Template-1", "")

    @patch.object(studio.email_marketing, "validate_schedule_preflight", side_effect=ValueError("Invalid template"))
    @patch.object(studio.frappe, "enqueue")
    @patch.object(studio.frappe, "get_doc")
    @patch.object(studio, "_ensure_utm_campaign")
    @patch.object(studio, "_campaign_values", return_value={"doctype": "Campaign", "campaign_name": "Launch"})
    @patch.object(studio, "_preview_response", return_value={"eligible_count": 12})
    @patch.object(studio, "_resolved_studio_audience", return_value=[])
    @patch.object(studio, "_audience_context")
    @patch.object(studio, "_check_permission")
    def test_studio_does_not_enqueue_when_preflight_fails(
        self, permission, context, resolved, preview, values, utm, get_doc, enqueue, preflight
    ):
        campaign = MagicMock()
        campaign.name = "Campaign-1"
        campaign.insert.return_value = campaign
        get_doc.return_value = campaign

        with self.assertRaisesRegex(ValueError, "Invalid template"):
            studio.create_campaign(payload="{}", launch="schedule")

        preflight.assert_called_once_with(campaign, 12)
        campaign.db_set.assert_not_called()
        enqueue.assert_not_called()
