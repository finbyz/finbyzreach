# Copyright (c) 2025, Finbyz Tech Pvt Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from finbyzreach.ai_email_outreach.doctype.outbound_email.outbound_email import get_schedule_objective



class TestoutboundEmail(FrappeTestCase):
	def test_schedule_objective_forwards_branch_condition(self):
		schedule = frappe._dict(
			description="Send a case study",
			send_after=2,
			custom_branch_condition="Opened Not Clicked",
		)

		self.assertEqual(
			get_schedule_objective(schedule, 2),
			"Email 2. Send a case study (Send After: 2 days, Branch Condition: Opened Not Clicked)\n",
		)

	def test_schedule_objective_works_without_custom_branch_field(self):
		schedule = frappe._dict(description="Introduce the company", send_after=0)

		self.assertEqual(
			get_schedule_objective(schedule, 1),
			"Email 1. Introduce the company (Send After: 0 days)\n",
		)
