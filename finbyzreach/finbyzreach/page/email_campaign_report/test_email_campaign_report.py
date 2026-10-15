from unittest import TestCase
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

from finbyzreach.finbyzreach.page.email_campaign_report import email_campaign_report as report


class TestEmailCampaignReport(TestCase):
    def setUp(self):
        self.enterContext(patch.object(report, "_", side_effect=lambda value: value))
        self.enterContext(patch.object(report, "nowdate", return_value="2026-10-06"))

    @patch.object(report, "_cohort_rows", return_value=[{"eligible": 2, "sent": 1, "opened": 1}])
    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    def test_studio_summary_uses_selected_send_cohort_and_permission_scope(self, campaign_names, cohort_rows):
        summary = report.get_campaign_summary("Campaign-1", 60)
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(summary["opened"], 1)
        self.assertEqual(summary["completed"], 1)
        campaign_names.assert_called_once_with("campaign", "Campaign-1")
        cohort_rows.assert_called_once_with(["Campaign-1"], date(2026, 10, 6) - timedelta(days=59), date(2026, 10, 6))

    @patch.object(report.frappe, "throw", side_effect=ValueError)
    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    def test_studio_summary_rejects_old_ninety_day_period(self, campaign_names, throw):
        with self.assertRaises(ValueError):
            report.get_campaign_summary("Campaign-1", 90)

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

    @patch.object(report, "nowdate", return_value="2026-01-06")
    def test_previous_month_crosses_year_boundary(self, nowdate):
        first, last, selected_range = report._period_range()
        self.assertEqual((first, last), (date(2025, 12, 1), date(2025, 12, 31)))
        self.assertEqual(selected_range["to_date"], "2025-12-31")

    def test_acceptance_and_engagement_denominators(self):
        rates = report._rates({"sent": 6, "hard_bounce": 1, "soft_bounce": 1, "spam": 1, "failed": 1, "opened": 3, "clicked": 2, "replied": 1})
        self.assertEqual(rates["accepted"], 9)
        self.assertEqual(rates["acceptance_rate"], 90.0)
        self.assertEqual(rates["open_rate"], 33.3)
        self.assertIsNone(report._rates(report._empty_aggregate())["acceptance_rate"])

    @patch.object(report.frappe, "db", new_callable=MagicMock)
    def test_cohort_query_filters_completed_outcomes_by_inclusive_send_period(self, db):
        db.sql.return_value = []
        report._cohort_rows(["Campaign-1"], date(2026, 9, 1), date(2026, 9, 30))
        query, args = db.sql.call_args.args[:2]
        self.assertIn("coalesce(q.modified, ec.modified) cohort_time", query)
        self.assertIn("effective_status in", query)
        self.assertEqual(args[-2:], [date(2026, 9, 1), date(2026, 10, 1)])

    @patch.object(report.frappe, "get_list")
    @patch.object(report.frappe, "has_permission")
    def test_overview_campaigns_are_permission_filtered(self, has_permission, get_list):
        get_list.return_value = [report.frappe._dict(name="Broadcast-1", custom_email_template="Welcome"), report.frappe._dict(name="Draft-2", custom_email_template="")]
        self.assertEqual(report._broadcast_names(), ["Broadcast-1"])
        get_list.assert_called_once_with("Campaign", filters={"custom_email_template": ["is", "set"]}, fields=["name", "custom_email_template"], limit_page_length=0)
        has_permission.assert_any_call("Email Campaign", "read", throw=True)

    @patch.object(report.frappe, "get_list")
    @patch.object(report.frappe, "has_permission")
    def test_comparison_options_allow_manual_lookup_of_permitted_items(self, has_permission, get_list):
        get_list.side_effect = [
            [report.frappe._dict(name="Campaign-2", custom_email_template="Welcome"), report.frappe._dict(name="Campaign-1", custom_email_template="Welcome")],
            [report.frappe._dict(name="Campaign-2", custom_email_template="Welcome"), report.frappe._dict(name="Campaign-1", custom_email_template="Welcome")],
            ["Welcome"],
        ]
        self.assertEqual(report.get_comparison_options("campaign"), ["Campaign-1", "Campaign-2"])
        self.assertEqual(report.get_comparison_options("template"), ["Welcome"])
        has_permission.assert_any_call("Email Template", "read", throw=True)
        self.assertEqual(get_list.call_args.args[0], "Email Template")

    @patch.object(report.frappe, "throw", side_effect=ValueError)
    def test_comparison_rejects_invalid_selection(self, throw):
        for values in (["one"], ["one"] * 2, ["one", "two", "three", "four", "five", "six"], ["one", 2]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                report.get_comparison(values=values)

    @patch.object(report, "_cohort_rows")
    @patch.object(report, "_campaign_names")
    def test_template_comparison_groups_permitted_campaigns(self, campaign_names, cohort_rows):
        campaign_names.side_effect = [["A", "B"], ["C"]]
        cohort_rows.return_value = [
            report.frappe._dict(campaign_name="A", eligible=2, sent=2, opened=1),
            report.frappe._dict(campaign_name="C", eligible=1, sent=1, clicked=1),
        ]
        data = report.get_comparison("template", ["Welcome", "Follow up"])
        self.assertEqual([item["campaign_count"] for item in data["items"]], [2, 1])
        self.assertEqual(data["items"][0]["summary"]["sent"], 2)
        self.assertEqual(data["items"][1]["summary"]["click_rate"], 100.0)
        cohort_rows.assert_called_once()

    @patch.object(report, "_cohort_rows", return_value=[])
    @patch.object(report, "_broadcast_names", return_value=[])
    @patch.object(report, "nowdate", return_value="2026-10-06")
    def test_empty_overview_has_no_attempts(self, nowdate, broadcast_names, cohort_rows):
        data = report.get_overview()
        self.assertEqual(data["campaign_count"], 0)
        self.assertEqual(data["summary"]["accepted"], 0)
        self.assertIsNone(data["summary"]["acceptance_rate"])
        self.assertEqual(len(data["trend"]), 30)
