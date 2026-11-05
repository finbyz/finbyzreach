from frappe.model.document import Document


class ReachSegmentMember(Document):
	pass


def on_doctype_update():
    import frappe
    frappe.db.add_unique('Reach Segment Member', ['segment', 'record_name'])
    frappe.db.add_index('Reach Segment Member', ['record_name', 'segment'])
