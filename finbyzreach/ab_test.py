"""EM-30 and EM-31: A/B test for a campaign, with two to four versions (A, B, C, D).

A share of the audience takes part in the test and is split equally between the versions
(different subject, different content, or both). Email C and D are optional. The rest waits. When the test time is over, the
variant with the higher open or click rate wins (a tie goes to the earlier version, so A) and the winner is sent to the rest.
"""
import hashlib
from math import ceil

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

HOLD = "2999-01-01 00:00:00"  # the rest of the audience waits here until a winner is chosen
MIN_TEST_RECIPIENTS = 2
MIN_SHARE, MAX_SHARE = 5, 50
ALL_VARIANTS = ("A", "B", "C", "D")
METRICS = {"Opens": "custom_opened", "Clicks": "custom_clicked"}


def enabled(campaign):
	return bool(cint(campaign.get("custom_ab_enabled")))


def _field(kind, variant):
	"""Campaign field of a version. B keeps its original names, C and D add a suffix."""
	v = variant.lower()
	if kind == "snapshot_subject":
		return "custom_ab_snapshot_subject" if v == "b" else f"custom_ab_snapshot_subject_{v}"
	if kind == "snapshot_html":
		return "custom_ab_snapshot_html" if v == "b" else f"custom_ab_snapshot_html_{v}"
	return f"custom_ab_{kind}_{v}"


def variants(campaign):
	"""The versions in this test: A, B, and C or D when they have their own email or subject."""
	out = ["A", "B"]
	for variant in ("C", "D"):
		if campaign.get(_field("template", variant)) or str(campaign.get(_field("subject", variant)) or "").strip():
			out.append(variant)
	return out


def validate(campaign):
	"""Throw a clear message when the test settings cannot work."""
	if not enabled(campaign):
		return
	if not (campaign.get("custom_ab_template_b") or str(campaign.get("custom_ab_subject_b") or "").strip()):
		frappe.throw(_("Choose a different email or a different subject for variant B."), title=_("A/B test"))
	share = cint(campaign.get("custom_ab_share"))
	if not MIN_SHARE <= share <= MAX_SHARE:
		frappe.throw(_("The test share must be between {0}% and {1}% of the audience.").format(MIN_SHARE, MAX_SHARE), title=_("A/B test"))
	if cint(campaign.get("custom_ab_hours")) < 1:
		frappe.throw(_("The test must run for at least one hour."), title=_("A/B test"))
	if campaign.get("custom_ab_metric") not in METRICS:
		frappe.throw(_("Choose whether opens or clicks decide the winner."), title=_("A/B test"))


def test_size(eligible_count, share, count=2):
	"""A test group that splits equally between the versions, at least one person each, never above the audience."""
	size = max(count, ceil(eligible_count * cint(share) / 100))
	size = min(size, eligible_count)
	return size - (size % count) if size >= count else size


def _order_key(campaign_name, row):
	return hashlib.sha256(f"{campaign_name}\0{row.normalized_email or row.email}".encode()).hexdigest()


def plan(campaign_name, eligible_rows, share, letters=("A", "B")):
	"""Return [(row, variant, phase)]: the test group first (rotating through the versions), then the rest."""
	ordered = sorted(eligible_rows, key=lambda row: _order_key(campaign_name, row))
	size = test_size(len(ordered), share, len(letters))
	return [
		(row, letters[index % len(letters)] if index < size else "", "Test" if index < size else "Rest")
		for index, row in enumerate(ordered)
	]


def test_end(batches, test_count, hours):
	"""The test ends `hours` after the last batch that carries a test recipient."""
	covered = 0
	for batch in batches:
		covered += batch.size
		if covered >= test_count:
			return add_to_date(get_datetime(batch.scheduled_at), hours=cint(hours))
	return add_to_date(get_datetime(batches[-1].scheduled_at), hours=cint(hours))


def variant_content(campaign, recipient):
	"""Subject and HTML for this recipient: versions B, C and D have their own frozen copy."""
	variant = recipient.get("custom_ab_variant")
	if enabled(campaign) and variant in ("B", "C", "D") and campaign.get(_field("snapshot_html", variant)):
		return campaign.get(_field("snapshot_subject", variant)) or campaign.custom_snapshot_subject, campaign.get(_field("snapshot_html", variant))
	return campaign.custom_snapshot_subject, campaign.custom_snapshot_html


def results(campaign_name):
	"""Sent, opened and clicked counts per variant for the test group."""
	table = frappe.qb.DocType("Email Campaign")
	rows = (
		frappe.qb.from_(table)
		.select(
			table.custom_ab_variant,
			frappe.query_builder.functions.Count("*").as_("sent"),
			frappe.query_builder.functions.Sum(table.custom_opened).as_("opened"),
			frappe.query_builder.functions.Sum(table.custom_clicked).as_("clicked"),
		)
		.where(table.campaign_name == campaign_name)
		.where(table.custom_ab_phase == "Test")
		.where(table.custom_email_queue.isnotnull())
		.where(table.custom_email_queue != "")
		.groupby(table.custom_ab_variant)
		.run(as_dict=True)
	)
	out = {variant: {"sent": 0, "opened": 0, "clicked": 0} for variant in ALL_VARIANTS}
	for row in rows:
		if row.custom_ab_variant in out:
			out[row.custom_ab_variant] = {"sent": cint(row.sent), "opened": cint(row.opened), "clicked": cint(row.clicked)}
	return out


def choose_winner(stats, metric):
	"""The highest rate wins. A tie, or no data at all, goes to the earlier version, so to A."""
	key = "opened" if metric == "Opens" else "clicked"

	def rate(variant):
		sent = stats[variant]["sent"]
		return stats[variant][key] / sent if sent else 0.0

	winner = "A"
	for variant in ALL_VARIANTS[1:]:
		if variant in stats and stats[variant]["sent"] and rate(variant) > rate(winner):
			winner = variant
	return winner


def decide(campaign_name):
	"""Pick the winner and release the rest of the audience with the winning email."""
	from finbyzreach import email_marketing as mail

	campaign = frappe.get_doc("Campaign", campaign_name, for_update=True)
	if campaign.custom_ab_status != "Testing" or campaign.custom_broadcast_status not in ("Scheduled", "Sending"):
		return None
	stats = results(campaign_name)
	winner = choose_winner(stats, campaign.custom_ab_metric)
	rest = frappe.get_all(
		"Email Campaign",
		filters={"campaign_name": campaign_name, "custom_ab_phase": "Rest", "custom_delivery_status": "Planned"},
		fields=["name"],
		order_by="name asc",
		limit_page_length=0,
	)
	if rest:
		batches = mail.calculate_delivery_batches(campaign, len(rest), start_local=now_datetime())
		mail._reschedule_recipient_batches(rest, batches)
		frappe.db.set_value("Email Campaign", {"name": ["in", [row.name for row in rest]]}, "custom_ab_variant", winner, update_modified=False)
		frappe.db.set_value("Campaign", campaign_name, "custom_last_scheduled_at", batches[-1].scheduled_at, update_modified=False)
	frappe.db.set_value("Campaign", campaign_name, {"custom_ab_status": "Decided", "custom_ab_winner": winner}, update_modified=False)
	return {"winner": winner, "stats": stats, "released": len(rest)}


def decide_due_tests():
	"""Scheduler job: decide every test whose time is over."""
	if not frappe.db.has_column("Campaign", "custom_ab_status"):
		return
	for name in frappe.get_all(
		"Campaign",
		filters={"custom_ab_status": "Testing", "custom_ab_ends_at": ["<=", now_datetime()]},
		pluck="name",
		limit_page_length=50,
	):
		try:
			decide(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"A/B test decision failed for {name}")
