from __future__ import annotations

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate


PAGE_SIZE = 25
METRICS = (
    "sent", "delivered", "opened", "clicked", "unsubscribed",
    "hard_bounce", "soft_bounce", "spam", "replied", "failed",
)
FIELD_METRICS = {
    "opened": ("custom_opened", "custom_opened_on"),
    "clicked": ("custom_clicked", "custom_clicked_on"),
    "unsubscribed": ("custom_unsubscribed", "custom_unsubscribed_on"),
    "replied": ("custom_replied", "custom_replied_on"),
}
FEEDBACK_METRICS = {
    "hard_bounce": "Bounced",
    "soft_bounce": "Soft-Bounced",
    "spam": "Marked As Spam",
}
EFFECTIVE_STATUS = (
    "case when comm.delivery_status in ('Bounced', 'Soft-Bounced', 'Marked As Spam') "
    "then comm.delivery_status else ec.custom_delivery_status end"
)
REPLY_CONDITION = (
    "ec.custom_replied = 1 and exists ("
    "select 1 from `tabCommunication` reply "
    "where reply.in_reply_to = ec.custom_communication "
    "and reply.sent_or_received = 'Received' "
    "and lower(trim(reply.sender)) = lower(trim(ec.custom_recipient_email)))"
)


def _campaign_names(scope, value):
    frappe.has_permission("Campaign", "read", throw=True)
    frappe.has_permission("Email Campaign", "read", throw=True)
    frappe.has_permission("Lead", "read", throw=True)
    if scope not in ("campaign", "template") or not value:
        frappe.throw(_("Select a campaign or email template"))
    value = str(value)
    if scope == "campaign":
        campaign = frappe.get_doc("Campaign", value)
        campaign.check_permission("read")
        if not campaign.custom_email_template:
            frappe.throw(_("Select an email broadcast campaign"))
        return [campaign.name]
    frappe.has_permission("Email Template", "read", throw=True)
    if not frappe.db.exists("Email Template", value):
        frappe.throw(_("Email Template does not exist"))
    return frappe.get_list(
        "Campaign",
        filters={"custom_email_template": value},
        pluck="name",
        limit_page_length=0,
    )


def _where(names, alias="ec"):
    return f"{alias}.campaign_name in ({', '.join(['%s'] * len(names))})"


def _summary(names):
    if not names:
        return {"eligible": 0, **{key: (None if key == "delivered" else 0) for key in METRICS}}
    rows = frappe.db.sql(
        f"""
        select
            sum(ec.custom_delivery_status not in ('Skipped', 'Cancelled')) eligible,
            sum(({EFFECTIVE_STATUS}) = 'Sent') sent,
            sum(({EFFECTIVE_STATUS}) = 'Failed') failed,
            sum(({EFFECTIVE_STATUS}) = 'Bounced') hard_bounce,
            sum(({EFFECTIVE_STATUS}) = 'Soft-Bounced') soft_bounce,
            sum(({EFFECTIVE_STATUS}) = 'Marked As Spam') spam,
            sum(ec.custom_opened = 1) opened,
            sum(ec.custom_clicked = 1) clicked,
            sum(ec.custom_unsubscribed = 1) unsubscribed,
            sum(({REPLY_CONDITION})) replied
        from `tabEmail Campaign` ec
        left join `tabCommunication` comm on comm.name = ec.custom_communication
        where {_where(names)}
        """,
        names,
        as_dict=True,
    )
    data = {key: cint(value) for key, value in (rows[0] if rows else {}).items()}
    data["delivered"] = None
    return data


def _timeline_range(days, from_date=None, to_date=None):
    if from_date or to_date:
        if not from_date or not to_date:
            frappe.throw(_("Select both From Date and To Date"))
        try:
            first_day = date.fromisoformat(str(from_date))
            last_day = date.fromisoformat(str(to_date))
        except ValueError:
            frappe.throw(_("Enter valid timeline dates"))
        if first_day > last_day:
            frappe.throw(_("From Date must be on or before To Date"))
        if (last_day - first_day).days >= 366:
            frappe.throw(_("Select no more than 366 days for the timeline"))
        label = _("{0} to {1}").format(first_day.isoformat(), last_day.isoformat())
    else:
        days = cint(days)
        if days not in (7, 30, 90):
            frappe.throw(_("Choose a 7, 30, or 90 day timeline"))
        last_day = getdate(nowdate())
        first_day = last_day - timedelta(days=days - 1)
        label = _("Last {0} days").format(days)
    return first_day, last_day, label


def _trend(names, first_day, last_day):
    if not names:
        return []
    end_exclusive = last_day + timedelta(days=1)
    series = {}
    for metric, (flag, timestamp) in FIELD_METRICS.items():
        condition = f"({REPLY_CONDITION})" if metric == "replied" else f"ec.`{flag}` = 1"
        rows = frappe.db.sql(
            f"""
            select date(ec.`{timestamp}`) day, count(*) total
            from `tabEmail Campaign` ec
            where {_where(names)} and {condition}
              and ec.`{timestamp}` >= %s and ec.`{timestamp}` < %s
            group by date(ec.`{timestamp}`)
            """,
            [*names, first_day, end_exclusive],
            as_dict=True,
        )
        for row in rows:
            series.setdefault(str(row.day), {})[metric] = cint(row.total)
    for metric, status in (
        ("sent", "Sent"), ("failed", "Failed"),
        ("hard_bounce", "Bounced"), ("soft_bounce", "Soft-Bounced"),
        ("spam", "Marked As Spam"),
    ):
        if metric == "sent":
            action_time = "q.modified"
        elif metric == "failed":
            action_time = "coalesce(q.modified, ec.modified)"
        else:
            action_time = "coalesce(comm.modified, ec.modified)"
        rows = frappe.db.sql(
            f"""
            select date({action_time}) day, count(*) total
            from `tabEmail Campaign` ec
            left join `tabEmail Queue` q on q.name = ec.custom_email_queue
            left join `tabCommunication` comm on comm.name = ec.custom_communication
            where {_where(names)} and ({EFFECTIVE_STATUS}) = %s
              and {action_time} >= %s and {action_time} < %s
            group by date({action_time})
            """,
            [*names, status, first_day, end_exclusive],
            as_dict=True,
        )
        for row in rows:
            series.setdefault(str(row.day), {})[metric] = cint(row.total)
    return [
        {"date": str(first_day + timedelta(days=offset)), **series.get(str(first_day + timedelta(days=offset)), {})}
        for offset in range((last_day - first_day).days + 1)
    ]


@frappe.whitelist()
def get_report(scope="campaign", value=None, days=30, from_date=None, to_date=None):
    first_day, last_day, range_label = _timeline_range(days, from_date, to_date)
    names = _campaign_names(scope, value)
    return {
        "summary": _summary(names),
        "trend": _trend(names, first_day, last_day),
        "campaign_count": len(names),
        "days": (last_day - first_day).days + 1,
        "range": {"from_date": first_day.isoformat(), "to_date": last_day.isoformat(), "label": range_label},
        "notes": {
            "delivered": _("Inbox delivery receipts are not available; Sent means the mail server accepted the message."),
            "hard_bounce": _("Recorded Frappe Communication Bounced statuses. Missing provider feedback cannot be counted."),
            "soft_bounce": _("Recorded Frappe Communication Soft-Bounced statuses. Missing provider feedback cannot be counted."),
            "spam": _("Recorded Frappe Communication Marked As Spam statuses. Zero does not prove no complaints occurred."),
            "timeline": _("Sent dates use mail queue time; bounce and spam dates use Communication update time. Engagement dates use the first recorded action."),
        },
    }


@frappe.whitelist()
def get_details(scope="campaign", value=None, metric="opened", page=1):
    if metric not in METRICS:
        frappe.throw(_("Invalid metric"))
    names = _campaign_names(scope, value)
    page = max(1, cint(page))
    if not names or metric == "delivered":
        return {"rows": [], "total": 0, "page": page, "page_size": PAGE_SIZE}

    if metric in FIELD_METRICS:
        flag, field = FIELD_METRICS[metric]
        condition = f"({REPLY_CONDITION})" if metric == "replied" else f"ec.`{flag}` = 1"
        condition_args = []
        timestamp, timestamp_args = f"ec.`{field}`", []
    else:
        status = FEEDBACK_METRICS.get(metric, "Sent" if metric == "sent" else "Failed")
        condition, condition_args = f"({EFFECTIVE_STATUS}) = %s", [status]
        if metric == "sent":
            timestamp = "q.modified"
        elif metric == "failed":
            timestamp = "coalesce(q.modified, ec.modified)"
        else:
            timestamp = "coalesce(comm.modified, ec.modified)"
        timestamp_args = []

    base = f"""from `tabEmail Campaign` ec
        left join `tabEmail Queue` q on q.name = ec.custom_email_queue
        left join `tabCommunication` comm on comm.name = ec.custom_communication
        where {_where(names)} and {condition}"""
    total = cint(frappe.db.sql(f"select count(*) {base}", [*names, *condition_args])[0][0])
    rows = frappe.db.sql(
        f"""
        select ec.name, ec.campaign_name, ec.recipient lead,
               ec.custom_recipient_email email, ec.custom_error_message error,
               {timestamp} action_time
        {base}
        order by action_time desc, ec.name desc
        limit %s offset %s
        """,
        [*timestamp_args, *names, *condition_args, PAGE_SIZE, (page - 1) * PAGE_SIZE],
        as_dict=True,
    )
    lead_names = list({row.lead for row in rows if row.lead})
    lead_labels = {}
    if lead_names:
        lead_labels = {
            row.name: row.lead_name or row.name
            for row in frappe.get_list(
                "Lead", filters={"name": ["in", lead_names]},
                fields=["name", "lead_name"], limit_page_length=PAGE_SIZE,
            )
        }
    for row in rows:
        row["full_name"] = lead_labels.get(row.lead, row.lead or row.email)
    return {"rows": rows, "total": total, "page": page, "page_size": PAGE_SIZE}
