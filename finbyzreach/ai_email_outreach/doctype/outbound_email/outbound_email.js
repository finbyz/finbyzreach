// Copyright (c) 2026, Finbyz and contributors
// For license information, please see license.txt

frappe.ui.form.on("Outbound Email", {
	refresh(frm) {
		if (frm.is_new()) return;

		// Say plainly whether the emails were written with research behind them.
		if (frm.doc.research_note) {
			const failed = /failed|returned nothing|in place of/i.test(frm.doc.research_note);
			frm.dashboard.add_indicator(
				__("Research: {0}", [frm.doc.research_note]),
				failed ? "orange" : "green"
			);
		}

		const held = (frm.doc.communication_email || []).filter(
			(r) => r.status === "Awaiting Approval"
		);

		if (held.length) {
			frm.dashboard.set_headline_alert(
				__("{0} email(s) waiting for approval. Nothing is sent until you approve.", [held.length]),
				"orange"
			);

			frm.add_custom_button(__("Approve & Send"), () => {
				frappe.confirm(
					__("Approve {0} email(s)? The first will be sent shortly; later steps wait for their branch condition.", [held.length]),
					() => {
						frm.call({
							method: "finbyzreach.ai_email_outreach.campaign_promotion.approve_emails",
							args: { outbound_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Approving…"),
						}).then((r) => {
							frappe.show_alert({
								message: (r.message || {}).message || __("Approved"),
								indicator: "green",
							});
							frm.reload_doc();
						});
					}
				);
			}).addClass("btn-primary");
		}

		// Editing a held email before approving it is the point of review mode.
		frm.fields_dict.communication_email.grid.get_field("subject").df.read_only = 0;
		frm.fields_dict.communication_email.grid.get_field("content").df.read_only = 0;

		// Pre-existing action, kept as it was.
		frm.add_custom_button(__("Regenerate Emails"), () => regenerate_emails(frm), __("Actions"));
	},
});

function regenerate_emails(frm) {
	frappe.confirm(
		__("This will clear existing unsent emails and generate new ones. Continue?"),
		function () {
			frm.doc.communication_email = frm.doc.communication_email.filter(
				(e) => e.status !== "Unsent"
			);

			frappe.call({
				method: "finbyzreach.ai_email_outreach.doctype.communication_log.communication_log.regenerate_emails_for_log",
				args: { log_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Generating emails..."),
				callback: function (r) {
					if (r.message) {
						frappe.msgprint({
							title: __("Success"),
							indicator: "green",
							message: __("Generated {0} emails successfully!", [r.message.count]),
						});
						frm.reload_doc();
					}
				},
			});
		}
	);
}
