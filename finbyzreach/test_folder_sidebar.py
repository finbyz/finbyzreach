from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from finbyzreach import folder_sidebar as folders


class TestFolderRename(TestCase):
    def setUp(self):
        self.document = MagicMock(name="folder")
        self.document.name = "Old"
        self.database = MagicMock()
        self.database.exists.return_value = False
        for target, kwargs in [
            ("get_doc", {"return_value": self.document}),
            ("rename_doc", {"side_effect": lambda doctype, old, new, **kw: new}),
            ("get_all", {"return_value": []}),
            ("db", {"new": self.database}),
            ("throw", {"side_effect": frappe.ValidationError}),
        ]:
            patcher = patch.object(frappe, target, **kwargs)
            setattr(self, target, patcher.start())
            self.addCleanup(patcher.stop)

    def test_native_folders_use_permission_checked_link_preserving_rename(self):
        for doctype in ["Email Folder", "Email Template Folder", "Reach Segment Folder"]:
            result = folders.rename_folder(doctype, "Old", "  New  ")
            self.assertEqual(result, {"name": "New", "renamed_folders": {"Old": "New"}})
            self.rename_doc.assert_called_with(doctype, "Old", "New", show_alert=False)
        self.assertEqual(self.document.check_permission.call_args_list, [call("write")] * 3)

    def test_readonly_folder_cannot_be_renamed(self):
        self.document.check_permission.side_effect = frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):
            folders.rename_folder("Email Folder", "Old", "New")
        self.rename_doc.assert_not_called()

    def test_only_supported_folders_are_accepted(self):
        with self.assertRaises(frappe.ValidationError):
            folders.rename_folder("User", "Old", "New")
        self.get_doc.assert_not_called()

    def test_roots_and_blank_labels_are_rejected(self):
        for doctype, root in folders.ROOTS.items():
            if root:
                with self.assertRaises(frappe.ValidationError):
                    folders.rename_folder(doctype, root, "New")
        with self.assertRaises(frappe.ValidationError):
            folders.rename_folder("Email Folder", "Old", "   ")
        self.rename_doc.assert_not_called()

    def test_workflow_paths_and_data_references_follow_parent_rename(self):
        self.document.name = "QA_2026"
        self.get_all.return_value = ["QA_2026/Child", "QAX2026/Unrelated"]
        result = folders.rename_folder("Automation Workflow Folder", "QA_2026", "New")
        self.assertEqual(result["renamed_folders"], {"QA_2026": "New", "QA_2026/Child": "New/Child"})
        self.assertEqual(self.rename_doc.call_count, 2)
        self.rename_doc.assert_has_calls([
            call("Automation Workflow Folder", "QA_2026", "New", force=True, show_alert=False),
            call("Automation Workflow Folder", "QA_2026/Child", "New/Child", force=True, show_alert=False),
        ])
        self.database.set_value.assert_any_call("Automation Workflow", {"folder": "QA_2026/Child"}, "folder", "New/Child", update_modified=False)

    def test_all_workflow_descendants_need_write_permission_before_any_change(self):
        self.get_all.return_value = ["Old/Child"]
        child = MagicMock()
        child.check_permission.side_effect = frappe.PermissionError
        self.get_doc.side_effect = lambda doctype, name: child if name == "Old/Child" else self.document
        with self.assertRaises(frappe.PermissionError):
            folders.rename_folder("Automation Workflow Folder", "Old", "New")
        self.rename_doc.assert_not_called()
        self.database.set_value.assert_not_called()

    def test_workflow_conflicts_and_invalid_names_do_not_change_anything(self):
        self.database.exists.return_value = True
        with self.assertRaises(frappe.ValidationError):
            folders.rename_folder("Automation Workflow Folder", "Old", "New")
        for label in ["New/Child", ".", ".."]:
            with self.assertRaises(frappe.ValidationError):
                folders.rename_folder("Automation Workflow Folder", "Old", label)
        self.rename_doc.assert_not_called()

    def test_workflow_long_descendant_paths_are_rejected_before_writing(self):
        self.get_all.return_value = ["Old/" + "x" * 135]
        with self.assertRaises(frappe.ValidationError):
            folders.rename_folder("Automation Workflow Folder", "Old", "Longer")
        self.rename_doc.assert_not_called()
