from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from finbyzreach.email_template_builder.schema import _visibility
from finbyzreach.email_template_builder.compiler import _conditions
from finbyzreach.segment_automation import referenced_segments


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
        with patch.object(frappe.local, 'db', database, create=True), patch.object(frappe.local, 'qb', MariaDB, create=True), patch.object(frappe, 'get_all', return_value=['OLD','VALID']), patch.object(frappe, 'get_doc', side_effect=[broken,valid,valid]), patch.object(service, 'member_query', side_effect=[frappe.ValidationError('removed field'),query,query]), patch.object(service, '_insert_members') as insert, patch.object(automation, 'emit_entry') as emit, patch.object(frappe, 'clear_last_message'), patch.object(frappe, 'logger'):
            self.assertEqual(automation.sync_record('Lead', 'LEAD'), {'VALID'})
        insert.assert_called_once_with('VALID', ['LEAD'])
        emit.assert_called_once()

    def test_workflow_publication_queues_once_for_each_new_active_version(self):
        from finbyzreach import segment_automation as automation
        doc = MagicMock(name='workflow')
        doc.name = 'WORKFLOW'
        doc.status = 'ACTIVE'
        doc.active_version = 'V2'
        doc.get_doc_before_save.return_value = frappe._dict(status='ACTIVE', active_version='V1')
        with patch.object(frappe, 'enqueue') as enqueue:
            automation.capture_publication(doc)
            self.assertTrue(enqueue.call_args.kwargs['enqueue_after_commit'])
            self.assertTrue(enqueue.call_args.kwargs['deduplicate'])
            self.assertEqual(enqueue.call_args.kwargs['version'], 'V2')
            enqueue.reset_mock()
            doc.get_doc_before_save.return_value.active_version = 'V2'
            automation.capture_publication(doc)
            enqueue.assert_not_called()

    def test_outdated_publication_job_cannot_enroll_records(self):
        from finbyzreach import segment_automation as automation
        workflow = frappe._dict(status='ACTIVE', active_version='V2')
        with patch.object(frappe, 'get_doc', return_value=workflow), patch('finbyzai.workflow_builder.engine.enroll') as enroll, patch.object(frappe, 'get_all') as get_all:
            automation.enroll_current_members('WORKFLOW', 'V1')
        enroll.assert_not_called()
        get_all.assert_not_called()
