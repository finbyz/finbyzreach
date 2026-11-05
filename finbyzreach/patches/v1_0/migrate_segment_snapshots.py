"""Move legacy static JSON snapshots to indexed membership rows."""
import frappe
from finbyzreach.segment_service import _insert_members, parsed_list


def execute():
    for row in frappe.get_all('Reach Segment', filters={'segment_type':'Static','members_initialized':0},
                              fields=['name','static_leads_json'], limit_page_length=0):
        names = parsed_list(row.static_leads_json)
        _insert_members(row.name, list(dict.fromkeys(names)))
        frappe.db.set_value('Reach Segment', row.name,
            {'members_initialized':1,'static_leads_json':'[]'}, update_modified=False)
