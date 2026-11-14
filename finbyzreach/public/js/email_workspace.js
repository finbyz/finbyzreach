// Navigation between existing Desk routes; no replacement pages or data writes.
frappe.provide("frappe.email_workspace");

frappe.email_workspace.mount = function (page, active) {
    const $layout = page.main.closest(".layout-main");
    if (!$layout.length || $layout.prev(".email-workspace-tabs").length) return;
    const tabs = [
        {key: "emails", label: __("Emails"), route: ["List", "Email Template"], url: "/app/email-template", allowed: frappe.model.can_read("Email Template")},
        {key: "statistics", label: __("Statistics"), route: ["email-campaign-report"], url: "/app/email-campaign-report", allowed: frappe.model.can_read("Campaign") && frappe.model.can_read("Email Campaign")},
        {key: "templates", label: __("Templates"), route: ["List", "Email Template Master"], url: "/app/email-template-master", allowed: frappe.model.can_read("Email Template Master")},
    ].filter(tab => tab.allowed || tab.key === active);
    const escape = frappe.utils.escape_html;
    const $tabs = $(`<nav class="email-workspace-tabs" aria-label="${escape(__("Email navigation"))}">${tabs.map(tab =>
        `<a class="email-workspace-tab${tab.key === active ? " active" : ""}" href="${tab.url}" data-email-tab="${tab.key}" ${tab.key === active ? 'aria-current="page"' : ""}>${escape(tab.label)}</a>`).join("")}</nav>`).insertBefore($layout);
    $tabs.on("click", "[data-email-tab]", event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        const tab = tabs.find(item => item.key === $(event.currentTarget).attr("data-email-tab"));
        if (tab && tab.key !== active) frappe.set_route(...tab.route);
    });
};
