frappe.ui.form.on("Email Campaign", {
	refresh(frm) {
		set_standard_email_campaign_layout(frm);
		if (frm.doc.campaign_name) {
			frm.add_custom_button(__("Open Campaign"), () => {
				frappe.set_route("Form", "Campaign", frm.doc.campaign_name);
			});
		}

		const requestId = (frm.__broadcast_check_request || 0) + 1;
		frm.__broadcast_check_request = requestId;
		const campaignName = frm.doc.campaign_name;
		if (!campaignName) return;
		frappe.db.get_value("Campaign", campaignName, [
			"custom_email_template",
			"custom_lead_filters_json",
			"custom_subscription_topic",
		]).then((response) => {
			if (requestId !== frm.__broadcast_check_request || campaignName !== frm.doc.campaign_name) return;
			const campaign = response.message || {};
			const isBroadcast = Boolean(
				campaign.custom_email_template ||
				campaign.custom_lead_filters_json ||
				campaign.custom_subscription_topic
			);
			if (!isBroadcast) return;
			set_broadcast_email_campaign_layout(frm);
			frm.set_intro(
				__("This is a generated delivery record. Manage targeting, content and scheduling from Email Campaign Studio."),
				"blue"
			);
		});
	},
});

function set_standard_email_campaign_layout(frm) {
	const editable = ["campaign_name", "start_date", "email_campaign_for", "recipient", "sender"];
	const visible = ["campaign_name", "status", "column_break_4", "start_date", "end_date", "email_campaign_for", "recipient", "sender"];
	visible.forEach((fieldname) => frm.toggle_display(fieldname, true));
	editable.forEach((fieldname) => frm.set_df_property(fieldname, "read_only", 0));
	["status", "end_date"].forEach((fieldname) => frm.set_df_property(fieldname, "read_only", 1));
	frm.enable_save();
	if (frm.__broadcast_layout_applied) frm.set_intro("");
	frm.__broadcast_layout_applied = false;
}

function set_broadcast_email_campaign_layout(frm) {
	frm.__broadcast_layout_applied = true;
	frm.meta.fields.forEach((field) => {
		if (field.fieldname) frm.set_df_property(field.fieldname, "read_only", 1);
	});
	["email_campaign_for", "sender", "start_date", "end_date"].forEach((fieldname) => {
		frm.toggle_display(fieldname, false);
	});
	frm.disable_save();
}
