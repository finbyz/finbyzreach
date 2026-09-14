frappe.ui.form.on("Email Template Master", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Open Visual Builder"), () => {
			window.location.href = `/builder?template=${encodeURIComponent(frm.doc.name)}&template_doctype=${encodeURIComponent("Email Template Master")}`;
		}, __("Builder"));

		frm.add_custom_button(__("Create Email from Master"), () => {
			frappe.email_template_library?.create_from_master(frm.doc.name, frm.doc.subject);
		}, __("Builder"));
	},
});
