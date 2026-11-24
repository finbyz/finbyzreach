"""Drop the Communication index an earlier version of the soft-bounce fix added.

Soft-bounce lookups read Email Soft Bounce Recipient now, so the index only
slowed every Communication write.
"""
import frappe

INDEX = "reach_delivery_failure_lookup"


def execute():
	if frappe.db.sql("SHOW INDEX FROM `tabCommunication` WHERE Key_name = %s", INDEX):
		frappe.db.sql_ddl(f"ALTER TABLE `tabCommunication` DROP INDEX `{INDEX}`")
