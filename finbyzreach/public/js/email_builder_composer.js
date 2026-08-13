(function () {
	if (window.finbyzreach_email_builder_composer_loaded) return;
	window.finbyzreach_email_builder_composer_loaded = true;

	const separator_element = "<div>---</div>";
	const communication_method =
		"finbyzreach.email_template_builder.api.send_communication_email";

	function as_bool(value) {
		return value === 1 || value === true || value === "1";
	}

	function set_check_disabled(field, disabled) {
		if (!field) return;
		field.df.read_only = disabled ? 1 : 0;
		if (field.$input) field.$input.prop("disabled", !!disabled);
		if (field.refresh) field.refresh();
	}

	function set_description(field, description) {
		if (!field) return;
		field.df.description = description || "";
		if (field.set_description) {
			field.set_description(description || "");
		}
	}

	function show_alert(message, indicator) {
		if (frappe.show_alert) {
			frappe.show_alert({ message, indicator: indicator || "blue" });
		}
	}

	function get_template_meta(email_template) {
		return frappe.db
			.get_value("Email Template", email_template, ["use_html", "custom_builder_mode"])
			.then((response) => response.message || {});
	}

	function save_item(key, value) {
		localforage.setItem(key, value).catch((error) => {
			if (error) {
				console.warn("[Email Builder] Unable to save communication draft", error);
			}
		});
	}

	function add_v15_fields(proto) {
		const original_get_fields = proto.get_fields;

		proto.get_fields = function () {
			const me = this;
			const fields = original_get_fields.call(this);
			const template_field = fields.find((field) => field.fieldname === "email_template");
			const content_field = fields.find((field) => field.fieldname === "content");

			if (template_field) {
				template_field.onchange = async function () {
					const email_template = this.value;
					if (!email_template) {
						return me.hide_use_html_field();
					}
					await me.check_email_template_html(email_template);
				};
			}

			if (content_field) {
				content_field.depends_on = "eval:!doc.use_html";
				const content_index = fields.indexOf(content_field);
				fields.splice(content_index + 1, 0, {
					label: __("HTML Message"),
					fieldtype: "Code",
					fieldname: "html_content",
					onchange: frappe.utils.debounce(this.save_as_draft.bind(this), 300),
					depends_on: "eval:doc.use_html",
					options: "HTML",
				});
			}

			const template_actions = fields.find(
				(field) => field.fieldname === "clear_and_add_template"
			);
			if (template_actions) {
				fields.splice(fields.indexOf(template_actions) + 1, 0, {
					label: __("Use HTML"),
					fieldtype: "Check",
					fieldname: "use_html",
					default: 0,
					hidden: 1,
					description: __("Use Raw HTML email editor."),
					onchange(event) {
						me.on_use_html_toggle(event);
					},
				});
			}

			const attachments = fields.find((field) => field.fieldname === "select_attachments");
			if (attachments) {
				fields.splice(fields.indexOf(attachments), 0, {
					label: __("Add CSS"),
					fieldtype: "Check",
					fieldname: "add_css",
					default: 1,
					depends_on: "eval:doc.use_html",
				});
			}

			return fields;
		};
	}

	function add_v15_content_methods(proto) {
		proto.get_content_field = function () {
			return this.dialog.fields_dict.use_html?.get_value()
				? this.dialog.fields_dict.html_content
				: this.dialog.fields_dict.content;
		};

		proto.get_email_content = function () {
			return this.get_content_field().get_value() || "";
		};

		proto.set_email_content = function (value) {
			return this.get_content_field().set_value(value);
		};

		proto.save_as_draft = function () {
			if (!this.dialog || !this.frm) return;
			let message = this.get_email_content();
			message = message.split(separator_element)[0];
			const key = this.frm.doctype + this.frm.docname;
			save_item(key, message);
			save_item(key + "_use_html", this.dialog.get_value("use_html"));
		};

		proto.set_values_from_last_edited_communication = async function () {
			if (this.message) return;

			const last_edited = this.get_last_edited_communication();
			if (!last_edited.content && !last_edited.html_content) return;

			if (last_edited.email_template) {
				const template_field = this.dialog.fields_dict.email_template;
				await template_field.set_model_value(last_edited.email_template);
				await this.check_email_template_html(last_edited.email_template);
				delete last_edited.email_template;
			}

			await this.dialog.set_values(last_edited);
			this.content_set = true;
		};

		proto.set_content = async function (sender_email) {
			if (this.content_set) return;

			let message = this.message || "";
			if (!message && this.frm) {
				const { doctype, docname } = this.frm;
				message = (await localforage.getItem(doctype + docname)) || "";
				const use_html = (await localforage.getItem(doctype + docname + "_use_html")) || 0;
				await this.dialog.set_value("use_html", use_html);
			}

			if (message) this.content_set = true;

			const signature = await this.get_signature(sender_email || "");
			if (!this.content_set || !strip_html(message).includes(strip_html(signature))) {
				message += signature;
			}

			if (this.is_a_reply && !this.reply_set) {
				message += this.get_earlier_reply();
			}

			await this.set_email_content(message);
		};
	}

	function add_v15_template_actions(proto) {
		proto.setup_email_template = function () {
			const me = this;
			const fields = this.dialog.fields_dict;
			const clear_and_add_template = $(fields.clear_and_add_template.wrapper);

			async function add_template() {
				const email_template = fields.email_template.get_value();
				if (!email_template) return;

				await me.check_email_template_html(email_template);
				frappe.call({
					method: "frappe.email.doctype.email_template.email_template.get_email_template",
					args: {
						template_name: email_template,
						doc: me.doc,
					},
					callback(response) {
						const reply = response.message;
						const content = me.get_email_content();
						me.set_email_content(reply.message + content);
						fields.subject.set_value(reply.subject);
					},
				});
			}

			frappe.utils.add_select_group_button(
				clear_and_add_template,
				[
					{
						label: __("Add Template"),
						description: __("Prepend the template to the email message"),
						action: () => add_template(),
					},
					{
						label: __("Clear & Add Template"),
						description: __("Clear the email message and add the template"),
						action: async () => {
							await me.set_email_content("");
							return add_template();
						},
					},
				],
				"btn-default"
			);
			$(fields.use_html.wrapper).addClass("mt-2 text-center").appendTo(clear_and_add_template);
		};
	}

	function add_v15_send_method(proto) {
		const original_send_email = proto.send_email;

		proto.send_email = function (
			btn,
			form_values,
			selected_attachments,
			print_html,
			print_format
		) {
			if (!as_bool(form_values.use_html)) {
				return original_send_email.call(
					this,
					btn,
					form_values,
					selected_attachments,
					print_html,
					print_format
				);
			}

			const me = this;
			this.dialog.hide();

			if (!form_values.recipients) {
				frappe.msgprint(__("Enter Email Recipient(s)"));
				return;
			}

			if (!form_values.attach_document_print) {
				print_html = null;
				print_format = null;
			}

			if (this.frm && !frappe.model.can_email(this.doc.doctype, this.frm)) {
				frappe.msgprint(__("You are not allowed to send emails related to this document"));
				return;
			}

			return frappe.call({
				method: communication_method,
				args: {
					recipients: form_values.recipients,
					cc: form_values.cc,
					bcc: form_values.bcc,
					subject: form_values.subject,
					content: me.get_email_content(),
					doctype: me.doc.doctype,
					name: me.doc.name,
					send_email: 1,
					print_html,
					send_me_a_copy: form_values.send_me_a_copy,
					print_format,
					sender: form_values.sender,
					sender_full_name: form_values.sender ? frappe.user.full_name() : undefined,
					email_template: form_values.email_template,
					attachments: selected_attachments,
					read_receipt: form_values.send_read_receipt,
					print_letterhead: me.is_print_letterhead_checked(),
					send_after: form_values.send_after || null,
					print_language: form_values.print_language,
					raw_html: 1,
					add_css: form_values.add_css,
				},
				btn,
				callback(response) {
					if (response.exc) {
						frappe.msgprint(__("There were errors while sending email. Please try again."));
						if (me.error) me.error(response);
						return;
					}

					frappe.utils.play_sound("email");
					if (response.message.emails_not_sent_to) {
						frappe.msgprint(
							__("Email not sent to {0} (unsubscribed / disabled)", [
								frappe.utils.escape_html(response.message.emails_not_sent_to),
							])
						);
					}

					me.clear_cache();
					if (me.frm) me.frm.reload_doc();
					if (me.success) me.success(response);
				},
			});
		};
	}

	function extend_composer() {
		const Composer = frappe?.views?.CommunicationComposer;
		if (!Composer) {
			window.setTimeout(extend_composer, 250);
			return;
		}

		const proto = Composer.prototype;
		if (proto.__finbyzreach_email_builder_composer_applied) return;
		proto.__finbyzreach_email_builder_composer_applied = true;

		const is_v15 = typeof proto.get_content_field !== "function";
		const original_hide_use_html_field = proto.hide_use_html_field;
		const original_on_use_html_toggle = proto.on_use_html_toggle;

		if (is_v15) {
			add_v15_fields(proto);
			add_v15_content_methods(proto);
			add_v15_template_actions(proto);
			add_v15_send_method(proto);
		}

		proto.hide_use_html_field = function () {
			this.finbyzreach_selected_template_is_visual = false;
			const use_html_field = this.dialog?.fields_dict?.use_html;
			set_check_disabled(use_html_field, false);
			set_description(use_html_field, __("Use Raw HTML email editor."));
			if (original_hide_use_html_field) {
				return original_hide_use_html_field.call(this);
			}
			if (use_html_field) {
				use_html_field.set_input(false);
				use_html_field.toggle(false);
			}
		};

		proto.check_email_template_html = async function (email_template) {
			if (!email_template) {
				return this.hide_use_html_field();
			}

			let template = {};
			try {
				template = await get_template_meta(email_template);
			} catch (error) {
				console.warn("[Email Builder] Unable to inspect Email Template mode", error);
				this.finbyzreach_selected_template_is_visual = false;
				return this.hide_use_html_field();
			}

			const use_html_field = this.dialog?.fields_dict?.use_html;
			const add_css_field = this.dialog?.fields_dict?.add_css;
			const is_html_template = as_bool(template.use_html);
			const is_visual_template = template.custom_builder_mode === "Visual";

			this.finbyzreach_selected_template_is_visual = is_visual_template;

			if (!use_html_field) return;

			if (!is_html_template) {
				this.hide_use_html_field();
				if (add_css_field) {
					add_css_field.toggle(true);
					await this.dialog.set_value("add_css", 1);
				}
				return;
			}

			use_html_field.toggle(true);
			await this.dialog.set_value("use_html", 1);
			use_html_field.set_input(true);

			if (is_visual_template) {
				set_check_disabled(use_html_field, true);
				set_description(
					use_html_field,
					__("Visual Builder templates are complete email HTML and must be sent as raw HTML.")
				);

				if (add_css_field) {
					await this.dialog.set_value("add_css", 0);
					add_css_field.toggle(false);
				}
			} else {
				set_check_disabled(use_html_field, false);
				set_description(use_html_field, __("Use Raw HTML email editor."));
				if (add_css_field) add_css_field.toggle(true);
			}
		};

		proto.on_use_html_toggle = function (event) {
			if (this.finbyzreach_restoring_use_html) return;
			if (this.finbyzreach_selected_template_is_visual && event?.target && !event.target.checked) {
				this.finbyzreach_restoring_use_html = true;
				Promise.resolve(this.dialog.set_value("use_html", 1)).finally(() => {
					this.finbyzreach_restoring_use_html = false;
				});
				show_alert(__("Visual Builder templates must be sent as raw HTML."), "orange");
				return;
			}

			if (original_on_use_html_toggle) {
				return original_on_use_html_toggle.call(this, event);
			}
			if (!event) return;

			this.save_as_draft();
			if (event.target.checked) {
				this.dialog.set_value("html_content", this.dialog.get_value("content"));
			} else {
				this.dialog.set_value("content", this.dialog.get_value("html_content"));
			}
		};
	}

	$(document).on("app_ready", extend_composer);
	extend_composer();
})();
