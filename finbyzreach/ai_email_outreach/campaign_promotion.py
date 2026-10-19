"""Turning approved candidates into CRM records and starting their outreach.

The shape follows frame 8 of the CRM board and the decisions agreed with
Megasol, not the shape of the Baublatt feed:

  - the **Lead** is a person. First name, last name, salutation, email.
  - the **Prospect** is the organisation. It is created as soon as there are
	company details, and every Lead at that firm is listed on it.
  - the **Contact** carries the address and links to both, which is what keeps
	one person joined to several projects instead of duplicated across them.

A person already in the CRM is reused rather than duplicated, and the repeat
enquiry is logged on the Lead that is already there.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, today

CANDIDATE = "Campaign Candidate"

# Aaron's rule is that an imported record becomes a Lead only through the
# selection step, and that the Lead says so. ERPNext dropped Lead.source in
# favour of `utm_source`, a Link to UTM Source - frame 8 keeps it and asks for
# it to be set everywhere - so that is where the provenance goes.
LEAD_SOURCE = "InfoManager"


def ensure_lead_source():
	"""The UTM Source every promoted Lead is stamped with, created on demand."""
	if not frappe.db.exists("UTM Source", LEAD_SOURCE):
		# UTM Source names itself by prompt, so the name is supplied here.
		frappe.get_doc({
			"doctype": "UTM Source",
			"name": LEAD_SOURCE,
			"description": "Imported from the Baublatt Infomanager feed and "
						   "promoted through campaign selection.",
		}).insert(ignore_permissions=True, ignore_if_duplicate=True)
	return LEAD_SOURCE


def ensure_salutation(label):
	"""The Salutation record for a Baublatt salutation, created on demand.

	Baublatt sends the German wording - "Herr" - and the installed list is
	English. Translating it would be a guess about how Megasol addresses people,
	so the German form is kept and registered as it arrived.
	"""
	label = (label or "").strip()
	if not label:
		return None
	if not frappe.db.exists("Salutation", label):
		frappe.get_doc({"doctype": "Salutation", "salutation": label}).insert(
			ignore_permissions=True, ignore_if_duplicate=True
		)
	return label


def swiss_phone(number):
	"""Infomanager sends Swiss numbers in local form; ERPNext demands a country code."""
	if not number:
		return None
	digits = re.sub(r"[^\d+]", "", number)
	if digits.startswith("+"):
		return digits
	if digits.startswith("00"):
		return "+" + digits[2:]
	if digits.startswith("0"):
		return "+41" + digits[1:]
	return "+41" + digits if digits else None


def opt_out_reason(email):
	"""Why this address must not be emailed, or None.

	The CRM Campaign path already answers this - unsubscribed, Do Not Contact,
	topic opt-outs, excluded email groups - and promotion has to give the same
	answer. Otherwise the AI path is simply a way around the opt-out.
	"""
	if not email:
		return _("No email address")
	from finbyzreach.email_marketing import test_recipient_exclusion

	return test_recipient_exclusion(email)


def source_records(candidate):
	"""The Infomanager person and firm behind a candidate, either of which may be absent."""
	person = company = None
	if candidate.party_type == "Contact" and candidate.contact:
		person = frappe.get_doc("Infomanager Contact", candidate.contact)
		if person.company:
			company = frappe.get_doc("Infomanager Company", person.company)
	if not company and candidate.company:
		company = frappe.get_doc("Infomanager Company", candidate.company)
	return person, company


def find_existing_lead(candidate, person):
	"""The Lead this recipient already has, if any.

	A person is never matched to their employer's Lead. Two people at the same
	firm are two Leads - frame 8 puts one Lead per person - and falling back to
	the company Lead would quietly merge them and send one of them an email
	addressed to the other.
	"""
	if candidate.email:
		lead = frappe.db.get_value("Lead", {"email_id": candidate.email}, "name")
		if lead:
			return lead

	if person:
		return frappe.db.get_value("Lead", {"custom_infomanager_contact_id": person.name}, "name")

	if candidate.company:
		lead = frappe.db.get_value("Infomanager Company", candidate.company, "lead")
		if lead and frappe.db.exists("Lead", lead):
			return lead
	return None


def apply_address(lead, *sources):
	"""Postcode and town, which is what partner matching runs on.

	The sources are applied in order, so the firm's address is laid down first
	and the person's overrides it where they have their own. Baublatt often
	sends a person with no address at all, and reading only the person would
	leave the Lead with no postcode to match a partner on.
	"""
	for source in sources:
		if not source:
			continue
		lead.city = source.get("town") or lead.city
		if lead.meta.has_field("custom_postal_code"):
			lead.custom_postal_code = source.get("postcode") or lead.custom_postal_code
		phone = swiss_phone(source.get("phone") or source.get("direct_phone"))
		if phone:
			lead.phone = phone
		mobile = swiss_phone(source.get("mobile_phone"))
		if mobile:
			lead.mobile_no = mobile


def apply_identity(lead, person, company):
	"""The Infomanager keys, so the Lead can always be traced back to the feed."""
	if person and lead.meta.has_field("custom_infomanager_contact_id"):
		lead.custom_infomanager_contact_id = person.name
	if company and lead.meta.has_field("custom_infomanager_company_id"):
		lead.custom_infomanager_company_id = company.name
	if lead.meta.has_field("custom_infomanager_status"):
		# Baublatt marks a contact inactive when the person has left the firm.
		lead.custom_infomanager_status = (
			"Inactive" if person and not cint(person.active) else "Active"
		)


def build_lead(candidate, person, company):
	"""A new Lead in the shape frame 8 asks for: a person, with their employer named."""
	lead = frappe.new_doc("Lead")
	lead.status = "Lead"
	lead.country = "Switzerland"
	lead.email_id = candidate.email

	if person:
		lead.salutation = ensure_salutation(person.salutation_label)
		lead.first_name = person.first_name or candidate.recipient_name
		lead.last_name = person.last_name

	# Organization Name is what creates the Prospect. It is set for a person's
	# employer too, not only for an enquiry that arrived without a person.
	if company:
		lead.company_name = company.name1
		lead.website = company.website
	elif not person:
		lead.company_name = candidate.recipient_name

	if not person:
		# Baublatt delivers plenty of firms with a general mailbox and nobody
		# named behind it. Left blank, ERPNext splits the organisation name
		# across the person fields and invents a Herr Hartmann with the surname
		# AG; naming the firm in one field keeps the record honest until a
		# person is actually delivered.
		lead.first_name = lead.company_name
		lead.last_name = None

	if lead.meta.has_field("utm_source"):
		lead.utm_source = ensure_lead_source()

	apply_address(lead, company, person)
	apply_identity(lead, person, company)

	lead.flags.ignore_permissions = True
	lead.insert(ignore_permissions=True)
	return lead


def refresh_lead(lead, person, company):
	"""Fill the gaps on a Lead we are reusing, without overwriting anyone's edits.

	`custom_base_data_manipulated` is the flag Megasol uses to say the imported
	base data has been corrected by hand. Once it is set, the feed stops being
	the authority for this record and only blank fields are filled.
	"""
	edited = cint(lead.get("custom_base_data_manipulated"))
	changed = False

	if not edited and person:
		for field, value in (
			("salutation", ensure_salutation(person.salutation_label)),
			("first_name", person.first_name),
			("last_name", person.last_name),
		):
			if value and lead.get(field) != value:
				lead.set(field, value)
				changed = True

	if company and not lead.company_name:
		lead.company_name = company.name1
		changed = True
	if company and not lead.website and company.website:
		lead.website = company.website
		changed = True
	if lead.meta.has_field("utm_source") and not lead.utm_source:
		lead.utm_source = ensure_lead_source()
		changed = True

	before = (lead.get("custom_infomanager_contact_id"), lead.get("custom_infomanager_company_id"))
	apply_identity(lead, person, company)
	if before != (lead.get("custom_infomanager_contact_id"), lead.get("custom_infomanager_company_id")):
		changed = True

	if changed:
		lead.flags.ignore_permissions = True
		lead.save(ignore_permissions=True)
	return lead


def log_inquiry(lead, candidate):
	"""Record this project against the Lead, as a repeat enquiry if it already has one.

	Megasol asked for repeat enquiries to stay on the same Lead rather than
	spawning another, so the project is appended to a running list and the
	counter frame 8 asks for is kept alongside it.
	"""
	line = "{0} · {1} · {2}".format(
		today(), candidate.project or "-", candidate.project_title or ""
	).strip(" ·")

	values = {}
	if lead.meta.has_field("custom_infomanager"):
		existing = (lead.get("custom_infomanager") or "").strip()
		if line not in existing:
			values["custom_infomanager"] = (existing + "\n" + line).strip()

	# A single Link field holds one project. The first one claims it; the rest
	# live in the list above until this becomes a child table.
	if lead.meta.has_field("custom_infomanager_projects") and candidate.project:
		if not lead.get("custom_infomanager_projects"):
			values["custom_infomanager_projects"] = candidate.project

	if lead.meta.has_field("custom_inquiry_count"):
		values["custom_inquiry_count"] = cint(lead.get("custom_inquiry_count")) + 1
	if lead.meta.has_field("custom_last_inquiry_on"):
		values["custom_last_inquiry_on"] = now_datetime()

	if values:
		frappe.db.set_value("Lead", lead.name, values, update_modified=False)
		lead.reload()
	return lead


def ensure_prospect(company, lead):
	"""The organisation record, created as soon as there are company details.

	Reused by name rather than recreated: ERPNext names a Prospect after the
	company, and its own create_prospect throws on a second Lead at the same
	firm instead of adding them to it.
	"""
	if not company or not company.name1:
		return None

	name = frappe.db.get_value("Prospect", {"company_name": company.name1}, "name")
	prospect = frappe.get_doc("Prospect", name) if name else frappe.new_doc("Prospect")
	if not name:
		prospect.company_name = company.name1
		prospect.company = lead.company

	prospect.website = prospect.website or company.website
	prospect.territory = prospect.territory or lead.territory
	prospect.prospect_owner = prospect.prospect_owner or lead.lead_owner

	if not any(row.lead == lead.name for row in prospect.leads):
		prospect.append("leads", {
			"lead": lead.name,
			"lead_name": lead.lead_name,
			"email": lead.email_id,
			"mobile_no": lead.mobile_no,
			"lead_owner": lead.lead_owner,
			"status": lead.status,
		})

	prospect.flags.ignore_permissions = True
	prospect.flags.ignore_mandatory = True
	prospect.save(ignore_permissions=True)

	if company.meta.has_field("prospect") and company.prospect != prospect.name:
		frappe.db.set_value("Infomanager Company", company.name, "prospect", prospect.name,
		                    update_modified=False)
	return prospect


def ensure_contact(candidate, lead, prospect, person, company):
	"""The Contact carrying the address, linked to the Lead and the Prospect.

	The links are appended, never replaced. Someone who turns up on a second
	project keeps the first project's Lead on their Contact, which is what
	Megasol asked for when a person appears across several projects.

	The outreach automation fires on Contact creation and would start the
	*default* campaign. Creating this candidate's Outbound Email in the same
	transaction makes that job's has_active_outbound_email() guard skip it, so
	the recipient stays on the campaign they were selected for.
	"""
	existing = frappe.db.get_value("Contact", {"email_id": candidate.email}, "name")
	if existing:
		contact = frappe.get_doc("Contact", existing)
	else:
		contact = frappe.new_doc("Contact")
		if person:
			contact.salutation = ensure_salutation(person.salutation_label)
			contact.first_name = person.first_name or candidate.recipient_name
			contact.last_name = person.last_name
		else:
			# A firm's general mailbox with nobody named behind it. The Contact
			# has to be called something, and the firm is all we were sent.
			contact.first_name = candidate.recipient_name or candidate.email
		contact.append("email_ids", {"email_id": candidate.email, "is_primary": 1})

	if person and contact.meta.has_field("custom_infomanager_contact_id"):
		contact.custom_infomanager_contact_id = person.name
	if company and contact.meta.has_field("custom_infomanager_company_id"):
		contact.custom_infomanager_company_id = company.name

	targets = [("Lead", lead.name)]
	if prospect:
		targets.append(("Prospect", prospect.name))
	for doctype, docname in targets:
		if not any(l.link_doctype == doctype and l.link_name == docname for l in contact.links):
			contact.append("links", {"link_doctype": doctype, "link_name": docname})

	contact.flags.ignore_permissions = True
	contact.save(ignore_permissions=True)
	return contact


def candidate_context_summary(candidate):
	bits = [
		f"{candidate.recipient_name} is listed as {candidate.role or 'a participant'}",
		f"on the project '{candidate.project_title}' in {candidate.town or 'Switzerland'}",
	]
	if candidate.planstage_name:
		bits.append(f"at stage '{candidate.planstage_name}'")
	if candidate.has_solar:
		bits.append("The project records a solar or flat-roof indicator.")
	return ". ".join(bits) + "."


def _research_call(default_path):
	"""Resolve a research entry point, honouring any site override.

	A site can remap these through override_whitelisted_methods — this one
	does — so the promotion path must use the same implementation the rest of
	the system uses rather than hardcoding one.
	"""
	overrides = frappe.get_hooks("override_whitelisted_methods") or {}
	target = overrides.get(default_path)
	if isinstance(target, list):
		target = target[-1] if target else None
	return frappe.get_attr(target or default_path)


def run_research(lead, contact, candidate, prospect=None):
	"""Research the company and the person before any email is written.

	The outreach automation normally does this, but it bails out as soon as an
	Outbound Email exists — and promotion creates one deliberately, to keep the
	recipient on their own campaign. So it has to happen here instead.

	Failure is reported, never fatal: an email written without research is worth
	more than no email, as long as it is obvious that is what happened.
	"""
	notes = []

	try:
		_research_call("finbyzreach.api.lead.research_lead")(lead.name)
		lead.reload()
		notes.append(
			_("Company research: done") if lead.get("customer_details")
			else _("Company research: returned nothing")
		)
	except Exception as exc:
		frappe.log_error(title=f"Company research failed - {lead.name}", message=frappe.get_traceback())
		notes.append(_("Company research: failed ({0})").format(str(exc)[:120]))

	try:
		_research_call("finbyzreach.api.contact.research_contact")(contact.name)
		contact.reload()
		notes.append(
			_("Person research: done") if contact.get("person_details")
			else _("Person research: returned nothing")
		)
	except Exception as exc:
		frappe.log_error(title=f"Person research failed - {contact.name}", message=frappe.get_traceback())
		notes.append(_("Person research: failed ({0})").format(str(exc)[:120]))

	# draft_emails refuses to run without person_details, so stand in with the
	# project context rather than blocking the whole sequence.
	if not contact.get("person_details"):
		frappe.db.set_value("Contact", contact.name, "person_details",
		                    candidate_context_summary(candidate), update_modified=False)
		contact.reload()
		notes.append(_("Used project details in place of person research"))

	# Person research lives on the Contact. The Lead keeps a copy, but only
	# refreshes it on save — and by this point the Lead has already been saved
	# by the company research above, so the copy would otherwise stay empty.
	copy_person_research_to_lead(lead, contact)
	copy_company_research_to_prospect(lead, prospect)

	return " · ".join(notes)


def copy_person_research_to_lead(lead, contact):
	if not lead.meta.has_field("custom_person_research"):
		return
	summary = contact.get("person_details")
	if summary and not lead.get("custom_person_research"):
		frappe.db.set_value("Lead", lead.name, "custom_person_research", summary,
		                    update_modified=False)
		lead.reload()


def copy_company_research_to_prospect(lead, prospect):
	"""Frame 8 moves company research off the Lead and onto the organisation."""
	if not prospect or not prospect.meta.has_field("custom_company_research"):
		return
	summary = lead.get("customer_details")
	if summary and not prospect.get("custom_company_research"):
		frappe.db.set_value("Prospect", prospect.name, "custom_company_research", summary,
		                    update_modified=False)


@frappe.whitelist()
def promote(names=None, campaign_name: str = None):
	"""Promote approved candidates into Leads and queue their outreach."""
	frappe.only_for("System Manager")

	if names:
		names = frappe.parse_json(names) if isinstance(names, str) else names
	else:
		names = frappe.get_all(
			CANDIDATE,
			filters={"ai_email_campaign": campaign_name, "status": "Approved"},
			pluck="name",
		)
	if not names:
		return {"ok": True, "promoted": 0, "message": _("No approved candidates to promote.")}

	promoted = skipped = failed = 0
	for name in names:
		candidate = frappe.get_doc(CANDIDATE, name)
		if candidate.status not in ("Approved",):
			skipped += 1
			continue

		blocked = opt_out_reason(candidate.email)
		if blocked:
			candidate.db_set({"status": "Skipped", "skip_reason": blocked}, update_modified=False)
			frappe.db.commit()
			skipped += 1
			continue

		try:
			person, company = source_records(candidate)
			lead_name = find_existing_lead(candidate, person)
			if lead_name:
				lead = refresh_lead(frappe.get_doc("Lead", lead_name), person, company)
			else:
				lead = build_lead(candidate, person, company)
			lead = log_inquiry(lead, candidate)

			if company and not company.lead:
				frappe.db.set_value("Infomanager Company", company.name, "lead", lead.name,
				                    update_modified=False)

			prospect = ensure_prospect(company, lead)
			contact = ensure_contact(candidate, lead, prospect, person, company)

			if person and not person.contact:
				frappe.db.set_value("Infomanager Contact", person.name, "contact", contact.name,
				                    update_modified=False)

			research_note = run_research(lead, contact, candidate, prospect)

			outbound = frappe.get_doc({
				"doctype": "Outbound Email",
				"contact": contact.name,
				"ai_email_campaign": candidate.ai_email_campaign,
				"research_note": research_note,
				# Recorded so a message can always be traced to the prospect and
				# the building it was written about.
				"lead": lead.name,
				"infomanager_project": candidate.project,
			})
			outbound.flags.ignore_permissions = True
			outbound.insert(ignore_permissions=True)

			candidate.db_set({
				"status": "Promoted",
				"lead": lead.name,
				"promoted_on": now_datetime(),
			}, update_modified=False)
			frappe.db.commit()
			promoted += 1
		except Exception:
			frappe.db.rollback()
			failed += 1
			frappe.log_error(title=f"Promote candidate failed - {name}",
			                 message=frappe.get_traceback())

	return {
		"ok": not failed,
		"promoted": promoted,
		"skipped": skipped,
		"failed": failed,
		"message": _("{0} promoted, {1} skipped, {2} failed.").format(promoted, skipped, failed),
	}


@frappe.whitelist()
def approve_emails(outbound_name: str, rows=None):
	"""Release held emails for sending in review mode."""
	frappe.only_for("System Manager")
	outbound = frappe.get_doc("Outbound Email", outbound_name)

	rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	released = 0
	for row in outbound.communication_email:
		if row.status != "Awaiting Approval":
			continue
		if rows and row.name not in rows:
			continue
		# Only the first step goes out now; later steps wait for their branch.
		frappe.db.set_value("Communication Email", row.name,
		                    "status", "Queued" if row.idx == 1 else "Pending",
		                    update_modified=False)
		released += 1
	frappe.db.commit()

	return {"ok": True, "released": released,
	        "message": _("{0} email(s) approved for sending.").format(released)}
