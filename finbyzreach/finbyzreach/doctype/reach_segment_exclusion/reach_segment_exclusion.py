from frappe.model.document import Document


class ReachSegmentExclusion(Document):
	pass


def on_doctype_update():
    import frappe
    frappe.db.add_unique('Reach Segment Exclusion', ['segment', 'record_name'])
