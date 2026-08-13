frappe.ui.form.on("Campaign", {
	setup(frm) {
		frm.set_query("custom_email_account", () => ({ filters: { enable_outgoing: 1 } }));
		frm.set_query("custom_subscription_topic", () => ({ filters: { disabled: 0 } }));
		frm.set_query("custom_email_template", () => ({
			filters: [["Email Template", "custom_reference_doctype", "in", ["", "Lead"]]],
		}));
	},

	refresh(frm) {
		frm.add_custom_button(
			__("Open Email Campaign Studio"),
			() => open_email_campaign_studio(frm),
			__("Email Broadcast")
		);
		const isBroadcast = Boolean(
			frm.doc.custom_email_template ||
			frm.doc.custom_lead_filters_json ||
			frm.doc.custom_subscription_topic
		);
		set_campaign_form_mode(frm, isBroadcast);
		if (frm.is_new()) return;
		if (!isBroadcast) return;

		const status = frm.doc.custom_broadcast_status || "Draft";
		frm.set_intro(__("Email broadcast status: {0}", [status]), broadcast_indicator(status));

		if (status === "Draft") {
			frm.add_custom_button(__("Preview Audience"), () => preview_audience(frm), __("Email Broadcast"));
		}
		frm.add_custom_button(__("Send Test"), () => show_test_dialog(frm), __("Email Broadcast"));
		// ERPNext's core View Leads action uses Lead UTM fields. Broadcast audiences are
		// frozen in Email Campaign recipient rows, so replace that action after all
		// refresh handlers have finished adding their buttons.
		setTimeout(() => {
			frm.remove_custom_button(__("View Leads"));
			if (Number(frm.doc.custom_candidate_count || 0) > 0) {
				frm.add_custom_button(
					__("View Leads"),
					() => view_campaign_leads(frm),
					__("Email Broadcast")
				);
			}
		}, 0);

		if (status === "Draft") {
			frm.add_custom_button(
				__("Review & Schedule"),
				() => open_email_campaign_studio(frm),
				__("Email Broadcast")
			);
		}
		if (status === "Failed" && Number(frm.doc.custom_failed_count || 0) > 0) {
			frm.add_custom_button(
				__("Retry Failed Recipients"),
				() => confirm_campaign_action(
					frm,
					"retry_failed_recipients",
					__("Retry only the {0} failed recipient(s)? Successful and excluded recipients will not be sent again.", [frm.doc.custom_failed_count]),
					__("Scheduling retries…")
				),
				__("Email Broadcast")
			);
		}
		if (["Scheduled", "Sending"].includes(status)) {
			frm.add_custom_button(
				__("Pause"),
				() => confirm_campaign_action(frm, "pause_campaign", __("Pause future batches? Emails already queued may still be delivered.")),
				__("Email Broadcast")
			);
		}
		if (status === "Paused") {
			frm.add_custom_button(
				__("Resume"),
				() => confirm_campaign_action(frm, "resume_campaign", __("Resume all remaining planned recipients from the next valid sending slot?")),
				__("Email Broadcast")
			);
		}
		if (["Scheduled", "Sending", "Paused"].includes(status)) {
			frm.add_custom_button(
				__("Cancel"),
				() => confirm_campaign_action(frm, "cancel_campaign", __("Cancel every recipient that has not yet been queued? This preserves delivery history and cannot be undone.")),
				__("Email Broadcast")
			);
		}
		if (!["Draft", "Preparing Audience"].includes(status)) {
			frm.add_custom_button(
				__("Refresh Metrics"),
				() => campaign_action(frm, "refresh_campaign_metrics_api"),
				__("Email Broadcast")
			);
		}
	},
});

function set_campaign_form_mode(frm, isBroadcast) {
	const frozen = isBroadcast && (frm.doc.custom_broadcast_status || "Draft") !== "Draft";
	if (frozen) frm.disable_save();
	[
		"custom_email_template", "custom_subject_override", "custom_subscription_topic",
		"custom_email_account", "custom_sender_name", "custom_reply_to", "custom_batch_size",
		"custom_repeat_every", "custom_repeat_unit", "custom_start_on", "custom_window_start",
		"custom_window_end", "custom_restrict_sending_window", "custom_send_monday",
		"custom_send_tuesday", "custom_send_wednesday", "custom_send_thursday",
		"custom_send_friday", "custom_send_saturday", "custom_send_sunday",
		"custom_enable_open_tracking", "custom_enable_click_tracking", "custom_utm_source",
		"custom_utm_medium",
	].forEach((fieldname) => frm.set_df_property(fieldname, "read_only", frozen ? 1 : 0));
}

function open_email_campaign_studio(frm) {
	if (frm.is_new()) {
		route_to_email_campaign_studio();
		return;
	}
	route_to_email_campaign_studio(frm.doc.name);
}

function route_to_email_campaign_studio(campaignName) {
	const path = "/app/email-campaign-studio";
	const session = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
	const query = campaignName
		? "?studio_campaign=" + encodeURIComponent(campaignName) + "&studio_session=" + session
		: "?new=" + session;
	frappe.route_options = {};
	window.history.pushState(null, null, path + query);
	frappe.router.route();
}

function view_campaign_leads(frm) {
	frappe.route_options = {
		campaign_name: frm.doc.name,
		email_campaign_for: "Lead",
	};
	frappe.set_route("List", "Email Campaign");
}

function broadcast_indicator(status) {
	if (status === "Completed") return "green";
	if (["Failed", "Cancelled"].includes(status)) return "red";
	if (status === "Paused") return "orange";
	return "blue";
}

function campaign_action(frm, method, freeze_message) {
	return frappe.call({
		method: "finbyzreach.email_marketing." + method,
		type: "POST",
		args: { campaign_name: frm.doc.name },
		freeze: Boolean(freeze_message),
		freeze_message: freeze_message,
	}).then((response) => {
		frm.reload_doc();
		if (response.message && response.message.message) {
			frappe.show_alert({ message: response.message.message, indicator: "green" });
		}
	});
}

function confirm_campaign_action(frm, method, message, freeze_message) {
	return frappe.confirm(message, () => campaign_action(frm, method, freeze_message));
}

function preview_audience(frm) {
	return frappe.call({
		method: "finbyzreach.email_marketing.preview_campaign_audience_api",
		args: { campaign_name: frm.doc.name },
	}).then((response) => {
		const data = response.message || {};
		const reasons = Object.entries(data.excluded_reasons || {})
			.map(([reason, count]) => frappe.utils.escape_html(reason) + ": " + count)
			.join("<br>");
		frappe.msgprint({
			title: __("Audience Preview"),
			message:
				__("Candidates: {0}<br>Eligible: {1}<br>Excluded: {2}", [
					data.candidate_count || 0,
					data.eligible_count || 0,
					data.excluded_count || 0,
				]) + (reasons ? "<hr>" + reasons : ""),
			indicator: data.eligible_count ? "green" : "orange",
		});
	});
}

function show_test_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Send Campaign Test"),
		fields: [
			{
				fieldname: "recipient",
				fieldtype: "Data",
				options: "Email",
				label: __("Recipient"),
				reqd: 1,
				default: frappe.session.user,
			},
			{
				fieldname: "sample_lead",
				fieldtype: "Link",
				options: "Lead",
				label: __("Personalize Using Lead"),
				reqd: 1,
			},
		],
		primary_action_label: __("Queue Test"),
		primary_action(values) {
			dialog.get_primary_btn().prop("disabled", true);
			frappe.call({
				method: "finbyzreach.email_marketing.send_campaign_test",
				type: "POST",
				args: { campaign_name: frm.doc.name, ...values },
			}).then(() => {
				dialog.hide();
				frappe.show_alert({ message: __("Test email queued"), indicator: "green" });
			}).always(() => dialog.get_primary_btn().prop("disabled", false));
		},
	});
	dialog.show();
}
