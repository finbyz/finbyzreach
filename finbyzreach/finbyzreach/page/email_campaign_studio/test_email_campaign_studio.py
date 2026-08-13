from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe
from frappe.model.base_document import import_controller

try:
	from frappe.tests import UnitTestCase
except ImportError:  # Frappe 15
	from unittest import TestCase as UnitTestCase

from finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio import (
	_campaign_values,
	_audience_context,
	_campaign_for_studio,
	_ensure_utm_campaign,
	_frozen_preview_response,
	_frozen_recipient_preview_rows,
	_lead_names,
	_preview_response,
	_parse_payload,
	_resolved_studio_audience,
	create_campaign,
	get_bootstrap,
	preview_email,
	send_test,
)
from finbyzreach.overrides.email_campaign import (
	Campaign as CampaignOverride,
	EmailCampaign as EmailCampaignOverride,
)


class TestEmailCampaignStudio(UnitTestCase):
	def test_v15_uses_studio_campaign_controller_overrides(self):
		campaign_controller = import_controller("Campaign")
		email_campaign_controller = import_controller("Email Campaign")

		self.assertTrue(issubclass(campaign_controller, CampaignOverride))
		self.assertTrue(issubclass(email_campaign_controller, EmailCampaignOverride))

	@patch(
		"finbyzreach.email_marketing._is_email_broadcast",
		return_value=True,
	)
	def test_studio_recipient_does_not_require_legacy_campaign_schedule(self, _is_broadcast):
		email_campaign_controller = import_controller("Email Campaign")
		recipient = email_campaign_controller(
			{
				"doctype": "Email Campaign",
				"__islocal": 1,
				"campaign_name": "Studio Campaign",
				"recipient": "LEAD-1",
				"custom_delivery_status": "Skipped",
				"custom_scheduled_at": "2026-08-11 18:02:01",
			}
		)

		recipient.validate()

		self.assertEqual(recipient.email_campaign_for, "Lead")
		self.assertEqual(recipient.status, "Completed")
		self.assertEqual(recipient.start_date, recipient.end_date)

	@patch(
		"erpnext.crm.doctype.email_campaign.email_campaign.EmailCampaign.validate",
		autospec=True,
	)
	@patch(
		"finbyzreach.email_marketing._is_email_broadcast",
		return_value=False,
	)
	def test_standard_email_campaign_keeps_erpnext_validation(self, _is_broadcast, native_validate):
		email_campaign_controller = import_controller("Email Campaign")
		recipient = email_campaign_controller(
			{
				"doctype": "Email Campaign",
				"__islocal": 1,
				"campaign_name": "Standard Campaign",
			}
		)

		recipient.validate()

		native_validate.assert_called_once_with(recipient)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.new_doc"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.load_doctype_module",
		side_effect=ImportError("No module named frappe.core.doctype.utm_campaign"),
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.db.exists",
		return_value=True,
	)
	def test_v15_skips_orphaned_utm_campaign_doctype(self, exists, load_module, new_doc):
		_ensure_utm_campaign("Studio Campaign")

		exists.assert_called_once_with("DocType", "UTM Campaign")
		load_module.assert_called_once_with("UTM Campaign")
		new_doc.assert_not_called()

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.new_doc"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.load_doctype_module"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.db.exists",
		side_effect=[True, False],
	)
	def test_v16_creates_supported_utm_campaign(self, exists, load_module, new_doc):
		utm = MagicMock()
		new_doc.return_value = utm

		_ensure_utm_campaign("Studio Campaign")

		self.assertEqual(
			exists.call_args_list,
			[
				(("DocType", "UTM Campaign"),),
				(("UTM Campaign", "Studio Campaign"),),
			],
		)
		load_module.assert_called_once_with("UTM Campaign")
		new_doc.assert_called_once_with("UTM Campaign")
		self.assertEqual(utm.name, "Studio Campaign")
		utm.insert.assert_called_once_with(ignore_permissions=True)

	def test_invalid_json_is_reported_as_campaign_validation(self):
		with self.assertRaises(frappe.ValidationError):
			_parse_payload("{invalid")

		with self.assertRaises(frappe.ValidationError):
			_audience_context("[invalid")

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_list",
		return_value=[frappe._dict(name="LEAD-1", lead_name="Ada", company_name="Example")],
	)
	def test_frozen_recipient_rows_query_lead_with_valid_call_shape(self, get_list):
		rows = _frozen_recipient_preview_rows(
			[frappe._dict(recipient="LEAD-1", custom_recipient_email="ada@example.com")],
			10,
		)

		self.assertEqual(rows[0].email_id, "ada@example.com")
		get_list.assert_called_once_with(
			"Lead",
			filters={"name": ["in", ["LEAD-1"]]},
			fields=["name", "lead_name", "company_name"],
			limit=10,
		)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.nowdate",
		return_value="2026-07-22",
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.now_datetime",
		return_value=datetime(2026, 7, 22, 10, 0, 0),
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._campaign_for_studio",
		return_value=None,
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_list",
		side_effect=[[], []],
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_bootstrap_has_no_application_delivery_limits(
		self, _permission, _get_list, _campaign, _now, _today
	):
		result = get_bootstrap()

		self.assertNotIn("delivery_limits", result)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.email_marketing.decorate_campaign_links",
		return_value='<p><a href="https://example.com/?utm_source=newsletter">Hello Ada</a></p>',
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.render_campaign_snapshot",
		return_value=frappe._dict(subject="Hello Ada", html="<p>Hello Ada</p>"),
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.get_campaign_snapshot",
		return_value=frappe._dict(
			mode="Visual",
			subject="Hello {{ doc.lead_name }}",
			preheader="",
			html="<p>Hello {{ doc.lead_name }}</p>",
		),
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_doc"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_email_preview_renders_without_queuing_mail(
		self, _permission, get_doc, _snapshot, render, decorate
	):
		lead = frappe._dict(name="LEAD-1", lead_name="Ada")
		lead.check_permission = MagicMock()
		get_doc.return_value = lead

		result = preview_email(
			payload=frappe.as_json(
				{
					"campaign_title": "Preview Campaign",
					"email_template": "Visual Welcome",
					"utm_source": "newsletter",
					"utm_medium": "email",
				}
			),
			sample_lead=lead.name,
		)

		self.assertEqual(result["subject"], "Hello Ada")
		self.assertIn("utm_source=newsletter", result["html"])
		self.assertEqual(result["frozen"], 0)
		lead.check_permission.assert_called_once_with("read")
		render.assert_called_once()
		decorate.assert_called_once()

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_doc"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_frozen_email_preview_never_falls_back_to_browser_content(
		self, _permission, get_doc
	):
		lead = frappe._dict(name="LEAD-1", lead_name="Ada")
		lead.check_permission = MagicMock()
		campaign = frappe._dict(
			name="Damaged Frozen Campaign",
			custom_broadcast_status="Scheduled",
			custom_snapshot_subject="",
			custom_snapshot_html="",
		)
		campaign.check_permission = MagicMock()
		get_doc.side_effect = [lead, campaign]

		with self.assertRaises(frappe.ValidationError):
			preview_email(
				payload=frappe.as_json(
					{
						"source_campaign": campaign.name,
						"email_template": "Manipulated Browser Template",
					}
				),
				sample_lead=lead.name,
			)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._frozen_recipient_preview_rows"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_all"
	)
	def test_frozen_preview_reads_scheduled_recipients_not_live_filters(
		self, get_all, preview_rows
	):
		campaign = frappe._dict(
			name="Frozen Campaign",
			custom_broadcast_status="Completed",
			custom_candidate_count=12,
			custom_eligible_count=10,
			custom_excluded_count=2,
			custom_subscription_topic="Product Updates",
		)
		get_all.side_effect = [
			[
				frappe._dict(recipient="LEAD-3", custom_recipient_email="three@example.com"),
				frappe._dict(recipient="LEAD-4", custom_recipient_email="four@example.com"),
			],
			[frappe._dict(custom_excluded_reason="Lead unsubscribed", count=2)],
			[],
		]
		preview_rows.side_effect = lambda rows, _limit: [row.recipient for row in rows]

		result = _frozen_preview_response(campaign, eligible_page=2, eligible_page_length=2)

		self.assertEqual(result["eligible_samples"], ["LEAD-3", "LEAD-4"])
		self.assertEqual(result["eligible_count"], 10)
		self.assertEqual(result["excluded_reasons"], {"Lead unsubscribed": 2})
		self.assertEqual(result["frozen"], 1)
		self.assertEqual(get_all.call_args_list[0].kwargs["start"], 2)
		self.assertEqual(
			get_all.call_args_list[0].kwargs["filters"]["custom_batch_number"],
			[">", 0],
		)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.email_marketing.test_recipient_exclusion",
		return_value="Unsubscribed from topic Frozen Topic",
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_doc"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_frozen_test_uses_saved_topic_not_browser_payload(
		self, _permission, get_doc, recipient_exclusion
	):
		campaign = frappe._dict(
			name="Frozen Campaign",
			custom_broadcast_status="Scheduled",
			custom_subscription_topic="Frozen Topic",
		)
		campaign.check_permission = MagicMock()
		get_doc.return_value = campaign

		with self.assertRaises(frappe.ValidationError):
			send_test(
				payload=frappe.as_json(
					{
						"source_campaign": campaign.name,
						"subscription_topic": "Manipulated Topic",
					}
				),
				recipient="optout@example.com",
				sample_lead="LEAD-1",
			)

		recipient_exclusion.assert_called_once_with(
			"optout@example.com", "Frozen Topic"
		)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.email_marketing.test_recipient_exclusion",
		return_value="Unsubscribed from topic Product Updates",
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_send_test_cannot_bypass_recipient_suppression(
		self, _check_permission, _recipient_exclusion
	):
		with self.assertRaises(frappe.ValidationError):
			send_test(
				payload=frappe.as_json({"subscription_topic": "Product Updates"}),
				recipient="optout@example.com",
				sample_lead="LEAD-1",
			)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_list"
	)
	def test_audience_query_is_distinct_for_child_table_joins(self, get_list):
		get_list.return_value = ["LEAD-1"]

		self.assertEqual(
			_lead_names('[ ["Lead", "email_id", "is", "set"] ]'),
			["LEAD-1"],
		)
		self.assertTrue(get_list.call_args.kwargs["distinct"])

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.email_marketing.resolve_campaign_audience",
		return_value=[],
	)
	def test_empty_resolved_filter_remains_a_valid_zero_recipient_preview(self, resolve_audience):
		context = frappe._dict(
			include_filters_json='[["Lead","email_id","=","missing@example.com"]]',
			exclude_filters_json="[]",
			email_groups=[],
			include_leads=[],
			exclude_leads=[],
		)

		result = _resolved_studio_audience(context, "Product Updates")

		self.assertEqual(result, [])
		campaign = resolve_audience.call_args.args[0]
		self.assertEqual(campaign.custom_lead_filters_json, context.include_filters_json)
		self.assertEqual(campaign.custom_exclude_filters_json, context.exclude_filters_json)

	def test_preview_response_reports_eligibility_reasons(self):
		response = _preview_response(
			[
				frappe._dict(lead="LEAD-1", eligible=True, reason=None),
				frappe._dict(lead="LEAD-2", eligible=False, reason="Lead unsubscribed"),
				frappe._dict(lead="LEAD-3", eligible=False, reason="Missing or invalid email"),
			]
		)
		self.assertEqual(response["candidate_count"], 3)
		self.assertEqual(response["eligible_count"], 1)
		self.assertEqual(response["excluded_count"], 2)
		self.assertEqual(response["excluded_reasons"]["Lead unsubscribed"], 1)
		self.assertEqual(response["eligible_page"], 1)
		self.assertEqual(response["eligible_total_pages"], 1)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._lead_preview_rows"
	)
	def test_preview_response_paginates_eligible_leads(self, preview_rows):
		resolved = [
			frappe._dict(lead=f"LEAD-{index:03}", eligible=True, reason=None)
			for index in range(1, 26)
		]
		preview_rows.side_effect = lambda names, _limit: names

		response = _preview_response(
			resolved, eligible_page=2, eligible_page_length=10
		)

		self.assertEqual(response["eligible_page"], 2)
		self.assertEqual(response["eligible_page_length"], 10)
		self.assertEqual(response["eligible_total_pages"], 3)
		self.assertEqual(response["eligible_samples"], [f"LEAD-{index:03}" for index in range(11, 21)])

		capped = _preview_response(resolved, eligible_page_length=5000)
		self.assertEqual(capped["eligible_page_length"], 1000)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_list"
	)
	def test_preview_response_identifies_topic_unsubscribed_leads(self, get_list):
		get_list.return_value = [
			frappe._dict(
				name="LEAD-2",
				lead_name="Topic Opt-out",
				company_name="Example AG",
				email_id="optout@example.com",
			)
		]
		response = _preview_response(
			[
				frappe._dict(
					lead="LEAD-2",
					eligible=False,
					reason="Globally unsubscribed",
					topic_unsubscribed=True,
				)
			],
			"Product Updates",
		)

		self.assertEqual(response["topic_unsubscribed_count"], 1)
		self.assertEqual(response["topic_unsubscribed_samples"][0].name, "LEAD-2")
		self.assertEqual(response["topic_unsubscribed_more"], 0)
		self.assertEqual(
			get_list.call_args.kwargs["filters"], {"name": ["in", ["LEAD-2"]]}
		)

	def test_campaign_values_apply_safe_delivery_defaults(self):
		context = frappe._dict(
			include_filters_json='[["Lead","status","=","Lead"]]',
			exclude_filters_json="[]",
			email_groups=[],
		)
		values = _campaign_values(
			frappe._dict(
				campaign_title="Studio Launch",
				email_template="Welcome",
				subscription_topic="Product Updates",
				email_account="Marketing",
				start_date="2026-07-21",
				start_time="10:00:00",
				send_monday=1,
			),
			context,
		)
		self.assertEqual(values["doctype"], "Campaign")
		self.assertEqual(values["custom_batch_size"], 100)
		self.assertEqual(values["custom_repeat_every"], 1)
		self.assertEqual(values["custom_repeat_unit"], "Hours")
		self.assertEqual(values["custom_subscription_topic"], "Product Updates")
		self.assertEqual(values["custom_utm_source"], "newsletter")
		self.assertEqual(values["custom_utm_medium"], "email")
		self.assertNotIn("time_zone", values)

	def test_campaign_values_store_preview_counts_for_delivery_validation(self):
		context = frappe._dict(
			include_filters_json='[["Lead","status","=","Lead"]]',
			exclude_filters_json="[]",
			email_groups=[],
		)
		values = _campaign_values(
			frappe._dict(
				campaign_title="Studio Launch",
				start_date="2026-07-21",
				start_time="10:00:00",
				batch_size=100,
			),
			context,
			require_ready=False,
			preview={"candidate_count": 1, "eligible_count": 1, "excluded_count": 0},
		)

		self.assertEqual(values["custom_candidate_count"], 1)
		self.assertEqual(values["custom_eligible_count"], 1)
		self.assertEqual(values["custom_excluded_count"], 0)
		self.assertEqual(values["custom_batch_count"], 1)

	def test_campaign_values_preserve_invalid_delivery_inputs_for_validation(self):
		context = frappe._dict(
			include_filters_json='[["Lead","email_id","is","set"]]',
			exclude_filters_json="[]",
			email_groups=[],
		)

		values = _campaign_values(
			frappe._dict(
				campaign_title="Studio Launch",
				start_date="2026-07-21",
				start_time="10:00:00",
				batch_size=0,
				repeat_every=0,
				repeat_unit="Weeks",
			),
			context,
			require_ready=False,
		)

		self.assertEqual(values["custom_batch_size"], 0)
		self.assertEqual(values["custom_repeat_every"], 0)
		self.assertEqual(values["custom_repeat_unit"], "Weeks")

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_doc"
	)
	def test_campaign_for_studio_returns_existing_campaign_values(self, get_doc):
		campaign = frappe._dict(
			name="Existing Studio Campaign",
			campaign_name="Existing Studio Campaign",
			custom_broadcast_status="Draft",
			custom_email_template="Welcome",
			custom_subject_override="Subject",
			custom_subscription_topic="Product Updates",
			custom_email_account="Marketing",
			custom_sender_name="Megasol",
			custom_reply_to="reply@example.com",
			custom_lead_filters_json='[["Lead","email_id","is","set"]]',
			custom_exclude_filters_json='[["Lead","unsubscribed","=",1]]',
			custom_exclude_email_groups_json='["Suppression"]',
			custom_start_on="2026-07-21 10:30:00",
			custom_batch_size=50,
			custom_repeat_every=2,
			custom_repeat_unit="Hours",
			custom_restrict_sending_window=1,
			custom_window_start="09:00:00",
			custom_window_end="17:00:00",
			custom_enable_open_tracking=1,
			custom_enable_click_tracking=0,
			custom_utm_source="campaign",
			custom_utm_medium="email",
			custom_send_monday=1,
			custom_send_tuesday=0,
			custom_send_wednesday=1,
			custom_send_thursday=0,
			custom_send_friday=1,
			custom_send_saturday=0,
			custom_send_sunday=0,
			check_permission=MagicMock(),
		)
		get_doc.return_value = campaign

		result = _campaign_for_studio("Existing Studio Campaign")

		self.assertEqual(result["name"], "Existing Studio Campaign")
		self.assertEqual(result["filters"], [["Lead", "email_id", "is", "set"]])
		self.assertEqual(result["exclude_email_groups"], ["Suppression"])
		self.assertEqual(result["start_date"], "2026-07-21")
		self.assertEqual(result["start_time"], "10:30:00")
		self.assertEqual(result["enable_click_tracking"], 0)
		campaign.check_permission.assert_called_once_with("read")

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._ensure_utm_campaign"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.email_marketing.schedule_campaign"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_doc"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._campaign_values"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._preview_response"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._resolved_studio_audience"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._audience_context"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_schedule_creates_one_core_campaign_without_hidden_segment(
		self,
		_check_permission,
		audience_context,
		resolved_audience,
		preview_response,
		campaign_values,
		get_doc,
		schedule_campaign,
		_ensure_utm_campaign,
	):
		audience_context.return_value = frappe._dict(
			include_filters_json='[["Lead","status","=","Lead"]]',
			exclude_filters_json="[]",
			email_groups=["Blacklist"],
			include_leads=["LEAD-1"],
			exclude_leads=[],
		)
		resolved_audience.return_value = [frappe._dict(lead="LEAD-1", eligible=True)]
		preview_response.return_value = {
			"candidate_count": 1,
			"eligible_count": 1,
			"excluded_count": 0,
			"excluded_reasons": {},
			"eligible_samples": [],
		}
		campaign_values.return_value = {"doctype": "Campaign", "campaign_name": "Studio Launch"}
		campaign = MagicMock()
		campaign.name = "Studio Launch"
		campaign.insert.return_value = campaign
		get_doc.return_value = campaign

		result = create_campaign(payload="{}", launch="schedule")

		self.assertEqual(result["status"], "Scheduled")
		self.assertTrue(result["created"])
		self.assertEqual(result["route"], ["Form", "Campaign", "Studio Launch"])
		self.assertEqual(get_doc.call_count, 1)
		schedule_campaign.assert_called_once_with(campaign.name)

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._ensure_utm_campaign"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.email_marketing.schedule_campaign"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_doc"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._campaign_values"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._preview_response"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._resolved_studio_audience"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._audience_context"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_save_existing_campaign_updates_in_place(
		self,
		_check_permission,
		audience_context,
		resolved_audience,
		preview_response,
		campaign_values,
		get_doc,
		schedule_campaign,
		_ensure_utm_campaign,
	):
		audience_context.return_value = frappe._dict(
			include_filters_json='[["Lead","status","=","Lead"]]',
			exclude_filters_json="[]",
			email_groups=[],
		)
		resolved_audience.return_value = [frappe._dict(lead="LEAD-1", eligible=True)]
		preview_response.return_value = {"eligible_count": 1}
		campaign_values.return_value = {
			"doctype": "Campaign",
			"campaign_name": "Updated Studio Campaign",
			"custom_email_template": "Welcome",
		}
		campaign = frappe._dict(
			name="Existing Studio Campaign",
			custom_broadcast_status="Draft",
			set=MagicMock(),
			save=MagicMock(),
			check_permission=MagicMock(),
		)
		get_doc.return_value = campaign

		result = create_campaign(
			payload=frappe.as_json({"source_campaign": "Existing Studio Campaign"}),
			launch="draft",
		)

		self.assertEqual(result["campaign"], "Existing Studio Campaign")
		self.assertFalse(result["created"])
		self.assertEqual(result["status"], "Draft")
		get_doc.assert_called_once_with("Campaign", "Existing Studio Campaign")
		campaign.check_permission.assert_called_once_with("write")
		campaign.set.assert_any_call("campaign_name", "Updated Studio Campaign")
		campaign.save.assert_called_once()
		schedule_campaign.assert_not_called()

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._ensure_utm_campaign"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.frappe.get_doc"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._preview_response",
		return_value={"eligible_count": 0},
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._resolved_studio_audience",
		return_value=[],
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._audience_context"
	)
	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_draft_can_be_saved_before_audience_and_content_are_complete(
		self, _permission, audience_context, _resolved, _preview, get_doc, _ensure_utm_campaign
	):
		audience_context.return_value = frappe._dict(
			include_filters_json="[]",
			exclude_filters_json="[]",
			email_groups=[],
			include_leads=[],
			exclude_leads=[],
		)
		campaign = MagicMock()
		campaign.name = "Early Draft"
		campaign.insert.return_value = campaign
		get_doc.return_value = campaign

		result = create_campaign(
			payload=frappe.as_json({"campaign_title": "Early Draft"}),
			launch="draft",
		)

		self.assertEqual(result["status"], "Draft")
		self.assertEqual(result["preview"]["eligible_count"], 0)
		self.assertFalse(audience_context.call_args.kwargs["require_filters"])
		values = get_doc.call_args.args[0]
		self.assertIsNone(values["custom_email_template"])
		self.assertIsNone(values["custom_subscription_topic"])

	@patch(
		"finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio._check_permission"
	)
	def test_create_campaign_rejects_unknown_launch_action(self, _check_permission):
		with self.assertRaises(frappe.ValidationError):
			create_campaign(payload="{}", launch="unexpected")
