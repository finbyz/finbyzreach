from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach.www import manage_subscriptions


class TestManageSubscriptions(TestCase):
	def test_customer_link_uses_linked_contact_language(self):
		recipient = frappe._dict(recipient="CUST-1", email_campaign_for="Customer",
			custom_contact="CONT-1", campaign_name="CAM-1")
		customer = frappe._dict(name="CUST-1", language="en")
		contact = frappe._dict(name="CONT-1", language="fr")
		with patch.object(frappe, "request", new=SimpleNamespace(query_string=b"signed")), \
			patch.object(frappe, "form_dict", new=frappe._dict(campaign_recipient="EC-1")), \
			patch.object(manage_subscriptions, "signed_recipient", return_value=(recipient, "a@example.com")), \
			patch.object(frappe, "get_doc", side_effect=lambda doctype, name:
				{"Customer": customer, "Contact": contact}[(doctype)]), \
			patch("finbyzreach.customer_campaign.contact_for_customer", return_value=True), \
			patch.object(frappe.db, "get_value", return_value=None), \
			patch.object(manage_subscriptions, "topic_rows", return_value=[]), \
			patch.object(manage_subscriptions, "get_copy", return_value={}), \
			patch.object(manage_subscriptions, "get_signed_params", return_value="signed"):
			context = manage_subscriptions.get_context(frappe._dict())
		self.assertEqual(context.language, "fr")
		self.assertNotIn("error_message", context)
