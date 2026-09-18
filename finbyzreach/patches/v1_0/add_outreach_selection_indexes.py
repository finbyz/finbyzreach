"""Index the columns the campaign selection pass filters and joins on.

Candidate building runs one duplicate check per party and joins participants
to projects, so every one of these is hit repeatedly. Unindexed they are full
table scans, which is invisible at a few hundred rows and fatal at a hundred
thousand.
"""

import frappe

INDEXES = [
	("Infomanager Project Participant", ["company"]),
	("Infomanager Project Participant", ["contact"]),
	("Infomanager Project Detail", ["detailtype_name"]),
	("Infomanager Project", ["planstage_name"]),
	("Infomanager Project", ["province_name"]),
	("Infomanager Project", ["projecttype_name"]),
	("Infomanager Company", ["email"]),
	("Infomanager Contact", ["email"]),
	("Campaign Candidate", ["email"]),
	("Campaign Candidate", ["ai_email_campaign"]),
	("Outbound Email", ["contact"]),
]


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
