from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach import email_marketing


class TestEmailMarketingFeedback(TestCase):
    @patch.object(email_marketing, "refresh_campaign_metrics")
    @patch.object(email_marketing.frappe, "get_all")
    @patch.object(email_marketing.frappe, "db", new=MagicMock())
    def test_sent_recipient_is_reconciled_to_hard_bounce(self, get_all, refresh):
        db = email_marketing.frappe.db
        recipient = frappe._dict(
            name="EC-1", campaign_name="Campaign-1", recipient="Lead-1",
            custom_email_queue="Q-1", custom_communication="C-1",
            custom_opened=0, custom_delivery_status="Sent",
            communication_delivery_status="Bounced",
        )
        db.sql.side_effect = [[], [recipient]]
        db.table_exists.return_value = False
        get_all.side_effect = [
            [],
            [frappe._dict(name="Q-1", status="Sent", error=None)],
            [frappe._dict(name="C-1", read_by_recipient=0, read_by_recipient_on=None, delivery_status="Bounced")],
        ]

        email_marketing.sync_marketing_email_statuses()

        db.set_value.assert_called_once_with(
            "Email Campaign", "EC-1",
            {"status": "Completed", "custom_delivery_status": "Bounced"},
            update_modified=False,
        )
        refresh.assert_called_once_with("Campaign-1")

    @patch.object(email_marketing.frappe, "db", new=MagicMock())
    def test_queued_recipient_uses_communication_bounce_before_queue_sent(self):
        db = email_marketing.frappe.db
        db.get_value.return_value = "Soft-Bounced"
        recipient = frappe._dict(
            custom_delivery_status="Queued", custom_email_queue="Q-1", custom_communication="C-1"
        )

        self.assertEqual(
            email_marketing._queued_delivery_status_updates(recipient),
            {"status": "Completed", "custom_delivery_status": "Soft-Bounced"},
        )
        db.get_value.assert_called_once_with("Communication", "C-1", "delivery_status")
