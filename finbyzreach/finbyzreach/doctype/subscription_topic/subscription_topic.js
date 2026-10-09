frappe.ui.form.on("Subscription Topic", {
    refresh(frm) {
        frm.add_custom_button(__("Add Translation"), () => {
            const existing = new Set((frm.doc.translations || []).map(row => row.language));
            const available = ["de", "en", "fr", "it"].filter(language => !existing.has(language));
            if (!available.length) {
                frappe.msgprint(__("All four languages already have translations."));
                return;
            }
            const dialog = new frappe.ui.Dialog({
                title: __("Add Translation"),
                fields: [
                    {fieldname: "language", label: __("Language"), fieldtype: "Select", options: available.join("\n"), reqd: 1},
                    {fieldname: "label", label: __("Label"), fieldtype: "Data", reqd: 1},
                    {fieldname: "description", label: __("Description"), fieldtype: "Small Text"}
                ],
                primary_action_label: __("Add"),
                primary_action(values) {
                    frm.add_child("translations", values);
                    frm.refresh_field("translations");
                    dialog.hide();
                }
            });
            dialog.show();
        });
    }
});
