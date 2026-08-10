frappe.listview_settings["Campaign"] = {
	onload(listview) {
		listview.page.add_inner_button(
			__("Open Email Campaign Studio"),
			() => {
				frappe.route_options = {};
				const session = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
				window.history.pushState(null, null, "/desk/email-campaign-studio?new=" + session);
				frappe.router.route();
			}
		);
	},
};
