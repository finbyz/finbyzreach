"""Live segments of CRM records whose primary email subscribed to an option."""
import json
import frappe
from frappe import _
from frappe.query_builder.functions import Lower, Trim


def subscription_condition(doctype, node):
	if doctype not in ("Lead", "Contact", "Customer"):
		frappe.throw(_("Subscription conditions require Lead, Contact or Customer"))
	frappe.has_permission("Email Subscription Preference", "read", throw=True)
	frappe.get_doc("Subscription Topic", node.get("topic")).check_permission("read")
	# Consent is stored per email address (chapter 16). "Not subscribed" means no
	# preference row for this option at all.
	status = node.get("status") or "Subscribed"
	if status not in ("Subscribed", "Pending", "Unsubscribed", "Not subscribed"):
		frappe.throw(_("Unsupported subscription status"))
	filters = {"subscription_topic": node.get("topic")}
	if status != "Not subscribed":
		filters["status"] = status
	addresses = frappe.qb.get_query("Email Subscription Preference", fields=["email"],
		filters=filters, ignore_permissions=False)
	table = frappe.qb.DocType(doctype)
	email = Lower(Trim(table.email_id))
	if status == "Not subscribed":
		return table.email_id.isnull() | (table.email_id == "") | email.notin(addresses)
	return email.isin(addresses)


@frappe.whitelist(methods=["POST"])
def create_subscriber_segment(topic, audience_doctype, segment_name):
	if audience_doctype not in ("Lead", "Contact", "Customer"):
		frappe.throw(_("Choose Lead, Contact or Customer"))
	frappe.has_permission(audience_doctype, "read", throw=True)
	frappe.has_permission("Reach Segment", "create", throw=True)
	frappe.has_permission("Email Subscription Preference", "read", throw=True)
	option = frappe.get_doc("Subscription Topic", topic)
	option.check_permission("read")
	if option.disabled or option.category == "System":
		frappe.throw(_("Choose an active subscription option"))
	doc = frappe.get_doc({"doctype": "Reach Segment", "segment_name": str(segment_name or "").strip(),
		"audience_doctype": audience_doctype, "segment_type": "Active", "filter_groups_json": "[]",
		"filter_expression_json": json.dumps({"kind": "subscription", "topic": topic}),
		"description": _("Records with a subscribed primary email address. Consent changes update membership.")})
	doc.insert()
	return {"name": doc.name}


def queue_subscription_records(preference_name, doctype="Lead", after=None):
	"""Fan out in bounded pages, then use the existing pending-record processor."""
	from finbyzreach.segment_automation import queue_identity, enqueue_changes
	email = frappe.db.get_value("Email Subscription Preference", preference_name, "email")
	if not email:
		return
	table = frappe.qb.DocType(doctype)
	query = frappe.qb.from_(table).select(table.name).where(Lower(Trim(table.email_id)) == email).orderby(table.name).limit(200)
	if after:
		query = query.where(table.name > after)
	names = [row[0] for row in query.run()]
	for name in names:
		queue_identity(doctype, name)
	if len(names) == 200:
		frappe.enqueue("finbyzreach.subscriber_segments.queue_subscription_records", preference_name=preference_name,
			doctype=doctype, after=names[-1], queue="short", enqueue_after_commit=True)
	elif doctype != "Customer":
		queue_subscription_records(preference_name, "Contact" if doctype == "Lead" else "Customer")
	enqueue_changes()
