"""Backfill recent exact mailbox matches before evaluating the bounce threshold."""
import frappe
from frappe.utils import add_days, now_datetime

from finbyzreach.consent import (
	SOFT_BOUNCE_DAYS, capture_delivery_failure, sync_soft_bounce_recipients,
)


def recent_bounces(since):
	after = ""
	while True:
		rows = frappe.get_all("Communication", filters={
			"name": [">", after], "sent_or_received": "Sent", "delivery_status": "Soft-Bounced",
			"creation": [">=", since],
		}, fields=["name", "creation", "recipients", "sent_or_received", "delivery_status"],
			order_by="name asc", limit_page_length=500)
		if not rows:
			return
		yield from rows
		after = rows[-1].name


def execute():
	frappe.reload_doc("finbyzreach", "doctype", "email_soft_bounce_recipient")
	since = add_days(now_datetime(), -SOFT_BOUNCE_DAYS)
	# Populate the whole window first, including addresses on later pages.
	for row in recent_bounces(since):
		sync_soft_bounce_recipients(row)
	for row in recent_bounces(since):
		capture_delivery_failure(row)
