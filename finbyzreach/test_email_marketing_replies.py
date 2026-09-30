from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach import email_marketing


class TestEmailMarketingReplies(TestCase):
    @patch.object(email_marketing, "refresh_campaign_metrics")
    @patch.object(email_marketing, "_log_event")
    @patch.object(email_marketing.frappe, "get_doc")
    @patch.object(email_marketing.frappe, "db", new=MagicMock())
    def test_bounce_notice_is_not_a_recipient_reply(self, get_doc, log_event, refresh):
        db = email_marketing.frappe.db
        db.get_value.return_value = "EC-1"
        recipient = frappe._dict(name="EC-1", campaign_name="Campaign-1", custom_recipient_email="test@example.com")
        get_doc.return_value = recipient
        notice = frappe._dict(
            communication_medium="Email", sent_or_received="Received",
            in_reply_to="OUT-1", sender="mailer-daemon@googlemail.com",
            creation="2026-09-30 13:42:16", name="IN-1",
        )

        email_marketing.communication_after_insert(notice)

        db.set_value.assert_not_called()
        log_event.assert_not_called()
        refresh.assert_not_called()

    @patch.object(email_marketing, "refresh_campaign_metrics")
    @patch.object(email_marketing, "_log_event")
    @patch.object(email_marketing.frappe, "get_doc")
    @patch.object(email_marketing.frappe, "db", new=MagicMock())
    def test_matching_sender_is_counted_as_reply(self, get_doc, log_event, refresh):
        db = email_marketing.frappe.db
        db.get_value.return_value = "EC-2"
        recipient = frappe._dict(name="EC-2", campaign_name="Campaign-2", custom_recipient_email="person@example.com")
        get_doc.return_value = recipient
        reply = frappe._dict(
            communication_medium="Email", sent_or_received="Received",
            in_reply_to="OUT-2", sender="Person <PERSON@example.com>",
            creation="2026-09-30 13:45:00", name="IN-2",
        )

        email_marketing.communication_after_insert(reply)

        db.set_value.assert_called_once_with(
            "Email Campaign", "EC-2",
            {"custom_replied": 1, "custom_replied_on": reply.creation},
            update_modified=False,
        )
        log_event.assert_called_once_with("Replied", recipient, communication="IN-2")
        refresh.assert_called_once_with("Campaign-2")
