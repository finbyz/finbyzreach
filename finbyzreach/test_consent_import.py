"""Bulk consent import: file parsing, row decisions and the background write path."""
import time
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from finbyzreach import consent_import as ci
from finbyzreach.subscription_preferences import PREFERENCE_DOCTYPE, _save, preference_name

TOPIC = "_CI Test Mailing"
TOPIC_B = "_CI Test Topic"


def records(text):
	return ci.parse_table(ci.read_table(text.encode("utf-8-sig"), "people.csv"))[1]


class TestConsentImportParsing(TestCase):
	def test_semicolon_csv_with_bom_and_german_headers(self):
		meta, rows = ci.parse_table(ci.read_table("﻿E-Mail;Thema;Datum;Quelle;Sprache\nA@Example.com;Marketing;14.03.2025;Messe;Deutsch\n\n".encode(), "x.csv"))
		self.assertEqual(meta["columns"], ["email", "language", "opted_in_on", "source", "topic"])
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["row"], 2)
		self.assertEqual(rows[0]["email"], "A@Example.com")
		self.assertEqual(ci._parse_date(rows[0]["opted_in_on"]), datetime(2025, 3, 14))
		self.assertEqual(ci._language(rows[0]["language"], None), "de")

	def test_cp1252_file_is_read(self):
		rows = ci.parse_table(ci.read_table("Email,Source\nb@example.com,Zürich Messe\n".encode("cp1252"), "x.csv"))[1]
		self.assertEqual(rows[0]["source"], "Zürich Messe")

	def test_file_without_email_or_record_column_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			ci.parse_table([["Name", "Topic"], ["Anna", "Marketing"]])

	def test_row_limit(self):
		with patch.object(ci, "MAX_ROWS", 2), self.assertRaises(frappe.ValidationError):
			ci.parse_table([["Email"], ["a@example.com"], ["b@example.com"], ["c@example.com"]])

	def test_dates_and_languages(self):
		for value in ("2025-03-14", "14.03.2025", "14/03/2025", "2025-03-14 10:30"):
			self.assertEqual(ci._parse_date(value).date(), datetime(2025, 3, 14).date())
		with self.assertRaises(ValueError):
			ci._parse_date("March 14")
		with self.assertRaises(ValueError):
			ci._language("Klingon", "de")
		self.assertEqual(ci._language("", "fr"), "fr")


class ConsentImportDB(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for name, category in ((TOPIC, "Mailing Type"), (TOPIC_B, "Topic")):
			if not frappe.db.exists("Subscription Topic", name):
				frappe.get_doc({"doctype": "Subscription Topic", "topic_name": name, "category": category, "description": "Test consent"}).insert()

	def tearDown(self):
		frappe.db.rollback()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()


class TestConsentImportPlan(ConsentImportDB):
	def plan(self, text, **kwargs):
		kwargs.setdefault("consent_source", "Trade fair")
		return ci.plan(records(text), **kwargs)

	def test_row_outcomes(self):
		items = self.plan(
			"Email,Topic\n"
			"bad-address,%s\n"
			"one@example.com,Nope\n"
			"two@example.com,Transactional\n"
			"three@example.com,%s | %s\n"
			"THREE@example.com,%s\n" % (TOPIC, TOPIC, TOPIC_B.lower(), TOPIC))
		outcome = [(item["row"], item["topic"], item["action"]) for item in items]
		self.assertIn((2, "", ci.FAIL), outcome)
		self.assertIn((3, "Nope", ci.FAIL), outcome)
		self.assertIn((4, "Transactional", ci.FAIL), outcome)
		self.assertIn((5, TOPIC, ci.SUBSCRIBE), outcome)
		self.assertIn((5, TOPIC_B, ci.SUBSCRIBE), outcome)
		self.assertIn((6, TOPIC, ci.SKIP), outcome)
		self.assertTrue(next(i for i in items if i["row"] == 5)["note"].startswith("No Lead or Contact"))

	def test_default_topics_and_missing_topic(self):
		items = self.plan("Email\nfour@example.com\n", default_topics=[TOPIC])
		self.assertEqual([(i["topic"], i["action"]) for i in items], [(TOPIC, ci.SUBSCRIBE)])
		items = self.plan("Email\nfour@example.com\n")
		self.assertEqual(items[0]["action"], ci.FAIL)

	def test_existing_status_wins_unless_opt_in_is_newer(self):
		_save("five@example.com", TOPIC, "Subscribed", "Earlier")
		_save("six@example.com", TOPIC, "Unsubscribed", "Earlier")
		frappe.db.set_value(PREFERENCE_DOCTYPE, preference_name("six@example.com", TOPIC), "unsubscribed_on", datetime(2025, 6, 1))
		future = (now_datetime() + timedelta(days=2)).strftime("%Y-%m-%d")
		items = self.plan(f"Email,Topic,Opted in on\nfive@example.com,{TOPIC},\nsix@example.com,{TOPIC},2025-01-01\n"
			f"six@example.com,{TOPIC},2025-07-01\nseven@example.com,{TOPIC},{future}\n")
		actions = {(i["row"]): (i["action"], i["reason"]) for i in items}
		self.assertEqual(actions[2], (ci.SKIP, "Already subscribed"))
		self.assertEqual(actions[3][0], ci.SKIP)
		self.assertEqual(actions[4][0], ci.SKIP)  # same email and topic as row 3
		self.assertEqual(actions[5][0], ci.FAIL)
		items = self.plan(f"Email,Topic,Opted in on\nsix@example.com,{TOPIC},2025-07-01\n")
		self.assertEqual(items[0]["action"], ci.SUBSCRIBE)

	def test_suppressed_address_is_skipped(self):
		with patch("finbyzreach.consent.suppressed_addresses", return_value={"eight@example.com": "Hard bounce"}):
			items = self.plan(f"Email,Topic\neight@example.com,{TOPIC}\n")
		self.assertEqual(items[0]["action"], ci.SKIP)

	def test_record_columns_resolve_email(self):
		lead = frappe.get_doc({"doctype": "Lead", "first_name": "Import", "last_name": "Test", "email_id": "lead.import@example.com"}).insert(ignore_permissions=True)
		items = self.plan(f"Record type,Record,Topic\nLead,{lead.name},{TOPIC}\nLead,MISSING-LEAD,{TOPIC}\nItem,X,{TOPIC}\n")
		self.assertEqual((items[0]["email"], items[0]["action"], items[0].get("note")), ("lead.import@example.com", ci.SUBSCRIBE, None))
		self.assertEqual(items[1]["action"], ci.FAIL)
		self.assertEqual(items[2]["action"], ci.FAIL)

	def test_twenty_thousand_rows_plan_quickly(self):
		text = "Email,Topic,Opted in on\n" + "".join(f"bulk{i}@example.com,{TOPIC},2025-01-01\n" for i in range(20000))
		started = time.monotonic()
		items = self.plan(text)
		elapsed = time.monotonic() - started
		self.assertEqual(sum(1 for i in items if i["action"] == ci.SUBSCRIBE), 20000, items[0]["reason"])
		self.assertLess(elapsed, 30, f"planning 20k rows took {elapsed:.1f}s")


class TestConsentImportRun(ConsentImportDB):
	def make_run(self, text, **values):
		values = {"doctype": ci.DOCTYPE, "import_file": "/private/files/test.csv", "consent_source": "Swissbau 2025", **values}
		doc = frappe.get_doc(values).insert()
		return doc, patch.object(ci, "_file_content", return_value=(text.encode(), "test.csv"))

	def test_run_writes_confirmed_consent_with_log_and_opt_in_date(self):
		doc, content = self.make_run(f"Email,Topic,Opted in on,Language\nnine@example.com,{TOPIC},2025-03-14,de\nbad,{TOPIC},,\n")
		doc.db_set("status", "Queued")
		with content, patch.object(ci, "_attach_result") as attach:
			ci.run(doc.name)
		doc.reload()
		self.assertEqual((doc.status, doc.subscribed, doc.skipped, doc.failed, doc.total_rows), ("Completed", 1, 0, 1, 2))
		pref = frappe.get_doc(PREFERENCE_DOCTYPE, preference_name("nine@example.com", TOPIC))
		self.assertEqual(pref.status, "Subscribed")
		self.assertEqual(pref.confirmed_on, datetime(2025, 3, 14))
		self.assertEqual(pref.consent_source, f"Import {doc.name} (2025-03-14): Swissbau 2025")
		self.assertTrue(pref.consent_text)
		event = frappe.get_all("Email Subscription Event", filters={"email": "nine@example.com", "subscription_topic": TOPIC}, fields=["status", "source"])
		self.assertEqual(event[0].status, "Subscribed")
		self.assertTrue(event[0].source.startswith(f"Import {doc.name}"))
		attach.assert_called_once()

	def test_run_only_starts_from_queued_and_failure_is_recorded(self):
		doc, content = self.make_run(f"Email,Topic\nten@example.com,{TOPIC}\n")
		with content:
			ci.run(doc.name)  # still Draft
		self.assertFalse(frappe.db.exists(PREFERENCE_DOCTYPE, preference_name("ten@example.com", TOPIC)))
		doc.db_set("status", "Queued")
		with patch.object(ci, "_file_content", side_effect=RuntimeError("disk gone")), self.assertRaises(RuntimeError):
			ci.run(doc.name)

	def test_a_failing_row_does_not_stop_the_others(self):
		from finbyzreach import subscription_preferences
		doc, content = self.make_run(f"Email,Topic\neleven@example.com,{TOPIC}\ntwelve@example.com,{TOPIC}\n")
		doc.db_set("status", "Queued")
		original = subscription_preferences._save

		def flaky(email, *args, **kwargs):
			if email == "eleven@example.com":
				raise frappe.ValidationError("boom")
			return original(email, *args, **kwargs)

		with content, patch.object(ci, "_attach_result"), patch.object(subscription_preferences, "_save", side_effect=flaky):
			ci.run(doc.name)
		doc.reload()
		self.assertEqual((doc.status, doc.subscribed, doc.failed), ("Completed", 1, 1))
		self.assertTrue(frappe.db.exists(PREFERENCE_DOCTYPE, preference_name("twelve@example.com", TOPIC)))

	def test_started_import_cannot_be_edited(self):
		doc, _content = self.make_run("Email\nx@example.com\n")
		doc.db_set("status", "Completed")
		doc.reload()
		doc.consent_source = "Changed"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_result_file_lists_every_row_and_topic(self):
		items = [dict(row=2, record="", email="a@example.com", topic=TOPIC, action=ci.SUBSCRIBE, reason="", opted_in_on=datetime(2025, 3, 14)),
			dict(row="Lead L-1", record="L-1", email="b@example.com", topic=TOPIC_B, action=ci.SKIP, reason="Already subscribed")]
		doc = frappe._dict(name="CI-TEST")
		captured = {}

		class FakeFile:
			file_url = "/private/files/CI-TEST-result.csv"

			def insert(self, **kwargs):
				return self

		def fake_get_doc(values):
			captured.update(values)
			return FakeFile()

		doc.db_set = lambda *args, **kwargs: None
		with patch.object(ci.frappe, "get_doc", side_effect=fake_get_doc):
			ci._attach_result(doc, items)
		text = captured["content"].decode("utf-8-sig").splitlines()
		self.assertEqual(text[0], "Row,Record,Email,Topic,Opted in on,Outcome,Reason,Note")
		self.assertEqual(text[1], f"2,,a@example.com,{TOPIC},2025-03-14,Subscribed,,")
		self.assertIn("Lead L-1,L-1,b@example.com", text[2])


class TestConsentImportLeads(ConsentImportDB):
	def lead(self, email, **values):
		return frappe.get_doc({"doctype": "Lead", "first_name": "Consent", "last_name": "Import", "email_id": email, **values}).insert(ignore_permissions=True)

	def test_selected_leads_without_file_are_imported_with_default_date(self):
		one, two = self.lead("lead.one@example.com"), self.lead("lead.two@example.com")
		doc = frappe.get_doc({"doctype": ci.DOCTYPE, "consent_source": "Signed order form", "leads": f"{one.name}\n{two.name}\n{one.name}",
			"default_topics": TOPIC, "default_opted_in_on": "2025-05-02"}).insert()
		doc.db_set("status", "Queued")
		with patch.object(ci, "_attach_result"):
			ci.run(doc.name)
		doc.reload()
		self.assertEqual((doc.status, doc.total_rows, doc.subscribed), ("Completed", 2, 2))
		pref = frappe.get_doc(PREFERENCE_DOCTYPE, preference_name("lead.two@example.com", TOPIC))
		self.assertEqual((pref.status, pref.confirmed_on), ("Subscribed", datetime(2025, 5, 2)))
		self.assertTrue(pref.consent_source.startswith(f"Import {doc.name} (2025-05-02): Signed order form"))

	def test_opted_out_lead_is_skipped(self):
		lead = self.lead("lead.out@example.com")
		frappe.db.set_value("Lead", lead.name, "status", "Do Not Contact")
		items = ci.plan(ci.lead_records([lead.name]), consent_source="x", default_topics=[TOPIC])
		self.assertEqual((items[0]["action"], items[0]["email"]), (ci.SKIP, "lead.out@example.com"))

	def test_settings_need_file_or_leads_and_topics_for_leads(self):
		doc = frappe._dict(consent_source="x", import_file=None, leads="", contacts="", customers="", default_topics="", default_opted_in_on=None)
		with self.assertRaises(frappe.ValidationError):
			ci._validate_settings(doc)
		doc.leads = "CRM-LEAD-1"
		with self.assertRaises(frappe.ValidationError):
			ci._validate_settings(doc)
		doc.default_topics = TOPIC
		ci._validate_settings(doc)
		doc.default_opted_in_on = (now_datetime() + timedelta(days=3)).date()
		with self.assertRaises(frappe.ValidationError):
			ci._validate_settings(doc)

	def test_check_with_leads_only_saves_a_draft(self):
		lead = self.lead("lead.check@example.com")
		result = ci.check(consent_source="Phone call", leads=f'["{lead.name}"]', default_topics=f'["{TOPIC}"]')
		self.assertEqual((result["total_rows"], result["subscribe"], result["fail"]), (1, 1, 0))
		doc = frappe.get_doc(ci.DOCTYPE, result["name"])
		self.assertEqual((doc.status, doc.leads, doc.import_file), ("Draft", lead.name, None))

	def test_example_file_imports_cleanly_with_site_topics(self):
		self.lead("lead.example@example.com")
		text = ci.template()
		items = ci.plan(records(text), consent_source="Example")
		self.assertEqual([i["action"] for i in items if i["action"] == ci.FAIL], [])
		self.assertGreaterEqual(sum(1 for i in items if i["action"] == ci.SUBSCRIBE), 4)


class TestConsentImportContactsAndCustomers(ConsentImportDB):
	def contact(self, email, customer=None, **values):
		doc = frappe.get_doc({"doctype": "Contact", "first_name": "Opt", "last_name": email.split("@")[0], **values,
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"links": [{"link_doctype": "Customer", "link_name": customer}] if customer else []})
		return doc.insert(ignore_permissions=True)

	def customer(self, name):
		return frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_type": "Company"}).insert(ignore_permissions=True)

	def plan(self, doctype, names, **kwargs):
		return ci.plan(ci.selected_records(doctype, names), consent_source="x", default_topics=[TOPIC], **kwargs)

	def test_contact_uses_primary_email_and_skips_unsubscribed(self):
		one = self.contact("contact.one@example.com")
		out = self.contact("contact.out@example.com", unsubscribed=1)
		items = self.plan("Contact", [one.name, out.name, "NO-SUCH-CONTACT"])
		self.assertEqual([(i["email"], i["action"]) for i in items],
			[("contact.one@example.com", ci.SUBSCRIBE), ("contact.out@example.com", ci.SKIP), ("", ci.FAIL)])
		self.assertEqual(items[0]["record"], f"Contact {one.name}")

	def test_customer_primary_or_all_contacts(self):
		customer = self.customer("_Opt-in Import Test AG")
		primary = self.contact("primary.ci@example.com", customer.name)
		self.contact("second.ci@example.com", customer.name)
		frappe.db.set_value("Customer", customer.name, "customer_primary_contact", primary.name)
		items = self.plan("Customer", [customer.name])
		self.assertEqual([(i["email"], i["action"]) for i in items], [("primary.ci@example.com", ci.SUBSCRIBE)])
		self.assertEqual(items[0]["record"], f"Customer {customer.name} / Contact {primary.name}")
		items = self.plan("Customer", [customer.name], customer_contacts=ci.ALL_CONTACTS)
		self.assertEqual(sorted(i["email"] for i in items if i["action"] == ci.SUBSCRIBE), ["primary.ci@example.com", "second.ci@example.com"])

	def test_customer_without_contacts_or_disabled(self):
		empty = self.customer("_Opt-in Import Empty AG")
		items = self.plan("Customer", [empty.name])
		self.assertEqual(items[0]["action"], ci.FAIL)
		frappe.db.set_value("Customer", empty.name, "disabled", 1)
		items = self.plan("Customer", [empty.name])
		self.assertEqual((items[0]["action"], items[0]["reason"]), (ci.SKIP, "Customer is disabled"))

	def test_email_unsubscribe_records_are_respected(self):
		contact = self.contact("ref.out@example.com")
		frappe.get_doc({"doctype": "Email Unsubscribe", "email": "ref.out@example.com", "reference_doctype": "Contact", "reference_name": contact.name}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Email Unsubscribe", "email": "global.out@example.com", "global_unsubscribe": 1}).insert(ignore_permissions=True)
		items = self.plan("Contact", [contact.name])
		self.assertEqual(items[0]["action"], ci.SKIP)
		items = ci.plan(records(f"Email,Topic\nglobal.out@example.com,{TOPIC}\n"), consent_source="x")
		self.assertEqual((items[0]["action"], items[0]["reason"]), (ci.SKIP, "Globally unsubscribed"))

	def test_run_imports_selected_contacts_and_customers(self):
		customer = self.customer("_Opt-in Import Run AG")
		primary = self.contact("run.primary@example.com", customer.name)
		frappe.db.set_value("Customer", customer.name, "customer_primary_contact", primary.name)
		contact = self.contact("run.contact@example.com")
		doc = frappe.get_doc({"doctype": ci.DOCTYPE, "consent_source": "Fair", "contacts": contact.name, "customers": customer.name,
			"default_topics": TOPIC}).insert()
		doc.db_set("status", "Queued")
		with patch.object(ci, "_attach_result"):
			ci.run(doc.name)
		doc.reload()
		self.assertEqual((doc.status, doc.total_rows, doc.subscribed), ("Completed", 2, 2))
		for email in ("run.primary@example.com", "run.contact@example.com"):
			self.assertEqual(frappe.db.get_value(PREFERENCE_DOCTYPE, preference_name(email, TOPIC), "status"), "Subscribed")


class TestConsentImportFilters(TestConsentImportLeads):
	COMPANY = "_Opt-in Filter Test GmbH"

	def filtered_leads(self):
		return [self.lead(f"filter.{n}@example.com", company_name=self.COMPANY) for n in range(3)]

	def test_filter_selects_matching_records_only(self):
		leads = self.filtered_leads()
		self.lead("filter.other@example.com", company_name="_Someone else")
		filters = [["Lead", "company_name", "=", self.COMPANY]]
		self.assertEqual(sorted(ci.filtered_names("Lead", filters)), sorted(lead.name for lead in leads))
		self.assertEqual(ci.count_records("Lead", frappe.as_json(filters)), {"count": 3, "limit": ci.MAX_ROWS, "with_email": 3})

	def test_filter_rejects_other_doctypes_bad_filters_and_too_many_matches(self):
		with self.assertRaises(frappe.ValidationError):
			ci.filtered_names("User", [])
		with self.assertRaises(frappe.ValidationError):
			ci._filter_list('"company_name"')
		self.filtered_leads()
		with patch.object(ci, "MAX_ROWS", 2), self.assertRaises(frappe.ValidationError):
			ci.filtered_names("Lead", [["Lead", "company_name", "=", self.COMPANY]])

	def test_check_and_run_with_filter_and_overlapping_pick(self):
		leads = self.filtered_leads()
		filters = frappe.as_json([["Lead", "company_name", "=", self.COMPANY]])
		result = ci.check(consent_source="Fair list", filter_doctype="Lead", record_filters=filters,
			leads=f'["{leads[0].name}"]', default_topics=f'["{TOPIC}"]')
		self.assertEqual((result["total_rows"], result["subscribe"], result["skip"], result["fail"]), (3, 3, 0, 0))
		doc = frappe.get_doc(ci.DOCTYPE, result["name"])
		self.assertEqual((doc.filter_doctype, frappe.parse_json(doc.record_filters)), ("Lead", frappe.parse_json(filters)))
		doc.db_set("status", "Queued")
		with patch.object(ci, "_attach_result"):
			ci.run(doc.name)
		doc.reload()
		self.assertEqual((doc.status, doc.subscribed), ("Completed", 3))
		self.assertEqual(frappe.db.get_value(PREFERENCE_DOCTYPE, preference_name("filter.2@example.com", TOPIC), "status"), "Subscribed")

	def test_filter_alone_needs_topics(self):
		with self.assertRaises(frappe.ValidationError):
			ci.check(consent_source="x", filter_doctype="Lead", record_filters="[]")
