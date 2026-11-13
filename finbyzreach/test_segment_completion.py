import json
from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from finbyzreach import segment_service as service, segment_snapshots as snapshots, segments, segment_automation as automation
from finbyzreach import test_segment_service as sql_tests


class SegmentCompletionSQLTest(TestCase):
    def setUp(self):
        self.sql = sql_tests.SegmentSQLTest()
        self.sql.setUp()
        self.addCleanup(self.sql.doCleanups)

    def test_store_purchase_excludes_goals_carts_and_other_sites(self):
        sql = self.sql
        sql.database.connection.execute('ALTER TABLE tabLead ADD COLUMN custom_website_tracking_visitor_id TEXT')
        sql.database.connection.execute('CREATE TABLE "tabTracker Conversion" (name TEXT,visitor_id TEXT,received_at TEXT,goal_id INTEGER,order_id TEXT,site_id INTEGER)')
        for name,goal,order,site in [('GOAL',5,None,1),('CART',0,'',1),('BUY',0,'ORDER',1),('OTHER',0,'OTHER-ORDER',2)]:
            sql.insert(name)
            sql.database.connection.execute('UPDATE tabLead SET custom_website_tracking_visitor_id=? WHERE name=?',(name,name))
            sql.database.connection.execute('INSERT INTO "tabTracker Conversion" VALUES (?,?,?,?,?,?)',(name,name,'2099-01-01',goal,order,site))
        segment = sql.segment(filter_expression_json=json.dumps({'kind':'activity','event':'Store purchase','days':30,'site':1}))
        meta = MagicMock()
        meta.has_field.side_effect = lambda field:field == 'custom_website_tracking_visitor_id'
        with patch.object(sql.database,'table_exists',return_value=True,create=True),patch.object(frappe,'has_permission',return_value=True),patch.object(frappe,'get_meta',return_value=meta):
            self.assertEqual(service.member_names(segment),['BUY'])

    def test_static_exclusion_can_be_restored_after_recalculation(self):
        sql = self.sql
        sql.insert('A');sql.insert('B')
        segment = sql.segment(segment_type='Static',members_initialized=1)
        sql.database.connection.execute('INSERT INTO "tabReach Segment Exclusion" (name,segment,record_name) VALUES ("EX","Bern","A")')
        service.refresh_static(segment)
        self.assertEqual(service.member_names(segment),['B'])
        sql.database.connection.execute('DELETE FROM "tabReach Segment Exclusion"')
        self.assertEqual(service.member_names(segment),['A','B'])

    def test_excluded_api_pages_beyond_fifty(self):
        sql = self.sql
        for number in range(60):
            name=f'L{number:03}'
            sql.insert(name)
            sql.database.connection.execute('INSERT INTO "tabReach Segment Exclusion" (name,segment,record_name) VALUES (?,?,?)',(name,'Bern',name))
        doc = sql.segment()
        with patch.object(segments,'_segment',return_value=doc),patch.object(frappe,'get_all',return_value=[]):
            first = segments.excluded_segment_records(doc.name,with_paging=1)
            second = segments.excluded_segment_records(doc.name,start=50,with_paging=1)
        self.assertEqual(len(first['rows']),50)
        self.assertTrue(first['has_more'])
        self.assertEqual(len(second['rows']),10)
        self.assertFalse(second['has_more'])
        self.assertEqual(second['rows'][0]['record_name'],'L050')

    def test_opportunity_and_sales_order_audiences(self):
        sql = self.sql
        for doctype in ('Opportunity','Sales Order'):
            sql.database.connection.execute(f'CREATE TABLE "tab{doctype}" (name TEXT,city TEXT,contact_email TEXT)')
            sql.database.connection.execute(f'INSERT INTO "tab{doctype}" VALUES ("DOC","Bern","test@example.invalid")')
            doc=sql.segment(name=doctype,audience_doctype=doctype,filter_groups_json=json.dumps([[[doctype,'city','=','Bern']]]))
            self.assertEqual(service.member_names(doc),['DOC'])

    def test_search_excluded_count_uses_the_same_record_scope(self):
        sql=self.sql
        sql.database.connection.execute('ALTER TABLE tabLead ADD COLUMN lead_name TEXT')
        sql.insert('A');sql.insert('B')
        sql.database.connection.execute('INSERT INTO "tabReach Segment Exclusion" (name,segment,record_name) VALUES ("EX","Bern","A")')
        with patch.object(segments,'_segment',return_value=sql.segment()),patch.object(segments,'effective_columns',return_value=['name']),patch.object(frappe,'get_list',return_value=[{'name':'B'}]):
            result=segments.preview_segment_page('Bern',search='B')
        self.assertEqual(result['count'],1)
        self.assertEqual(result['excluded_count'],0)


class SegmentCompletionTest(TestCase):
    def setUp(self):
        for name,value in (('db',MagicMock()),('flags',frappe._dict(mute_messages=True)),
                           ('session',frappe._dict(user='Administrator'))):
            patcher=patch.object(frappe.local,name,value,create=True)
            patcher.start();self.addCleanup(patcher.stop)

    def test_large_static_preparation_is_bounded_and_keeps_old_generation(self):
        doc=frappe._dict(name='SEG',audience_doctype='Contact',segment_type='Static',snapshot_generation='OLD')
        with patch.object(service,'member_names',return_value=[str(i) for i in range(1001)]) as query,patch.object(frappe,'enqueue') as enqueue,patch.object(snapshots,'insert_rows') as insert:
            snapshots.prepare(doc)
        self.assertEqual(query.call_args.kwargs['limit'],1001)
        self.assertFalse(query.call_args.kwargs['apply_exclusions'])
        self.assertEqual(doc.snapshot_generation,'OLD')
        self.assertEqual(doc.snapshot_status,'Queued')
        insert.assert_not_called()
        self.assertTrue(enqueue.call_args.kwargs['enqueue_after_commit'])

    def test_snapshot_chunk_never_publishes_a_partial_generation(self):
        doc=frappe._dict(name='SEG',archived=0,segment_type='Static',snapshot_pending_generation='GEN',snapshot_definition='{"name":"SEG","audience_doctype":"Contact","segment_type":"Active"}')
        with patch.object(frappe,'get_doc',return_value=doc),patch.object(frappe,'get_all',return_value=[]),patch.object(service,'member_names',return_value=[str(i) for i in range(500)]),patch.object(snapshots,'insert_rows') as insert,patch.object(frappe,'enqueue') as enqueue:
            snapshots.build('SEG','GEN')
        self.assertEqual(len(insert.call_args.args[2]),500)
        self.assertEqual(frappe.db.set_value.call_args.args,('Reach Segment','SEG','snapshot_status','Building'))
        self.assertEqual(enqueue.call_args.kwargs['after'],'499')

    def test_stale_snapshot_job_does_not_touch_newer_preparation(self):
        doc=frappe._dict(archived=0,segment_type='Static',snapshot_pending_generation='NEW')
        with patch.object(frappe,'get_doc',return_value=doc),patch.object(service,'member_names') as query:
            snapshots.build('SEG','OLD')
        query.assert_not_called()
        frappe.db.set_value.assert_not_called()

    def test_invalid_snapshot_definition_is_retryable(self):
        doc=frappe._dict(name='SEG',archived=0,segment_type='Static',snapshot_pending_generation='GEN',snapshot_definition='{')
        with patch.object(frappe,'get_doc',return_value=doc),patch.object(frappe,'log_error'):
            snapshots.build('SEG','GEN')
        frappe.db.rollback.assert_called_once_with(save_point='reach_snapshot_chunk')
        self.assertEqual(frappe.db.set_value.call_args.args[2]['snapshot_status'],'Failed')
        self.assertEqual(doc.snapshot_pending_generation,'GEN')

    def test_failed_publication_rolls_back_before_marking_failed(self):
        doc=MagicMock(name='segment')
        doc.name='SEG';doc.archived=0;doc.segment_type='Static'
        doc.snapshot_pending_generation='GEN';doc.snapshot_definition='{}'
        with patch.object(frappe,'get_doc',return_value=doc),patch.object(frappe,'get_all',return_value=[]),patch.object(service,'member_names',return_value=[]),patch.object(service,'count_members',side_effect=RuntimeError('count failed')),patch.object(frappe,'log_error'):
            snapshots.build('SEG','GEN')
        frappe.db.rollback.assert_called_once_with(save_point='reach_snapshot_chunk')
        self.assertEqual(frappe.db.set_value.call_args.args[2]['snapshot_status'],'Failed')

    def test_dependency_graph_schedules_transitive_and_static_dependents_once(self):
        rows=[frappe._dict(name='B',exclude_segments_json='["A"]'),
              frappe._dict(name='C',filter_expression_json=json.dumps({'kind':'segment','segment':'B'})),
              frappe._dict(name='D',exclude_segments_json='["A","B"]')]
        with patch.object(frappe,'get_all',return_value=rows),patch.object(frappe,'enqueue') as enqueue:
            automation.schedule_dependents({'A'})
        self.assertEqual([call.kwargs['segment_name'] for call in enqueue.call_args_list],['B','D','C'])

    def test_manual_member_exit_is_retained_for_later_reentry(self):
        from finbyzreach.segment_history import record_event
        previous=frappe._dict(name='MEM',source='Manual',is_current=1)
        with patch('finbyzreach.segment_history.record_event') as event:
            automation.mark_left(frappe._dict(name='SEG'),previous,'CONTACT')
        event.assert_called_once()
        self.assertEqual(event.call_args.args[2],'Left')
        frappe.db.delete.assert_not_called()
        frappe.db.set_value.assert_called_once_with(service.MEMBER,'MEM','is_current',0,update_modified=False)

    def test_visitor_identity_fanout_is_paged_and_coalesces_changes(self):
        names=[f'C{number:03}' for number in range(200)]
        meta=MagicMock()
        meta.has_field.return_value=True
        with patch.object(frappe,'get_meta',return_value=meta),patch.object(frappe,'get_all',return_value=names) as query,patch.object(automation,'capture_change') as capture,patch.object(automation,'enqueue_changes') as drain,patch.object(frappe,'enqueue') as enqueue:
            automation.queue_visitor_records('Contact','VISITOR',after='C-previous')
        self.assertEqual(query.call_args.kwargs['limit_page_length'],200)
        self.assertEqual(query.call_args.kwargs['filters'],{'name':['>','C-previous']})
        self.assertEqual(capture.call_count,200)
        self.assertTrue(all(call.kwargs['enqueue'] is False for call in capture.call_args_list))
        drain.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs['after'],'C199')

    def test_preview_and_export_share_default_fields_but_explicit_export_is_exact(self):
        doc=frappe._dict(audience_doctype='Contact',columns_json=None)
        with patch('frappe.model.get_permitted_fields',return_value=['name','full_name','email_id']):
            self.assertEqual(segments.effective_columns(doc),['name','full_name','email_id'])
            self.assertEqual(segments.effective_columns(doc,'["full_name"]'),['full_name'])
