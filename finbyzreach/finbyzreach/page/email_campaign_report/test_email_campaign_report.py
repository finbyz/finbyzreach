from unittest import TestCase
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

import frappe

from finbyzreach.finbyzreach.page.email_campaign_report import email_campaign_report as report


class TestEmailCampaignReport(TestCase):
    def setUp(self):
        self.enterContext(patch.object(report, "_", side_effect=lambda value: value))
        self.enterContext(patch.object(report, "nowdate", return_value="2026-10-06"))

    @patch.object(report, "_cohort_rows", return_value=[{"eligible": 2, "sent": 1, "opened": 1}])
    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    def test_studio_summary_uses_selected_send_cohort_and_permission_scope(self, campaign_names, cohort_rows):
        summary = report.get_campaign_summary("Campaign-1", 90)
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(summary["opened"], 1)
        self.assertEqual(summary["completed"], 1)
        campaign_names.assert_called_once_with("campaign", "Campaign-1")
        cohort_rows.assert_called_once_with(["Campaign-1"], date(2026, 10, 6) - timedelta(days=89), date(2026, 10, 6))

    @patch.object(report.frappe, "throw", side_effect=ValueError)
    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    def test_studio_summary_rejects_unsupported_period(self, campaign_names, throw):
        with self.assertRaises(ValueError):
            report.get_campaign_summary("Campaign-1", 45)

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


class SkippedAndLinkClicksTest(TestCase):
    def test_skipped_is_a_metric_but_not_an_attempt(self):
        self.assertIn("skipped", report.METRICS)
        self.assertIn("skipped", report.AGGREGATE_FIELDS)
        self.assertIn("Skipped", report.COHORT_STATUSES)
        self.assertNotIn("Skipped", report.COMPLETED_STATUSES)
        counts = {"sent": 8, "failed": 2, "skipped": 40}
        self.assertEqual(report._rates(counts)["completed"], 10)

    @patch.object(report.frappe.db, "table_exists", return_value=True)
    @patch.object(report.frappe.db, "sql")
    def test_link_clicks_are_counted_per_url_for_the_selected_campaigns(self, sql, table_exists):
        sql.return_value = [frappe._dict(url="https://megasol.ch/bipv", clicks=7, last_click="2026-11-17 10:00:00")]
        links = report._link_clicks(["Campaign-1"])
        self.assertEqual(links, [{"url": "https://megasol.ch/bipv", "clicks": 7, "last_click": "2026-11-17 10:00:00"}])
        self.assertIn("Clicked", sql.call_args.args[0])
        self.assertEqual(sql.call_args.args[1][:1], ["Campaign-1"])
        self.assertEqual(report._link_clicks([]), [])


class ExportAndSegmentTest(TestCase):
    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    @patch.object(report.frappe, "has_permission", return_value=True)
    @patch.object(report.frappe.db, "sql")
    def test_export_neutralises_spreadsheet_formulas(self, sql, has_permission, names):
        self.enterContext(patch.object(frappe.local, "response", frappe._dict(), create=True))
        sql.return_value = [frappe._dict(email="=HYPERLINK(1)", audience="Lead", record="LEAD-1", campaign="Campaign-1", action_time=None, reason="")]
        report.export_metric("campaign", "Campaign-1", "sent")
        text = frappe.response["filecontent"].decode("utf-8-sig")
        self.assertIn("'=HYPERLINK(1)", text)
        self.assertEqual(frappe.response["type"], "download")

    @patch.object(report, "_campaign_names", return_value=["Campaign-1"])
    @patch.object(report.frappe.db, "sql")
    def test_segment_needs_one_record_type_and_someone_behind_the_number(self, sql, names):
        sql.return_value = []
        with self.assertRaises(frappe.ValidationError):
            report.save_metric_as_segment("campaign", "Campaign-1", "opened", "Openers")
        sql.return_value = [frappe._dict(audience="Lead", record="L-1"), frappe._dict(audience="Customer", record="C-1")]
        with self.assertRaises(frappe.ValidationError):
            report.save_metric_as_segment("campaign", "Campaign-1", "opened", "Openers")
        with self.assertRaises(frappe.ValidationError):
            report.save_metric_as_segment("campaign", "Campaign-1", "opened", "  ")


class WorkflowOverviewTest(TestCase):
    @patch.object(report, "_read_reporting_permissions")
    @patch.object(report.frappe, "db", new_callable=MagicMock)
    @patch.object(report.frappe, "get_all")
    @patch.object(report, "_sent_workflow_rows")
    def test_only_verified_handoffs_count_and_duplicates_do_not_inflate_rates(self, verify, get_all, db, permissions):
        db.table_exists.return_value = True
        ledger_rows = [frappe._dict(name="effect-1", result_json="{}"), frappe._dict(name="effect-2", result_json="{}")]
        verified = dict(email_queue="queue-1", communication="comm-1", recipient="person@example.com", email_template="Welcome")
        verify.return_value = [verified, dict(verified, recipient="PERSON@example.com")]
        get_all.side_effect = [ledger_rows, [frappe._dict(communication="comm-1", event_type="Opened")] * 2]
        data = report.get_workflow_overview("custom", "2026-09-01", "2026-09-30")
        self.assertEqual((data["summary"]["sent"], data["summary"]["opened"], data["summary"]["open_rate"]), (1, 1, 100.0))
        self.assertEqual(data["email_count"], 1)
        verify.assert_called_once_with(ledger_rows)
        filters = get_all.call_args_list[0].kwargs["filters"]
        self.assertIn(["completed_at", ">=", date(2026, 9, 1)], filters)
        self.assertIn(["completed_at", "<", date(2026, 10, 1)], filters)
        self.assertEqual(get_all.call_args_list[1].kwargs["filters"]["communication"], ["in", ["comm-1"]])

    @patch.object(report, "_read_reporting_permissions")
    @patch.object(report.frappe, "db", new_callable=MagicMock)
    @patch.object(report.frappe, "get_all")
    @patch.object(report, "_sent_workflow_rows", return_value=[])
    def test_completed_queue_creation_without_handoff_is_not_sent(self, verify, get_all, db, permissions):
        db.table_exists.return_value = True
        get_all.return_value = [frappe._dict(name="pending-effect", result_json="{}")]
        data = report.get_workflow_overview("30")
        self.assertEqual(data["summary"]["sent"], 0)
        self.assertIsNone(data["summary"]["open_rate"])
        self.assertEqual(data["email_count"], 0)
        self.assertEqual(get_all.call_count, 1)

    @patch.object(report, "_read_reporting_permissions")
    @patch.object(report.frappe, "db", new_callable=MagicMock)
    @patch.object(report.frappe, "get_all")
    @patch.object(report, "_sent_workflow_rows")
    def test_pagination_and_missing_tracking_table_preserve_confirmed_send(self, verify, get_all, db, permissions):
        db.table_exists.side_effect = lambda table: table == "Automation Effect Ledger"
        rows = [frappe._dict(name=f"effect-{i:04}", result_json="{}") for i in range(500)]
        get_all.side_effect = [rows, []]
        verify.side_effect = [[dict(email_queue="q", communication="c", recipient="p@example.com", email_template="T")], []]
        data = report.get_workflow_overview("30")
        self.assertEqual(data["summary"]["sent"], 1)
        self.assertEqual(data["summary"]["opened"], 0)
        self.assertIn(["name", ">", "effect-0499"], get_all.call_args_list[1].kwargs["filters"])


class HistoricalSendTimeTest(TestCase):
    def test_purged_queue_keeps_sent_timeline_detail_and_export_date(self):
        # Execute the actual report SQL against a small relational fixture.
        import sqlite3

        self.enterContext(patch.object(frappe.local, "response", frappe._dict(), create=True))
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.executescript('''
            create table `tabEmail Campaign` (
                name text, campaign_name text, modified text, custom_email_queue text,
                custom_communication text, custom_delivery_status text, custom_opened int,
                custom_opened_on text, custom_clicked int, custom_clicked_on text,
                custom_unsubscribed int, custom_unsubscribed_on text, custom_replied int,
                custom_replied_on text, custom_recipient_email text, recipient text,
                email_campaign_for text, custom_contact text, custom_error_message text,
                custom_excluded_reason text);
            create table `tabEmail Queue` (name text, modified text);
            create table `tabCommunication` (name text, delivery_status text, modified text,
                in_reply_to text, sent_or_received text, sender text);
            insert into `tabEmail Campaign` (name, campaign_name, modified, custom_email_queue,
                custom_delivery_status, custom_recipient_email)
                values ('old', 'Campaign-1', '2026-09-24 12:00:00', 'purged', 'Sent', 'p@example.com'),
                       ('current', 'Campaign-1', '2026-09-25 12:00:00', 'existing', 'Sent', 'q@example.com');
            insert into `tabEmail Queue` values ('existing', '2026-09-24 13:00:00');
        ''')

        def sql(query, args=None, as_dict=False):
            args = [str(value) if isinstance(value, date) else value for value in (args or [])]
            rows = connection.execute(query.replace("%s", "?"), args).fetchall()
            return [frappe._dict(dict(row)) for row in rows] if as_dict else [tuple(row) for row in rows]

        db = MagicMock()
        db.sql.side_effect = sql
        with (patch.object(report.frappe, "db", db),
              patch.object(report, "_campaign_names", return_value=["Campaign-1"]),
              patch.object(report.frappe, "has_permission", return_value=True)):
            trend = report._trend(["Campaign-1"], date(2026, 9, 24), date(2026, 9, 25))
            self.assertEqual([row.get("sent", 0) for row in trend], [2, 0])
            details = report.get_details("campaign", "Campaign-1", "sent")
            self.assertEqual(details["total"], 2)
            self.assertEqual({row["action_time"] for row in details["rows"]}, {"2026-09-24 12:00:00", "2026-09-24 13:00:00"})
            report.export_metric("campaign", "Campaign-1", "sent")
            csv = frappe.response["filecontent"].decode("utf-8-sig")
            self.assertIn("2026-09-24 12:00:00", csv)
            self.assertIn("2026-09-24 13:00:00", csv)
