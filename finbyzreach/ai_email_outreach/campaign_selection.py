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
	"""Every address already written to, mapped to the campaigns that did it.

	Two queries in total. Checking per candidate instead cost two or three
	queries each, which is the bulk of the work when a campaign produces
	thousands of candidates. Naming the campaign lets a reviewer see why
	someone was held back rather than just that they were.
	"""
	contacted = {}

	for email, campaign in frappe.db.sql(
		"""select ct.email_id, oe.ai_email_campaign from `tabContact` ct
		   join `tabOutbound Email` oe on oe.contact = ct.name
		   where ifnull(ct.email_id, '') != ''"""
	):
		contacted.setdefault(email.strip().lower(), set()).add(campaign)

	for email, campaign in frappe.db.sql(
		"""select email, ai_email_campaign from `tabCampaign Candidate`
		   where status in ('Approved', 'Promoted') and ifnull(email, '') != ''"""
	):
		contacted.setdefault(email.strip().lower(), set()).add(campaign)

	return contacted


def already_contacted(email):
	"""Single-address check, for the approval path where volume is small."""
	if not email:
		return False
	return email.strip().lower() in contacted_emails()


def party_rows(project_name, excluded_roles, excluded_companies=None, excluded_contacts=None):
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

	excluded_companies = excluded_companies or set()
	excluded_contacts = excluded_contacts or set()

	parties = []
	for row in rows:
		if row.roletype_name in excluded_roles:
			continue
		# A campaign can drop one specific firm or person without touching the
		# imported record, which stays available to every other campaign.
		if row.company and row.company in excluded_companies:
			continue
		if row.contact and row.contact in excluded_contacts:
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


def notify_progress(
	campaign_name: str,
	step: str,
	message: str,
	completed: int = 0,
	total: int = 0,
	user: str = None,
):
	"""Publish realtime progress to whoever has the campaign open."""
	percent = int((completed / total) * 100) if total else (100 if step in ("completed", "done") else 0)
	title = _("AI Relevance Scoring") if step == "scoring" else _("Finding Project Candidates")
	payload = {
		"campaign_name": campaign_name,
		"step": step,
		"title": title,
		"message": str(message),
		"completed": completed,
		"total": total,
		"percent": percent,
	}

	# 1. Custom realtime event for form listeners
	frappe.publish_realtime(
		event="campaign_candidate_progress",
		message=payload,
		doctype="AI Email Campaign",
		docname=campaign_name,
		after_commit=False,
	)
	if user:
		frappe.publish_realtime(
			event="campaign_candidate_progress",
			message=payload,
			user=user,
			after_commit=False,
		)

	# 2. Frappe native progress dialog (socketio_client.js -> frappe.show_progress)
	frappe.publish_progress(
		percent=percent,
		title=title,
		description=str(message),
		doctype="AI Email Campaign",
		docname=campaign_name,
	)


@frappe.whitelist()
def build_candidates(campaign_name: str, score_with_ai: int = 1):
	"""Queue the selection pass.

	Done in the background because a wide campaign can walk tens of thousands
	of projects, which no web request should be holding open.
	"""
	frappe.only_for("System Manager")
	frappe.get_doc("AI Email Campaign", campaign_name)  # exists, and permission-checked
	user = frappe.session.user

	frappe.enqueue(
		"finbyzreach.ai_email_outreach.campaign_selection.run_build",
		queue="long", timeout=7200, enqueue_after_commit=True,
		campaign_name=campaign_name, score_with_ai=cint(score_with_ai), user=user,
		job_name=f"Find candidates for {campaign_name}",
	)
	return {"ok": True, "message": _(
		"Finding candidates in the background. Live progress will appear below."
	)}


def run_build(campaign_name: str, score_with_ai: int = 1, user: str = None):
	"""Find everyone this campaign could approach and store them for review."""
	notify_progress(campaign_name, "finding", _("Scanning matching projects and candidates…"), 0, 0, user=user)

	campaign = frappe.get_doc("AI Email Campaign", campaign_name)
	excluded_roles = set(_lines(campaign.excluded_roles))
	excluded_companies = set(_lines(campaign.get("excluded_companies")))
	excluded_contacts = set(_lines(campaign.get("excluded_contacts")))

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
	notify_progress(
		campaign_name, "finding",
		_("Found {0} qualifying project(s). Extracting participants…").format(len(projects)),
		0, len(projects), user=user
	)

	seen = set()
	rows = []

	for project in projects:
		for party in party_rows(project.name, excluded_roles, excluded_companies, excluded_contacts):
			email = party["email"].strip().lower()
			# One candidate per address per campaign: a firm on six projects is
			# one conversation, not six.
			if email in seen or email in existing:
				continue
			seen.add(email)

			prior = contacted.get(email)
			rows.append((
				frappe.generate_hash(length=10),
				campaign_name,
				"Skipped" if prior else "Suggested",
				_("Already contacted by: {0}").format(", ".join(sorted(c for c in prior if c)))
				if prior else None,
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
	added = len(rows) - skipped

	if cint(score_with_ai) and rows:
		notify_progress(
			campaign_name, "finding",
			_("Added {0} candidates ({1} skipped). Starting AI scoring…").format(added, skipped),
			len(rows), len(rows), user=user
		)
		enqueue_scoring(campaign_name, user=user)
	else:
		notify_progress(
			campaign_name, "completed",
			_("{0} project(s) matched. {1} candidate(s) added, {2} skipped.").format(
				len(projects), added, skipped
			),
			len(rows), len(rows), user=user
		)

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


def enqueue_scoring(campaign_name: str, user: str = None, force: int = 0):
	frappe.enqueue(
		"finbyzreach.ai_email_outreach.campaign_selection.score_candidates",
		queue="long", timeout=3600, enqueue_after_commit=True,
		campaign_name=campaign_name, user=user, force=cint(force),
		job_name=f"Score candidates for {campaign_name}",
	)


@frappe.whitelist()
def trigger_scoring(campaign_name: str, force: int = 0):
	"""Queue AI scoring pass in background with realtime updates."""
	frappe.only_for("System Manager")
	frappe.get_doc("AI Email Campaign", campaign_name)
	user = frappe.session.user

	enqueue_scoring(campaign_name, user=user, force=cint(force))
	return {"ok": True, "message": _("Scoring candidates in the background. Live progress will appear below.")}


@frappe.whitelist()
def score_candidates(campaign_name: str, limit: int = 0, user: str = None, force: int = 0):
	"""Ask the campaign's agent how relevant each candidate is to the brief."""
	user = user or frappe.session.user
	campaign = frappe.get_doc("AI Email Campaign", campaign_name)
	if not campaign.description:
		msg = _("Add a campaign description before scoring.")
		notify_progress(campaign_name, "failed", msg, user=user)
		return {"ok": False, "message": msg}
	agent_name = resolve_relevance_agent(campaign)
	if not agent_name:
		msg = _("No relevance agent configured. Set one on the campaign, or in Followup Settings.")
		notify_progress(campaign_name, "failed", msg, user=user)
		return {"ok": False, "message": msg}

	filters = {"ai_email_campaign": campaign_name, "status": "Suggested"}
	if not cint(force):
		filters["ai_score"] = 0

	names = frappe.get_all(
		CANDIDATE,
		filters=filters,
		pluck="name", limit=cint(limit) or None,
	)

	# If all candidates already have a score, re-score the Suggested candidates
	if not names:
		names = frappe.get_all(
			CANDIDATE,
			filters={"ai_email_campaign": campaign_name, "status": "Suggested"},
			pluck="name", limit=cint(limit) or None,
		)

	total = len(names)
	if not names:
		msg = _("No candidates found in this campaign.")
		notify_progress(campaign_name, "completed", msg, 0, 0, user=user)
		return {"ok": True, "scored": 0, "message": msg}

	notify_progress(
		campaign_name, "scoring",
		_("Starting AI relevance scoring for {0} candidates…").format(total),
		0, total, user=user
	)

	service = frappe.get_doc("AI Agent", agent_name).agent_service
	scored = failed = 0

	for idx, name in enumerate(names, start=1):
		candidate = frappe.get_doc(CANDIDATE, name)
		recipient = candidate.recipient_name or candidate.email or "Candidate"
		try:
			result = service.invoke(**relevance_input(campaign, candidate))
			score = max(0, min(100, cint(getattr(result, "score", 0))))
			reason = (getattr(result, "reason", "") or "")[:500]
			candidate.db_set({
				"ai_score": score,
				"ai_reason": reason,
			}, update_modified=False)
			scored += 1
			notify_progress(
				campaign_name, "scoring",
				_("Scored {0} ({1}/{2}) — Score: {3}").format(recipient, idx, total, score),
				idx, total, user=user
			)
		except Exception:
			failed += 1
			frappe.log_error(
				title=f"Campaign relevance scoring failed - {name}",
				message=frappe.get_traceback(),
			)
			notify_progress(
				campaign_name, "scoring",
				_("Failed scoring {0} ({1}/{2})").format(recipient, idx, total),
				idx, total, user=user
			)
		frappe.db.commit()

	msg = _("AI scoring complete! {0} scored, {1} failed.").format(scored, failed)
	notify_progress(campaign_name, "completed", msg, total, total, user=user)

	return {
		"ok": not failed,
		"scored": scored,
		"failed": failed,
		"message": msg,
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
	contacted = contacted_emails() if status == "Approved" else {}
	changed = blocked = 0

	for name in names:
		candidate = frappe.get_doc(CANDIDATE, name)
		prior = contacted.get((candidate.email or "").strip().lower())
		if status == "Approved" and prior:
			candidate.db_set({"status": "Skipped",
			                  "skip_reason": _("Already contacted by: {0}").format(
			                      ", ".join(sorted(c for c in prior if c)))},
			                 update_modified=False)
			blocked += 1
			continue
		candidate.db_set("status", status, update_modified=False)
		# Approving claims the address, so later rows in the same batch see it.
		if status == "Approved" and candidate.email:
			contacted.setdefault(candidate.email.strip().lower(), set()).add(
				candidate.ai_email_campaign)
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
