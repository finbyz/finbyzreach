import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet, rebuild_tree


ROOT_FOLDER = "All Reach Segment Folders"
PARENT_FIELD = "parent_reach_segment_folder"


class ReachSegmentFolder(NestedSet):
    nsm_parent_field = PARENT_FIELD
    allow_root_deletion = False

    def validate(self):
        # Other folder edits can change these bounds without changing modified.
        # Use the locked server version so stale forms cannot corrupt the tree.
        before = self.get_doc_before_save()
        if before:
            for field in ("lft", "rgt", "old_parent"):
                self.set(field, before.get(field))
        self.is_group = 1
        if self.name == ROOT_FOLDER or self.folder_name == ROOT_FOLDER:
            if self.get(PARENT_FIELD):
                frappe.throw(_("The root segment folder cannot have a parent"))
            self.folder_name = ROOT_FOLDER
        elif not self.get(PARENT_FIELD):
            self.set(PARENT_FIELD, ROOT_FOLDER)

    def on_update(self):
        super().on_update()
        self.validate_one_root()

    def before_rename(self, olddn, newdn, merge=False):
        if olddn == ROOT_FOLDER:
            frappe.throw(_("The root segment folder cannot be renamed"))
        super().before_rename(olddn, newdn, merge=merge)


def on_doctype_update():
    frappe.db.add_index("Reach Segment Folder", ["lft", "rgt"])


def setup_segment_folders():
    """Attach existing flat folders to the root without changing segment links."""
    doctype = "Reach Segment Folder"
    if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, PARENT_FIELD):
        return
    folders = frappe.get_all(doctype, fields=["name", PARENT_FIELD, "lft", "rgt", "is_group"])
    rebuild = False
    for folder in folders:
        values = {}
        if folder.name != ROOT_FOLDER and not folder.get(PARENT_FIELD):
            values.update({PARENT_FIELD: ROOT_FOLDER, "old_parent": ROOT_FOLDER})
        if not folder.is_group:
            values["is_group"] = 1
        if values:
            frappe.db.set_value(doctype, folder.name, values, update_modified=False)
        rebuild |= bool(values) or not folder.lft or not folder.rgt
    if not any(folder.name == ROOT_FOLDER for folder in folders):
        frappe.get_doc({"doctype": doctype, "folder_name": ROOT_FOLDER, "is_group": 1}).insert(ignore_permissions=True)
        rebuild = True
    if rebuild:
        rebuild_tree(doctype)
