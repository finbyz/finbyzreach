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
	return {"types": types, "counts": counts if can_count else None, "can_edit": frappe.has_permission("Subscription Topic", "write"), "can_create": frappe.has_permission("Subscription Topic", "create"), "can_delete": frappe.has_permission("Subscription Topic", "delete"), "can_log": frappe.has_permission("Email Subscription Event", "read"), "can_preview": can_count}


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
