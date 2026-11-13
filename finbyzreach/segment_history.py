"""Append-only membership changes and one size sample per segment/day."""
from hashlib import sha256

import frappe
from frappe.utils import now_datetime, today

EVENT = 'Reach Segment Membership Event'
SAMPLE = 'Reach Segment Size Sample'


def record_event(segment, record_name, event, occurrence):
    if not getattr(frappe.db, 'table_exists', lambda dt: False)(EVENT):
        return
    now = now_datetime()
    user = frappe.session.user
    key = sha256(f'{segment.name}\0{record_name}\0{event}\0{occurrence}'.encode()).hexdigest()
    frappe.db.bulk_insert(EVENT,
        ['name','creation','modified','owner','modified_by','segment','record_name','event','actor','event_time'],
        [(key,now,now,user,user,segment.name,record_name,event,user,now)], ignore_duplicates=True)


def sample_size(segment):
    if not frappe.db.table_exists(SAMPLE):
        return
    from finbyzreach.segment_service import count_members
    day = today()
    key = sha256(f'{segment.name}\0{day}'.encode()).hexdigest()
    values = dict(member_count=count_members(segment), excluded_count=segment.get('excluded_count') or 0)
    if frappe.db.exists(SAMPLE, key):
        frappe.db.set_value(SAMPLE, key, values, update_modified=False)
    else:
        frappe.get_doc(dict(doctype=SAMPLE,segment=segment.name,sample_date=day,**values)).insert(ignore_permissions=True,set_name=key)


def sample_all():
    for name in frappe.get_all('Reach Segment', filters={'archived':0}, pluck='name'):
        frappe.enqueue('finbyzreach.segment_history.sample_one', segment_name=name,
                       queue='long', enqueue_after_commit=True)


def sample_one(segment_name):
    segment = frappe.get_doc('Reach Segment', segment_name)
    if not segment.archived:
        sample_size(segment)
