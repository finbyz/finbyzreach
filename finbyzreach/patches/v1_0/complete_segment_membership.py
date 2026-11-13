"""Indexes for generation snapshots, dependency routing and append-only history."""
import frappe


def execute():
    for name in ('reach_segment','reach_segment_member','reach_segment_snapshot_row',
                 'reach_segment_membership_event','reach_segment_size_sample'):
        frappe.reload_doc('finbyzreach','doctype',name)
    for doctype, fields, name in (
        ('Reach Segment Snapshot Row',['segment','generation','record_name'],'reach_snapshot_page'),
        ('Reach Segment Membership Event',['segment','creation','name'],'reach_history_page'),
        ('Reach Segment Membership Event',['segment','record_name','event_time'],'reach_record_history'),
        ('Reach Segment Member',['segment','is_current','record_name'],'reach_current_members'),
        ('Contact',['custom_reach_main_customer','name'],'reach_main_customer'),
    ):
        if all(frappe.db.has_column(doctype, field) for field in fields):
            frappe.db.add_index(doctype,fields,name)
    frappe.db.add_unique('Reach Segment Size Sample',['segment','sample_date'],'reach_daily_size')
