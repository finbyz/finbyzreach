frappe.ui.form.on("Lead", {
   onload(frm){
        frm.add_custom_button("Research", function() {
            frappe.call({
                method: "finbyzreach.api.lead.research_lead",
                freeze: true,
			    freeze_message: __("Gethering Information..."),
                args: {
                    name: cur_frm.doc.name
                },
                callback: function(r) {
                    if (r.message) {
                        frm.refresh_fields()
                        frappe.msgprint("Research completed");
                    }
                }
            });
        })
   }, 
});