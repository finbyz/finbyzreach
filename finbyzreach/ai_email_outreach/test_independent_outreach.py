"""Outreach can draft and approve emails without a client-specific app."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach.ai_email_outreach import approval
from finbyzreach.ai_email_outreach.doctype.outbound_email.outbound_email import OutboundEmail


class TestIndependentOutreach(unittest.TestCase):
	def test_template_context_does_not_query_a_source_integration(self):
		contact = SimpleNamespace(
			first_name="Anna", last_name="Example", email_id="anna@example.com", company_name="Acme"
		)
		with patch.object(frappe, "db", MagicMock()) as database:
			context = OutboundEmail.get_template_context(
				SimpleNamespace(name="OUT-1"), contact, None, SimpleNamespace(campaign_name="Campaign")
			)
		self.assertEqual(context["full_name"], "Anna Example")
		self.assertEqual(context["company_name"], "Acme")
		database.get_value.assert_not_called()
		database.sql.assert_not_called()

	def test_approval_releases_only_selected_held_rows(self):
		rows = [
			SimpleNamespace(name="first", idx=1, status="Awaiting Approval"),
			SimpleNamespace(name="later", idx=2, status="Awaiting Approval"),
			SimpleNamespace(name="already-sent", idx=3, status="Sent"),
		]
		with patch.object(approval, "frappe", MagicMock()) as framework, patch.object(
			approval, "_", side_effect=lambda value: value
		):
			framework.get_doc.return_value = SimpleNamespace(communication_email=rows)
			result = approval.approve_emails("OUT-1", rows=["later", "already-sent"])
		self.assertEqual(result["released"], 1)
		framework.only_for.assert_called_once_with("System Manager")
		framework.db.set_value.assert_called_once_with(
			"Communication Email", "later", "status", "Pending", update_modified=False
		)

	def test_standard_links_resolve_without_optional_source_doctypes(self):
		import json

		root = Path(__file__).parent / "doctype"
		for doctype in ("ai_email_campaign", "outbound_email"):
			schema = json.loads((root / doctype / f"{doctype}.json").read_text())
			for field in schema["fields"]:
				if field["fieldtype"] == "Link":
					self.assertNotIn("Infomanager", field.get("options", ""))
