from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from finbyzreach.customer_campaign import (
	contact_for_customer,
	customer_contacts,
	resolve_customer_audience,
	current_customer_exclusion,
)
from finbyzreach.email_marketing import _recipient_values


def _make_get_value(records):
	"""Return a mock for frappe.db.get_value that returns values from *records*."""
	def _get_value(*args, **kwargs):
		dn = kwargs.get("dn") or kwargs.get("filters") or (args[1] if len(args) > 1 else None)
		if isinstance(dn, dict):
			return None
		return records.get(dn)
	return _get_value


class TestCustomerCampaign(TestCase):
	def setUp(self):
		self.enterContext(patch.object(frappe, "_", side_effect=lambda value: value))

	def test_contact_for_customer_requires_both_names(self):
		self.assertFalse(contact_for_customer("CUST-1", ""))
		self.assertFalse(contact_for_customer("", "CONT-1"))

	@patch.object(frappe.db, "exists", return_value=True)
	def test_contact_for_customer_validates_dynamic_link(self, db_exists):
		result = contact_for_customer("CUST-1", "CONT-1")
		self.assertTrue(result)
		db_exists.assert_called_once_with("Dynamic Link", {
			"parenttype": "Contact", "parent": "CONT-1",
			"link_doctype": "Customer", "link_name": "CUST-1",
		})

	@patch.object(frappe.db, "exists", return_value=False)
	def test_contact_for_customer_rejects_invalid_link(self, db_exists):
		self.assertFalse(contact_for_customer("CUST-1", "WRONG"))

	def test_customer_contacts_primary_mode_returns_primary(self):
		customer = frappe._dict(name="CUST-1", customer_primary_contact="CONT-P")
		with patch("finbyzreach.customer_campaign.contact_for_customer", return_value=True):
			self.assertEqual(customer_contacts(customer, "Primary Contact"), ["CONT-P"])

	def test_customer_contacts_primary_without_link_returns_empty(self):
		customer = frappe._dict(name="CUST-1", customer_primary_contact="CONT-P")
		with patch("finbyzreach.customer_campaign.contact_for_customer", return_value=False):
			self.assertEqual(customer_contacts(customer, "Primary Contact"), [])

	@patch.object(frappe, "get_all", return_value=["CONT-A", "CONT-B"])
	def test_customer_contacts_all_mode_returns_all_linked(self, get_all):
		customer = frappe._dict(name="CUST-1")
		result = customer_contacts(customer, "All Linked Contacts")
		self.assertEqual(result, ["CONT-A", "CONT-B"])

	def _resolve_with(self, campaign, lead_names, contacts_list, db_records):
		with patch(
			"finbyzreach.email_marketing._globally_unsubscribed_emails", return_value=set()
		), patch(
			"finbyzreach.email_marketing._reference_unsubscribed_pairs", return_value=set()
		), patch(
			"finbyzreach.email_marketing._normalized_email",
			side_effect=lambda v: str(v or "").strip().lower(),
		), patch(
			"finbyzreach.email_marketing.validate_excluded_email_groups", return_value=[]
		), patch(
			"finbyzreach.email_marketing._lead_names_from_filter_groups",
			return_value=lead_names,
		), patch.object(
			frappe.db, "get_value", side_effect=_make_get_value(db_records)
		), patch.object(
			frappe, "get_all", return_value=contacts_list
		), patch.object(
			frappe.db, "exists", return_value=True
		):
			return resolve_customer_audience(campaign)

	def test_eligible_primary_contact(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1"],
			studio_exclude_leads=[],
			custom_contact_mode="Primary Contact",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="Test Co",
				customer_primary_contact="CONT-A", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", full_name="Test Contact",
				email_id="test@example.com", unsubscribed=0),
		}
		result = self._resolve_with(campaign, [], ["CONT-A"], records)

		self.assertEqual(len(result), 1)
		self.assertEqual(result[0].lead, "CUST-1")
		self.assertEqual(result[0].contact, "CONT-A")
		self.assertEqual(result[0].email, "test@example.com")
		self.assertTrue(result[0].eligible)

	def test_excludes_disabled_customer(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1"],
			studio_exclude_leads=[],
			custom_contact_mode="Primary Contact",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="Disabled Co",
				customer_primary_contact="CONT-A", disabled=1),
			"CONT-A": frappe._dict(name="CONT-A", full_name="Test Contact",
				email_id="test@example.com", unsubscribed=0),
		}
		result = self._resolve_with(campaign, [], ["CONT-A"], records)

		self.assertEqual(len(result), 1)
		self.assertFalse(result[0].eligible)
		self.assertEqual(result[0].reason, "Customer disabled")

	def test_excludes_unsubscribed_contact(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1"],
			studio_exclude_leads=[],
			custom_contact_mode="Primary Contact",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="Test Co",
				customer_primary_contact="CONT-A", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", full_name="Test Contact",
				email_id="test@example.com", unsubscribed=1),
		}
		result = self._resolve_with(campaign, [], ["CONT-A"], records)

		self.assertEqual(len(result), 1)
		self.assertFalse(result[0].eligible)
		self.assertEqual(result[0].reason, "Contact unsubscribed")

	def test_excludes_missing_email(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1"],
			studio_exclude_leads=[],
			custom_contact_mode="Primary Contact",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="Test Co",
				customer_primary_contact="CONT-A", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", full_name="Test Contact",
				email_id="", unsubscribed=0),
		}
		result = self._resolve_with(campaign, [], ["CONT-A"], records)

		self.assertEqual(len(result), 1)
		self.assertFalse(result[0].eligible)
		self.assertEqual(result[0].reason, "Missing or invalid email")

	def test_deduplicates_shared_email(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1", "CUST-2"],
			studio_exclude_leads=[],
			custom_contact_mode="Primary Contact",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="First Co",
				customer_primary_contact="CONT-A", disabled=0),
			"CUST-2": frappe._dict(name="CUST-2", customer_name="Second Co",
				customer_primary_contact="CONT-A", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", full_name="Shared Contact",
				email_id="shared@example.com", unsubscribed=0),
		}
		result = self._resolve_with(campaign, [], ["CONT-A"], records)

		self.assertEqual(len(result), 2)
		eligible = [row for row in result if row.eligible]
		self.assertEqual(len(eligible), 1)
		self.assertEqual(eligible[0].email, "shared@example.com")

	def test_customer_without_contacts_is_excluded(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1"],
			studio_exclude_leads=[],
			custom_contact_mode="Primary Contact",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="No Contact Co",
				customer_primary_contact=None, disabled=0),
		}
		result = self._resolve_with(campaign, [], [], records)

		self.assertEqual(len(result), 1)
		self.assertFalse(result[0].eligible)
		self.assertEqual(result[0].reason, "No linked Contact")

	def test_all_linked_contacts_create_separate_delivery_candidates(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1"], studio_exclude_leads=[],
			custom_contact_mode="All Linked Contacts",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="Company",
				customer_primary_contact="CONT-A", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", full_name="First", email_id="a@example.com", unsubscribed=0),
			"CONT-B": frappe._dict(name="CONT-B", full_name="Second", email_id="b@example.com", unsubscribed=0),
		}
		result = self._resolve_with(campaign, [], ["CONT-A", "CONT-B"], records)
		self.assertEqual({row.contact for row in result if row.eligible}, {"CONT-A", "CONT-B"})
		self.assertEqual(len(result), 2)

	def test_topic_preference_excludes_customer_contact(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1"], studio_exclude_leads=[],
			custom_contact_mode="Primary Contact", custom_subscription_topic="Updates",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="Company",
				customer_primary_contact="CONT-A", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", full_name="First", email_id="a@example.com", unsubscribed=0),
		}
		with patch("finbyzreach.customer_campaign.statuses", return_value={"Updates": "Unsubscribed"}):
			result = self._resolve_with(campaign, [], ["CONT-A"], records)
		self.assertFalse(result[0].eligible)
		self.assertTrue(result[0].topic_unsubscribed)

	def test_customer_contact_requires_confirmed_double_opt_in(self):
		campaign = frappe._dict(
			studio_include_leads=["CUST-1"], studio_exclude_leads=[],
			custom_contact_mode="Primary Contact", custom_subscription_topic="Updates",
		)
		records = {
			"CUST-1": frappe._dict(name="CUST-1", customer_name="Company",
				customer_primary_contact="CONT-A", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", full_name="First",
				email_id="a@example.com", unsubscribed=0),
		}
		with patch("finbyzreach.customer_campaign.statuses", return_value={"Updates": "Pending"}):
			pending = self._resolve_with(campaign, [], ["CONT-A"], records)
		with patch("finbyzreach.customer_campaign.statuses", return_value={"Updates": "Subscribed"}):
			confirmed = self._resolve_with(campaign, [], ["CONT-A"], records)
		self.assertFalse(pending[0].eligible)
		self.assertEqual(pending[0].reason, "No confirmed subscription to Updates")
		self.assertFalse(pending[0].topic_unsubscribed)
		self.assertTrue(confirmed[0].eligible)

	def test_scheduled_row_keeps_customer_and_contact_identity(self):
		campaign = frappe._dict(name="CAM-1", custom_audience_doctype="Customer", custom_start_on="2026-10-13")
		row = frappe._dict(lead="CUST-1", contact="CONT-A", eligible=True,
			email="a@example.com", normalized_email="a@example.com", reason=None)
		values = _recipient_values(campaign, row, batch_number=1, scheduled_at="2026-10-13 09:00:00")
		self.assertEqual(values["email_campaign_for"], "Customer")
		self.assertEqual(values["recipient"], "CUST-1")
		self.assertEqual(values["custom_contact"], "CONT-A")
		self.assertEqual(values["custom_recipient_email"], "a@example.com")

	@patch("finbyzreach.email_marketing._globally_unsubscribed_emails", return_value=set())
	@patch("finbyzreach.email_marketing._reference_unsubscribed_pairs", return_value=set())
	@patch("finbyzreach.email_marketing._normalized_email", return_value="ok@example.com")
	@patch("finbyzreach.customer_campaign.is_subscribed", return_value=True)
	@patch.object(frappe.db, "get_value")
	def test_current_exclusion_passes_eligible(self, get_value, is_sub, norm, reference_unsub, glob_unsub):
		get_value.side_effect = _make_get_value({
			"CUST-1": frappe._dict(name="CUST-1", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", email_id="ok@example.com", unsubscribed=0),
		})

		recipient = frappe._dict(
			recipient="CUST-1",
			**{"custom_contact": "CONT-A", "custom_normalized_email": "ok@example.com"},
		)
		campaign = frappe._dict(
			custom_subscription_topic="Updates",
			custom_content_topic=None,
		)

		with patch("finbyzreach.customer_campaign.contact_for_customer", return_value=True):
			self.assertIsNone(current_customer_exclusion(recipient, campaign))

	@patch("finbyzreach.email_marketing._normalized_email", return_value="new@example.com")
	@patch("finbyzreach.email_marketing._globally_unsubscribed_emails", return_value=set())
	@patch("finbyzreach.email_marketing._reference_unsubscribed_pairs", return_value=set())
	@patch.object(frappe.db, "get_value")
	def test_current_exclusion_detects_changed_email(self, get_value, reference_unsub, glob_unsub, norm_email):
		get_value.side_effect = _make_get_value({
			"CUST-1": frappe._dict(name="CUST-1", disabled=0),
			"CONT-A": frappe._dict(name="CONT-A", email_id="new@example.com", unsubscribed=0),
		})

		recipient = frappe._dict(
			recipient="CUST-1",
			**{"custom_contact": "CONT-A", "custom_normalized_email": "old@example.com"},
		)
		campaign = frappe._dict(
			custom_subscription_topic="Updates",
			custom_content_topic=None,
		)

		with patch("finbyzreach.customer_campaign.contact_for_customer", return_value=True):
			result = current_customer_exclusion(recipient, campaign)
			self.assertEqual(result, "Contact email changed")

	@patch.object(frappe.db, "get_value")
	def test_current_exclusion_detects_disabled_customer(self, get_value):
		get_value.return_value = frappe._dict(name="CUST-1", disabled=1)

		recipient = frappe._dict(recipient="CUST-1")
		campaign = frappe._dict(custom_subscription_topic="Updates")

		result = current_customer_exclusion(recipient, campaign)
		self.assertEqual(result, "Customer disabled")

	def test_current_exclusion_honors_contact_reference_unsubscribe(self):
		recipient = frappe._dict(
			recipient="CUST-1", custom_contact="CONT-A",
			custom_normalized_email="ok@example.com",
		)
		campaign = frappe._dict(custom_subscription_topic="Updates", custom_content_topic=None)
		records = {
			"CUST-1": frappe._dict(disabled=0),
			"CONT-A": frappe._dict(email_id="ok@example.com", unsubscribed=0),
		}
		with patch.object(frappe.db, "get_value", side_effect=_make_get_value(records)), \
			patch("finbyzreach.customer_campaign.contact_for_customer", return_value=True), \
			patch("finbyzreach.email_marketing._normalized_email", return_value="ok@example.com"), \
			patch("finbyzreach.email_marketing._globally_unsubscribed_emails", return_value=set()), \
			patch("finbyzreach.email_marketing._reference_unsubscribed_pairs", side_effect=[set(), {("CONT-A", "ok@example.com")}]):
			self.assertEqual(
				current_customer_exclusion(recipient, campaign),
				"Unsubscribed from Customer or Contact emails",
			)

	def test_send_time_blocks_customer_contact_without_confirmed_opt_in(self):
		recipient = frappe._dict(
			recipient="CUST-1", custom_contact="CONT-A",
			custom_normalized_email="ok@example.com",
		)
		campaign = frappe._dict(custom_subscription_topic="Updates", custom_content_topic=None)
		records = {
			"CUST-1": frappe._dict(disabled=0),
			"CONT-A": frappe._dict(email_id="ok@example.com", unsubscribed=0),
		}
		with patch.object(frappe.db, "get_value", side_effect=_make_get_value(records)), \
			patch("finbyzreach.customer_campaign.contact_for_customer", return_value=True), \
			patch("finbyzreach.email_marketing._normalized_email", return_value="ok@example.com"), \
			patch("finbyzreach.email_marketing._globally_unsubscribed_emails", return_value=set()), \
			patch("finbyzreach.email_marketing._reference_unsubscribed_pairs", return_value=set()), \
			patch("finbyzreach.customer_campaign.is_subscribed", return_value=False):
			self.assertEqual(
				current_customer_exclusion(recipient, campaign),
				"No confirmed subscription to Updates",
			)
