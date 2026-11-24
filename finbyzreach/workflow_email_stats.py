"""EM-27: e-mails sent by workflows, counted separately from campaigns."""
import json

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime, validate_email_address

TRACKED = {"Opened": "opened", "Clicked": "clicked", "Bounced": "bounced", "Soft-Bounced": "bounced", "Unsubscribed": "unsubscribed"}


def aggregate(sent_rows, tracking_rows):
	"""sent_rows: dicts with workflow, workflow_title, email_template, communication.
	tracking_rows: dicts with communication, event_type. One count per e-mail, however often it was opened."""
	groups = {}
	by_communication = {}
	for row in sent_rows:
		key = (row["workflow"], row.get("email_template") or "")
		group = groups.setdefault(key, {
			"workflow": row["workflow"], "workflow_title": row.get("workflow_title") or row["workflow"],
			"email_template": row.get("email_template") or "", "sent": 0, "opened": 0, "clicked": 0, "bounced": 0, "unsubscribed": 0,
		})
		group["sent"] += 1
		by_communication[row["communication"]] = key
	seen = set()
	for event in tracking_rows:
		kind = TRACKED.get(event["event_type"])
		key = by_communication.get(event["communication"])
		if not kind or key is None or (event["communication"], kind) in seen:
			continue
		seen.add((event["communication"], kind))
		groups[key][kind] += 1
	return sorted(groups.values(), key=lambda g: (-g["sent"], g["workflow_title"]))


# Communication statuses that are only reached after SMTP handoff.
HANDED_OFF_COMMUNICATION_STATUSES = ("Sent", "Opened", "Read", "Clicked", "Bounced", "Soft-Bounced", "Marked As Spam")


def _handoff_key(row):
	return (row["email_queue"], row["communication"], validate_email_address(str(row["recipient"])).strip().lower())


def _sent_workflow_rows(ledger_rows):
	"""A completed effect proves queue creation, not SMTP handoff to its recipient."""
	candidates = []
	for row in ledger_rows:
		try:
			result = json.loads(row.result_json or "{}")
		except (TypeError, ValueError):
			continue
		if not isinstance(result, dict) or result.get("suppressed"):
			continue
		if not all(isinstance(result.get(field), str) and result[field].strip()
			for field in ("communication", "email_queue", "recipient")):
			continue
		candidates.append({"workflow": row.workflow, "workflow_title": row.title,
			"email_template": result.get("email_template") or "", "communication": result["communication"],
			"email_queue": result["email_queue"], "recipient": result["recipient"]})
	if not candidates:
		return []
	queue = frappe.qb.DocType("Email Queue")
	recipient = frappe.qb.DocType("Email Queue Recipient")
	# A partially sent/error queue can still have delivered this recipient. Later
	# bounces and unsubscribes do not erase its successful SMTP handoff either.
	handoffs = (frappe.qb.from_(queue).join(recipient).on(recipient.parent == queue.name)
		.select(queue.name, queue.communication, recipient.recipient)
		.where(queue.name.isin(list({row["email_queue"] for row in candidates})))
		.where((recipient.parenttype == "Email Queue") & (recipient.parentfield == "recipients")
			& (recipient.status == "Sent"))).run(as_dict=True)
	sent = {(row.name, row.communication, validate_email_address(str(row.recipient)).strip().lower()) for row in handoffs}
	# Log Settings purges old Email Queue rows. Their Communication keeps the
	# delivery status Frappe copied from the queue, so use that for purged queues.
	queue_names = list({row["email_queue"] for row in candidates})
	existing = set(frappe.get_all("Email Queue", filters={"name": ["in", queue_names]}, pluck="name"))
	purged = [row for row in candidates if row["email_queue"] not in existing]
	delivered = set()
	if purged:
		delivered = set(frappe.get_all("Communication", pluck="name", filters={
			"name": ["in", list({row["communication"] for row in purged})],
			"delivery_status": ["in", HANDED_OFF_COMMUNICATION_STATUSES]}))
	return [row for row in candidates if _handoff_key(row) in sent
		or (row["email_queue"] not in existing and row["communication"] in delivered)]


@frappe.whitelist(methods=["GET"])
def workflow_email_usage(days=30):
	"""Per workflow and e-mail: sent, opened, clicked, bounced and unsubscribed in the last N days."""
	frappe.has_permission("Email Template", "read", throw=True)
	if not frappe.db.table_exists("Automation Effect Ledger"):
		return {"rows": [], "totals": {}}
	days = max(1, min(int(days or 30), 3650))
	since = add_days(now_datetime(), -days)
	ledger = frappe.qb.DocType("Automation Effect Ledger")
	run = frappe.qb.DocType("Automation Run")
	workflow = frappe.qb.DocType("Automation Workflow")
	query = (
		frappe.qb.from_(ledger).join(run).on(run.name == ledger.run).join(workflow).on(workflow.name == run.workflow)
		.select(ledger.name, ledger.result_json, run.workflow, workflow.title)
		.where((ledger.status == "COMPLETED") & ledger.result_json.isnotnull() & (ledger.completed_at >= since))
	)
	groups = {}
	after = None
	has_tracking = frappe.db.table_exists("Email Tracking Event")
	while True:
		page = query.where(ledger.name > after) if after else query
		found = page.orderby(ledger.name).limit(500).run(as_dict=True)
		if not found:
			break
		sent_rows = _sent_workflow_rows(found)
		names = list({row["communication"] for row in sent_rows})
		tracking = frappe.get_all("Email Tracking Event", filters={"communication": ["in", names]},
			fields=["communication", "event_type"], group_by="communication, event_type", limit_page_length=0) if names and has_tracking else []
		for row in aggregate(sent_rows, tracking):
			key = (row["workflow"], row["email_template"])
			if key not in groups:
				groups[key] = row
			else:
				for field in ("sent", "opened", "clicked", "bounced", "unsubscribed"):
					groups[key][field] += row[field]
		after = found[-1].name
		if len(found) < 500:
			break
	rows = sorted(groups.values(), key=lambda row: (-row["sent"], row["workflow_title"]))
	totals = {key: sum(row[key] for row in rows) for key in ("sent", "opened", "clicked", "bounced", "unsubscribed")}
	return {"rows": rows, "totals": totals, "days": days}
