frappe.ui.form.on("Contact", {
    onload(frm) {
        frm.add_custom_button("Research", function () {
            frappe.call({
                method: "finbyzreach.api.contact.research_contact",
                freeze: true,
                freeze_message: __("Gethering Information..."),
                args: {
                    name: cur_frm.doc.name
                },
                callback: function (r) {
                    if (r.message) {
                        frm.refresh_fields()
                        frappe.msgprint("Research completed");
                    }
                }
            });
        })
        frm.add_custom_button("Create Emails", function () {
            const d = new frappe.ui.Dialog({
                title: "Select AI Email Campaign",
                fields: [
                    {
                        label: "Campaign",
                        fieldname: "campaign",
                        fieldtype: "Link",
                        options: "AI Email Campaign",
                        reqd: 1
                    }
                ],
                primary_action_label: "Create",
                primary_action(values) {
                    frappe.call({
                        method: "finbyzreach.api.contact.add_to_ai_email_campaign",
                        freeze: true,
                        freeze_message: __("Gathering Information..."),
                        args: {
                            name: cur_frm.doc.name,
                            campaign: values.campaign
                        },
                        callback: function (r) {
                            if (r.message) {
                                frm.refresh_fields();
                                frappe.msgprint("Research completed");
                            }
                        }
                    });
                    d.hide();
                }
            });
            d.show();
        });
    },
});