frappe.ui.form.on("Email Template Master", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Open Visual Builder"), () => {
			frappe.email_template_library.open_builder(frm.doc.name, "Email Template Master");
		}, __("Builder"));

		frm.add_custom_button(__("Create Email from Master"), () => {
			frappe.email_template_library?.create_from_master(frm.doc.name, frm.doc.subject);
		}, __("Builder"));

		frm.add_custom_button(__("New Folder"), () => {
			frappe.email_template_library.new_folder();
		}, __("Library"));
	},
});
