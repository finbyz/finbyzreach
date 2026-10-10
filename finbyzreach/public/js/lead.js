frappe.ui.form.on("Lead", {
    refresh(frm) {
        if (frm.fields_dict.custom_subscriptions) frm.set_df_property("custom_subscriptions", "hidden", 1);
        if (frm.fields_dict.custom_unsubscribe_topics) frm.set_df_property("custom_unsubscribe_topics", "hidden", 1);
        window.finbyzreachPreferences?.render(frm);
        frm.add_custom_button("Research", function () {
            frappe.call({
                method: "finbyzreach.api.lead.research_lead",
                freeze: true,
                freeze_message: __("Gethering Information..."),
                args: {
                    name: cur_frm.doc.name
                },
                callback: function (r) {
                    if (r.message) {
                        frm.refresh_fields()
                        frappe.msgprint("Research completed");
                        frm.reload_doc()
                    }
                }
            });
        })
    },
});
