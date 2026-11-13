frappe.listview_settings["Email Template Master"] = frappe.listview_settings["Email Template Master"] || {};

(function () {
	const settings = frappe.listview_settings["Email Template Master"];
	const existing_onload = settings.onload;

	settings.onload = function (listview) {
		if (existing_onload) existing_onload(listview);
		frappe.reach_folder_sidebar.setup(listview);
		if (listview._template_library_actions_added) return;

		listview.page.add_button(__("New Master"), () => {
			frappe.email_template_library.choose_master({ initial_action: "template" });
		});
		listview.page.add_action_item(__("Open Visual Builder"), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Select a master template first."));
				return;
			}
			frappe.email_template_library.open_builder(selected[0].name, "Email Template Master");
		});
		listview.page.add_action_item(__("Create Email from Master"), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Select a master template first."));
				return;
			}
			frappe.email_template_library.create_from_master(selected[0].name, selected[0].subject);
		});
		listview._template_library_actions_added = true;
	};
})();
