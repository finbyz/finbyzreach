"""EM-40: filter the e-mail list by sending status, using the words of its Status column."""
import frappe
from frappe import _

# The campaign status the e-mail was last used with, in the words the list shows.
STATUS_OF_CAMPAIGN = {
	"Draft": "Draft",
	"Preparing Audience": "Sending",
	"Sending": "Sending",
	"Scheduled": "Scheduled",
	"Paused": "Paused",
	"Completed": "Completed",
	"Cancelled": "Cancelled",
	"Failed": "Failed",
}
STATUSES = ("Draft", "Scheduled", "Sending", "Paused", "Completed", "Cancelled", "Failed")


def sending_statuses():
	"""{email template name: status}. An e-mail never used in a campaign is a Draft."""
	rows = frappe.get_all(
		"Campaign",
		filters={"custom_email_template": ["is", "set"]},
		fields=["custom_email_template", "custom_broadcast_status"],
		order_by="creation desc",
		limit_page_length=0,
	)
	latest = {}
	for row in rows:
		latest.setdefault(row.custom_email_template, STATUS_OF_CAMPAIGN.get(row.custom_broadcast_status or "Draft", "Draft"))
	return latest


@frappe.whitelist()
def emails_by_sending_status(status):
	"""Names of the e-mails with this sending status, for the list filter."""
	frappe.has_permission("Email Template", "read", throw=True)
	if status not in STATUSES:
		frappe.throw(_("Unknown sending status"))
	used = sending_statuses()
	if status == "Draft":
		everything = frappe.get_all("Email Template", pluck="name", limit_page_length=0)
		return [name for name in everything if used.get(name, "Draft") == "Draft"]
	return [name for name, value in used.items() if value == status]
