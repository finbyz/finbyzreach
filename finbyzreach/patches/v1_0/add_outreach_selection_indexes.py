"""Index contact lookups for outreach."""

import frappe

INDEXES = [("Outbound Email", ["contact"])]


def execute():
	for doctype, fields in INDEXES:
		if not frappe.db.table_exists(doctype):
			continue
		try:
			frappe.db.add_index(doctype, fields)
		except Exception:
			# An index that already exists, or a column a site has not got yet,
			# must not stop the rest being created.
			frappe.log_error(
				title=f"Could not index {doctype}.{','.join(fields)}",
				message=frappe.get_traceback(),
			)
