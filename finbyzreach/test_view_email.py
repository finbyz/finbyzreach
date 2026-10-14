"""Regression tests for signed browser-preview references."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach.www import view_email


class TestViewEmail(TestCase):
	def setUp(self):
		self.enterContext(patch.object(view_email, "_sign_message", return_value="valid"))

	def test_unsigned_reference_appended_after_signature_is_rejected(self):
		query = (b"is_test=1&campaign=CAM-1&_signature=valid"
			b"&reference_doctype=Contact&reference_name=OTHER-CONTACT")
		with patch.object(frappe, "request", new=SimpleNamespace(query_string=query)), \
			patch.object(frappe, "get_doc") as get_doc:
			context = view_email.get_context(frappe._dict())
		self.assertIn("invalid", context.error_message.lower())
		get_doc.assert_not_called()

	def test_signed_duplicate_reference_key_is_rejected(self):
		query = b"campaign=CAM-1&reference_name=CONT-1&reference_name=CONT-2&_signature=valid"
		with patch.object(frappe, "request", new=SimpleNamespace(query_string=query)):
			self.assertIsNone(view_email._verified_params())

	def _customer_preview(self, query, linked=True):
		campaign = frappe._dict(
			name="CAM-1", custom_broadcast_status="Draft", custom_email_template="Template-1",
			custom_subject_override=None, custom_email_account=None, custom_sender_name="Megasol",
			custom_audience_doctype="Customer", custom_contact_mode="Primary Contact",
		)
		customer = frappe._dict(name="CUST-1", email_id="customer@example.com")
		contact = frappe._dict(name="CONT-1", email_id="person@example.com")
		documents = {("Campaign", "CAM-1"): campaign, ("Customer", "CUST-1"): customer,
			("Contact", "CONT-1"): contact}
		with patch.object(frappe, "request", new=SimpleNamespace(query_string=query)), \
			patch.object(frappe.db, "exists", return_value=True), \
			patch.object(frappe, "get_doc", side_effect=lambda doctype, name: documents[(doctype, name)]), \
			patch.object(view_email, "get_campaign_snapshot", return_value=frappe._dict(
				subject="Preview", html="<p>Hello</p>", mode="Visual", preheader="")), \
			patch.object(view_email, "render_campaign_snapshot", return_value=frappe._dict(
				subject="Preview", html="<p>Hello</p>")) as render, \
			patch("finbyzreach.customer_campaign.contact_for_customer", return_value=linked) as linkage:
			context = view_email.get_context(frappe._dict())
			return context, render, linkage, customer, contact

	def test_customer_preview_restores_signed_contact_context(self):
		query = (b"is_test=1&campaign=CAM-1&reference_doctype=Customer&reference_name=CUST-1"
			b"&customer=CUST-1&contact=CONT-1&_signature=valid")
		context, render, linkage, customer, contact = self._customer_preview(query)
		self.assertEqual(context.email_subject, "Preview")
		self.assertIs(render.call_args.args[2], customer)
		self.assertIs(render.call_args.kwargs["extra_context"]["contact"], contact)
		linkage.assert_called_once_with("CUST-1", "CONT-1")

	def test_contact_personalization_keeps_customer_context(self):
		query = (b"is_test=1&campaign=CAM-1&reference_doctype=Contact&reference_name=CONT-1"
			b"&customer=CUST-1&contact=CONT-1&_signature=valid")
		context, render, linkage, customer, contact = self._customer_preview(query)
		self.assertEqual(context.email_subject, "Preview")
		self.assertIs(render.call_args.args[2], contact)
		self.assertIs(render.call_args.kwargs["extra_context"]["customer"], customer)
		linkage.assert_called_once_with("CUST-1", "CONT-1")

	def test_customer_preview_rejects_unlinked_contact(self):
		query = (b"is_test=1&campaign=CAM-1&reference_doctype=Customer&reference_name=CUST-1"
			b"&customer=CUST-1&contact=CONT-1&_signature=valid")
		context, render, _linkage, _customer, _contact = self._customer_preview(query, linked=False)
		self.assertIn("not linked", context.error_message)
		render.assert_not_called()
