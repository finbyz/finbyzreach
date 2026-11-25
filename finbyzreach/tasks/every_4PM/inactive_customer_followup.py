"""Follow up with customers who have not ordered for a set number of days.

Runs from the daily Smart Followup job. Settings live in Lead Followup Setting.
"""

import frappe
from frappe import _
from frappe.core.doctype.communication.email import make
from frappe.utils import cint, formatdate, today
from frappe.utils.nestedset import get_descendants_of

from finbyzreach.consent import suppressed_addresses

ORDER_DOCTYPES = {
	"Sales Order": ("transaction_date", "Sales Order Item"),
	"Sales Invoice": ("posting_date", "Sales Invoice Item"),
}


def settings_filters(setting):
	return frappe._dict(
		days=cint(setting.days_since_last_order) or 60,
		max_days=cint(setting.max_days_since_last_order),
		order_basis=setting.order_basis or "Sales Order",
		cooldown_days=cint(setting.followup_cooldown_days),
		limit=cint(setting.max_inactive_per_run) or 50,
		customer_group=setting.inactive_customer_group,
		territory=setting.inactive_territory,
	)


def run_inactive_customer_followup(setting=None):
	setting = setting or frappe.get_single("Lead Followup Setting")
	if not cint(setting.enable_inactive_customer_followup):
		return {"queued": 0}

	rows = get_inactive_customer_followups(settings_filters(setting))
	for row in rows:
		frappe.enqueue(
			"finbyzreach.tasks.every_4PM.inactive_customer_followup.process_inactive_customer",
			queue="long",
			timeout=900,
			enqueue_after_commit=True,
			job_id=f"inactive-customer-followup:{row.customer}",
			deduplicate=True,
			row=dict(row),
		)
	return {"queued": len(rows)}


def _tree_values(doctype, name):
	if not name:
		return None
	return [name, *(get_descendants_of(doctype, name, ignore_permissions=True) or [])]


def get_inactive_customer_followups(filters):
	"""Customers whose last order is at least `days` old, with an email we may send to."""
	filters = frappe._dict(filters)
	if filters.order_basis not in ORDER_DOCTYPES:
		frappe.throw(_("Invalid order basis {0}").format(filters.order_basis))

	limit = max(cint(filters.limit), 0)
	if not limit:
		return []

	date_field = ORDER_DOCTYPES[filters.order_basis][0]
	return_clause = "AND so.is_return = 0" if filters.order_basis == "Sales Invoice" else ""
	values = {
		"days": cint(filters.days),
		"max_days": cint(filters.max_days),
		"cooldown": cint(filters.cooldown_days),
		# fetch extra rows: some are dropped below for a missing or suppressed email
		"fetch": limit * 3,
	}

	conditions = ""
	groups = _tree_values("Customer Group", filters.customer_group)
	if groups:
		conditions += " AND c.customer_group IN %(groups)s"
		values["groups"] = tuple(groups)
	territories = _tree_values("Territory", filters.territory)
	if territories:
		conditions += " AND c.territory IN %(territories)s"
		values["territories"] = tuple(territories)
	if values["max_days"] > 0:
		conditions += " AND o.last_order_date >= DATE_SUB(CURDATE(), INTERVAL %(max_days)s DAY)"
	if values["cooldown"] > 0:
		conditions += """
			AND NOT EXISTS (
				SELECT 1 FROM `tabCommunication` cm
				WHERE cm.reference_doctype = 'Customer'
					AND cm.reference_name = c.name
					AND cm.communication_medium = 'Email'
					AND cm.sent_or_received = 'Sent'
					AND cm.communication_date >= DATE_SUB(NOW(), INTERVAL %(cooldown)s DAY)
			)"""

	rows = frappe.db.sql(
		f"""
		SELECT
			c.name AS customer,
			c.customer_name,
			c.customer_group,
			c.territory,
			c.customer_primary_contact AS contact_name,
			c.email_id AS customer_email,
			o.last_order_date,
			o.num_orders,
			o.total_value,
			DATEDIFF(CURDATE(), o.last_order_date) AS days_since_last_order
		FROM `tabCustomer` c
		INNER JOIN (
			SELECT so.customer,
				MAX(so.{date_field}) AS last_order_date,
				COUNT(so.name) AS num_orders,
				SUM(so.base_net_total) AS total_value
			FROM `tab{filters.order_basis}` so
			WHERE so.docstatus = 1 {return_clause}
			GROUP BY so.customer
		) o ON o.customer = c.name
		WHERE c.disabled = 0
			AND o.last_order_date <= DATE_SUB(CURDATE(), INTERVAL %(days)s DAY)
			{conditions}
		ORDER BY o.last_order_date DESC
		LIMIT %(fetch)s
		""",
		values,
		as_dict=True,
	)

	attach_emails(rows)
	rows = [row for row in rows if row.email]
	if rows:
		blocked = suppressed_addresses([row.email for row in rows])
		rows = [row for row in rows if row.email not in blocked]
	for row in rows:
		row.order_basis = filters.order_basis
	return rows[:limit]


def attach_emails(rows):
	"""Primary contact email first, then the customer's own email. Unsubscribed contacts get none."""
	contact_names = [row.contact_name for row in rows if row.contact_name]
	contacts = {}
	if contact_names:
		contacts = {
			c.name: c
			for c in frappe.get_all(
				"Contact",
				filters={"name": ["in", contact_names]},
				fields=["name", "email_id", "unsubscribed", "first_name"],
				limit_page_length=0,
			)
		}
	for row in rows:
		contact = contacts.get(row.contact_name)
		if contact and cint(contact.unsubscribed):
			row.email = None
			continue
		contact_email = (contact.email_id or "").strip() if contact else ""
		email = contact_email or row.customer_email
		row.email = str(email or "").strip().lower() or None
		row.contact_first_name = contact.first_name if contact else None


def get_recent_items(customer, order_basis, orders=3, limit=10):
	if order_basis not in ORDER_DOCTYPES:
		frappe.throw(_("Invalid order basis {0}").format(order_basis))
	date_field, item_doctype = ORDER_DOCTYPES[order_basis]
	return_clause = "AND is_return = 0" if order_basis == "Sales Invoice" else ""
	parents = frappe.db.sql_list(
		f"""SELECT name FROM `tab{order_basis}`
		WHERE customer = %s AND docstatus = 1 {return_clause}
		ORDER BY {date_field} DESC, name DESC LIMIT %s""",
		(customer, orders),
	)
	if not parents:
		return []
	return frappe.db.sql(
		f"""SELECT item_code, item_name, SUM(qty) AS qty, uom
		FROM `tab{item_doctype}`
		WHERE parenttype = %s AND parent IN %s
		GROUP BY item_code, item_name, uom
		ORDER BY SUM(base_net_amount) DESC
		LIMIT %s""",
		(order_basis, tuple(parents), limit),
		as_dict=True,
	)


def _field(result, name):
	if result is None:
		return None
	return result.get(name) if isinstance(result, dict) else getattr(result, name, None)


def draft_inactive_email(row, setting):
	from finbyzai.ai.agent.agent_service import AgentService

	items = get_recent_items(row["customer"], row["order_basis"])
	item_summary = "\n".join(
		f"- {i.item_name} ({float(i.qty or 0):g} {i.uom or ''})".rstrip() for i in items
	)
	result = AgentService(setting.inactive_email_agent).invoke(
		customer_name=row.get("customer_name") or "",
		contact_first_name=row.get("contact_first_name") or "",
		customer_group=row.get("customer_group") or "",
		territory=row.get("territory") or "",
		last_order_date=formatdate(row.get("last_order_date"), "d MMMM yyyy"),
		days_since_last_order=row.get("days_since_last_order") or "",
		num_orders=row.get("num_orders") or 0,
		recent_items=item_summary or "No item details.",
		today=formatdate(today(), "d MMMM yyyy"),
	)
	subject = _field(result, "subject")
	body = _field(result, "body")
	if not (str(subject or "").strip() and str(body or "").strip()):
		return None
	signature = (
		frappe.db.get_value("Email Account", setting.email_account, "signature")
		if setting.email_account
		else None
	)
	return {
		"subject": subject,
		"body": f"{body}<br><br>{signature}" if signature else body,
	}


def process_inactive_customer(row):
	setting = frappe.get_single("Lead Followup Setting")
	if not cint(setting.enable_inactive_customer_followup):
		return
	try:
		draft = draft_inactive_email(row, setting)
		if not draft:
			frappe.log_error(
				"Inactive Customer Followup: empty AI draft", f"Customer {row.get('customer')}"
			)
			return
		sender = (
			frappe.db.get_value("Email Account", setting.email_account, "email_id")
			if setting.email_account
			else None
		)
		make(
			recipients=row["email"],
			subject=draft["subject"],
			content=draft["body"],
			doctype="Customer",
			name=row["customer"],
			sender=sender,
			send_email=True,
		)
	except Exception:
		frappe.log_error(
			"Inactive Customer Followup failed", f"Customer {row.get('customer')}\n{frappe.get_traceback()}"
		)


@frappe.whitelist()
def preview_inactive_customers():
	"""Who the next run would email, using the saved settings. Sends nothing."""
	frappe.only_for(("System Manager", "Social Media Manager"))
	setting = frappe.get_single("Lead Followup Setting")
	rows = get_inactive_customer_followups(settings_filters(setting))
	return [
		{
			"customer": r.customer,
			"customer_name": r.customer_name,
			"email": r.email,
			"last_order_date": r.last_order_date,
			"days_since_last_order": r.days_since_last_order,
		}
		for r in rows
	]
