"""EM-27: e-mails sent by workflows, counted separately from campaigns."""
import json

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

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
		sent_rows = []
		for row in found:
			try:
				result = json.loads(row.result_json or "{}")
			except ValueError:
				continue
			if isinstance(result, dict) and result.get("communication"):
				sent_rows.append({"workflow": row.workflow, "workflow_title": row.title,
					"email_template": result.get("email_template") or "", "communication": result["communication"]})
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
