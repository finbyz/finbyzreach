import frappe


def execute():
    frappe.db.add_index("Communication", ["delivery_status", "sent_or_received", "creation"],
        "reach_delivery_failure_lookup")
