"""EM-04: latest sales order and latest quotation merge fields."""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from .. import latest_documents
from ..reference_fields import is_permitted_reference_path, link_target_doctype, reference_field_rows, resolve_linked_value


class LatestDocumentsTest(IntegrationTestCase):
	def setUp(self):
		frappe.local.latest_documents_cache = {}

	def test_the_picker_lists_both_fields_for_lead_contact_and_customer_only(self):
		for doctype in ("Lead", "Contact", "Customer"):
			names = {row["fieldname"]: row for row in reference_field_rows(doctype)}
			self.assertEqual(names["latest_sales_order"]["fieldtype"], "Link")
			self.assertEqual(names["latest_sales_order"]["options"], "Sales Order")
			self.assertEqual(names["latest_quotation"]["options"], "Quotation")
		self.assertNotIn("latest_sales_order", {row["fieldname"] for row in reference_field_rows("Opportunity")})

	def test_children_are_the_short_fixed_list(self):
		rows = latest_documents.virtual_child_rows("latest_sales_order")
		self.assertEqual([row["fieldname"] for row in rows], [f"latest_sales_order.{name}" for name in ("name", "transaction_date", "grand_total", "currency", "status", "delivery_date")])
		self.assertEqual(link_target_doctype("Customer", "latest_quotation"), "Quotation")

	def test_only_listed_fields_pass_the_field_check(self):
		self.assertTrue(is_permitted_reference_path("Customer", "latest_sales_order.grand_total"))
		self.assertTrue(is_permitted_reference_path("Lead", "latest_quotation.valid_till"))
		self.assertFalse(is_permitted_reference_path("Customer", "latest_sales_order.owner"))
		self.assertFalse(is_permitted_reference_path("Opportunity", "latest_sales_order.grand_total"))
		self.assertFalse(is_permitted_reference_path("Customer", "latest_sales_order.items.rate"))

	def test_values_are_formatted_and_blank_when_the_person_has_no_document(self):
		row = frappe._dict(name="SAL-ORD-1", transaction_date="2026-11-10", grand_total=12345.5, currency="CHF", status="To Deliver", delivery_date=None)
		with patch.object(latest_documents, "_latest_row", return_value=row):
			self.assertEqual(resolve_linked_value("Customer", "latest_sales_order.name", {"name": "C-1"}), ("SAL-ORD-1", True))
			total, valid = resolve_linked_value("Customer", "latest_sales_order.grand_total", {"name": "C-1"})
			self.assertTrue(valid)
			self.assertIn("12", total)
			self.assertIn("345", total)
			self.assertNotEqual(total, "12345.5")
			self.assertEqual(resolve_linked_value("Customer", "latest_sales_order.delivery_date", {"name": "C-1"}), ("", True))
			date, _ok = resolve_linked_value("Customer", "latest_sales_order.transaction_date", {"name": "C-1"})
			self.assertIn("2026", date)
		frappe.local.latest_documents_cache = {}
		with patch.object(latest_documents, "_latest_row", return_value=None):
			self.assertEqual(resolve_linked_value("Lead", "latest_quotation.name", {"name": "L-1"}), ("", True))

	def test_an_unlisted_field_or_unsupported_doctype_is_not_resolved(self):
		self.assertEqual(resolve_linked_value("Customer", "latest_sales_order.owner", {"name": "C-1"}), (None, False))

	def test_the_lookup_is_done_once_per_person_and_field_group(self):
		with patch.object(latest_documents, "_latest_row", return_value=frappe._dict(name="X", currency="CHF")) as lookup:
			resolve_linked_value("Customer", "latest_sales_order.name", {"name": "C-1"})
			resolve_linked_value("Customer", "latest_sales_order.status", {"name": "C-1"})
			self.assertEqual(lookup.call_count, 1)
