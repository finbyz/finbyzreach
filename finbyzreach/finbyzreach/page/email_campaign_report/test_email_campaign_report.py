from unittest import TestCase
from unittest.mock import MagicMock, patch

from finbyzreach.finbyzreach.page.email_campaign_report import email_campaign_report as report


class TestEmailCampaignReport(TestCase):
    def setUp(self):
        self.enterContext(patch.object(report, "_", side_effect=lambda value: value))

    @patch.object(report.frappe, "get_doc")
    @patch.object(report.frappe, "has_permission")
    def test_campaign_scope_checks_document_permission(self, has_permission, get_doc):
        campaign = MagicMock(custom_email_template="Template-1")
        campaign.name = "Campaign-1"
        get_doc.return_value = campaign

        self.assertEqual(report._campaign_names("campaign", "Campaign-1"), ["Campaign-1"])

        campaign.check_permission.assert_called_once_with("read")
        has_permission.assert_any_call("Email Campaign", "read", throw=True)

    @patch.object(report.frappe, "get_list", return_value=["Campaign-1", "Campaign-2"])
    @patch.object(report.frappe, "db", new_callable=MagicMock)
    @patch.object(report.frappe, "has_permission")
    def test_template_scope_uses_permitted_campaigns(self, has_permission, db, get_list):
        db.exists.return_value = True
        self.assertEqual(report._campaign_names("template", "Template-1"), ["Campaign-1", "Campaign-2"])
        has_permission.assert_any_call("Email Template", "read", throw=True)
        get_list.assert_called_once_with(
            "Campaign", filters={"custom_email_template": "Template-1"},
            pluck="name", limit_page_length=0,
        )

    @patch.object(report, "_campaign_names", return_value=[])
    @patch.object(report, "nowdate", return_value="2026-09-30")
    def test_empty_template_has_no_recorded_feedback(self, nowdate, campaign_names):
        data = report.get_report("template", "Unused Template")
        self.assertEqual(data["summary"]["sent"], 0)
        self.assertIsNone(data["summary"]["delivered"])
        for key in ("hard_bounce", "soft_bounce", "spam"):
            self.assertEqual(data["summary"][key], 0)
        self.assertEqual(data["trend"], [])
        self.assertEqual(data["campaign_count"], 0)


    def test_custom_timeline_dates_are_inclusive(self):
        first, last, label = report._timeline_range(30, "2026-09-05", "2026-09-07")
        self.assertEqual(first.isoformat(), "2026-09-05")
        self.assertEqual(last.isoformat(), "2026-09-07")
        self.assertEqual(label, "2026-09-05 to 2026-09-07")

    @patch.object(report.frappe, "throw", side_effect=ValueError)
    def test_custom_timeline_rejects_missing_reversed_and_oversized_dates(self, throw):
        for start, end in (("2026-09-01", None), ("2026-09-08", "2026-09-07"), ("2025-01-01", "2026-09-07")):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                report._timeline_range(30, start, end)

    @patch.object(report.frappe, "db", new_callable=MagicMock)
    def test_timeline_queries_stop_after_inclusive_end_date(self, db):
        from datetime import date

        db.sql.return_value = []
        db.table_exists.return_value = False
        rows = report._trend(["Campaign-1"], date(2026, 9, 5), date(2026, 9, 7))

        self.assertEqual([row["date"] for row in rows], ["2026-09-05", "2026-09-06", "2026-09-07"])
        for call in db.sql.call_args_list:
            self.assertEqual(call.args[1][-2:], [date(2026, 9, 5), date(2026, 9, 8)])

    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    @patch.object(report.frappe, "db", new_callable=MagicMock)
    def test_detail_query_is_scoped_and_paged(self, db, campaign_names):
        db.sql.side_effect = [[(1,)], [report.frappe._dict(name="EC-1", lead=None, email="a@example.com")]]

        data = report.get_details("campaign", "Campaign-1", "opened", 2)

        self.assertEqual(data["total"], 1)
        self.assertEqual(data["rows"][0]["full_name"], "a@example.com")
        self.assertIn("ec.campaign_name in (%s)", db.sql.call_args_list[0].args[0])
        self.assertEqual(db.sql.call_args_list[1].args[1][-2:], [25, 25])

    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    @patch.object(report.frappe, "db", new_callable=MagicMock)
    def test_hard_bounce_details_use_communication_feedback(self, db, campaign_names):
        db.sql.side_effect = [[(1,)], [report.frappe._dict(name="EC-1", lead=None, email="a@example.com")]]

        data = report.get_details("campaign", "Campaign-1", "hard_bounce")

        self.assertEqual(data["total"], 1)
        query = db.sql.call_args_list[0].args[0]
        self.assertIn("comm.delivery_status", query)
        self.assertIn("ec.custom_delivery_status", query)
        self.assertIn("Bounced", db.sql.call_args_list[0].args[1])

    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    @patch.object(report.frappe, "db", new_callable=MagicMock)
    def test_replied_details_require_matching_inbound_sender(self, db, campaign_names):
        db.sql.side_effect = [[(0,)], []]

        data = report.get_details("campaign", "Campaign-1", "replied")

        self.assertEqual(data["total"], 0)
        query = db.sql.call_args_list[0].args[0]
        self.assertIn("reply.in_reply_to = ec.custom_communication", query)
        self.assertIn("lower(trim(reply.sender)) = lower(trim(ec.custom_recipient_email))", query)
