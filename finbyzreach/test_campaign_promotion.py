"""Promotion builds the CRM records in the shape frame 8 asks for.

The rules being held to here are Megasol's, agreed on the CRM board:

  - one Lead per person, not per firm;
  - a Prospect as soon as there are company details, with every Lead at that
	firm listed on it;
  - a repeat enquiry logged on the Lead that already exists;
  - a Contact that keeps its links when the person turns up again;
  - nobody emailed who has opted out.
"""

import frappe
from frappe.tests import UnitTestCase

from finbyzreach.ai_email_outreach import campaign_promotion as promotion

COMPANY = "Hartmann Metallbau AG"
PROJECT = "TEST-PROMO-1"


def candidate(**kwargs):
	"""A Campaign Candidate's values without the record, which needs a campaign."""
	values = {
		"party_type": "Contact",
		"recipient_name": "",
		"email": "",
		"company": None,
		"contact": None,
		"project": None,
		"project_title": "",
		"role": "",
		"town": "",
		"planstage_name": "",
		"has_solar": 0,
	}
	values.update(kwargs)
	return frappe._dict(values)


class TestPromotionShape(UnitTestCase):
	"""Frame 8's record shape, built from Infomanager source records."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.purge()
		cls.company = frappe.get_doc({
			"doctype": "Infomanager Company",
			"external_id": "TEST-CO-1",
			"name1": COMPANY,
			"town": "Olten",
			"postcode": "4600",
			"phone": "062 555 11 22",
			"website": "https://hartmann-metallbau.example",
		}).insert(ignore_permissions=True)

		cls.anna = frappe.get_doc({
			"doctype": "Infomanager Contact",
			"external_id": "TEST-PE-1",
			"first_name": "Anna",
			"last_name": "Hartmann",
			"full_name": "Anna Hartmann",
			"salutation_label": "Frau",
			"email": "anna.hartmann@example.ch",
			"mobile_phone": "079 555 00 11",
			"company": cls.company.name,
			"active": 1,
		}).insert(ignore_permissions=True)

		cls.beat = frappe.get_doc({
			"doctype": "Infomanager Contact",
			"external_id": "TEST-PE-2",
			"first_name": "Beat",
			"last_name": "Suter",
			"full_name": "Beat Suter",
			"salutation_label": "Herr",
			"email": "beat.suter@example.ch",
			"company": cls.company.name,
			"active": 1,
		}).insert(ignore_permissions=True)

		frappe.get_doc({
			"doctype": "Infomanager Project",
			"external_id": PROJECT,
			"title": "Neubau Werkhalle",
		}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.purge()
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		self.purge_crm()

	tearDown = setUp

	@classmethod
	def purge_crm(cls):
		"""Drop the CRM records, leaving the Infomanager source records in place.

		Run before and after every test, because nothing here is rolled back.
		The Prospect is named after the company and the Leads are listed on it,
		so a Prospect left behind silently adopts the next test's Leads and
		makes the row counts meaningless - as does a Lead left behind, which the
		next test reuses instead of building the one it meant to assert on.
		"""
		# The source records point at the CRM records, so the links are released
		# first - a Prospect still named on a Company cannot be deleted.
		if frappe.db.exists("Infomanager Company", "TEST-CO-1"):
			frappe.db.set_value("Infomanager Company", "TEST-CO-1",
								{"lead": None, "prospect": None}, update_modified=False)
		for person in ("TEST-PE-1", "TEST-PE-2"):
			if frappe.db.exists("Infomanager Contact", person):
				frappe.db.set_value("Infomanager Contact", person, "contact", None,
									update_modified=False)

		for email in ("anna.hartmann@example.ch", "beat.suter@example.ch", "info@hartmann.example"):
			for contact in frappe.get_all("Contact", filters={"email_id": email}, pluck="name"):
				frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True,
								  delete_permanently=True)
			for lead in frappe.get_all("Lead", filters={"email_id": email}, pluck="name"):
				frappe.delete_doc("Lead", lead, force=True, ignore_permissions=True,
								  delete_permanently=True)
		if frappe.db.exists("Prospect", COMPANY):
			frappe.delete_doc("Prospect", COMPANY, force=True, ignore_permissions=True,
							  delete_permanently=True)
		frappe.db.commit()

	@classmethod
	def purge(cls):
		"""Remove everything these tests create, in dependency order."""
		cls.purge_crm()
		for email in ("anna.hartmann@example.ch", "beat.suter@example.ch", "info@hartmann.example"):
			for contact in frappe.get_all("Contact", filters={"email_id": email}, pluck="name"):
				frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True,
								  delete_permanently=True)
			for lead in frappe.get_all("Lead", filters={"email_id": email}, pluck="name"):
				frappe.delete_doc("Lead", lead, force=True, ignore_permissions=True,
								  delete_permanently=True)
		if frappe.db.exists("Prospect", COMPANY):
			frappe.delete_doc("Prospect", COMPANY, force=True, ignore_permissions=True,
							  delete_permanently=True)
		for doctype, name in (
			("Infomanager Contact", "TEST-PE-1"),
			("Infomanager Contact", "TEST-PE-2"),
			("Infomanager Company", "TEST-CO-1"),
			("Infomanager Project", PROJECT),
		):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
								  delete_permanently=True)

	def promote_person(self, person, project=None):
		"""Everything promotion does for one person, short of research and email."""
		row = candidate(
			party_type="Contact",
			recipient_name=person.full_name,
			email=person.email,
			contact=person.name,
			company=self.company.name,
			project=project,
			project_title="Neubau Werkhalle" if project else "",
		)
		source_person, source_company = promotion.source_records(row)
		existing = promotion.find_existing_lead(row, source_person)
		if existing:
			lead = promotion.refresh_lead(frappe.get_doc("Lead", existing), source_person, source_company)
		else:
			lead = promotion.build_lead(row, source_person, source_company)
		lead = promotion.log_inquiry(lead, row)
		prospect = promotion.ensure_prospect(source_company, lead)
		contact = promotion.ensure_contact(row, lead, prospect, source_person, source_company)
		return lead, prospect, contact

	def test_a_person_becomes_a_person_lead_not_a_company_lead(self):
		lead, prospect, contact = self.promote_person(self.anna)

		self.assertEqual(lead.first_name, "Anna")
		self.assertEqual(lead.last_name, "Hartmann")
		self.assertEqual(lead.salutation, "Frau")
		# The firm is the organisation on the Lead, never the Lead's own name.
		self.assertEqual(lead.company_name, COMPANY)
		self.assertNotEqual(lead.lead_name, COMPANY)
		self.assertEqual(lead.utm_source, promotion.LEAD_SOURCE)
		self.assertEqual(lead.custom_infomanager_contact_id, self.anna.name)
		self.assertEqual(lead.custom_infomanager_company_id, self.company.name)
		self.assertEqual(lead.custom_infomanager_status, "Active")
		self.assertEqual(lead.custom_postal_code, "4600")

		self.assertEqual(prospect.name, COMPANY)
		self.assertEqual(prospect.website, "https://hartmann-metallbau.example")

		links = {(l.link_doctype, l.link_name) for l in contact.links}
		self.assertIn(("Lead", lead.name), links)
		self.assertIn(("Prospect", prospect.name), links)
		self.assertEqual(contact.custom_infomanager_contact_id, self.anna.name)

	def test_the_prospect_is_written_back_to_the_infomanager_company(self):
		self.promote_person(self.anna)
		self.assertEqual(
			frappe.db.get_value("Infomanager Company", self.company.name, "prospect"), COMPANY
		)

	def test_two_people_at_one_firm_are_two_leads_on_one_prospect(self):
		anna_lead, prospect, __ = self.promote_person(self.anna)
		beat_lead, prospect, __ = self.promote_person(self.beat)

		self.assertNotEqual(anna_lead.name, beat_lead.name)
		listed = {row.lead for row in prospect.leads}
		self.assertIn(anna_lead.name, listed)
		self.assertIn(beat_lead.name, listed)
		self.assertEqual(frappe.db.count("Prospect", {"company_name": COMPANY}), 1)

	def test_a_repeat_enquiry_stays_on_the_same_lead(self):
		first, __, first_contact = self.promote_person(self.anna, project=PROJECT)
		second, __, second_contact = self.promote_person(self.anna, project=PROJECT)

		self.assertEqual(first.name, second.name)
		self.assertEqual(first_contact.name, second_contact.name)
		self.assertEqual(second.custom_inquiry_count, 2)
		self.assertTrue(second.custom_last_inquiry_on)
		self.assertEqual(second.custom_infomanager_projects, PROJECT)
		# The project is logged once, not once per promotion.
		self.assertEqual(second.custom_infomanager.count(PROJECT), 1)
		# And the person keeps the single Contact, with its links intact.
		links = {(l.link_doctype, l.link_name) for l in second_contact.links}
		self.assertIn(("Lead", second.name), links)
		self.assertIn(("Prospect", COMPANY), links)

	def test_a_hand_corrected_lead_is_not_overwritten_by_the_feed(self):
		lead, __, __ = self.promote_person(self.anna)
		frappe.db.set_value("Lead", lead.name, {
			"first_name": "Anna-Maria",
			"custom_base_data_manipulated": 1,
		}, update_modified=False)

		again, __, __ = self.promote_person(self.anna)
		self.assertEqual(again.first_name, "Anna-Maria")

	def test_a_firm_without_a_named_person_keeps_its_own_shape(self):
		row = candidate(
			party_type="Company",
			recipient_name=COMPANY,
			email="info@hartmann.example",
			company=self.company.name,
		)
		person, company = promotion.source_records(row)
		self.assertIsNone(person)

		lead = promotion.build_lead(row, person, company)
		prospect = promotion.ensure_prospect(company, lead)

		# No person was delivered, so none is invented. Left to itself ERPNext
		# would split the firm into a Herr Hartmann with the surname AG.
		self.assertEqual(lead.first_name, COMPANY)
		self.assertFalse(lead.last_name)
		self.assertFalse(lead.middle_name)
		self.assertEqual(lead.company_name, COMPANY)
		self.assertEqual(prospect.name, COMPANY)

	def test_a_person_is_never_matched_to_their_employers_lead(self):
		"""The company's Lead must not swallow a colleague who shares the firm."""
		row = candidate(
			party_type="Company",
			recipient_name=COMPANY,
			email="info@hartmann.example",
			company=self.company.name,
		)
		__, company = promotion.source_records(row)
		company_lead = promotion.build_lead(row, None, company)
		frappe.db.set_value("Infomanager Company", self.company.name, "lead", company_lead.name,
							update_modified=False)

		person_row = candidate(
			party_type="Contact",
			recipient_name=self.beat.full_name,
			email=self.beat.email,
			contact=self.beat.name,
			company=self.company.name,
		)
		person, __ = promotion.source_records(person_row)
		self.assertIsNone(promotion.find_existing_lead(person_row, person))


class TestPromotionOptOut(UnitTestCase):
	"""An opted-out address is skipped, not promoted."""

	EMAIL = "optout.promotion@example.ch"

	def setUp(self):
		for lead in frappe.get_all("Lead", filters={"email_id": self.EMAIL}, pluck="name"):
			frappe.delete_doc("Lead", lead, force=True, ignore_permissions=True,
							  delete_permanently=True)

	tearDown = setUp

	def test_an_unsubscribed_lead_blocks_promotion(self):
		lead = frappe.get_doc({
			"doctype": "Lead",
			"first_name": "Opted",
			"last_name": "Out",
			"email_id": self.EMAIL,
			"status": "Lead",
			"unsubscribed": 1,
		}).insert(ignore_permissions=True)
		self.assertTrue(lead.name)
		self.assertTrue(promotion.opt_out_reason(self.EMAIL))

	def test_a_do_not_contact_lead_blocks_promotion(self):
		frappe.get_doc({
			"doctype": "Lead",
			"first_name": "Do Not",
			"last_name": "Contact",
			"email_id": self.EMAIL,
			"status": "Do Not Contact",
		}).insert(ignore_permissions=True)
		self.assertEqual(promotion.opt_out_reason(self.EMAIL), "Do Not Contact")

	def test_a_clean_address_is_not_blocked(self):
		self.assertIsNone(promotion.opt_out_reason("never.seen.before@example.ch"))
