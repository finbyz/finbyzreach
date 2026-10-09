frappe.ui.form.on("Subscription Center Settings", {
    refresh(frm) {
        frm.add_custom_button(__("Get Embed Code"), () => {
            const origin = window.location.origin;
            const dialog = new frappe.ui.Dialog({
                title: __("Embed Subscription Form"),
                fields: [
                    {fieldname: "language", fieldtype: "Select", label: __("Default Language"), options: "de\nen\nfr\nit", default: "en"},
                    {fieldname: "share_url", fieldtype: "Data", label: __("Standalone Form Link"), read_only: 1},
                    {fieldname: "embed_code", fieldtype: "Small Text", label: __("Embed Code"), read_only: 1, description: __("Add the website's HTTPS origin to Allowed Embed Origins above, then paste this code on that website. The standalone link works without an allowed origin.")},
                ],
                primary_action_label: __("Copy Embed Code"),
                primary_action() {
                    const code = dialog.get_value("embed_code");
                    if (!navigator.clipboard?.writeText) {
                        frappe.msgprint(__("Clipboard access is unavailable. Select and copy the embed code from the field above."));
                        return;
                    }
                    navigator.clipboard.writeText(code)
                        .then(() => frappe.show_alert({message: __("Embed code copied"), indicator: "green"}))
                        .catch(() => frappe.msgprint(__("Clipboard access was denied. Select and copy the embed code from the field above.")));
                },
            });
            const update = () => {
                const language = dialog.get_value("language") || "en";
                const shareUrl = origin + "/subscribe?lang=" + encodeURIComponent(language);
                const embedUrl = shareUrl + "&embed=1";
                const code = '<div data-finbyzreach-subscription-form data-src="' + embedUrl + '"><a href="' + shareUrl + '">Subscribe to email updates</a></div>\n'
                    + '<script defer src="' + origin + '/assets/finbyzreach/js/subscription_form_embed.js"></' + 'script>';
                dialog.set_value("share_url", shareUrl);
                dialog.set_value("embed_code", code);
            };
            dialog.fields_dict.language.$input.on("change", update);
            dialog.show();
            update();
        });
    },
});
