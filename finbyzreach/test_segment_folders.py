from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils.nestedset import NestedSet
from finbyzreach.finbyzreach.doctype.reach_segment_folder import reach_segment_folder as folders


class SegmentFolderTest(TestCase):
    def test_uses_native_nested_set(self):
        self.assertTrue(issubclass(folders.ReachSegmentFolder, NestedSet))
        self.assertFalse(folders.ReachSegmentFolder.allow_root_deletion)

    def test_normal_folder_defaults_to_root(self):
        doc = frappe._dict(name='Swiss', folder_name='Swiss')
        doc.set = lambda key, value: doc.update({key: value})
        doc.get_doc_before_save = lambda: None
        folders.ReachSegmentFolder.validate(doc)
        self.assertEqual(doc.parent_reach_segment_folder, folders.ROOT_FOLDER)
        self.assertEqual(doc.is_group, 1)

    def test_explicit_subfolder_parent_is_preserved(self):
        doc = frappe._dict(name='Zurich', folder_name='Zurich', parent_reach_segment_folder='Swiss')
        doc.get_doc_before_save = lambda: None
        folders.ReachSegmentFolder.validate(doc)
        self.assertEqual(doc.parent_reach_segment_folder, 'Swiss')

    def test_root_cannot_move_or_be_renamed(self):
        doc = frappe._dict(name=folders.ROOT_FOLDER, folder_name=folders.ROOT_FOLDER, parent_reach_segment_folder='Swiss')
        doc.get_doc_before_save = lambda: None
        with patch.object(frappe, 'throw', side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                folders.ReachSegmentFolder.validate(doc)
            with self.assertRaises(frappe.ValidationError):
                folders.ReachSegmentFolder.before_rename(doc, folders.ROOT_FOLDER, 'Other')

    def test_migration_preserves_names_and_only_attaches_flat_folders(self):
        rows = [frappe._dict(name='Existing', parent_reach_segment_folder=None, lft=0, rgt=0, is_group=0),
                frappe._dict(name='Child', parent_reach_segment_folder='Existing', lft=2, rgt=3, is_group=1)]
        database = MagicMock()
        with patch.object(frappe.local, 'db', database, create=True), patch.object(frappe, 'get_all', return_value=rows), patch.object(frappe, 'get_doc') as get_doc, patch.object(folders, 'rebuild_tree') as rebuild:
            folders.setup_segment_folders()
        database.set_value.assert_called_once_with('Reach Segment Folder', 'Existing', {
            folders.PARENT_FIELD: folders.ROOT_FOLDER, 'old_parent': folders.ROOT_FOLDER, 'is_group': 1,
        }, update_modified=False)
        self.assertEqual(get_doc.call_args.args[0]['folder_name'], folders.ROOT_FOLDER)
        rebuild.assert_called_once_with('Reach Segment Folder')

    def test_migration_is_idempotent_for_valid_tree(self):
        rows = [frappe._dict(name=folders.ROOT_FOLDER, parent_reach_segment_folder='', lft=1, rgt=4, is_group=1),
                frappe._dict(name='Existing', parent_reach_segment_folder=folders.ROOT_FOLDER, lft=2, rgt=3, is_group=1)]
        database = MagicMock()
        with patch.object(frappe.local, 'db', database, create=True), patch.object(frappe, 'get_all', return_value=rows), patch.object(frappe, 'get_doc') as get_doc, patch.object(folders, 'rebuild_tree') as rebuild:
            folders.setup_segment_folders()
        get_doc.assert_not_called()
        database.set_value.assert_not_called()
        rebuild.assert_not_called()

    def test_stale_form_uses_server_tree_bounds_and_old_parent(self):
        doc = frappe._dict(name='Swiss', folder_name='Swiss', lft=2, rgt=3, old_parent='Wrong', parent_reach_segment_folder='New')
        doc.set = lambda key, value: doc.update({key: value})
        doc.get_doc_before_save = lambda: frappe._dict(lft=2, rgt=9, old_parent=folders.ROOT_FOLDER)
        folders.ReachSegmentFolder.validate(doc)
        self.assertEqual((doc.lft,doc.rgt,doc.old_parent),(2,9,folders.ROOT_FOLDER))
        self.assertEqual(doc.parent_reach_segment_folder,'New')
