"""Resumable preparation: stage validated candidates, then insert bounded chunks.

The staging row and corresponding recipient are changed in one transaction.
A crash retries the same remaining stage rows, without deleting delivery history.
"""
from hashlib import sha256
from itertools import islice

import frappe
from frappe import _
from frappe.utils import now_datetime

STAGING = 'Reach Campaign Preparation Row'
CHUNK_SIZE = 200


def stage(campaign):
    from finbyzreach import email_marketing as mail
    snapshot = mail.validate_schedule_preflight(campaign)
    resolved = mail.resolve_campaign_audience(campaign)
    eligible_count = sum(bool(row.eligible) for row in resolved)
    if not eligible_count:
        frappe.throw(_('No eligible recipients remain after exclusions'))
    batches = mail.calculate_delivery_batches(campaign, eligible_count)

    def candidates():
        eligible = (row for row in resolved if row.eligible)
        for batch in batches:
            for row in islice(eligible, batch.size):
                yield mail._recipient_values(campaign, row, batch.number, batch.scheduled_at)
        for row in resolved:
            if not row.eligible:
                yield mail._recipient_values(campaign, row)

    now = now_datetime()
    user = frappe.session.user
    values = ((sha256(f'{campaign.name}\0{index}'.encode()).hexdigest(), now, now, user, user,
               campaign.name, frappe.as_json(payload)) for index, payload in enumerate(candidates()))
    # Native bulk_insert consumes iterables in bounded chunks; do not build a
    # second full audience of serialized recipient payloads in memory.
    frappe.db.bulk_insert(STAGING, ['name','creation','modified','owner','modified_by','campaign','payload'],
                          values, chunk_size=500)
    frappe.db.set_value('Campaign', campaign.name, {
        **mail._snapshot_values(snapshot), 'custom_broadcast_status': 'Preparing Audience',
        'custom_candidate_count': len(resolved), 'custom_eligible_count': eligible_count,
        'custom_excluded_count': len(resolved)-eligible_count, 'custom_batch_count': len(batches),
        'custom_first_scheduled_at': batches[0].scheduled_at,
        'custom_last_scheduled_at': batches[-1].scheduled_at,
    })


def process(campaign_name):
    from finbyzreach import email_marketing as mail
    campaign = frappe.get_doc('Campaign', campaign_name, for_update=True)
    if campaign.custom_broadcast_status != 'Draft':
        campaign.check_permission('write')
        campaign.check_permission('email')
    if campaign.custom_broadcast_status in ('Completed','Failed'):
        frappe.throw(_('Only a Draft or preparing campaign can be scheduled'))
    if campaign.custom_broadcast_status == 'Draft':
        stage(campaign)
        # Persist the frozen candidates before doing expensive document hooks.
        frappe.db.commit()
        campaign = frappe.get_doc('Campaign', campaign_name, for_update=True)
    if campaign.custom_broadcast_status != 'Preparing Audience':
        return
    rows = frappe.get_all(STAGING, filters={'campaign': campaign.name},
                          fields=['name','payload'], order_by='name asc', limit_page_length=CHUNK_SIZE)
    for row in rows:
        mail._insert_scheduled_recipient(frappe.parse_json(row.payload))
        frappe.db.delete(STAGING, {'name': row.name})
    remaining = frappe.db.count(STAGING, {'campaign': campaign.name})
    if remaining:
        frappe.enqueue('finbyzreach.email_marketing.schedule_campaign', campaign_name=campaign.name,
                       queue='long', enqueue_after_commit=True, job_id=f'reach-prepare:{campaign.name}:{remaining}', deduplicate=True)
    else:
        frappe.db.set_value('Campaign', campaign.name, {'custom_broadcast_status':'Scheduled', 'custom_queued':0})
    return {'remaining': remaining}


def recover_preparations():
    if not frappe.db.table_exists(STAGING):
        return
    for name in frappe.get_all('Campaign', filters={'custom_broadcast_status':'Preparing Audience'},
                               pluck='name', limit_page_length=10):
        remaining = frappe.db.count(STAGING, {'campaign':name})
        frappe.enqueue('finbyzreach.email_marketing.schedule_campaign', campaign_name=name,
                       queue='long', enqueue_after_commit=True, job_id=f'reach-prepare:{name}:{remaining}', deduplicate=True)
