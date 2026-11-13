from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from finbyzreach import segments
from finbyzreach.patches.v1_0 import remove_segment_user_permissions as cleanup


class NativeSegmentPermissionTest(TestCase):
    def test_export_uses_native_read_and_export_without_requiring_write(self):
        doc = MagicMock(audience_doctype='Contact')
        doc.get.return_value = None
        with patch.object(frappe, 'get_doc', return_value=doc), patch.object(frappe, 'has_permission', return_value=True), \
             patch.object(segments, 'effective_columns',return_value=['name']), \
             patch.object(frappe.local, 'session', frappe._dict(user='reader@example.invalid'), create=True), \
             patch.object(frappe, 'enqueue') as enqueue:
            result = segments.request_segment_export('SEGMENT')
        self.assertEqual([call.args for call in doc.check_permission.call_args_list], [('read',), ('export',)])
        self.assertIn('job_id', result)
        self.assertTrue(enqueue.call_args.kwargs['enqueue_after_commit'])

    def test_export_denial_cannot_enqueue_a_job(self):
        doc = MagicMock(audience_doctype='Contact')
        doc.check_permission.side_effect = [None, frappe.PermissionError]
        with patch.object(frappe, 'get_doc', return_value=doc), patch.object(frappe, 'has_permission', return_value=True), \
             patch.object(frappe, 'enqueue') as enqueue:
            with self.assertRaises(frappe.PermissionError):
                segments.request_segment_export('SEGMENT')
        enqueue.assert_not_called()

    def test_direct_export_rechecks_native_export_permission(self):
        doc = MagicMock()
        doc.check_permission.side_effect = frappe.PermissionError
        with patch.object(segments, '_segment', return_value=doc), patch('finbyzreach.segment_service.member_names') as members:
            with self.assertRaises(frappe.PermissionError):
                segments.export_segment('SEGMENT')
        doc.check_permission.assert_called_once_with('export')
        members.assert_not_called()

    def test_cleanup_only_removes_the_obsolete_user_fields(self):
        with patch.object(cleanup, 'delete_custom_fields') as delete:
            cleanup.execute()
        fields = delete.call_args.args[0]
        self.assertEqual(set(fields), {'User'})
        self.assertEqual(set(fields['User']), {
            'custom_segment_permissions_section', 'custom_segment_permissions_enabled',
            'custom_segment_read', 'custom_segment_edit', 'custom_segment_delete',
        })

    def test_historical_patches_do_not_reinstall_custom_fields(self):
        from finbyzreach.patches.v1_0 import add_segment_user_permissions, secure_segment_user_permissions
        with patch('frappe.custom.doctype.custom_field.custom_field.create_custom_fields') as create:
            add_segment_user_permissions.execute()
            secure_segment_user_permissions.execute()
        create.assert_not_called()
