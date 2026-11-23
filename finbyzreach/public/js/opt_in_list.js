// "Import opt-ins" in the Lead, Contact and Customer lists: opens the Import Opt-ins page with
// the list's current filters, or with the ticked records.
(function () {
	const KEYS = {Lead: "leads", Contact: "contacts", Customer: "customers"};
	const allowed = () => frappe.user.has_role("Marketing Manager") || frappe.user.has_role("System Manager");
	const open = (options) => {
		// Kept in memory, not in route_options: those end up in the URL, and a ticked list can be long.
		frappe.opt_in_import_options = options;
		frappe.set_route("import-opt-ins");
	};
	for (const doctype of Object.keys(KEYS)) {
		const previous = frappe.listview_settings[doctype] || {};
		if (previous._optInImportAction) continue;
		frappe.listview_settings[doctype] = {...previous, _optInImportAction: true, onload(list) {
			previous.onload?.(list);
			if (!allowed()) return;
			list.page.add_menu_item(__("Import opt-ins for this list"), () => {
				const filters = list.get_filters_for_args().map((row) => row.slice(0, 4));
				open({filter_doctype: doctype, filters});
			});
			list.page.add_action_item(__("Import opt-ins"), () => {
				const names = list.get_checked_items(true);
				if (!names.length) return frappe.msgprint(__("Select records first"));
				open({[KEYS[doctype]]: names});
			});
		}};
	}
})();
