// Copyright (c) 2025, sandeep and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lead Followup Setting", {
    provider: function(frm) {
        frm.set_value('llm', '');

        frm.set_query('llm', function() {
            return {
                filters: {
                    provider: frm.doc.provider
                }
            };
        });
    },
    research_provider: function(frm) {
        frm.set_value('research_llm', '');

        frm.set_query('research_llm', function() {
            return {
                filters: {
                    provider: frm.doc.research_llm
                }
            };
        });
    },

    onload: function(frm) {
        frm.set_query('llm', function() {
            if (frm.doc.provider) {
                return {
                    filters: {
                        provider: frm.doc.provider
                    }
                };
            }
        });
        frm.set_query('research_llm', function() {
            if (frm.doc.research_provider) {
                return {
                    filters: {
                        provider: frm.doc.research_provider
                    }
                };
            }
        });
    },

    refresh: function(frm) {
        if (cint(frm.doc.enable_inactive_customer_followup)) {
            frm.add_custom_button(__("Preview Inactive Customers"), function() {
                preview_inactive_customers(frm);
            });
        }
    }
});

function preview_inactive_customers(frm) {
    frappe.call({
        method: "finbyzreach.tasks.every_4PM.inactive_customer_followup.preview_inactive_customers",
        freeze: true,
        freeze_message: __("Loading inactive customers..."),
        callback: function(r) {
            const rows = Array.isArray(r.message) ? r.message : [];
            const dialog = new frappe.ui.Dialog({
                title: __("Preview Inactive Customers"),
                size: "large",
                fields: [
                    {
                        fieldname: "preview_html",
                        fieldtype: "HTML"
                    }
                ],
                primary_action_label: __("Close"),
                primary_action: function() {
                    dialog.hide();
                }
            });

            const noteHtml = `<p class="text-muted mb-2">${__("Save settings before previewing.")}</p>`;
            const dirtyHtml = frm.is_dirty()
                ? `<div class="alert alert-warning py-2 px-3 mb-2">${__("You have unsaved changes. Save settings first to preview the updated criteria.")}</div>`
                : "";
            const countHtml = `<p class="mb-3"><strong>${__("Matching customers: {0}", [rows.length])}</strong></p>`;

            let tableHtml = `<p class="text-muted">${__("No inactive customers matched the saved settings.")}</p>`;
            if (rows.length) {
                const bodyRows = rows.map(function(row) {
                    const customerLink = frappe.utils.get_form_link("Customer", row.customer, true);
                    const customerName = frappe.utils.escape_html(row.customer_name || "");
                    const email = frappe.utils.escape_html(row.email || "");
                    const lastOrderDate = row.last_order_date
                        ? frappe.utils.escape_html(frappe.datetime.str_to_user(row.last_order_date))
                        : "";
                    const daysSince = cint(row.days_since_last_order);
                    return `<tr>
                        <td>${customerLink}</td>
                        <td>${customerName}</td>
                        <td>${email}</td>
                        <td>${lastOrderDate}</td>
                        <td class="text-right">${daysSince}</td>
                    </tr>`;
                }).join("");

                tableHtml = `
                    <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                        <table class="table table-bordered table-sm mb-0">
                            <thead>
                                <tr>
                                    <th>${__("Customer")}</th>
                                    <th>${__("Customer Name")}</th>
                                    <th>${__("Email")}</th>
                                    <th>${__("Last Order Date")}</th>
                                    <th class="text-right">${__("Days Since Last Order")}</th>
                                </tr>
                            </thead>
                            <tbody>${bodyRows}</tbody>
                        </table>
                    </div>
                `;
            }

            dialog.fields_dict.preview_html.$wrapper.html(noteHtml + dirtyHtml + countHtml + tableHtml);
            dialog.show();
        }
    });
}
