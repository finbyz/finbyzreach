from __future__ import annotations

from datetime import date, timedelta
import json

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
COMPLETED_STATUSES = ("Sent", "Failed", "Bounced", "Soft-Bounced", "Marked As Spam")
COHORT_TIME = "coalesce(q.modified, ec.modified)"
AGGREGATE_FIELDS = ("eligible", "sent", "failed", "hard_bounce", "soft_bounce", "spam", "opened", "clicked", "unsubscribed", "replied")
COHORT_NOTE = (
    "Period membership uses Email Queue update time, or the recipient update time when no queue exists. "
    "Older send dates may be approximate if these records were updated later. Engagement includes later recorded actions."
)


def _campaign_names(scope, value):
    frappe.has_permission("Campaign", "read", throw=True)
    frappe.has_permission("Email Campaign", "read", throw=True)
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


def _period_range(period="previous_month", from_date=None, to_date=None):
    if period == "custom":
        first, last, label = _timeline_range(30, from_date, to_date)
    elif period == "previous_month":
        if from_date or to_date:
            frappe.throw(_("Custom dates require the Custom period"))
        first_of_month = getdate(nowdate()).replace(day=1)
        last = first_of_month - timedelta(days=1)
        first = last.replace(day=1)
        label = _("Previous calendar month: {0} to {1}").format(first.isoformat(), last.isoformat())
    elif str(period) in ("7", "30", "90"):
        if from_date or to_date:
            frappe.throw(_("Custom dates require the Custom period"))
        first, last, label = _timeline_range(period)
    else:
        frappe.throw(_("Choose a valid period"))
    return first, last, {"from_date": first.isoformat(), "to_date": last.isoformat(), "label": label}


def _read_reporting_permissions():
    for doctype in ("Campaign", "Email Campaign", "Lead"):
        frappe.has_permission(doctype, "read", throw=True)


def _broadcast_names():
    _read_reporting_permissions()
    return [
        row.name for row in frappe.get_list(
            "Campaign", filters={"custom_email_template": ["is", "set"]},
            fields=["name", "custom_email_template"], limit_page_length=0,
        ) if row.custom_email_template
    ]


@frappe.whitelist()
def get_comparison_options(scope="campaign"):
    _read_reporting_permissions()
    if scope not in ("campaign", "template"):
        frappe.throw(_("Choose a valid comparison type"))
    campaigns = frappe.get_list(
        "Campaign", filters={"custom_email_template": ["is", "set"]},
        fields=["name", "custom_email_template"], limit_page_length=0,
    )
    if scope == "campaign":
        return sorted(row.name for row in campaigns if row.custom_email_template)
    frappe.has_permission("Email Template", "read", throw=True)
    template_names = {row.custom_email_template for row in campaigns if row.custom_email_template}
    if not template_names:
        return []
    return frappe.get_list(
        "Email Template", filters={"name": ["in", sorted(template_names)]},
        pluck="name", limit_page_length=0, order_by="name asc",
    )


def _empty_aggregate():
    return {**{key: 0 for key in AGGREGATE_FIELDS}, "delivered": None}


def _rates(counts):
    accepted = sum(cint(counts.get(key)) for key in ("sent", "hard_bounce", "soft_bounce", "spam"))
    completed = accepted + cint(counts.get("failed"))
    return {
        "accepted": accepted,
        "completed": completed,
        "acceptance_rate": round(100 * accepted / completed, 1) if completed else None,
        "open_rate": round(100 * cint(counts.get("opened")) / accepted, 1) if accepted else None,
        "click_rate": round(100 * cint(counts.get("clicked")) / accepted, 1) if accepted else None,
        "reply_rate": round(100 * cint(counts.get("replied")) / accepted, 1) if accepted else None,
    }


def _cohort_rows(names, first, last, daily=False):
    if not names:
        return []
    grouped = "date(cohort_time), ec.campaign_name" if daily else "ec.campaign_name"
    day_column = "date(cohort_time) as day," if daily else ""
    rows = []
    for offset in range(0, len(names), 500):
        batch = names[offset:offset + 500]
        rows.extend(frappe.db.sql(
            f"""
            select ec.campaign_name, {day_column}
                count(*) eligible,
                sum(effective_status = 'Sent') sent,
                sum(effective_status = 'Failed') failed,
                sum(effective_status = 'Bounced') hard_bounce,
                sum(effective_status = 'Soft-Bounced') soft_bounce,
                sum(effective_status = 'Marked As Spam') spam,
                sum(ec.custom_opened = 1) opened,
                sum(ec.custom_clicked = 1) clicked,
                sum(ec.custom_unsubscribed = 1) unsubscribed,
                sum(({REPLY_CONDITION})) replied
            from (
                select ec.name, ec.campaign_name, ec.custom_communication, ec.custom_recipient_email,
                    ec.custom_opened, ec.custom_clicked, ec.custom_unsubscribed, ec.custom_replied,
                    {EFFECTIVE_STATUS} effective_status, {COHORT_TIME} cohort_time
                from `tabEmail Campaign` ec
                left join `tabEmail Queue` q on q.name = ec.custom_email_queue
                left join `tabCommunication` comm on comm.name = ec.custom_communication
                where {_where(batch)}
            ) ec
            where effective_status in ({', '.join(['%s'] * len(COMPLETED_STATUSES))})
                and cohort_time >= %s and cohort_time < %s
            group by {grouped}
            """,
            [*batch, *COMPLETED_STATUSES, first, last + timedelta(days=1)],
            as_dict=True,
        ))
    return rows


def _add_counts(target, row):
    for key in AGGREGATE_FIELDS:
        target[key] += cint(row.get(key))


@frappe.whitelist()
def get_overview(period="previous_month", from_date=None, to_date=None):
    first, last, selected_range = _period_range(period, from_date, to_date)
    names = _broadcast_names()
    summary = _empty_aggregate()
    daily = {}
    for row in _cohort_rows(names, first, last, daily=True):
        _add_counts(summary, row)
        day = str(row.day)
        _add_counts(daily.setdefault(day, _empty_aggregate()), row)
    return {
        "summary": {**summary, **_rates(summary)},
        "trend": [
            {"date": str(first + timedelta(days=offset)), **daily.get(str(first + timedelta(days=offset)), _empty_aggregate())}
            for offset in range((last - first).days + 1)
        ],
        "campaign_count": len(names),
        "range": selected_range,
        "note": _(COHORT_NOTE),
    }


@frappe.whitelist()
def get_comparison(scope="campaign", values=None, period="previous_month", from_date=None, to_date=None):
    first, last, selected_range = _period_range(period, from_date, to_date)
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            frappe.throw(_("Select 2 to 5 campaigns or email templates"))
    if scope not in ("campaign", "template") or not isinstance(values, list) or not 2 <= len(values) <= 5 or any(not isinstance(value, str) or not value.strip() for value in values) or len(set(values)) != len(values):
        frappe.throw(_("Select 2 to 5 distinct campaigns or email templates"))
    selections = {}
    for value in values:
        selections[value] = _campaign_names(scope, value)
    all_names = list(dict.fromkeys(name for names in selections.values() for name in names))
    counts_by_campaign = {name: _empty_aggregate() for name in all_names}
    for row in _cohort_rows(all_names, first, last):
        _add_counts(counts_by_campaign[row.campaign_name], row)
    results = []
    for value, names in selections.items():
        summary = _empty_aggregate()
        for name in names:
            _add_counts(summary, counts_by_campaign[name])
        results.append({"name": value, "campaign_count": len(names), "summary": {**summary, **_rates(summary)}})
    return {"scope": scope, "items": results, "range": selected_range, "note": _(COHORT_NOTE)}


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
        select ec.name, ec.campaign_name, ec.recipient lead, ec.email_campaign_for audience_doctype,
               ec.custom_contact contact,
               ec.custom_recipient_email email, ec.custom_error_message error,
               {timestamp} action_time
        {base}
        order by action_time desc, ec.name desc
        limit %s offset %s
        """,
        [*timestamp_args, *names, *condition_args, PAGE_SIZE, (page - 1) * PAGE_SIZE],
        as_dict=True,
    )
    lead_names = list({row.lead for row in rows if row.lead and row.audience_doctype == "Lead"})
    customer_names = list({row.lead for row in rows if row.lead and row.audience_doctype == "Customer"})
    lead_labels = {row.name: row.lead_name or row.name for row in frappe.get_list(
        "Lead", filters={"name": ["in", lead_names]}, fields=["name", "lead_name"], limit_page_length=0,
    )} if lead_names and frappe.has_permission("Lead", "read") else {}
    customer_labels = {row.name: row.customer_name or row.name for row in frappe.get_list(
        "Customer", filters={"name": ["in", customer_names]}, fields=["name", "customer_name"], limit_page_length=0,
    )} if customer_names and frappe.has_permission("Customer", "read") else {}
    contact_names = list({row.contact for row in rows if row.contact})
    contact_labels = {row.name: row.full_name or row.name for row in frappe.get_list(
        "Contact", filters={"name": ["in", contact_names]}, fields=["name", "full_name"], limit_page_length=0,
    )} if contact_names and frappe.has_permission("Contact", "read") else {}
    for row in rows:
        if row.audience_doctype == "Customer":
            row["full_name"] = customer_labels.get(row.lead, row.lead or row.email)
            if row.contact:
                row["full_name"] += " / " + contact_labels.get(row.contact, row.contact)
        else:
            row["full_name"] = lead_labels.get(row.lead, row.lead or row.email)
    return {"rows": rows, "total": total, "page": page, "page_size": PAGE_SIZE}
