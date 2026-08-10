frappe.listview_settings["Email Template"] = frappe.listview_settings["Email Template"] || {};

(function () {
	const existing_onload = frappe.listview_settings["Email Template"].onload;

	function can_design_email() {
		return frappe.user.has_role("Email Designer") || frappe.user.has_role("System Manager");
	}

	function open_builder(template_name) {
		window.location.href = `/builder?template=${encodeURIComponent(template_name)}`;
	}

	function show_new_visual_template_dialog() {
		let should_autofill_subject = true;
		const dialog = new frappe.ui.Dialog({
			title: __("New visual email template"),
			fields: [
				{
					fieldname: "template_name",
					fieldtype: "Data",
					label: __("Template name"),
					reqd: 1,
					description: __("This becomes the Email Template document name."),
				},
				{
					fieldname: "subject",
					fieldtype: "Data",
					label: __("Subject"),
					reqd: 1,
				},
			],
			primary_action_label: __("Create and open builder"),
			primary_action() {
				const values = dialog.get_values();
				if (!values) return;

				frappe.call({
					method: "finbyzreach.email_template_builder.api.create_visual_template",
					args: {
						template_name: values.template_name,
						subject: values.subject,
					},
					freeze: true,
					freeze_message: __("Creating visual template..."),
					callback(response) {
						const message = response.message || {};
						if (!message.name) return;
						dialog.hide();
						open_builder(message.name);
					},
				});
			},
		});

		dialog.show();
		dialog.fields_dict.subject.$input.on("input", () => {
			should_autofill_subject = !dialog.fields_dict.subject.get_value();
		});
		dialog.fields_dict.template_name.$input.on("input", () => {
			if (should_autofill_subject) {
				dialog.set_value("subject", dialog.fields_dict.template_name.get_value() || "");
			}
		});
	}

	frappe.listview_settings["Email Template"].onload = function (listview) {
		if (existing_onload) existing_onload(listview);
		if (!can_design_email() || listview._visual_builder_actions_added) return;

		listview.page.add_inner_button(__("New Visual Email"), show_new_visual_template_dialog, __("Builder"));
		listview.page.add_action_item(__("Open Visual Builder"), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Select an Email Template first."));
				return;
			}
			open_builder(selected[0].name);
		});
		listview._visual_builder_actions_added = true;
	};
})();
