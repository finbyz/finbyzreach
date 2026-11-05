from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from finbyzreach.email_template_builder.schema import _visibility
from finbyzreach.email_template_builder.compiler import _conditions
from finbyzreach.segment_automation import referenced_segments
from finbyzreach import segment_permissions


class SegmentIntegrationTest(TestCase):
    def setUp(self):
        frappe.local.conf=frappe._dict()
        frappe.local.flags=frappe._dict()
        frappe.local.session=frappe._dict(user='review@example.invalid')
    def test_segment_visibility_survives_normalization_and_compilation(self):
        value=_visibility({'segment_conditions':[{'segment':'Swiss customers','member':True}],'match':'all'})
        html=_conditions(value,'<p>Member offer</p>')
        self.assertIn('is_segment_member("Swiss customers", doc)',html)
        self.assertIn('Member offer',html)
    def test_nonmember_visibility_compiles_negation(self):
        value=_visibility({'segment_conditions':[{'segment':'Swiss customers','member':False}]})
        self.assertIn('not is_segment_member',_conditions(value,'Offer'))
    def test_publication_dependencies_use_actual_event_filter_shape(self):
        graph={'nodes':[{'config':{'event_topic':'crm.segment.entered','event_filter':{
            'kind':'predicate','field':'segment','operator':'eq','value':'Swiss customers'}}}]}
        self.assertEqual(referenced_segments(graph),{'Swiss customers'})
    def test_unrestricted_segment_trigger_protects_all_segments(self):
        graph={'nodes':[{'config':{'event_topic':'crm.segment.entered'}}]}
        self.assertEqual(referenced_segments(graph),{'*'})
    def test_user_read_only_setting_denies_export_and_delete(self):
        values=frappe._dict(custom_segment_permissions_enabled=1,custom_segment_read=1,custom_segment_edit=0,custom_segment_delete=0)
        with patch.object(frappe,'get_meta',return_value=MagicMock()),patch.object(frappe,'get_cached_value',return_value=values):
            self.assertTrue(segment_permissions.setting('read'))
            self.assertFalse(segment_permissions.setting('export'))
            self.assertFalse(segment_permissions.setting('delete'))
    def test_user_without_read_gets_no_segment_rows(self):
        values=frappe._dict(custom_segment_permissions_enabled=1,custom_segment_read=0)
        with patch.object(frappe,'get_meta',return_value=MagicMock()),patch.object(frappe,'get_cached_value',return_value=values):
            self.assertEqual(segment_permissions.query_conditions(),'1=0')

    def test_default_permission_passes_through_actual_frappe_hook_dispatch(self):
        from frappe.permissions import has_controller_permissions
        hooks = {'Reach Segment': [segment_permissions.has_permission]}
        doc = frappe._dict(doctype='Reach Segment', name='TEST')
        with patch.object(frappe, 'get_hooks', return_value=hooks), patch.object(segment_permissions, 'setting', return_value=None):
            self.assertTrue(has_controller_permissions(doc, 'read', user='ordinary@example.invalid'))
            self.assertTrue(has_controller_permissions(doc, 'write', user='ordinary@example.invalid'))
        with patch.object(frappe, 'get_hooks', return_value=hooks), patch.object(segment_permissions, 'setting', return_value=False):
            self.assertFalse(has_controller_permissions(doc, 'write', user='restricted@example.invalid'))

    def test_folder_permissions_keep_default_read_and_enforce_edit_restriction(self):
        doc = frappe._dict(doctype='Reach Segment Folder')
        with patch.object(segment_permissions, 'setting', return_value=None):
            self.assertTrue(segment_permissions.folder_permission(doc, ptype='read'))
        with patch.object(segment_permissions, 'setting', return_value=False), patch.object(frappe, 'has_permission', return_value=True):
            self.assertFalse(segment_permissions.folder_permission(doc, ptype='write'))

    def test_user_restrictions_have_same_protection_as_role_assignment(self):
        from finbyzreach.patches.v1_0 import add_segment_user_permissions
        with patch.object(add_segment_user_permissions, 'create_custom_fields') as create:
            add_segment_user_permissions.execute()
        fields = create.call_args.args[0]['User']
        self.assertEqual(len(fields), 5)
        self.assertTrue(all(field.get('permlevel') == 1 for field in fields))

    def test_invalid_old_segment_does_not_block_valid_segment_entry(self):
        from finbyzreach import segment_automation as automation
        from finbyzreach import segment_service as service
        from frappe.query_builder.builder import MariaDB
        broken = frappe._dict(name='OLD', audience_doctype='Lead')
        valid = frappe._dict(name='VALID', audience_doctype='Lead')
        query = MagicMock()
        query.select.return_value.where.return_value.limit.return_value.run.return_value = [('LEAD',)]
        database = MagicMock()
        database.get_value.return_value = None
        with patch.object(frappe.local, 'db', database), patch.object(frappe.local, 'qb', MariaDB, create=True), patch.object(frappe, 'get_all', return_value=['OLD','VALID']), patch.object(frappe, 'get_doc', side_effect=[broken,valid]), patch.object(service, 'member_query', side_effect=[frappe.ValidationError('removed field'),query]), patch.object(service, '_insert_members') as insert, patch.object(automation, 'emit_entry') as emit, patch.object(frappe, 'clear_last_message'), patch.object(frappe, 'logger'):
            self.assertEqual(automation.sync_record('Lead', 'LEAD'), {'VALID'})
        insert.assert_called_once_with('VALID', ['LEAD'])
        emit.assert_called_once()
