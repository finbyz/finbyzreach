import frappe
from frappe.model.document import Document


class ReachSegmentPendingRecord(Document):
    pass


def on_doctype_update():
    frappe.db.add_index('Reach Segment Pending Record', ['creation', 'name'])
