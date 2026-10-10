frappe.query_reports["Communication Subscriptions"] = {
    filters: [
        {fieldname: "category", label: __("Category"), fieldtype: "Select", options: "\nMailing Type\nTopic"},
        {fieldname: "subscription_topic", label: __("Subscription Type or Topic"), fieldtype: "Link", options: "Subscription Topic"},
        {fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nSubscribed\nPending\nUnsubscribed"},
        {fieldname: "email", label: __("Email"), fieldtype: "Data"}
    ]
};
