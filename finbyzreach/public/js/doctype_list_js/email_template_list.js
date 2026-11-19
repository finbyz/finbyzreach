frappe.listview_settings["Email Template"] = frappe.listview_settings["Email Template"] || {};

(function () {
	frappe.listview_settings["Email Template"].get_form_link = function (doc) {
		if (frappe.user.has_role("Email Designer") || frappe.user.has_role("System Manager")) {
			return `/app/email-template-builder/${encodeURIComponent(doc.name)}/${encodeURIComponent("Email Template")}/${encodeURIComponent(frappe.app?.sidebar?.current_module || "")}`;
		}
		return `/app/email-template/${encodeURIComponent(doc.name)}`;
	};
	const existing_onload = frappe.listview_settings["Email Template"].onload;

	function can_design_email() {
		return frappe.user.has_role("Email Designer") || frappe.user.has_role("System Manager");
	}

	function open_builder(template_name) {
		frappe.email_template_library.open_builder(template_name);
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
				// EM-16: the email type, language and folder are chosen here, not only in the Studio.
				{
					fieldname: "email_type",
					fieldtype: "Link",
					options: "Subscription Topic",
					label: __("Email type"),
					description: __("Decides who may receive this email. Transactional ignores marketing opt-outs."),
					get_query: () => ({ filters: { disabled: 0, category: ["in", ["Mailing Type", "System"]] } }),
				},
				{
					fieldname: "language",
					fieldtype: "Select",
					label: __("Language"),
					options: ["", "de", "fr", "it", "en"].join("\n"),
					default: "de",
				},
				{
					fieldname: "folder",
					fieldtype: "Link",
					options: "Email Folder",
					label: __("Folder"),
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
						email_type: values.email_type || "",
						language: values.language || "",
						folder: values.folder || "",
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

	function show_ai_create_dialog(template_doctype) {
		// Frappe passes the click event to a button handler, so a bare reference
		// would arrive here as an Event rather than a doctype name. Sending that
		// on to frappe.call makes jQuery.param throw "Illegal invocation", which
		// leaves the freeze overlay up for ever.
		if (typeof template_doctype !== "string" || !template_doctype) {
			template_doctype = "Email Template";
		}
		const is_master = template_doctype === "Email Template Master";
		const sample_prompts = [
			{ label: __("Product Launch"), text: "Product launch announcement with hero banner, headline, 3 feature columns, and a prominent 'Get Started' CTA button." },
			{ label: __("Welcome / Onboarding"), text: "Warm welcome email for new customers with an introduction, 3 quick-start steps, helpful resources, and support contact." },
			{ label: __("Monthly Newsletter"), text: "Company newsletter featuring top monthly highlights, a featured customer story, upcoming events, and social media links." },
			{ label: __("Special Offer / Promo"), text: "Limited-time promotional email with an eye-catching discount banner, urgency headline, product showcase, and 'Claim Discount' button." },
		];

		const dialog = new frappe.ui.Dialog({
			title: __(is_master ? "Build Master Template with AI ✨" : "Build Email Template with AI ✨"),
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
						template_doctype,
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

	// The list's main button creates an email template. Campaigns start from the
	// Campaign list, the Marketing start page or a segment (Email Campaign Studio).
	// EM-40: status, where used and send time of the emails on screen. They describe the campaigns and
	// workflows that use an email, so they are fetched once per page and added to each row.
	const STATUS_COLOURS = {Draft: "gray", Scheduled: "blue", "Preparing Audience": "blue", Sending: "orange", Paused: "orange",
		Completed: "green", Failed: "red", Cancelled: "gray", "In workflow": "purple"};
	// The two columns that carry no information on this list (Builder Mode is always "Visual", Response
	// is empty) show the status and where the email is used. Rows and their layout are left untouched.
	const STATUS_COLUMN = "custom_builder_mode", USED_COLUMN = "response";
	function relabel_columns(listview) {
		[[STATUS_COLUMN, __("Status")], [USED_COLUMN, __("Used in")]].forEach(([fieldname, label]) => {
			const $label = listview.$result.find(`.list-row-head .list-row-col[data-fieldname="${fieldname}"]`).find("span, .ellipsis").first();
			if ($label.length) $label.text(label);
		});
	}
	function show_usage(listview) {
		relabel_columns(listview);
		const rows = listview.$result.find(".list-row-container").toArray()
			.map((el) => ({el: $(el), name: $(el).find(".list-row-checkbox").attr("data-name")})).filter((row) => row.name);
		if (!rows.length) return;
		frappe.call({
			method: "finbyzreach.email_template_builder.languages.email_usage", type: "POST", args: {template_names: JSON.stringify(rows.map((row) => row.name))},
		}).then(({message}) => {
			rows.forEach(({el, name}) => {
				const usage = (message || {})[name];
				if (!usage) return;
				const status = usage.status
					? `<span class="indicator-pill ${STATUS_COLOURS[usage.status] || "gray"}">${frappe.utils.escape_html(__(usage.status))}</span>`
					: `<span class="text-muted">${__("Not used yet")}</span>`;
				const titles = usage.used_in.map((u) => u.title);
				const time = usage.send_time ? frappe.datetime.str_to_user(usage.send_time.slice(0, 16)) : "";
				const used = titles.join(", ") + (time ? (titles.length ? " · " : "") + time : "");
				el.find(`.list-row-col[data-fieldname="${STATUS_COLUMN}"]`).html(status);
				el.find(`.list-row-col[data-fieldname="${USED_COLUMN}"]`)
					.html(`<span class="text-muted">${frappe.utils.escape_html(used)}</span>`).attr("title", used);
			});
		});
	}
	frappe.listview_settings["Email Template"].refresh = show_usage;

	function selected_emails(listview) {
		const names = listview.get_checked_items().map((row) => row.name);
		if (!names.length) frappe.msgprint(__("Select at least one email first."));
		return names;
	}

	frappe.listview_settings["Email Template"].primary_action = function () {
		if (can_design_email()) show_new_visual_template_dialog();
		else frappe.new_doc("Email Template");
	};

	function set_create_button(listview) {
		if (!listview.can_create || frappe.boot.read_only) return;
		// A site translation renames "Email Template" to "Emails", which made Frappe's label read "Add Emails".
		listview.page.set_primary_action(
			{label: __("New Email"), short_label: __("New")},
			() => frappe.listview_settings["Email Template"].primary_action(),
			"plus"
		);
	}

	frappe.listview_settings["Email Template"].onload = function (listview) {
		if (existing_onload) existing_onload(listview);
		if (!listview._create_button_relabelled && typeof listview.set_primary_action === "function") {
			listview._create_button_relabelled = true;
			const original = listview.set_primary_action.bind(listview);
			listview.set_primary_action = function () { original(); set_create_button(listview); };
			set_create_button(listview);
		}
		frappe.reach_folder_sidebar.setup(listview);
		frappe.require([
			"/assets/finbyzreach/css/email_workspace.css",
			"/assets/finbyzreach/js/email_workspace.js",
		], () => frappe.email_workspace?.mount(listview.page, "emails"));
		// EM-40: sending status (draft, scheduled, sending, sent) as a filter and a badge.
		if (!listview._sending_status_filter) {
			listview._sending_status_filter = true;
			const apply = status => {
				listview.filter_area.remove("name");
				if (!status) return listview.refresh();
				frappe.call({method: "finbyzreach.email_status.emails_by_sending_status", args: {status}}).then(({message}) => {
					listview.filter_area.add([["Email Template", "name", "in", message.length ? message : ["__none__"]]]);
				});
			};
			// Toolbar buttons, not a header field: Frappe would filter a header field on a real column.
			const group = __("Sending status");
			listview.page.add_inner_button(__("All e-mails"), () => apply(""), group);
			for (const status of ["Draft", "Scheduled", "Sending", "Paused", "Completed", "Cancelled", "Failed"]) {
				listview.page.add_inner_button(__(status), () => apply(status), group);
			}
		}
		if (!listview._email_row_actions_added && typeof listview.page.add_action_item === "function") {
			listview._email_row_actions_added = true;
			// EM-41: duplicate (one or several) and move to a folder, from the row selection.
			listview.page.add_action_item(__("Duplicate"), async () => {
				const names = selected_emails(listview);
				for (const name of names) {
					await frappe.call({method: "finbyzreach.email_template_builder.languages.duplicate_email", type: "POST", args: {template_name: name}, freeze: true});
				}
				if (names.length) { frappe.show_alert({message: __("{0} email(s) duplicated", [names.length]), indicator: "green"}); listview.refresh(); }
			});
			listview.page.add_action_item(__("Move to folder…"), () => {
				const names = selected_emails(listview);
				if (!names.length) return;
				frappe.prompt([{fieldname: "folder", fieldtype: "Link", options: "Email Folder", label: __("Folder"), description: __("Leave empty for “No folder”.")}], async (values) => {
					const {message} = await frappe.call({method: "finbyzreach.email_template_builder.languages.move_emails_to_folder", type: "POST",
						args: {template_names: JSON.stringify(names), folder: values.folder || ""}, freeze: true});
					frappe.show_alert({message: __("{0} email(s) moved", [message.moved]), indicator: "green"});
					listview.refresh();
				}, __("Move to folder"), __("Move"));
			});
		}
		if (!can_design_email() || listview._visual_builder_actions_added) return;

		listview.page.add_button(__("Build with AI ✨"), () => show_ai_create_dialog("Email Template"));
		listview.page.add_button(__("Choose Template"), () => frappe.email_template_library.choose_master());
		listview.page.add_inner_button(__("Choose from Library"), () => frappe.email_template_library.choose_master(), __("Builder"));
		listview.page.add_inner_button(__("Manage Master Templates"), () => frappe.set_route("List", "Email Template Master"), __("Builder"));
		listview.page.add_inner_button(__("Build with AI ✨"), () => show_ai_create_dialog("Email Template"), __("Builder"));
		listview.page.add_inner_button(__("New Visual Email"), show_new_visual_template_dialog, __("Builder"));
		listview.page.add_action_item(__("Open Visual Builder"), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Select an Email Template first."));
				return;
			}
			open_builder(selected[0].name);
		});
		listview.page.add_action_item(__("Create Master from Email"), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Select an Email Template first."));
				return;
			}
			frappe.email_template_library.create_master_from_email(selected[0].name);
		});
        listview.page.add_action_item(__("Add language version…"), () => {
            const selected = listview.get_checked_items();
            if (selected.length !== 1) return frappe.msgprint(__("Select one email first."));
            frappe.prompt([
                {fieldname:"language", fieldtype:"Select", options:"de\nfr\nit\nen", label:__("New language"), reqd:1},
                {fieldname:"new_name", fieldtype:"Data", label:__("Email name"), reqd:1},
                {fieldname:"master_name", fieldtype:"Link", options:"Email Template Master", label:__("Start from master (optional)"), description:__("Leave empty to copy the existing version's content.")}
            ], async values => {
                const {message} = await frappe.call({method:"finbyzreach.email_template_builder.languages.add_language_version", type:"POST", args:{template_name:selected[0].name, ...values}});
                open_builder(message.name);
            }, __("Add language version"));
        });
		listview._visual_builder_actions_added = true;
	};
})();

(() => {
    const doctype = "Email Template";
    if (frappe.builder_list_navigation) {
        frappe.builder_list_navigation.setup(doctype);
    } else {
        // An already-open Desk session may not have the new boot asset yet.
        const onload = frappe.listview_settings[doctype].onload;
        frappe.listview_settings[doctype].onload = function (listview) {
            frappe.require("/assets/finbyzreach/js/builder_list_navigation.js", () => {
                frappe.builder_list_navigation.setup(doctype);
                frappe.builder_list_navigation.mount(listview);
            });
            return onload?.call(this, listview);
        };
    }
})();
