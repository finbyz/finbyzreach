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


def contacted_emails():
	"""Every address already written to, as one lowercase set.

	Two queries in total. Checking per candidate instead cost two or three
	queries each, which is the bulk of the work when a campaign produces
	thousands of candidates.
	"""
	rows = frappe.db.sql(
		"""select distinct ct.email_id from `tabContact` ct
		   join `tabOutbound Email` oe on oe.contact = ct.name
		   where ifnull(ct.email_id, '') != ''"""
	)
	claimed = frappe.db.sql(
		"""select distinct email from `tabCampaign Candidate`
		   where status in ('Approved', 'Promoted') and ifnull(email, '') != ''"""
	)
	return {r[0].strip().lower() for r in rows + claimed if r[0]}


def already_contacted(email):
	"""Single-address check, for the approval path where volume is small."""
	if not email:
		return False
	return email.strip().lower() in contacted_emails()


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
	"""Queue the selection pass.

	Done in the background because a wide campaign can walk tens of thousands
	of projects, which no web request should be holding open.
	"""
	frappe.only_for("System Manager")
	frappe.get_doc("AI Email Campaign", campaign_name)  # exists, and permission-checked

	frappe.enqueue(
		"finbyzreach.ai_email_outreach.campaign_selection.run_build",
		queue="long", timeout=7200, enqueue_after_commit=True,
		campaign_name=campaign_name, score_with_ai=cint(score_with_ai),
		job_name=f"Find candidates for {campaign_name}",
	)
	return {"ok": True, "message": _(
		"Finding candidates in the background. Reopen the campaign shortly to see the counts."
	)}


def run_build(campaign_name: str, score_with_ai: int = 1):
	"""Find everyone this campaign could approach and store them for review."""
	campaign = frappe.get_doc("AI Email Campaign", campaign_name)
	excluded_roles = set(_lines(campaign.excluded_roles))

	# Loaded once rather than per candidate.
	contacted = contacted_emails()
	existing = {
		row[0].strip().lower()
		for row in frappe.db.sql(
			"select email from `tabCampaign Candidate` where ai_email_campaign = %s",
			campaign_name,
		)
		if row[0]
	}

	projects = qualifying_projects(campaign)
	seen = set()
	rows = []

	for project in projects:
		for party in party_rows(project.name, excluded_roles):
			email = party["email"].strip().lower()
			# One candidate per address per campaign: a firm on six projects is
			# one conversation, not six.
			if email in seen or email in existing:
				continue
			seen.add(email)

			is_contacted = email in contacted
			rows.append((
				frappe.generate_hash(length=10),
				campaign_name,
				"Skipped" if is_contacted else "Suggested",
				_("Already contacted by an earlier campaign") if is_contacted else None,
				project.name, project.title, project.town, project.planstage_name,
				project.value, cint(project.has_solar),
				party["party_type"], party["company"], party["contact"],
				party["recipient_name"], party["email"], party["role"],
				frappe.session.user, frappe.utils.now(),
			))

	if rows:
		frappe.db.bulk_insert(
			CANDIDATE,
			fields=["name", "ai_email_campaign", "status", "skip_reason", "project",
			        "project_title", "town", "planstage_name", "project_value", "has_solar",
			        "party_type", "company", "contact", "recipient_name", "email", "role",
			        "owner", "creation"],
			values=rows,
			chunk_size=500,
		)
	frappe.db.commit()

	skipped = sum(1 for r in rows if r[2] == "Skipped")
	if cint(score_with_ai) and rows:
		enqueue_scoring(campaign_name)

	return {
		"ok": True, "projects": len(projects), "created": len(rows), "skipped": skipped,
		"message": _("{0} project(s) matched. {1} candidate(s) added, {2} skipped as already contacted.").format(
			len(projects), len(rows), skipped
		),
	}


def resolve_relevance_agent(campaign=None):
	"""The agent that scores candidates.

	A campaign may name its own; otherwise the shared one from Followup
	Settings is used, so a change there applies everywhere at once. Nothing is
	hardcoded — an agent that has been renamed or removed simply resolves to
	nothing and the caller reports it.
	"""
	if campaign and campaign.get("relevance_agent"):
		name = campaign.get("relevance_agent")
		if frappe.db.exists("AI Agent", name):
			return name

	name = frappe.db.get_single_value("Followup Settings", "relevance_agent")
	if name and frappe.db.exists("AI Agent", name):
		return name
	return None


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
	agent_name = resolve_relevance_agent(campaign)
	if not agent_name:
		return {"ok": False, "message": _(
			"No relevance agent configured. Set one on the campaign, or in Followup Settings."
		)}

	names = frappe.get_all(
		CANDIDATE,
		filters={"ai_email_campaign": campaign_name, "status": "Suggested", "ai_score": 0},
		pluck="name", limit=cint(limit) or None,
	)
	if not names:
		return {"ok": True, "scored": 0, "message": _("Nothing left to score.")}

	service = frappe.get_doc("AI Agent", agent_name).agent_service
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
	# Loaded once for the whole batch, not per row.
	contacted = contacted_emails() if status == "Approved" else set()
	changed = blocked = 0

	for name in names:
		candidate = frappe.get_doc(CANDIDATE, name)
		if status == "Approved" and (candidate.email or "").strip().lower() in contacted:
			candidate.db_set({"status": "Skipped",
			                  "skip_reason": _("Already contacted by an earlier campaign")},
			                 update_modified=False)
			blocked += 1
			continue
		candidate.db_set("status", status, update_modified=False)
		# Approving claims the address, so later rows in the same batch see it.
		if status == "Approved" and candidate.email:
			contacted.add(candidate.email.strip().lower())
		changed += 1
	frappe.db.commit()

	message = _("{0} candidate(s) set to {1}.").format(changed, status)
	if blocked:
		message += " " + _("{0} skipped, already contacted.").format(blocked)
	return {"ok": True, "changed": changed, "blocked": blocked, "message": message}


@frappe.whitelist()
def candidate_counts(campaign_name: str):
	"""Candidates per status, for the campaign dashboard.

	Done server-side because the client get_list API rejects aggregate
	expressions such as count(name).
	"""
	rows = frappe.db.sql(
		"""select status, count(*) as n from `tabCampaign Candidate`
		   where ai_email_campaign = %s group by status""",
		campaign_name,
		as_dict=True,
	)
	return {row.status: row.n for row in rows}
