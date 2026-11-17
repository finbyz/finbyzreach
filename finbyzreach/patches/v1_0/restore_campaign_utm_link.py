"""Restore ERPNext's Campaign mirror field on sites missing its install-time setup."""
import frappe
from erpnext.setup.install import create_marketing_campaign_custom_fields


def execute():
	# Reuse the ERPNext field definition rather than maintaining a custom replacement.
	create_marketing_campaign_custom_fields()
	# Existing metadata can survive a partially applied schema update.
	if not frappe.db.has_column("UTM Campaign", "crm_campaign"):
		frappe.db.updatedb("UTM Campaign")
	frappe.clear_cache(doctype="UTM Campaign")
