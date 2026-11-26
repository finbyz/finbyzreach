"""Recover campaign summaries even when their last delivery update was missed."""
import frappe
from frappe.query_builder.functions import Coalesce
from pypika.terms import ExistsCriterion

from finbyzreach.email_marketing import TERMINAL_DELIVERY_STATUSES, refresh_campaign_metrics

RECONCILE_LIMIT = 50
ACTIVE_STATUSES = ('Scheduled', 'Sending', 'Paused')


def _unfinished_recipients(campaign_name):
    recipient = frappe.qb.DocType('Email Campaign')
    return (frappe.qb.from_(recipient).select(recipient.name)
            .where(recipient.campaign_name == campaign_name)
            .where(Coalesce(recipient.custom_delivery_status, '').notin(TERMINAL_DELIVERY_STATUSES)))


def finished_campaign_candidates():
    campaign = frappe.qb.DocType('Campaign')
    recipient = frappe.qb.DocType('Email Campaign')
    history = frappe.qb.from_(recipient).select(recipient.name).where(recipient.campaign_name == campaign.name)
    # Filter before LIMIT, so campaigns still sending cannot starve stale summaries.
    return (frappe.qb.from_(campaign).select(campaign.name)
            .where(campaign.custom_broadcast_status.isin(ACTIVE_STATUSES))
            .where(Coalesce(campaign.custom_queued, 0) == 0)
            .where(Coalesce(campaign.custom_email_template, '') != '')
            .where(ExistsCriterion(history))
            .where(~ExistsCriterion(_unfinished_recipients(campaign.name)))
            .orderby(campaign.modified).orderby(campaign.name)
            .limit(RECONCILE_LIMIT).run(as_dict=True))


def reconcile_campaign_metrics():
    """Scheduler-owned transactions; update summaries only, never dispatch email."""
    candidates = finished_campaign_candidates()
    for row in candidates:
        # The candidate scan's snapshot may predate a concurrent resume/retry.
        # Take a fresh transaction and the same Campaign lock used by those paths.
        frappe.db.commit()
        try:
            campaign = frappe.db.get_value('Campaign', row.name,
                ['custom_broadcast_status', 'custom_queued'], as_dict=True, for_update=True)
            if (not campaign or campaign.custom_broadcast_status not in ACTIVE_STATUSES
                    or campaign.custom_queued):
                continue
            if _unfinished_recipients(row.name).limit(1).for_update().run():
                continue
            if not frappe.db.exists('Email Campaign', {'campaign_name': row.name}):
                continue
            refresh_campaign_metrics(row.name)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title=f'Campaign summary reconciliation failed - {row.name}',
                             message=frappe.get_traceback())
        finally:
            # Release locks on skipped/deleted campaigns too.
            frappe.db.rollback()
