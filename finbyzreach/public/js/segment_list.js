// Runs after native list settings from DocType metadata have loaded.
for (const doctype of ["Lead","Contact","Customer","Opportunity","Sales Order"]) {
    frappe.reach_segment_membership.setup_list(doctype);
}
