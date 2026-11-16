frappe.listview_settings["Email Template Master"] = frappe.listview_settings["Email Template Master"] || {};

(function () {
	frappe.listview_settings["Email Template Master"].get_form_link = function (doc) {
		if (frappe.user.has_role("Email Designer") || frappe.user.has_role("System Manager")) {
			return `/app/email-template-builder/${encodeURIComponent(doc.name)}/${encodeURIComponent("Email Template Master")}/${encodeURIComponent(frappe.app?.sidebar?.current_module || "")}`;
		}
		return `/app/email-template-master/${encodeURIComponent(doc.name)}`;
	};
	const settings = frappe.listview_settings["Email Template Master"];
	const existing_onload = settings.onload;

	settings.onload = function (listview) {
		if (existing_onload) existing_onload(listview);
		frappe.reach_folder_sidebar.setup(listview);
		frappe.require([
			"/assets/finbyzreach/css/email_workspace.css",
			"/assets/finbyzreach/js/email_workspace.js",
		], () => frappe.email_workspace?.mount(listview.page, "templates"));
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

(() => {
    const doctype = "Email Template Master";
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
