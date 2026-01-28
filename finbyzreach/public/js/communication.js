frappe.ui.form.on('Communication', {
    refresh: function (frm) {
        // Only show button for existing, received communications that are linked to a document
        if (!frm.is_new() && frm.doc.sent_or_received === "Received" && frm.doc.reference_doctype && frm.doc.reference_name) {

            // Allow manual trigger even if it's already analyzed, for testing purposes
            frm.add_custom_button(__('Analyze with AI'), function () {
                frappe.call({
                    method: "finbyzreach.doc_events.communication.analyze_communication",
                    args: {
                        doc_name: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Analyzing Communication..."),
                    callback: function (r) {
                        // The method returns the category on success, or handles errors/messages itself
                        if (r.message) {
                            // Reload to see any changes in linked docs if possible, 
                            // though linked doc updates won't reflect in Communication view immediately without reload of page
                            // But getting the success message is good enough.
                            frm.reload_doc();
                        }
                    }
                });
            }, __("Actions"));
        }
    }
});
