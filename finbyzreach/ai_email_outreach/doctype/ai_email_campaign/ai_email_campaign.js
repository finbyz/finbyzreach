// Copyright (c) 2026, Finbyz and contributors
// For license information, please see license.txt

const SEL = "finbyzreach.ai_email_outreach.campaign_selection";
const PROM = "finbyzreach.ai_email_outreach.campaign_promotion";

function counts(frm) {
	return frappe.db.get_list("Campaign Candidate", {
		filters: { ai_email_campaign: frm.doc.name },
		fields: ["status", "count(name) as n"],
		group_by: "status",
		limit: 0,
	});
}

function show_counts(frm) {
	counts(frm).then((rows) => {
		if (!rows || !rows.length) return;
		const colour = {
			Suggested: "orange", Approved: "blue", Promoted: "green",
			Rejected: "gray", Skipped: "gray",
		};
		rows.forEach((r) =>
			frm.dashboard.add_indicator(`${r.status}: ${r.n}`, colour[r.status] || "gray")
		);
	});
}

function run(frm, method, args, label) {
	return frm
		.call({ method, args, freeze: true, freeze_message: label })
		.then((r) => {
			const res = r.message || {};
			frappe.msgprint({
				title: res.ok === false ? __("Did not complete") : __("Done"),
				indicator: res.ok === false ? "red" : "green",
				message: res.message || __("No response."),
			});
			frm.refresh();
		});
}

frappe.ui.form.on("AI Email Campaign", {
	refresh(frm) {
		if (frm.is_new()) return;
		show_counts(frm);

		frm.add_custom_button(__("Find Candidates"), () => {
			if (!frm.doc.description) {
				frappe.msgprint(__("Add a campaign description first — the AI scores against it."));
				return;
			}
			frappe.confirm(
				__("Find everyone the criteria match and score them against the brief?<br><br>Nothing is contacted — candidates are stored for review."),
				() => run(frm, `${SEL}.build_candidates`,
					{ campaign_name: frm.doc.name, score_with_ai: 1 },
					__("Finding candidates…"))
			);
		}, __("Candidates"));

		frm.add_custom_button(__("Score Again"), () =>
			run(frm, `${SEL}.score_candidates`, { campaign_name: frm.doc.name }, __("Scoring…")),
			__("Candidates"));

		frm.add_custom_button(__("Review Candidates"), () =>
			frappe.set_route("List", "Campaign Candidate", {
				ai_email_campaign: frm.doc.name, status: "Suggested",
			}), __("Candidates"));

		frm.add_custom_button(__("Promote Approved"), () => {
			frappe.confirm(
				__("Turn every approved candidate into a Lead and start their outreach?<br><br>In <b>Review Before Sending</b> mode the emails are still held for approval."),
				() => run(frm, `${PROM}.promote`, { campaign_name: frm.doc.name }, __("Promoting…"))
			);
		}, __("Candidates")).addClass("btn-primary");

		if (frm.doc.approval_mode === "Send Automatically") {
			frm.dashboard.set_headline_alert(
				__("This campaign sends without review. Approved candidates will be emailed automatically."),
				"orange"
			);
		}
	},
});
