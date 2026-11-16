// Keep builder navigation optional without changing document data or permissions.
frappe.provide("frappe.builder_list_navigation");

(() => {
    const preference = "open_in_builder";
    const enabled = doctype => frappe.get_user_settings(doctype)[preference] !== false;

    frappe.builder_list_navigation.mount = function (listview) {
        if (listview._builder_navigation_button) return;
        const doctype = listview.doctype;
        const button = listview.page.add_inner_button(__("Open in builder"), async () => {
            button.prop("disabled", true);
            try {
                await frappe.model.user_settings.save(doctype, preference, !enabled(doctype));
                update();
                await listview.refresh();
            } catch (error) {
                frappe.msgprint(__("Could not update the builder preference. Please try again."));
            } finally {
                button.prop("disabled", false);
            }
        });
        function update() {
            const on = enabled(doctype);
            button.text(on ? __("Open in builder: On") : __("Open in builder: Off"));
            button.attr("aria-pressed", String(on));
            button.attr("title", __("Choose whether clicking a row opens the builder or the document form."));
        }
        update();
        listview._builder_navigation_button = button;
    };

    frappe.builder_list_navigation.setup = function (doctype) {
        const settings = frappe.listview_settings[doctype];
        if (settings._builder_navigation_toggle) return;
        settings._builder_navigation_toggle = true;
        const original_link = settings.get_form_link;
        const original_onload = settings.onload;

        settings.get_form_link = function (doc) {
            if (enabled(doctype)) return original_link.call(this, doc);
            // Same route as the installed Frappe ListView's default get_form_link.
            return `/desk/${encodeURIComponent(frappe.router.slug(frappe.router.doctype_layout || doctype))}/${encodeURIComponent(doc.name)}`;
        };
        settings.onload = function (listview) {
            original_onload?.call(this, listview);
            frappe.builder_list_navigation.mount(listview);
        };
    };
})();
