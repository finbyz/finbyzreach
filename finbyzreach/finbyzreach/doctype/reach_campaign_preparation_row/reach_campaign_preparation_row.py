import frappe
from frappe.model.document import Document


class ReachCampaignPreparationRow(Document):
    pass


def on_doctype_update():
    frappe.db.add_index('Reach Campaign Preparation Row', ['campaign', 'name'])
