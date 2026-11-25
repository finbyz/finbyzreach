"""Tests for Inactive Customer Follow-up selection, AI drafting, queueing, preview, and SQL."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, now_datetime, today

from finbyzreach.tasks.every_4PM import inactive_customer_followup as icf
from finbyzreach.tasks.every_4PM import smart_followup


def _bind_local_state(testcase):
	"""Ensure frappe.local proxies are bound when running standalone unittest without a site."""
	missing = object()
	saved = {
		key: getattr(frappe.local, key, missing)
		for key in ("db", "flags", "session", "lang")
	}

	def _restore():
		for key, value in saved.items():
			if value is missing:
				if hasattr(frappe.local, key):
					delattr(frappe.local, key)
			else:
				setattr(frappe.local, key, value)

	testcase.addCleanup(_restore)
	if saved["db"] is missing:
		frappe.local.db = MagicMock()
	if saved["flags"] is missing:
		frappe.local.flags = frappe._dict()
	if saved["session"] is missing:
		frappe.local.session = frappe._dict(user="Administrator")
	if saved["lang"] is missing:
		frappe.local.lang = "en"


class TestInactiveCustomerFollowup(TestCase):
	def setUp(self):
		_bind_local_state(self)
		self.enterContext(patch.object(frappe, "_", side_effect=lambda value: value))
		self.enterContext(patch.object(icf, "_", side_effect=lambda value: value))
		self.enterContext(patch.object(icf, "today", return_value="2026-11-25"))

	def test_attach_emails_prefers_primary_contact_and_falls_back(self):
		rows = [
			frappe._dict(customer="CUST-1", contact_name="CONT-1", customer_email="cust1@example.com"),
			frappe._dict(customer="CUST-2", contact_name="CONT-2", customer_email="CUST2@EXAMPLE.COM "),
			frappe._dict(customer="CUST-3", contact_name=None, customer_email="Cust3@Example.com"),
		]
		contacts = [
			frappe._dict(name="CONT-1", email_id=" Primary@Example.com ", unsubscribed=0, first_name="Asha"),
			frappe._dict(name="CONT-2", email_id="", unsubscribed=0, first_name="Vikram"),
		]
		with patch.object(frappe, "get_all", return_value=contacts):
			icf.attach_emails(rows)

		self.assertEqual(rows[0].email, "primary@example.com")
		self.assertEqual(rows[0].contact_first_name, "Asha")
		self.assertEqual(rows[1].email, "cust2@example.com")
		self.assertEqual(rows[1].contact_first_name, "Vikram")
		self.assertEqual(rows[2].email, "cust3@example.com")
		self.assertIsNone(rows[2].contact_first_name)

	def test_attach_emails_skips_unsubscribed_contact_and_missing_email(self):
		rows = [
			frappe._dict(customer="CUST-UNSUB", contact_name="CONT-U", customer_email="fallback@example.com"),
			frappe._dict(customer="CUST-NONE", contact_name=None, customer_email=""),
		]
		contacts = [
			frappe._dict(name="CONT-U", email_id="unsub@example.com", unsubscribed=1, first_name="No"),
		]
		with patch.object(frappe, "get_all", return_value=contacts):
			icf.attach_emails(rows)

		self.assertIsNone(rows[0].email)
		self.assertIsNone(rows[1].email)

	def test_get_inactive_customer_followups_filters_suppressed_and_respects_limit(self):
		sql_rows = [
			frappe._dict(customer="CUST-1", contact_name="C1", customer_email=None),
			frappe._dict(customer="CUST-2", contact_name=None, customer_email="bounced@example.com"),
			frappe._dict(customer="CUST-3", contact_name=None, customer_email=""),
			frappe._dict(customer="CUST-4", contact_name=None, customer_email="ok2@example.com"),
			frappe._dict(customer="CUST-5", contact_name=None, customer_email="ok3@example.com"),
		]
		contacts = [
			frappe._dict(name="C1", email_id="ok1@example.com", unsubscribed=0, first_name="One"),
		]
		with patch.object(frappe.db, "sql", return_value=sql_rows), \
			patch.object(frappe, "get_all", return_value=contacts), \
			patch.object(icf, "suppressed_addresses", return_value={"bounced@example.com": "Hard bounce"}):
			result = icf.get_inactive_customer_followups(
				{"days": 60, "max_days": 365, "order_basis": "Sales Order", "cooldown_days": 30, "limit": 2}
			)

		self.assertEqual([r.customer for r in result], ["CUST-1", "CUST-4"])
		self.assertTrue(all(r.order_basis == "Sales Order" for r in result))

	def test_get_inactive_customer_followups_rejects_invalid_order_basis(self):
		with patch.object(frappe, "throw", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				icf.get_inactive_customer_followups({"order_basis": "Quotation", "days": 60, "limit": 10})

	def test_process_inactive_customer_empty_ai_result_does_not_send(self):
		setting = frappe._dict(
			enable_inactive_customer_followup=1,
			inactive_email_agent="Inactive Agent",
			email_account="Sales Mail",
		)
		row = {
			"customer": "CUST-1",
			"customer_name": "Acme",
			"email": "buyer@acme.test",
			"order_basis": "Sales Order",
		}
		for empty_result in (None, {}, SimpleNamespace(subject="", body="<p>Hi</p>")):
			with self.subTest(empty_result=empty_result), \
				patch.object(frappe, "get_single", return_value=setting), \
				patch.object(icf, "get_recent_items", return_value=[]), \
				patch("finbyzai.ai.agent.agent_service.AgentService") as agent_cls, \
				patch.object(icf, "make") as make_mock, \
				patch.object(frappe, "log_error") as log_error:
				agent_cls.return_value.invoke.return_value = empty_result
				icf.process_inactive_customer(row)
				make_mock.assert_not_called()
				log_error.assert_called_once()

	def test_process_inactive_customer_sends_with_dict_and_object_ai_results(self):
		setting = frappe._dict(
			enable_inactive_customer_followup=1,
			inactive_email_agent="Inactive Agent",
			email_account="Sales Mail",
		)
		row = {
			"customer": "CUST-1",
			"customer_name": "Acme Corp",
			"contact_first_name": "Sara",
			"customer_group": "Retail",
			"territory": "West",
			"last_order_date": "2026-08-01",
			"days_since_last_order": 116,
			"num_orders": 4,
			"email": "sara@acme.test",
			"order_basis": "Sales Order",
		}
		items = [frappe._dict(item_name="Widget A", qty=10, uom="Nos")]

		for ai_result in (
			{"subject": "Checking in", "body": "<p>Hello Sara</p>"},
			SimpleNamespace(subject="Checking in", body="<p>Hello Sara</p>"),
		):
			with self.subTest(ai_result=type(ai_result).__name__), \
				patch.object(frappe, "get_single", return_value=setting), \
				patch.object(icf, "get_recent_items", return_value=items), \
				patch.object(frappe.db, "get_value", side_effect=["--<br>Team", "sales@company.test"]), \
				patch("finbyzai.ai.agent.agent_service.AgentService") as agent_cls, \
				patch.object(icf, "make") as make_mock:
				agent_cls.return_value.invoke.return_value = ai_result
				icf.process_inactive_customer(row)

				invoke_kwargs = agent_cls.return_value.invoke.call_args.kwargs
				self.assertEqual(invoke_kwargs["customer_name"], "Acme Corp")
				self.assertEqual(invoke_kwargs["contact_first_name"], "Sara")
				self.assertEqual(invoke_kwargs["num_orders"], 4)
				self.assertIn("Widget A (10 Nos)", invoke_kwargs["recent_items"])
				make_mock.assert_called_once_with(
					recipients="sara@acme.test",
					subject="Checking in",
					content="<p>Hello Sara</p><br><br>--<br>Team",
					doctype="Customer",
					name="CUST-1",
					sender="sales@company.test",
					send_email=True,
				)

	def test_process_inactive_customer_logs_exception_without_raising(self):
		setting = frappe._dict(
			enable_inactive_customer_followup=1,
			inactive_email_agent="Inactive Agent",
			email_account="Sales Mail",
		)
		row = {
			"customer": "CUST-ERR",
			"email": "err@acme.test",
			"order_basis": "Sales Order",
		}
		with patch.object(frappe, "get_single", return_value=setting), \
			patch.object(icf, "get_recent_items", return_value=[]), \
			patch("finbyzai.ai.agent.agent_service.AgentService") as agent_cls, \
			patch.object(icf, "make") as make_mock, \
			patch.object(frappe, "log_error") as log_error, \
			patch.object(frappe, "get_traceback", return_value="TRACE"):
			agent_cls.return_value.invoke.side_effect = RuntimeError("LLM timeout")
			icf.process_inactive_customer(row)

		make_mock.assert_not_called()
		log_error.assert_called_once()
		self.assertIn("CUST-ERR", log_error.call_args.args[1])

	def test_process_inactive_customer_skips_when_disabled(self):
		setting = frappe._dict(enable_inactive_customer_followup=0)
		with patch.object(frappe, "get_single", return_value=setting), \
			patch.object(icf, "draft_inactive_email") as draft_mock, \
			patch.object(icf, "make") as make_mock:
			icf.process_inactive_customer({"customer": "CUST-1", "email": "a@example.com"})
		draft_mock.assert_not_called()
		make_mock.assert_not_called()

	def test_run_inactive_customer_followup_queues_long_deduplicated_jobs(self):
		setting = frappe._dict(
			enable_inactive_customer_followup=1,
			days_since_last_order=60,
			max_days_since_last_order=365,
			order_basis="Sales Order",
			followup_cooldown_days=30,
			max_inactive_per_run=50,
		)
		rows = [
			frappe._dict(customer="CUST-1", email="a@example.com"),
			frappe._dict(customer="CUST-2", email="b@example.com"),
		]
		with patch.object(icf, "get_inactive_customer_followups", return_value=rows), \
			patch.object(frappe, "enqueue") as enqueue_mock:
			res = icf.run_inactive_customer_followup(setting)

		self.assertEqual(res, {"queued": 2})
		self.assertEqual(enqueue_mock.call_count, 2)
		self.assertEqual(enqueue_mock.call_args_list[0].kwargs["queue"], "long")
		self.assertTrue(enqueue_mock.call_args_list[0].kwargs["deduplicate"])
		self.assertEqual(enqueue_mock.call_args_list[0].kwargs["job_id"], "inactive-customer-followup:CUST-1")
		self.assertEqual(enqueue_mock.call_args_list[1].kwargs["job_id"], "inactive-customer-followup:CUST-2")

	def test_run_followup_job_runs_inactive_mode_when_is_enable_is_zero(self):
		setting = frappe._dict(
			is_enable=0,
			enable_inactive_customer_followup=1,
			days_since_last_activity=5,
		)
		with patch.object(frappe, "get_single", return_value=setting), \
			patch.object(icf, "run_inactive_customer_followup", return_value={"queued": 3}) as run_inactive, \
			patch.object(smart_followup, "get_opportunity_followups") as opp_followups:
			result = smart_followup.run_followup_job()

		run_inactive.assert_called_once_with(setting)
		opp_followups.assert_not_called()
		self.assertEqual(result, {"queued": 0, "inactive_customers_queued": 3})

	def test_run_followup_job_isolates_inactive_failure_from_opportunity_followup(self):
		setting = frappe._dict(
			is_enable=1,
			enable_inactive_customer_followup=1,
			days_since_last_activity=5,
		)
		with patch.object(frappe, "get_single", return_value=setting), \
			patch.object(icf, "run_inactive_customer_followup", side_effect=RuntimeError("boom")), \
			patch.object(smart_followup, "get_opportunity_followups", return_value=[]) as opp_followups, \
			patch.object(frappe, "log_error") as log_error, \
			patch.object(frappe, "get_traceback", return_value="TRACE"):
			result = smart_followup.run_followup_job()

		log_error.assert_called_once()
		opp_followups.assert_called_once_with(5)
		self.assertEqual(result, {"queued": 0})

	def test_preview_inactive_customers_sends_nothing_and_checks_roles(self):
		with patch.object(frappe, "only_for", side_effect=frappe.PermissionError) as only_for, \
			patch.object(icf, "get_inactive_customer_followups") as get_rows:
			with self.assertRaises(frappe.PermissionError):
				icf.preview_inactive_customers()
			only_for.assert_called_once_with(("System Manager", "Social Media Manager"))
			get_rows.assert_not_called()

		setting = frappe._dict(
			enable_inactive_customer_followup=1,
			days_since_last_order=60,
			max_days_since_last_order=365,
			order_basis="Sales Order",
			followup_cooldown_days=30,
			max_inactive_per_run=50,
		)
		rows = [
			frappe._dict(
				customer="CUST-1",
				customer_name="Acme",
				email="acme@example.com",
				last_order_date=datetime.date(2026, 8, 1),
				days_since_last_order=116,
				num_orders=3,
			)
		]
		with patch.object(frappe, "only_for") as only_for, \
			patch.object(frappe, "get_single", return_value=setting), \
			patch.object(icf, "get_inactive_customer_followups", return_value=rows), \
			patch.object(icf, "make") as make_mock, \
			patch.object(frappe, "enqueue") as enqueue_mock:
			preview = icf.preview_inactive_customers()

		only_for.assert_called_once_with(("System Manager", "Social Media Manager"))
		make_mock.assert_not_called()
		enqueue_mock.assert_not_called()
		self.assertEqual(
			preview,
			[
				{
					"customer": "CUST-1",
					"customer_name": "Acme",
					"email": "acme@example.com",
					"last_order_date": datetime.date(2026, 8, 1),
					"days_since_last_order": 116,
				}
			],
		)


class TestInactiveCustomerFollowupSQL(IntegrationTestCase):
	"""DB-backed tests exercising the real MariaDB queries in inactive_customer_followup."""

	def setUp(self):
		super().setUp()
		self.tag = frappe.generate_hash(length=8)
		self.parent_group = self._ensure_customer_group(f"_Test Parent Group {self.tag}", is_group=1)
		self.child_group = self._ensure_customer_group(
			f"_Test Child Group {self.tag}", parent=self.parent_group, is_group=0
		)
		self.other_group = self._ensure_customer_group(f"_Test Other Group {self.tag}", is_group=0)

		self.parent_territory = self._ensure_territory(f"_Test Parent Territory {self.tag}", is_group=1)
		self.child_territory = self._ensure_territory(
			f"_Test Child Territory {self.tag}", parent=self.parent_territory, is_group=0
		)
		self.other_territory = self._ensure_territory(f"_Test Other Territory {self.tag}", is_group=0)

	def _ensure_customer_group(self, name, parent="All Customer Groups", is_group=0):
		if not frappe.db.exists("Customer Group", name):
			frappe.get_doc(
				{
					"doctype": "Customer Group",
					"customer_group_name": name,
					"parent_customer_group": parent,
					"is_group": is_group,
				}
			).insert(ignore_permissions=True)
		return name

	def _ensure_territory(self, name, parent="All Territories", is_group=0):
		if not frappe.db.exists("Territory", name):
			frappe.get_doc(
				{
					"doctype": "Territory",
					"territory_name": name,
					"parent_territory": parent,
					"is_group": is_group,
				}
			).insert(ignore_permissions=True)
		return name

	def _make_customer(
		self,
		suffix,
		*,
		group=None,
		territory=None,
		disabled=0,
		email=None,
		contact_email=None,
		unsubscribed=0,
	):
		cust_name = f"_Test ICF Cust {self.tag} {suffix}"
		contact_name = None
		if contact_email is not None or unsubscribed:
			contact = frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": f"First{suffix}",
					"email_id": contact_email or "",
					"unsubscribed": unsubscribed,
				}
			)
			contact.db_insert()
			contact_name = contact.name

		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"name": cust_name,
				"customer_name": cust_name,
				"customer_type": "Company",
				"customer_group": group or self.child_group,
				"territory": territory or self.child_territory,
				"disabled": disabled,
				"email_id": email,
				"customer_primary_contact": contact_name,
			}
		)
		customer.db_insert()
		return cust_name

	def _insert_sales_order(self, customer, days_ago, items=None, net_total=1000, docstatus=1):
		so_name = f"_Test ICF SO {self.tag} {frappe.generate_hash(length=6)}"
		so = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"name": so_name,
				"customer": customer,
				"transaction_date": add_days(today(), -days_ago),
				"docstatus": docstatus,
				"base_net_total": net_total,
			}
		)
		so.db_insert()
		for idx, item in enumerate(items or [("ITEM-1", "Test Item", 1, "Nos", net_total)], start=1):
			code, name, qty, uom, amt = item
			row = frappe.get_doc(
				{
					"doctype": "Sales Order Item",
					"name": f"{so_name}-I-{idx}",
					"parent": so_name,
					"parenttype": "Sales Order",
					"parentfield": "items",
					"idx": idx,
					"item_code": code,
					"item_name": name,
					"qty": qty,
					"uom": uom,
					"base_net_amount": amt,
				}
			)
			row.db_insert()
		return so_name

	def _insert_sales_invoice(self, customer, days_ago, is_return=0, items=None, net_total=1000, docstatus=1):
		si_name = f"_Test ICF SI {self.tag} {frappe.generate_hash(length=6)}"
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"name": si_name,
				"customer": customer,
				"posting_date": add_days(today(), -days_ago),
				"docstatus": docstatus,
				"is_return": is_return,
				"base_net_total": net_total,
			}
		)
		si.db_insert()
		for idx, item in enumerate(items or [("ITEM-1", "Test Item", 1, "Nos", net_total)], start=1):
			code, name, qty, uom, amt = item
			row = frappe.get_doc(
				{
					"doctype": "Sales Invoice Item",
					"name": f"{si_name}-I-{idx}",
					"parent": si_name,
					"parenttype": "Sales Invoice",
					"parentfield": "items",
					"idx": idx,
					"item_code": code,
					"item_name": name,
					"qty": qty,
					"uom": uom,
					"base_net_amount": amt,
				}
			)
			row.db_insert()
		return si_name

	def _insert_sent_email(self, customer, days_ago):
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"name": f"_Test ICF Comm {self.tag} {frappe.generate_hash(length=6)}",
				"reference_doctype": "Customer",
				"reference_name": customer,
				"communication_medium": "Email",
				"sent_or_received": "Sent",
				"communication_date": add_days(now_datetime(), -days_ago),
				"subject": "Follow-up",
				"content": "Hi",
			}
		)
		comm.db_insert()
		return comm.name

	def _base_filters(self, **overrides):
		filters = {
			"days": 60,
			"max_days": 365,
			"order_basis": "Sales Order",
			"cooldown_days": 30,
			"limit": 50,
			"customer_group": self.parent_group,
			"territory": self.parent_territory,
		}
		filters.update(overrides)
		return filters

	def test_age_threshold_max_days_and_recency_ordering(self):
		recent = self._make_customer("RECENT", contact_email="recent@example.com")
		older = self._make_customer("OLDER", contact_email="older@example.com")
		oldest = self._make_customer("OLDEST", contact_email="oldest@example.com")
		too_old = self._make_customer("TOO-OLD", contact_email="tooold@example.com")

		self._insert_sales_order(recent, 30)
		self._insert_sales_order(older, 75)
		self._insert_sales_order(oldest, 180)
		self._insert_sales_order(too_old, 400)

		rows = icf.get_inactive_customer_followups(self._base_filters())
		self.assertEqual([r.customer for r in rows], [older, oldest])

		# max_days=0 disables upper age cutoff
		rows_unlimited = icf.get_inactive_customer_followups(self._base_filters(max_days=0))
		self.assertEqual([r.customer for r in rows_unlimited], [older, oldest, too_old])

	def test_sales_invoice_credit_note_does_not_count_as_last_order(self):
		cust = self._make_customer("SI-RET", contact_email="siret@example.com")
		self._insert_sales_invoice(cust, days_ago=90, is_return=0, net_total=500)
		self._insert_sales_invoice(cust, days_ago=5, is_return=1, net_total=-500)

		rows = icf.get_inactive_customer_followups(self._base_filters(order_basis="Sales Invoice"))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].customer, cust)
		self.assertEqual(rows[0].num_orders, 1)
		self.assertEqual(getdate(rows[0].last_order_date), getdate(add_days(today(), -90)))

	def test_cooldown_excludes_recently_emailed_customer(self):
		within_cooldown = self._make_customer("COOL-IN", contact_email="in@example.com")
		outside_cooldown = self._make_customer("COOL-OUT", contact_email="out@example.com")
		self._insert_sales_order(within_cooldown, 90)
		self._insert_sales_order(outside_cooldown, 90)

		self._insert_sent_email(within_cooldown, days_ago=10)
		self._insert_sent_email(outside_cooldown, days_ago=40)

		rows = icf.get_inactive_customer_followups(self._base_filters(cooldown_days=30))
		self.assertEqual([r.customer for r in rows], [outside_cooldown])

	def test_unsubscribed_missing_email_and_suppressed_are_skipped(self):
		unsub = self._make_customer("UNSUB", email="fallback@example.com", contact_email="u@example.com", unsubscribed=1)
		no_email = self._make_customer("NOEMAIL", email=None, contact_email="")
		suppressed = self._make_customer("SUPP", contact_email="Bounced@Example.com")
		fallback_ok = self._make_customer("FALLBACK", email="Sales@Fallback.test", contact_email="")

		for cust in (unsub, no_email, suppressed, fallback_ok):
			self._insert_sales_order(cust, 80)

		supp = frappe.get_doc(
			{
				"doctype": "Email Delivery Suppression",
				"name": f"_Test Supp {self.tag}",
				"email": "bounced@example.com",
				"reason": "Hard bounce",
			}
		)
		supp.db_insert()

		rows = icf.get_inactive_customer_followups(self._base_filters())
		self.assertEqual([(r.customer, r.email) for r in rows], [(fallback_ok, "sales@fallback.test")])

	def test_disabled_customer_and_hierarchy_filters(self):
		in_child = self._make_customer("CHILD", group=self.child_group, territory=self.child_territory, contact_email="c@example.com")
		disabled = self._make_customer("DISABLED", disabled=1, contact_email="d@example.com")
		wrong_group = self._make_customer("WGRP", group=self.other_group, contact_email="wg@example.com")
		wrong_terr = self._make_customer("WTERR", territory=self.other_territory, contact_email="wt@example.com")

		for cust in (in_child, disabled, wrong_group, wrong_terr):
			self._insert_sales_order(cust, 85)

		rows = icf.get_inactive_customer_followups(self._base_filters())
		self.assertEqual([r.customer for r in rows], [in_child])

	def test_max_inactive_per_run_is_respected(self):
		customers = []
		for idx, days_ago in enumerate((70, 80, 90, 100)):
			cust = self._make_customer(f"LIM-{idx}", contact_email=f"lim{idx}@example.com")
			self._insert_sales_order(cust, days_ago)
			customers.append(cust)

		rows = icf.get_inactive_customer_followups(self._base_filters(limit=2))
		self.assertEqual([r.customer for r in rows], customers[:2])

	def test_get_recent_items_uses_last_three_non_return_orders(self):
		cust = self._make_customer("ITEMS", contact_email="items@example.com")
		# Oldest (4th) order should not be included
		self._insert_sales_order(cust, 150, items=[("OLD-ITEM", "Old Item", 5, "Nos", 9999)])
		self._insert_sales_order(cust, 100, items=[("ITEM-A", "Alpha", 2, "Kg", 200)])
		self._insert_sales_order(cust, 80, items=[("ITEM-B", "Beta", 3, "Nos", 500)])
		self._insert_sales_order(cust, 65, items=[("ITEM-A", "Alpha", 1, "Kg", 400)])

		recent_items = icf.get_recent_items(cust, "Sales Order", orders=3, limit=10)
		self.assertEqual([(i.item_code, i.qty) for i in recent_items], [("ITEM-A", 3), ("ITEM-B", 3)])

		# Sales Invoice excludes returns
		self._insert_sales_invoice(cust, 90, is_return=0, items=[("SI-A", "Invoice Item", 4, "Nos", 400)])
		self._insert_sales_invoice(cust, 10, is_return=1, items=[("RET-X", "Return Item", -1, "Nos", -100)])
		si_items = icf.get_recent_items(cust, "Sales Invoice", orders=3, limit=10)
		self.assertEqual([i.item_code for i in si_items], ["SI-A"])

	def test_preview_inactive_customers_db_sends_nothing_and_checks_role(self):
		cust = self._make_customer("PREV", contact_email="prev@example.com")
		self._insert_sales_order(cust, 95)

		setting = frappe.get_single("Lead Followup Setting")
		setting.enable_inactive_customer_followup = 1
		setting.days_since_last_order = 60
		setting.max_days_since_last_order = 365
		setting.order_basis = "Sales Order"
		setting.followup_cooldown_days = 30
		setting.max_inactive_per_run = 50
		setting.inactive_customer_group = self.parent_group
		setting.inactive_territory = self.parent_territory
		setting.flags.ignore_mandatory = True
		setting.save(ignore_permissions=True)

		with patch.object(icf, "make") as make_mock, patch.object(frappe, "enqueue") as enqueue_mock:
			rows = icf.preview_inactive_customers()

		make_mock.assert_not_called()
		enqueue_mock.assert_not_called()
		self.assertEqual([r["customer"] for r in rows], [cust])
		self.assertEqual(rows[0]["email"], "prev@example.com")

		user = f"_test_icf_denied_{self.tag}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": "Denied",
				"roles": [{"role": "Sales User"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				icf.preview_inactive_customers()
		finally:
			frappe.set_user("Administrator")
