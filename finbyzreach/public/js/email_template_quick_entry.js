frappe.provide("frappe.ui.form");

(function () {
	function can_design_email() {
		return (
			frappe.user.has_role("Email Designer") ||
			frappe.user.has_role("System Manager")
		);
	}

	function open_builder(template_name) {
		window.location.href = `/builder?template=${encodeURIComponent(template_name)}`;
	}

	class EmailTemplateQuickEntryForm extends frappe.ui.form.QuickEntryForm {
		constructor(...args) {
			super(...args);
			this.skip_redirect_on_error = true;
		}

		is_quick_entry() {
			if (can_design_email()) {
				return true;
			}

			return super.is_quick_entry();
		}

		set_meta_and_mandatory_fields() {
			super.set_meta_and_mandatory_fields();

			if (!can_design_email()) {
				return;
			}

			this.docfields = [
				{
					fieldname: "template_name",
					fieldtype: "Data",
					label: __("Template name"),
					reqd: 1,
				},
				{
					fieldname: "subject",
					fieldtype: "Data",
					label: __("Subject"),
					reqd: 1,
				},
			];
		}

		render_dialog() {
			if (!can_design_email()) {
				return super.render_dialog();
			}

			this.title = __("New visual email template");
			this.hide_full_form_button = true;

			super.render_dialog();

			this.setup_subject_autofill();
		}

		register_primary_action() {
			if (!can_design_email()) {
				return super.register_primary_action();
			}

			this.set_primary_action(
				__("Create and open builder"),
				() => this.create_visual_template()
			);
		}

		setup_subject_autofill() {
			const template_name = this.fields_dict.template_name;
			const subject = this.fields_dict.subject;

			if (!template_name || !subject) {
				return;
			}

			let autofill_subject = !subject.get_value();

			subject.$input.on("input", () => {
				autofill_subject = !subject.get_value();
			});

			template_name.$input.on("input", () => {
				if (autofill_subject) {
					this.set_value(
						"subject",
						template_name.get_value() || ""
					);
				}
			});
		}

		async create_visual_template() {
			const values = this.get_values();

			if (!values) {
				return;
			}

			const response = await frappe.call({
				method:
					"finbyzreach.email_template_builder.api.create_visual_template",
				args: {
					template_name: values.template_name,
					subject: values.subject,
				},
				freeze: true,
				freeze_message: __("Creating visual template..."),
			});

			const message = response.message || {};

			if (!message.name) {
				return;
			}

			this.hide();
			open_builder(message.name);
		}
	}

	frappe.ui.form.EmailTemplateQuickEntryForm =
		EmailTemplateQuickEntryForm;
})();