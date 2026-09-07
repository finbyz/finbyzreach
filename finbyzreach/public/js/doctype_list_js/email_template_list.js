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

	function show_ai_create_dialog() {
		const sample_prompts = [
			{ label: __("Product Launch"), text: "Product launch announcement with hero banner, headline, 3 feature columns, and a prominent 'Get Started' CTA button." },
			{ label: __("Welcome / Onboarding"), text: "Warm welcome email for new customers with an introduction, 3 quick-start steps, helpful resources, and support contact." },
			{ label: __("Monthly Newsletter"), text: "Company newsletter featuring top monthly highlights, a featured customer story, upcoming events, and social media links." },
			{ label: __("Special Offer / Promo"), text: "Limited-time promotional email with an eye-catching discount banner, urgency headline, product showcase, and 'Claim Discount' button." },
		];

		const dialog = new frappe.ui.Dialog({
			title: __("Build Email Template with AI ✨"),
			fields: [
				{
					fieldname: "prompt_desc",
					fieldtype: "HTML",
					options: `<p style="margin:0 0 10px; color:var(--text-muted); font-size:12px;">
						${__("Describe the email you want to build. AI will design the full layout, write persuasive copy, generate visuals, and open the visual builder.")}
					</p>`,
				},
				{
					fieldname: "prompt",
					fieldtype: "Small Text",
					label: __("What kind of email do you want to build?"),
					reqd: 1,
					placeholder: __("e.g. Modern welcome email for MegaSol Solar Solutions introducing our services, with solar benefits in 3 columns and a CTA button to schedule a consultation."),
				},
				{
					fieldname: "sample_chips_html",
					fieldtype: "HTML",
				},
				{
					fieldname: "details_section",
					fieldtype: "Section Break",
					label: __("Template Details (Optional)"),
					collapsible: 1,
					collapsed: 1,
				},
				{
					fieldname: "template_name",
					fieldtype: "Data",
					label: __("Template name"),
					description: __("Leave blank to auto-generate from your prompt."),
				},
				{
					fieldname: "subject",
					fieldtype: "Data",
					label: __("Subject line"),
					description: __("Leave blank to auto-generate from your prompt."),
				},
			],
			primary_action_label: __("Generate & Open Builder ✨"),
			primary_action() {
				const values = dialog.get_values();
				if (!values || !values.prompt) return;

				frappe.call({
					method: "finbyzreach.email_template_builder.ai.create_template_with_ai",
					args: {
						prompt: values.prompt,
						template_name: values.template_name || "",
						subject: values.subject || "",
					},
					freeze: true,
					freeze_message: __("AI is designing your email template from scratch..."),
					callback(response) {
						const message = response.message || {};
						if (!message.name || !message.route) return;
						dialog.hide();
						frappe.show_alert({
							message: __("Created '{0}'! Opening builder...", [message.name]),
							indicator: "green",
						});
						window.location.href = message.route;
					},
				});
			},
		});

		dialog.show();

		// Render quick suggestion chips
		const $wrapper = dialog.fields_dict.sample_chips_html.$wrapper;
		$wrapper.empty();
		const $chips = $('<div style="display:flex; flex-wrap:wrap; gap:6px; margin: 4px 0 10px;"></div>');
		sample_prompts.forEach((chip) => {
			const $btn = $(`<button type="button" class="btn btn-xs btn-default" style="border-radius:12px; font-size:11px;">${chip.label}</button>`);
			$btn.on("click", () => {
				dialog.set_value("prompt", chip.text);
			});
			$chips.append($btn);
		});
		$wrapper.append($('<small class="text-muted" style="display:block; margin-bottom:4px; font-size:11px;">Quick prompt ideas:</small>')).append($chips);
	}

	frappe.provide("frappe.email_template_builder");
	frappe.email_template_builder.show_ai_create_dialog = show_ai_create_dialog;

	frappe.listview_settings["Email Template"].onload = function (listview) {
		if (existing_onload) existing_onload(listview);
		if (!can_design_email() || listview._visual_builder_actions_added) return;

		listview.page.add_button(__("Build with AI ✨"), show_ai_create_dialog);
		listview.page.add_inner_button(__("Build with AI ✨"), show_ai_create_dialog, __("Builder"));
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
