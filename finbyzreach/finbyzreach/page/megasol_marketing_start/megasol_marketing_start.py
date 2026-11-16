"""Small, permission-aware landing page over the existing marketing apps."""

import frappe
from frappe.utils import cint

from finbyzreach.finbyzreach.page.email_campaign_report.email_campaign_report import _rates, _summary

UPCOMING_LIMIT = 8
RECENT_LIMIT = 3
UPCOMING_STATUSES = ("Draft", "Preparing Audience", "Scheduled", "Sending", "Paused")
CAMPAIGN_FIELDS = (
    "name", "campaign_name", "custom_email_template", "custom_broadcast_status",
    "custom_start_on", "custom_last_scheduled_at", "custom_queued", "modified",
)


def _allowed(doctype, ptype="read"):
    return bool(frappe.db.exists("DocType", doctype) and frappe.has_permission(doctype, ptype))


def _form_teams():
    if "forms_pro" not in frappe.get_installed_apps() or "Forms Pro User" not in frappe.get_roles():
        return []
    from forms_pro.utils.teams import get_user_teams

    # This lookup must never create a team just because the Start page was opened.
    return [{"value": team.name, "label": team.team_name} for team in get_user_teams(create_if_empty=False)]


def _campaign_row(row):
    from finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio import _system_to_studio_datetime

    scheduled = _system_to_studio_datetime(row.custom_start_on) if row.custom_start_on else None
    return {
        "name": row.name,
        "title": row.campaign_name or row.name,
        "template": row.custom_email_template,
        "status": "Preparing Audience" if row.custom_queued else row.custom_broadcast_status or "Draft",
        "scheduled_at": str(scheduled) if scheduled else None,
    }


@frappe.whitelist(methods=["GET"])
def get_start_data():
    teams = _form_teams()
    result = {
        "first_name": frappe.get_cached_value("User", frappe.session.user, "first_name") or "",
        "timezone": "Europe/Zurich",
        "actions": {
            "email": _allowed("Campaign", "create") and (
                _allowed("Lead") or (_allowed("Customer") and _allowed("Contact"))
            ),
            "segment": _allowed("Reach Segment", "create"),
            "workflow": _allowed("Automation Workflow", "create") and bool(
                {"Automation Builder", "Automation Publisher", "System Manager"}.intersection(frappe.get_roles())
            ),
            "form": bool(teams),
        },
        "form_teams": teams,
        "can_read_campaigns": _allowed("Campaign"),
        "can_read_statistics": _allowed("Campaign") and _allowed("Email Campaign"),
        "upcoming": [],
        "recent": [],
    }
    if not result["can_read_campaigns"]:
        return result
    filters = {"custom_email_template": ["is", "set"]}
    upcoming = frappe.get_list(
        "Campaign", fields=list(CAMPAIGN_FIELDS),
        filters={**filters, "custom_broadcast_status": ["in", UPCOMING_STATUSES]},
        order_by="custom_broadcast_status desc, custom_start_on asc, modified desc", limit_page_length=UPCOMING_LIMIT,
    )
    result["upcoming"] = [_campaign_row(row) for row in upcoming]
    if not result["can_read_statistics"]:
        return result
    recent = frappe.get_list(
        "Campaign", fields=list(CAMPAIGN_FIELDS),
        filters={**filters, "custom_sent_count": [">", 0]},
        order_by="custom_last_scheduled_at desc, modified desc", limit_page_length=RECENT_LIMIT,
    )
    names = [row.name for row in recent]
    skipped = {}
    if names:
        skipped = {row.campaign_name: cint(row.skipped) for row in frappe.get_list(
            "Email Campaign", fields=["campaign_name", {"COUNT": "name", "as": "skipped"}],
            filters={"campaign_name": ["in", names], "custom_delivery_status": "Skipped"},
            group_by="campaign_name", limit_page_length=RECENT_LIMIT,
        )}
    for row in recent:
        counts = _summary([row.name])
        result["recent"].append({
            **_campaign_row(row), "sent": cint(counts.get("sent")),
            "delivered": counts.get("delivered"), "click_rate": _rates(counts)["click_rate"],
            "unsubscribed": cint(counts.get("unsubscribed")), "skipped": skipped.get(row.name, 0),
        })
    return result
