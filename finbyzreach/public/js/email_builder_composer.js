(function () {
	if (window.finbyzreach_email_builder_composer_loaded) return;
	window.finbyzreach_email_builder_composer_loaded = true;

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

	function extend_composer() {
		const Composer = frappe?.views?.CommunicationComposer;
		if (!Composer) {
			window.setTimeout(extend_composer, 250);
			return;
		}

		const proto = Composer.prototype;
		if (proto.__finbyzreach_email_builder_composer_applied) return;
		proto.__finbyzreach_email_builder_composer_applied = true;

		const original_hide_use_html_field = proto.hide_use_html_field;
		const original_on_use_html_toggle = proto.on_use_html_toggle;

		proto.hide_use_html_field = function () {
			this.finbyzreach_selected_template_is_visual = false;
			set_check_disabled(this.dialog?.fields_dict?.use_html, false);
			set_description(this.dialog?.fields_dict?.use_html, __("Use Raw HTML email editor."));
			return original_hide_use_html_field.call(this);
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
					this.dialog.set_value("add_css", 1);
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
			if (this.finbyzreach_selected_template_is_visual && event?.target && !event.target.checked) {
				this.dialog.set_value("use_html", 1);
				show_alert(__("Visual Builder templates must be sent as raw HTML."), "orange");
				return;
			}

			return original_on_use_html_toggle.call(this, event);
		};
	}

	$(document).on("app_ready", extend_composer);
	extend_composer();
})();
