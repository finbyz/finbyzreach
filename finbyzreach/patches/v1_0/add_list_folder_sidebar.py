"""Add Email Template folders and indexes without changing existing assignments."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    from finbyzreach.email_template_builder.doctype.email_folder.email_folder import ROOT_FOLDER
    existing = frappe.get_meta("Email Template").get_field("custom_folder")
    if existing and (existing.fieldtype != "Link" or existing.options != "Email Folder"):
        frappe.throw("Email Template.custom_folder already belongs to another configuration")
    frappe.reload_doc("email_template_builder", "doctype", "email_folder")
    create_custom_fields({"Email Template": [{
        "fieldname": "custom_folder", "fieldtype": "Link", "label": "Folder",
        "options": "Email Folder", "insert_after": "subject", "module": "Email Template Builder",
        "in_standard_filter": 1, "in_list_view": 1, "search_index": 1,
    }]}, update=True)
    if not frappe.db.exists("Email Folder", ROOT_FOLDER):
        frappe.get_doc({"doctype": "Email Folder", "folder_name": ROOT_FOLDER}).insert(ignore_permissions=True)
    for doctype, field, index in (
        ("Reach Segment", "folder", "reach_folder_list"),
        ("Email Template Master", "folder", "master_folder_list"),
        ("Email Template", "custom_folder", "email_folder_list"),
    ):
        if frappe.db.has_column(doctype, field):
            frappe.db.add_index(doctype, [field, "name"], index)
    frappe.clear_cache(doctype="Email Template")
