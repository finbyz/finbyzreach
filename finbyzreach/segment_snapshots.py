"""Bounded, resumable Static snapshots; publish a generation atomically."""
import json
from hashlib import sha256

import frappe
from frappe.utils import now_datetime

ROW = 'Reach Segment Snapshot Row'
PAGE_SIZE = 500
SYNC_LIMIT = 1000


def definition(segment, as_active=True):
    keys = ('name','audience_doctype','filter_groups_json','filter_expression_json',
            'exclude_filters_json','exclude_segments_json','exclude_email_groups_json')
    result = {key:segment.get(key) for key in keys}
    result.update(segment_type='Active' if as_active else segment.segment_type)
    if not as_active:
        result.update({key:segment.get(key) for key in ('members_initialized','snapshot_generation','static_leads_json')})
    return result


def insert_rows(segment_name, generation, names):
    now = now_datetime()
    user = frappe.session.user
    frappe.db.bulk_insert(ROW,
        ['name','creation','modified','owner','modified_by','segment','generation','record_name'],
        [(sha256(f'{segment_name}\0{generation}\0{name}'.encode()).hexdigest(),now,now,user,user,
          segment_name,generation,name) for name in names], ignore_duplicates=True, chunk_size=PAGE_SIZE)


def prepare(segment, source=None):
    from finbyzreach.segment_service import member_names
    original = source
    source = definition(source or segment, as_active=source is None)
    if original and original.segment_type == 'Static' and original.name != segment.name:
        source['copy_manual_from'] = original.name
    generation = frappe.generate_hash(length=32)
    # The bounded probe keeps small saves immediate, without loading 30k IDs.
    names = member_names(frappe._dict(source), limit=SYNC_LIMIT+1,apply_exclusions=False)
    segment.snapshot_definition = json.dumps(source)
    segment.snapshot_error = None
    segment.members_initialized = 1
    segment.static_leads_json = '[]'
    if len(names) <= SYNC_LIMIT:
        if names:
            insert_rows(segment.name, generation, names)
            copy_manual(segment.name,source,names)
        segment.snapshot_generation = generation
        segment.snapshot_pending_generation = None
        segment.snapshot_status = 'Ready'
    else:
        segment.snapshot_pending_generation = generation
        segment.snapshot_status = 'Queued'
        frappe.enqueue('finbyzreach.segment_snapshots.build', segment_name=segment.name,
                       generation=generation, queue='long', enqueue_after_commit=True)


def build(segment_name, generation, after=None):
    segment = frappe.get_doc('Reach Segment', segment_name, for_update=True)
    if (segment.archived or segment.segment_type != 'Static' or
        segment.snapshot_pending_generation != generation):
        return
    from finbyzreach.segment_service import member_names
    savepoint = 'reach_snapshot_chunk'
    frappe.db.savepoint(savepoint)
    try:
        source = frappe._dict(frappe.parse_json(segment.snapshot_definition))
        # Resume after the last committed staging row if a continuation job was lost.
        if after is None:
            rows = frappe.get_all(ROW,filters={'segment':segment.name,'generation':generation},
                                  pluck='record_name',order_by='record_name desc',limit_page_length=1)
            after = rows[0] if rows else None
        names = member_names(source, after=after, limit=PAGE_SIZE,apply_exclusions=False)
        if names:
            insert_rows(segment.name, generation, names)
            copy_manual(segment.name,source,names)
        if len(names) == PAGE_SIZE:
            frappe.db.set_value('Reach Segment',segment.name,'snapshot_status','Building',update_modified=False)
            frappe.enqueue('finbyzreach.segment_snapshots.build',segment_name=segment.name,
                generation=generation,after=names[-1],queue='long',enqueue_after_commit=True)
        else:
            # No partially prepared snapshot is ever served to preview/export/mail.
            frappe.db.set_value('Reach Segment',segment.name,{
                'snapshot_generation':generation,'snapshot_pending_generation':None,
                'snapshot_status':'Ready','snapshot_error':None},update_modified=False)
            segment.reload()
            from finbyzreach.segment_service import count_members
            frappe.db.set_value('Reach Segment',segment.name,'member_count',count_members(segment),update_modified=False)
            from finbyzreach.segment_automation import schedule_reconciliation
            schedule_reconciliation(segment.name)
    except Exception:
        # A failed count or publication must leave the old generation available
        # and retain the pending generation so Retry can resume it.
        frappe.db.rollback(save_point=savepoint)
        frappe.db.set_value('Reach Segment',segment.name,{
                'snapshot_status':'Failed','snapshot_error':'Membership preparation failed. Retry or check Error Log.'},update_modified=False)
        frappe.log_error(title='Reach Segment snapshot failed')


def recover():
    for row in frappe.get_all('Reach Segment',filters={'snapshot_status':['in',['Queued','Building']],
        'archived':0},fields=['name','snapshot_pending_generation'],limit_page_length=10):
        frappe.enqueue('finbyzreach.segment_snapshots.build',segment_name=row.name,
            generation=row.snapshot_pending_generation,queue='long',enqueue_after_commit=True,
            job_id=f'reach-snapshot:{row.name}:{row.snapshot_pending_generation}',deduplicate=True)


def clean_old_rows(segment_name):
    segment = frappe.get_doc('Reach Segment',segment_name,for_update=True)
    keep = [value for value in (segment.snapshot_generation,segment.snapshot_pending_generation) if value]
    filters = {'segment':segment.name}
    if keep:
        filters['generation'] = ['not in',keep]
    rows = frappe.get_all(ROW,filters=filters,pluck='name',limit_page_length=PAGE_SIZE)
    if rows:
        frappe.db.delete(ROW,{'name':['in',rows]})
    if len(rows) == PAGE_SIZE:
        frappe.enqueue('finbyzreach.segment_snapshots.clean_old_rows',segment_name=segment.name,
                       queue='long',enqueue_after_commit=True)


def copy_manual(segment_name, source, names):
    if not source.get('copy_manual_from'):
        return
    from finbyzreach.segment_service import MEMBER, _insert_members
    manual = frappe.get_all(MEMBER,filters={'segment':source['copy_manual_from'],
        'source':'Manual','record_name':['in',names]},pluck='record_name',limit_page_length=len(names))
    if manual:
        _insert_members(segment_name,manual,source='Manual',is_current=0)
