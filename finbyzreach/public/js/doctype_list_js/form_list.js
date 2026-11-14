frappe.listview_settings["Form"] = frappe.listview_settings["Form"] || {};

(() => {
    const settings = frappe.listview_settings["Form"];
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
        return `/app/forms-pro-designer/${encodeURIComponent(doc.name)}/${encodeURIComponent(sidebar)}`;
    };
})();
