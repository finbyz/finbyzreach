"""Permission-checked folder actions shared by the native Reach list sidebars."""

import frappe
from frappe import _

ROOTS = {
    "Email Folder": "All Email Folders",
    "Email Template Folder": "All Email Template Folders",
    "Reach Segment Folder": "All Reach Segment Folders",
    "Automation Workflow Folder": None,
    "FP Form Folder": None,
}


@frappe.whitelist(methods=["POST"])
def rename_folder(doctype: str, name: str, new_name: str):
    if doctype not in ROOTS:
        frappe.throw(_("This folder type cannot be renamed."))
    folder = frappe.get_doc(doctype, name)
    folder.check_permission("write")
    if name == ROOTS[doctype]:
        frappe.throw(_("The root folder cannot be renamed."))
    new_name = (new_name or "").strip()
    if not new_name or len(new_name) > 140:
        frappe.throw(_("Enter a folder name between 1 and 140 characters."))
    if doctype == "Automation Workflow Folder":
        return _rename_workflow_folder(folder, new_name)
    if name == new_name:
        return {"name": name, "renamed_folders": {name: name}}
    # Form folders have field-based names but no generic Desk rename action.
    # This dedicated action still enforces native document write permissions.
    options = {"force": True} if doctype == "FP Form Folder" else {}
    renamed = frappe.rename_doc(doctype, name, new_name, show_alert=False, **options)
    return {"name": renamed, "renamed_folders": {name: renamed}}


def _rename_workflow_folder(folder, label):
    # Workflow folders use path identities, while Workflow.folder is a Data
    # field. Native renaming handles parent Links; update the Data field too.
    if "/" in label or label in {".", ".."}:
        frappe.throw(_("Enter one valid folder name without a slash."))
    doctype = "Automation Workflow Folder"
    old = folder.name
    parent = old.rsplit("/", 1)[0] if "/" in old else ""
    new = f"{parent}/{label}" if parent else label
    if new == old:
        return {"name": old, "renamed_folders": {old: old}}
    candidates = frappe.get_all(doctype, filters={"name": ["like", f"{old}/%"]},
        pluck="name", order_by="name asc", limit_page_length=0)
    # A literal prefix check prevents SQL LIKE wildcards in folder names
    # (for example QA_2026 or 50% off) from including unrelated folders.
    names = [old, *(value for value in candidates if value.startswith(old + "/"))]
    renamed = {value: new + value[len(old):] for value in names}
    for source, target in renamed.items():
        frappe.get_doc(doctype, source).check_permission("write")
        if len(target) > 140:
            frappe.throw(_("The new name makes a subfolder path longer than 140 characters."))
        if frappe.db.exists(doctype, target):
            frappe.throw(_("A folder with this name already exists here."))
    for source, target in renamed.items():
        # Only this path-aware action may rename the otherwise non-renamable
        # Workflow Folder DocType. Native document permissions still apply.
        frappe.rename_doc(doctype, source, target, force=True, show_alert=False)
        frappe.db.set_value(doctype, target, "folder_name", target.rsplit("/", 1)[-1])
        frappe.db.set_value("Automation Workflow", {"folder": source}, "folder", target, update_modified=False)
    return {"name": new, "renamed_folders": renamed}
