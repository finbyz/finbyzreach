"""Choosing who a campaign should approach.

Imported Infomanager records are never turned into Leads automatically. A
campaign states what it is about and which projects qualify; this module finds
the parties on those projects, scores each one against the campaign brief, and
leaves them as Campaign Candidates for a human to review.

Nothing here contacts anybody. Promotion to a Lead is a separate, explicit
step, and a candidate whose address has already been written to by another
campaign is marked Skipped rather than quietly mailed twice.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

CANDIDATE = "Campaign Candidate"
SOLAR_DETAILS = ("Solarenergie", "Photovoltaik", "Flachdach", "Dachbegrünungen")


def _lines(value):
	"""Small Text holding one value per line -> a clean list."""
	if not value:
		return []
	return [line.strip() for line in str(value).splitlines() if line.strip()]


def qualifying_projects(campaign):
	"""Projects matching the campaign's criteria."""
	conditions = ["1=1"]
	values = {}

	if campaign.require_solar_signal:
		conditions.append(
			"""exists (select 1 from `tabInfomanager Project Detail` d
			           where d.parent = p.name and d.detailtype_name in %(solar)s)"""
		)
		values["solar"] = SOLAR_DETAILS

	for field, column in (("plan_stages", "planstage_name"),
	                      ("cantons", "province_name"),
	                      ("project_types", "projecttype_name")):
		wanted = _lines(campaign.get(field))
		if wanted:
			conditions.append(f"p.{column} in %({field})s")
			values[field] = wanted

	if flt(campaign.min_project_value):
		conditions.append("p.value >= %(min_value)s")
		values["min_value"] = flt(campaign.min_project_value)
	if flt(campaign.max_project_value):
		conditions.append("p.value <= %(max_value)s")
		values["max_value"] = flt(campaign.max_project_value)

	return frappe.db.sql(
		f"""select p.name, p.title, p.town, p.planstage_name, p.projecttype_name,
		           p.province_name, p.value,
		           exists (select 1 from `tabInfomanager Project Detail` d
		                   where d.parent = p.name
		                     and d.detailtype_name in {('%(solar_flag)s')}) as has_solar
		    from `tabInfomanager Project` p
		    where {' and '.join(conditions)}
		    order by has_solar desc, p.value desc""",
		{**values, "solar_flag": SOLAR_DETAILS},
		as_dict=True,
	)


def already_contacted(email):
	"""True when this address has already been written to by any campaign.

	Aaron's requirement is no duplicate messages to the same recipient, so the
	check spans campaigns rather than being scoped to one.
	"""
	if not email:
		return False

	contacts = frappe.get_all("Contact", filters={"email_id": email}, pluck="name")
	if contacts and frappe.db.exists("Outbound Email", {"contact": ["in", contacts]}):
		return True

	return bool(
		frappe.db.exists(CANDIDATE, {"email": email, "status": ["in", ("Approved", "Promoted")]})
	)


def party_rows(project_name, excluded_roles):
	"""Every contactable party on a project, company or person.

	Aaron wants all parties eligible rather than a fixed role whitelist, so the
	only filter is the campaign's own exclusions and whether an address exists.
	"""
	rows = frappe.db.sql(
		"""select pp.party_type, pp.roletype_name, pp.company, pp.contact,
		          co.name1 as company_name, co.email as company_email,
		          ct.full_name as contact_name, ct.email as contact_email
		   from `tabInfomanager Project Participant` pp
		   left join `tabInfomanager Company` co on co.name = pp.company
		   left join `tabInfomanager Contact` ct on ct.name = pp.contact
		   where pp.parent = %s""",
		project_name,
		as_dict=True,
	)

	parties = []
	for row in rows:
		if row.roletype_name in excluded_roles:
			continue
		if row.party_type == "Contact":
			# Prefer a person's own address; fall back to nothing rather than
			# silently addressing a person at a company inbox.
			email, name = row.contact_email, row.contact_name
		else:
			email, name = row.company_email, row.company_name
		if not email:
			continue
		parties.append({
			"party_type": row.party_type,
			"company": row.company,
			"contact": row.contact,
			"recipient_name": name or "",
			"email": email,
			"role": row.roletype_name or "",
		})
	return parties


@frappe.whitelist()
def build_candidates(campaign_name: str, score_with_ai: int = 1):
	"""Find everyone this campaign could approach and store them for review."""
	frappe.only_for("System Manager")
	campaign = frappe.get_doc("AI Email Campaign", campaign_name)
	excluded_roles = set(_lines(campaign.excluded_roles))

	projects = qualifying_projects(campaign)
	seen_emails = set()
	created = skipped = 0

	for project in projects:
		for party in party_rows(project.name, excluded_roles):
			email = party["email"].strip().lower()

			# One candidate per address per campaign: a firm on six projects is
			# one conversation, not six.
			if email in seen_emails:
				continue
			if frappe.db.exists(CANDIDATE, {"ai_email_campaign": campaign_name, "email": party["email"]}):
				seen_emails.add(email)
				continue
			seen_emails.add(email)

			contacted = already_contacted(party["email"])
			doc = frappe.get_doc({
				"doctype": CANDIDATE,
				"ai_email_campaign": campaign_name,
				"status": "Skipped" if contacted else "Suggested",
				"skip_reason": _("Already contacted by an earlier campaign") if contacted else None,
				"project": project.name,
				"project_title": project.title,
				"town": project.town,
				"planstage_name": project.planstage_name,
				"project_value": project.value,
				"has_solar": cint(project.has_solar),
				**party,
			})
			doc.insert(ignore_permissions=True)
			created += 1
			skipped += 1 if contacted else 0

	frappe.db.commit()

	if cint(score_with_ai):
		enqueue_scoring(campaign_name)

	return {
		"ok": True,
		"projects": len(projects),
		"created": created,
		"skipped": skipped,
		"message": _("{0} project(s) matched. {1} candidate(s) added, {2} skipped as already contacted.").format(
			len(projects), created, skipped
		),
	}


def enqueue_scoring(campaign_name: str):
	frappe.enqueue(
		"finbyzreach.ai_email_outreach.campaign_selection.score_candidates",
		queue="long", timeout=3600, enqueue_after_commit=True,
		campaign_name=campaign_name,
		job_name=f"Score candidates for {campaign_name}",
	)


@frappe.whitelist()
def score_candidates(campaign_name: str, limit: int = 0):
	"""Ask the campaign's agent how relevant each candidate is to the brief."""
	campaign = frappe.get_doc("AI Email Campaign", campaign_name)
	if not campaign.description:
		return {"ok": False, "message": _("Add a campaign description before scoring.")}
	if not campaign.ai_agent:
		return {"ok": False, "message": _("Set an AI Agent on the campaign before scoring.")}

	names = frappe.get_all(
		CANDIDATE,
		filters={"ai_email_campaign": campaign_name, "status": "Suggested", "ai_score": 0},
		pluck="name", limit=cint(limit) or None,
	)
	if not names:
		return {"ok": True, "scored": 0, "message": _("Nothing left to score.")}

	agent = frappe.get_doc("AI Agent", campaign.ai_agent)
	service = agent.agent_service
	scored = failed = 0

	for name in names:
		candidate = frappe.get_doc(CANDIDATE, name)
		try:
			result = service.invoke(**relevance_input(campaign, candidate))
			candidate.db_set({
				"ai_score": max(0, min(100, cint(getattr(result, "score", 0)))),
				"ai_reason": (getattr(result, "reason", "") or "")[:500],
			}, update_modified=False)
			scored += 1
		except Exception:
			failed += 1
			frappe.log_error(
				title=f"Campaign relevance scoring failed - {name}",
				message=frappe.get_traceback(),
			)
		frappe.db.commit()

	return {
		"ok": not failed,
		"scored": scored,
		"failed": failed,
		"message": _("Scored {0} candidate(s), {1} failed.").format(scored, failed),
	}


def relevance_input(campaign, candidate):
	"""What the agent needs to judge one candidate."""
	details = frappe.get_all(
		"Infomanager Project Detail",
		filters={"parent": candidate.project},
		fields=["parentdetailtype_name", "detailtype_name"],
		limit=40,
	)
	description = "; ".join(
		f"{d.parentdetailtype_name}: {d.detailtype_name}" for d in details if d.detailtype_name
	)

	return {
		"campaign_description": campaign.description or "",
		"recipient_name": candidate.recipient_name or "",
		"recipient_type": "private person" if candidate.party_type == "Contact" else "company",
		"role": candidate.role or "",
		"project_title": candidate.project_title or "",
		"town": candidate.town or "",
		"plan_stage": candidate.planstage_name or "",
		"project_value": flt(candidate.project_value),
		"has_solar": bool(candidate.has_solar),
		"construction_details": description,
	}


@frappe.whitelist()
def set_status(names, status: str):
	"""Bulk approve or reject from the list view."""
	frappe.only_for("System Manager")
	if status not in ("Approved", "Rejected", "Suggested"):
		frappe.throw(_("Unsupported status {0}").format(status))

	names = frappe.parse_json(names) if isinstance(names, str) else names
	changed = blocked = 0
	for name in names:
		candidate = frappe.get_doc(CANDIDATE, name)
		if status == "Approved" and already_contacted(candidate.email):
			candidate.db_set({"status": "Skipped",
			                  "skip_reason": _("Already contacted by an earlier campaign")},
			                 update_modified=False)
			blocked += 1
			continue
		candidate.db_set("status", status, update_modified=False)
		changed += 1
	frappe.db.commit()

	message = _("{0} candidate(s) set to {1}.").format(changed, status)
	if blocked:
		message += " " + _("{0} skipped, already contacted.").format(blocked)
	return {"ok": True, "changed": changed, "blocked": blocked, "message": message}
