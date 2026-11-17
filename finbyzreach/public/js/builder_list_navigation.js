// Keep builder navigation optional without changing document data or permissions.
frappe.provide("frappe.builder_list_navigation");

(() => {
    const preference = "open_in_builder";
    // The choice applies at once in this browser; the server save follows. Rows are links built
    // when they render, so waiting for the save left old links behind and the first click after
    // switching still opened the previous target.
    const pending = {};
    const enabled = doctype => doctype in pending ? pending[doctype] : frappe.get_user_settings(doctype)[preference] !== false;
    const rerender = listview => {
        if (typeof listview.render === "function" && Array.isArray(listview.data)) listview.render();
    };

    function injectStyle() {
        if (typeof document === "undefined" || document.getElementById("builder-nav-toggle-style")) return;
        const style = document.createElement("style");
        style.id = "builder-nav-toggle-style";
        style.textContent = `
            .btn.builder-nav-toggle { display: inline-flex; align-items: center; gap: 8px; }
            .builder-nav-switch { position: relative; width: 26px; height: 15px; flex: none; border-radius: 999px;
                background: var(--gray-400, #c0c6cc); transition: background .15s; }
            .builder-nav-switch::after { content: ""; position: absolute; top: 2px; left: 2px; width: 11px; height: 11px;
                border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.2); transition: transform .15s; }
            .builder-nav-toggle.is-on .builder-nav-switch { background: var(--primary, #171717); }
            .builder-nav-toggle.is-on .builder-nav-switch::after { transform: translateX(11px); }
        `;
        document.head.appendChild(style);
    }

    frappe.builder_list_navigation.mount = function (listview) {
        if (listview._builder_navigation_button) return;
        const doctype = listview.doctype;
        const button = listview.page.add_inner_button(__("Open in builder"), async () => {
            const next = !enabled(doctype);
            pending[doctype] = next;
            update();
            rerender(listview);
            button.prop("disabled", true);
            try {
                await frappe.model.user_settings.save(doctype, preference, next);
                await listview.refresh();
            } catch (error) {
                pending[doctype] = !next;
                update();
                rerender(listview);
                frappe.msgprint(__("Could not update the builder preference. Please try again."));
            } finally {
                button.prop("disabled", false);
            }
        });
        injectStyle();
        button.addClass("builder-nav-toggle").attr("role", "switch");
        button.html(`<span>${__("Open in builder")}</span><span class="builder-nav-switch" aria-hidden="true"></span>`);
        function update() {
            const on = enabled(doctype);
            button.toggleClass("is-on", on);
            button.attr("aria-checked", String(on));
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
