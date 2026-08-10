frappe.ui.form.on("Email Template", {
	refresh(frm) {
		const can_design = frappe.user.has_role("Email Designer") || frappe.user.has_role("System Manager");
		if (frm.fields_dict.custom_builder_mode) frm.set_df_property("custom_builder_mode", "read_only", 1);
		const visual = frm.doc.custom_builder_mode === "Visual";
		frm.set_df_property("response_html", "read_only", visual ? 1 : 0);
		if (!frm.is_new() && can_design) {
			frm.add_custom_button(__(visual ? "Open Visual Builder" : "Start Visual Builder"), () => {
				window.location.href = `/builder?template=${encodeURIComponent(frm.doc.name)}`;
			}, __("Builder"));
			if (visual) {
				frm.add_custom_button(__("Switch to Raw HTML"), () => {
					frappe.confirm(__("Raw HTML mode unlocks the generated HTML for manual editing. The visual schema is retained for later use."), async () => {
						await frappe.call({ method: "finbyzreach.email_template_builder.api.switch_to_raw_html", args: { template_name: frm.doc.name, expected_modified: frm.doc.modified }, freeze: true });
						await frm.reload_doc();
					});
				}, __("Builder"));
			}
		}
		if (!frm.is_new() && frm.doc.custom_enable_ai_suggestion) {
			frm.add_custom_button(__("Summarize Template"), () => {
				analyze_template(frm);
			});
		}
	},
	after_save(frm) {
		if (frm.doc.custom_enable_ai_suggestion && !frm.doc.custom_ai_description) {
			analyze_template(frm);
		}
	}
});

function analyze_template(frm) {
	frappe.call({
		method: "finbyzreach.finbyzreach.ai_engine.analyze_email_template",
		args: {
			template_name: frm.doc.name
		},
		freeze: true,
		freeze_message: __("Analyzing template with AI..."),
		callback: function(r) {
			if (r.message && r.message.status === "success") {
				frappe.show_alert({
					message: r.message.message,
					indicator: 'green'
				});
				frm.reload_doc();
			}
		}
	});
}
