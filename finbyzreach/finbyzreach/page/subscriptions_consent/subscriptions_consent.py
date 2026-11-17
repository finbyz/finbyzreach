import frappe


@frappe.whitelist(methods=["GET"])
def overview():
	frappe.has_permission("Subscription Topic", "read", throw=True)
	from finbyzreach.consent import policy_ready
	if not policy_ready():
		frappe.throw("Apply the consent policy migration to enable this page")
	types = frappe.get_list("Subscription Topic", fields=["name", "category", "disabled", "description", "consent_required", "double_opt_in", "deliver_while_pending"], order_by="category asc, name asc", limit_page_length=500)
	can_count = frappe.has_permission("Email Subscription Preference", "read")
	counts = {}
	if can_count and types:
		for row in frappe.get_list("Email Subscription Preference", filters={"subscription_topic": ["in", [t.name for t in types]]}, fields=["subscription_topic", "status", {"COUNT": "name", "as": "total"}], group_by="subscription_topic, status", limit_page_length=1500):
			counts.setdefault(row.subscription_topic, {})[row.status] = row.total
	labels = {}
	if types:
		for row in frappe.get_all("Subscription Topic Translation", filters={"parent": ["in", [t.name for t in types]], "parenttype": "Subscription Topic"},
				fields=["parent", "language", "label"], limit_page_length=0):
			labels.setdefault(row.parent, {})[row.language] = row.label
	return {"types": types, "labels": labels, "can_design": frappe.has_permission("Subscription Center Settings", "write"), "counts": counts if can_count else None, "can_edit": frappe.has_permission("Subscription Topic", "write"), "can_create": frappe.has_permission("Subscription Topic", "create"), "can_delete": frappe.has_permission("Subscription Topic", "delete"), "can_log": frappe.has_permission("Email Subscription Event", "read"), "can_preview": can_count}


@frappe.whitelist(methods=["GET"])
def address_preview(email):
	frappe.has_permission("Email Subscription Preference", "read", throw=True)
	from finbyzreach.subscription_preferences import normalize_email
	from finbyzreach.consent import consent_exclusion, suppressed_addresses, POLICY_FIELDS
	email = normalize_email(email)
	state = {row.subscription_topic: row.status for row in frappe.get_list("Email Subscription Preference", filters={"email": email}, fields=["subscription_topic", "status"], limit_page_length=500)}
	blocks = suppressed_addresses([email])
	rows = frappe.get_list("Subscription Topic", filters={"disabled": 0, "category": ["in", ["Mailing Type", "System"]]}, fields=POLICY_FIELDS, order_by="name asc", limit_page_length=500)
	for row in rows:
		row.available = True
	return [{"name": row.name, "status": state.get(row.name, "Not subscribed"), "reason": consent_exclusion(email, row.name, policy=row, suppressions=blocks, status=state.get(row.name), status_loaded=True)} for row in rows]


LOG_FIELDS = ["name", "event_time", "email", "subscription_topic", "status", "source", "consent_version"]


def _log_filters(search=None, status=None, topic=None, source=None):
	filters, or_filters = {}, None
	if status:
		filters["status"] = status
	if topic:
		filters["subscription_topic"] = topic
	if source:
		filters["source"] = ["like", f"%{str(source)[:100]}%"]
	if search:
		or_filters = {"email": ["like", f"%{str(search).strip().lower()[:140]}%"]}
	return filters, or_filters


def _people(emails):
	"""Contact or lead behind each address, limited to records the user may read."""
	people = {}
	if not emails:
		return people
	for row in frappe.get_list("Lead", filters={"email_id": ["in", list(emails)]}, fields=["name", "lead_name", "email_id"], limit_page_length=0):
		people.setdefault((row.email_id or "").lower(), {"doctype": "Lead", "name": row.name, "label": row.lead_name or row.name})
	for row in frappe.get_list("Contact", filters={"email_id": ["in", list(emails)]}, fields=["name", "full_name", "email_id"], limit_page_length=0):
		people[(row.email_id or "").lower()] = {"doctype": "Contact", "name": row.name, "label": row.full_name or row.name}
	return people


@frappe.whitelist(methods=["GET"])
def consent_log(search=None, status=None, topic=None, source=None, start=0):
	"""CS-10: consent log with search, filters and the matching contact or lead."""
	frappe.has_permission("Email Subscription Event", "read", throw=True)
	filters, or_filters = _log_filters(search, status, topic, source)
	start = max(0, frappe.utils.cint(start))
	rows = frappe.get_list("Email Subscription Event", filters=filters, or_filters=or_filters, fields=LOG_FIELDS,
		order_by="event_time desc, name desc", start=start, limit_page_length=51)
	people = _people({row.email for row in rows[:50]})
	for row in rows:
		row["person"] = people.get(row.email)
	return {"rows": rows[:50], "has_more": len(rows) > 50,
		"can_export": frappe.has_permission("Email Subscription Event", "export"),
		"sources": sorted({value for value in frappe.get_list("Email Subscription Event", pluck="source", distinct=True, limit_page_length=200) if value})}


@frappe.whitelist(methods=["GET"])
def export_consent_log(search=None, status=None, topic=None, source=None):
	frappe.has_permission("Email Subscription Event", "export", throw=True)
	from frappe.utils.csvutils import to_csv
	filters, or_filters = _log_filters(search, status, topic, source)
	rows = frappe.get_list("Email Subscription Event", filters=filters, or_filters=or_filters, fields=LOG_FIELDS,
		order_by="event_time desc, name desc", limit_page_length=50000)
	people = _people({row.email for row in rows})
	safe = lambda value: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
	data = [["Date and time", "Contact / lead", "Email", "Mailing type / topic", "Action", "Source", "Text version"]]
	for row in rows:
		person = people.get(row.email) or {}
		data.append([str(row.event_time or ""), safe(person.get("label") or ""), safe(row.email), safe(row.subscription_topic),
			row.status, safe(row.source), safe(row.consent_version)])
	frappe.response["filecontent"] = to_csv(data)
	frappe.response["type"] = "download"
	frappe.response["filename"] = "consent_log.csv"
