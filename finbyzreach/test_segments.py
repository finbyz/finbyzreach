from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach.segments import _calculate_static_leads


class TestCustomerStaticSegment(TestCase):
	def test_excludes_customer_only_when_all_linked_contacts_are_in_email_group(self):
		links = [frappe._dict(parent="CONT-1", link_name="CUST-1"),
			frappe._dict(parent="CONT-2", link_name="CUST-1")]
		with patch("finbyzreach.segments.email_marketing._lead_names_from_filter_groups",
			return_value=["CUST-1"]), \
			patch("finbyzreach.segments.email_marketing.validate_excluded_email_groups",
				return_value=["Excluded Group"]), \
			patch("finbyzreach.segments.email_marketing._email_group_addresses",
				return_value={"blocked@example.com"}), \
			patch.object(frappe, "get_all", return_value=links), \
			patch.object(frappe, "get_list", return_value=["CONT-1", "CONT-2"]) as contacts:
			self.assertEqual(_calculate_static_leads("[]", "[]", '["Excluded Group"]', "Customer"), [])
			contacts.return_value = ["CONT-1"]
			self.assertEqual(_calculate_static_leads("[]", "[]", '["Excluded Group"]', "Customer"), ["CUST-1"])
