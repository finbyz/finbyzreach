"""EM-04: "latest sales order" and "latest quotation" merge fields for Lead, Contact and Customer.

They behave like a Link field with a short, fixed list of readable values, so the personalisation
picker, the field check and the renderer all use the normal Link path ({{ latest_sales_order.grand_total }}).
Only submitted documents count. Money and dates are shown formatted, ready for an email.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import fmt_money, formatdate

SUPPORTED_REFERENCE_DOCTYPES = {"Lead", "Contact", "Customer"}

VIRTUAL_LINKS = {
	"latest_sales_order": {
		"doctype": "Sales Order",
		"label": "Latest sales order",
		"fields": {
			"name": "ID", "transaction_date": "Order date", "grand_total": "Total",
			"currency": "Currency", "status": "Status", "delivery_date": "Delivery date",
		},
	},
	"latest_quotation": {
		"doctype": "Quotation",
		"label": "Latest quotation",
		"fields": {
			"name": "ID", "transaction_date": "Quotation date", "grand_total": "Total",
			"currency": "Currency", "status": "Status", "valid_till": "Valid until",
		},
	},
}
_DATE_FIELDS = {"transaction_date", "delivery_date", "valid_till"}


def is_virtual_root(reference_doctype: str, name: str) -> bool:
	return reference_doctype in SUPPORTED_REFERENCE_DOCTYPES and name in VIRTUAL_LINKS


def virtual_link_rows(reference_doctype: str) -> list[dict]:
	"""Rows that the picker lists next to the real Link fields."""
	if reference_doctype not in SUPPORTED_REFERENCE_DOCTYPES:
		return []
	return [
		{"fieldname": name, "label": _(meta["label"]), "fieldtype": "Link", "options": meta["doctype"]}
		for name, meta in VIRTUAL_LINKS.items()
	]


def virtual_child_rows(root: str) -> list[dict]:
	meta = VIRTUAL_LINKS[root]
	return [
		{"fieldname": f"{root}.{field}", "label": _(label), "fieldtype": "Data", "options": ""}
		for field, label in meta["fields"].items()
	]


def is_virtual_path(reference_doctype: str, root: str, field: str) -> bool:
	return is_virtual_root(reference_doctype, root) and field in VIRTUAL_LINKS[root]["fields"]


def _customers_for(source_doctype: str, source_name: str) -> list[str]:
	if source_doctype == "Customer":
		return [source_name]
	if source_doctype == "Lead":
		return frappe.get_all("Customer", filters={"lead_name": source_name}, pluck="name", limit_page_length=20)
	if source_doctype == "Contact":
		return frappe.get_all(
			"Dynamic Link", filters={"parent": source_name, "parenttype": "Contact", "link_doctype": "Customer"},
			pluck="link_name", limit_page_length=20,
		)
	return []


def _latest_row(source_doctype: str, source_name: str, root: str) -> dict | None:
	target = VIRTUAL_LINKS[root]["doctype"]
	fields = list(VIRTUAL_LINKS[root]["fields"])
	order = "transaction_date desc, creation desc"
	customers = _customers_for(source_doctype, source_name)
	rows = []
	if target == "Sales Order":
		if customers:
			rows = frappe.get_all(target, filters={"customer": ["in", customers], "docstatus": 1}, fields=fields, order_by=order, limit_page_length=1)
	else:
		if source_doctype == "Lead":
			rows += frappe.get_all(target, filters={"quotation_to": "Lead", "party_name": source_name, "docstatus": 1}, fields=fields + ["creation"], order_by=order, limit_page_length=1)
		if customers:
			rows += frappe.get_all(target, filters={"quotation_to": "Customer", "party_name": ["in", customers], "docstatus": 1}, fields=fields + ["creation"], order_by=order, limit_page_length=1)
		rows.sort(key=lambda row: (str(row.get("transaction_date") or ""), str(row.get("creation") or "")), reverse=True)
	return rows[0] if rows else None


def latest_value(source_doctype: str, root: str, field: str, source: dict):
	"""The formatted value for one token, or "" when the person has no such document yet."""
	name = str(source.get("name") or "")
	if not name:
		return ""
	cache = getattr(frappe.local, "latest_documents_cache", None)
	if cache is None:
		cache = frappe.local.latest_documents_cache = {}
	key = (source_doctype, name, root)
	if key not in cache:
		cache[key] = _latest_row(source_doctype, name, root) or {}
	row = cache[key]
	value = row.get(field)
	if value in (None, ""):
		return ""
	if field in _DATE_FIELDS:
		return formatdate(value)
	if field == "grand_total":
		return fmt_money(value, currency=row.get("currency"))
	return value
