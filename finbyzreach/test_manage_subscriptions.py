from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach.www import manage_subscriptions


class TestManageSubscriptions(TestCase):
	def setUp(self):
		self.database = MagicMock()
		patcher = patch.object(frappe.local, "db", self.database, create=True)
		patcher.start()
		self.addCleanup(patcher.stop)
		flags = patch.object(frappe.local, "flags", frappe._dict(mute_messages=True), create=True)
		flags.start()
		self.addCleanup(flags.stop)

	def test_contact_signed_link_uses_contact_language_and_rejects_tampering(self):
		from frappe.utils.verified_command import get_signed_params
		recipient = frappe._dict(name="EC-CONTACT", recipient="CONT-1", email_campaign_for="Contact",
			custom_normalized_email="contact@example.invalid", campaign_name="CAM-1")
		contact = frappe._dict(name="CONT-1", custom_preferred_language="fr", language="en")
		self.database.exists.return_value = True
		self.database.get_value.return_value = None
		with patch("frappe.utils.verified_command.get_secret", return_value="test-signing-secret"), \
			patch.object(frappe, "get_doc", side_effect=lambda doctype, name: recipient if doctype == "Email Campaign" else contact) as get_doc, \
			patch.object(manage_subscriptions, "topic_rows", return_value=[]) as topics, \
			patch.object(manage_subscriptions, "get_copy", return_value={}):
			signed = get_signed_params({"campaign_recipient":recipient.name,"email":recipient.custom_normalized_email})
			for query, invalid in ((signed, False), (signed.replace("EC-CONTACT", "EC-OTHER"), True),
				(get_signed_params({"campaign_recipient":recipient.name,"email":"other@example.invalid"}), True)):
				with self.subTest(invalid=invalid, query=query), \
					patch.object(frappe, "request", new=SimpleNamespace(query_string=query.encode())), \
					patch.object(frappe, "form_dict", new=frappe._dict(campaign_recipient=recipient.name)):
					context = manage_subscriptions.get_context(frappe._dict())
					if invalid:
						self.assertIn("error_message", context)
					else:
						self.assertNotIn("error_message", context)
						self.assertEqual(context.language, "fr")
						self.assertEqual(context.email, recipient.custom_normalized_email)
						self.assertEqual(len(context.language_urls), 4)
						get_doc.assert_any_call("Contact", contact.name)
						topics.assert_called_with(recipient.custom_normalized_email, "fr")

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
