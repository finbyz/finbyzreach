"""Approval of drafted outreach emails."""

import frappe
from frappe import _


@frappe.whitelist(methods=["POST"])
def approve_emails(outbound_name: str, rows=None):
	"""Release selected held emails, preserving later branch conditions."""
	frappe.only_for("System Manager")
	if not isinstance(outbound_name, str) or not outbound_name.strip():
		frappe.throw(_("Outbound Email is required."), frappe.ValidationError)
	rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	if rows is not None and (
		not isinstance(rows, list) or any(not isinstance(name, str) for name in rows)
	):
		frappe.throw(_("Rows must be a list of email row names."), frappe.ValidationError)

	outbound = frappe.get_doc("Outbound Email", outbound_name)
	outbound.check_permission("write")
	released = 0
	for row in outbound.communication_email:
		if row.status != "Awaiting Approval":
			continue
		if rows is not None and row.name not in rows:
			continue
		frappe.db.set_value(
			"Communication Email", row.name,
			"status", "Queued" if row.idx == 1 else "Pending",
			update_modified=False,
		)
		released += 1

	return {
		"ok": True,
		"released": released,
		"message": _("{0} email(s) approved for sending.").format(released),
	}
