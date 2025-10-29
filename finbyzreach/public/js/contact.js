frappe.ui.form.on("Contact", {
   onload(frm){
        frm.add_custom_button("Research", function() {
            frappe.call({
                method: "finbyzreach.api.contact.research_contact",
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