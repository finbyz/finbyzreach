frappe.listview_settings["Automation Workflow"] = frappe.listview_settings["Automation Workflow"] || {};

(() => {
    const settings = frappe.listview_settings["Automation Workflow"];
    const previous = settings.onload;
    settings.onload = function (listview) {
        previous?.(listview);
        frappe.require([
            "/assets/finbyzreach/css/folder_sidebar.css",
            "/assets/finbyzreach/js/folder_sidebar.js",
        ], () => frappe.reach_folder_sidebar?.setup(listview));
    };
    settings.get_form_link = doc => {
        const sidebar = frappe.app?.sidebar?.current_module || "";
        return `/app/automation-workflow-designer/${encodeURIComponent(doc.name)}/${encodeURIComponent(sidebar)}`;
    };
})();

(() => {
    const doctype = "Automation Workflow";
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
