// Copyright (c) 2026, Finbyz and contributors
// For license information, please see license.txt

frappe.listview_settings["Campaign Candidate"] = {
	add_fields: ["status", "ai_score", "has_solar"],

	get_indicator(doc) {
		const map = {
			Suggested: "orange", Approved: "blue", Promoted: "green",
			Rejected: "gray", Skipped: "gray",
		};
		return [__(doc.status), map[doc.status] || "gray", "status,=," + doc.status];
	},

	onload(listview) {
		const selected = () => {
			const rows = listview.get_checked_items(true);
			if (!rows.length) frappe.msgprint(__("Select at least one candidate."));
			return rows;
		};

		const act = (method, args, label) =>
			frappe.call({ method, args, freeze: true, freeze_message: label }).then((r) => {
				frappe.show_alert({ message: (r.message || {}).message || __("Done"), indicator: "green" });
				listview.refresh();
			});

		listview.page.add_actions_menu_item(__("Approve"), () => {
			const names = selected();
			if (names.length)
				act("finbyzreach.ai_email_outreach.campaign_selection.set_status",
					{ names, status: "Approved" }, __("Approving…"));
		});

		listview.page.add_actions_menu_item(__("Reject"), () => {
			const names = selected();
			if (names.length)
				act("finbyzreach.ai_email_outreach.campaign_selection.set_status",
					{ names, status: "Rejected" }, __("Rejecting…"));
		});

		listview.page.add_actions_menu_item(__("Promote to Lead"), () => {
			const names = selected();
			if (!names.length) return;
			frappe.confirm(
				__("Promote {0} candidate(s) to Leads and start their outreach?", [names.length]),
				() => act("finbyzreach.ai_email_outreach.campaign_promotion.promote",
					{ names }, __("Promoting…"))
			);
		});
	},
};
