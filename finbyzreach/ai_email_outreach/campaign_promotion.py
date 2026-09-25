"""Turning approved candidates into Leads and starting their outreach.

One Lead per recipient, not one per project. A firm on six projects becomes a
single Lead carrying all six as context, so it receives one conversation.

An existing Lead with the same address is reused rather than duplicated, which
is what Aaron asked for: "become Leads, or link to existing Leads".
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

CANDIDATE = "Campaign Candidate"


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


def find_existing_lead(candidate):
	"""An address already in the CRM is the same prospect, not a new one."""
	if candidate.email:
		lead = frappe.db.get_value("Lead", {"email_id": candidate.email}, "name")
		if lead:
			return lead
	if candidate.company:
		lead = frappe.db.get_value("Infomanager Company", candidate.company, "lead")
		if lead and frappe.db.exists("Lead", lead):
			return lead
	return None


def source_record(candidate):
	"""The Infomanager record this candidate came from."""
	if candidate.party_type == "Contact" and candidate.contact:
		return frappe.get_doc("Infomanager Contact", candidate.contact)
	if candidate.company:
		return frappe.get_doc("Infomanager Company", candidate.company)
	return None


def build_lead(candidate, source):
	lead = frappe.new_doc("Lead")
	is_person = candidate.party_type == "Contact"

	lead.update({
		"lead_name": candidate.recipient_name,
		"first_name": candidate.recipient_name,
		"email_id": candidate.email,
		"status": "Lead",
		"country": "Switzerland",
	})
	if source:
		lead.city = source.get("town")
		phone = swiss_phone(source.get("phone"))
		if phone:
			lead.phone = phone
			lead.mobile_no = phone
		if not is_person:
			lead.company_name = source.get("name1")
			lead.website = source.get("website")
			if frappe.get_meta("Lead").has_field("custom_infomanager_company_id"):
				lead.custom_infomanager_company_id = source.name
		elif frappe.get_meta("Lead").has_field("custom_infomanager_contact_id"):
			lead.custom_infomanager_contact_id = source.name

	lead.flags.ignore_permissions = True
	lead.insert(ignore_permissions=True)
	return lead


def ensure_contact(candidate, lead):
	"""A Contact carrying the address, linked to the Lead.

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
		contact.first_name = candidate.recipient_name or candidate.email
		contact.company_name = candidate.recipient_name if candidate.party_type == "Company" else None
		contact.append("email_ids", {"email_id": candidate.email, "is_primary": 1})

	if not any(l.link_doctype == "Lead" and l.link_name == lead.name for l in contact.links):
		contact.append("links", {"link_doctype": "Lead", "link_name": lead.name})

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


def run_research(lead, contact, candidate):
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
		notes.append(_("Used project details in place of person research"))

	return " · ".join(notes)


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

		try:
			source = source_record(candidate)
			lead_name = find_existing_lead(candidate)
			lead = frappe.get_doc("Lead", lead_name) if lead_name else build_lead(candidate, source)

			if source and source.doctype == "Infomanager Company" and not source.lead:
				frappe.db.set_value("Infomanager Company", source.name, "lead", lead.name,
				                    update_modified=False)

			contact = ensure_contact(candidate, lead)

			if source and source.doctype == "Infomanager Contact" and not source.contact:
				frappe.db.set_value("Infomanager Contact", source.name, "contact", contact.name,
				                    update_modified=False)

			research_note = run_research(lead, contact, candidate)

			outbound = frappe.get_doc({
				"doctype": "Outbound Email",
				"contact": contact.name,
				"ai_email_campaign": candidate.ai_email_campaign,
				"research_note": research_note,
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
