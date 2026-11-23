import json
from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from finbyzreach import segment_service as service, segment_snapshots as snapshots, segments, segment_automation as automation
from finbyzreach import test_segment_service as sql_tests


def mock_local(test):
    """Swap frappe.local.db/flags/session for the test and put the real ones back.

    patch.object(frappe.local, ..., create=True) deletes the attribute on stop without restoring
    it, because frappe's Local proxy keeps it outside __dict__, so later tests lost frappe.local.db.
    """
    missing=object()
    for name,value in (('db',MagicMock()),('flags',frappe._dict(mute_messages=True)),
                       ('session',frappe._dict(user='Administrator'))):
        try:
            original=getattr(frappe.local,name)
        except (AttributeError,RuntimeError):
            original=missing
        setattr(frappe.local,name,value)
        test.addCleanup(lambda name=name,original=original:delattr(frappe.local,name) if original is missing
                        else setattr(frappe.local,name,original))


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
        with patch.object(segments,'_segment',return_value=doc),patch.object(frappe,'get_all',return_value=[]), \
                patch.object(segments,'effective_columns',return_value=['name']),patch.object(frappe,'get_list',return_value=[]):
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
        mock_local(self)

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

    def test_drain_skips_pending_record_taken_by_concurrent_drain(self):
        rows=[frappe._dict(name='TAKEN',record_doctype='Contact',record_name='C-1'),
              frappe._dict(name='LIVE',record_doctype='Contact',record_name='C-2')]
        frappe.db.get_value.side_effect=lambda doctype,name,*args,**kwargs:None if name=='TAKEN' else name
        with patch.object(automation,'pending_batch',return_value=rows),\
             patch.object(automation,'sync_record',return_value=set()) as sync,\
             patch.object(automation,'schedule_dependents'):
            automation.drain_batch()
        sync.assert_called_once_with('Contact','C-2')
        self.assertTrue(all(call.kwargs.get('for_update') for call in frappe.db.get_value.call_args_list))
        frappe.db.delete.assert_called_once_with('Reach Segment Pending Record',{'name':'LIVE'})

    def test_preview_and_export_share_default_fields_but_explicit_export_is_exact(self):
        doc=frappe._dict(audience_doctype='Contact',columns_json=None)
        with patch('frappe.model.get_permitted_fields',return_value=['name','full_name','email_id']):
            self.assertEqual(segments.effective_columns(doc),['name','full_name','email_id'])
            self.assertEqual(segments.effective_columns(doc,'["full_name"]'),['full_name'])


class PendingRecordDrainRaceTest(TestCase):
    """Two drains on real connections: the other one takes a row after this one read its batch."""
    PENDING='Reach Segment Pending Record'

    def setUp(self):
        if not frappe.db.table_exists(self.PENDING):
            self.skipTest('Reach Segment Pending Record table is missing')
        from frappe.utils import now_datetime
        prefix=f'test-drain-race-{frappe.generate_hash(length=8)}'
        self.taken,self.live=f'{prefix}-taken',f'{prefix}-live'
        now=now_datetime()
        frappe.db.bulk_insert(self.PENDING,['name','creation','modified','owner','modified_by','record_doctype','record_name'],
            [(name,now,now,'Administrator','Administrator','Contact',name) for name in (self.taken,self.live)])
        frappe.db.commit()
        conf=frappe.conf
        self.other=frappe.database.get_db(socket=conf.db_socket,host=conf.db_host,port=conf.db_port,
            user=conf.db_user or conf.db_name,password=conf.db_password,cur_db_name=conf.db_name)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        frappe.db.rollback()
        frappe.db.delete(self.PENDING,{'name':['in',[self.taken,self.live]]})
        frappe.db.commit()
        self.other.close()

    def test_drain_skips_row_deleted_by_concurrent_drain_after_batch_read(self):
        # This drain reads its batch, which fixes its REPEATABLE READ snapshot.
        rows=frappe.db.sql(f'select name, record_doctype, record_name from `tab{self.PENDING}` where name in %s order by name',
                           [[self.taken,self.live]],as_dict=True)
        self.assertEqual(len(rows),2)
        # The other drain takes and finishes one record before this drain reaches it.
        self.other.sql(f'select name from `tab{self.PENDING}` where name=%s for update',self.taken)
        self.other.sql(f'delete from `tab{self.PENDING}` where name=%s',self.taken)
        self.other.commit()
        live,=[row for row in rows if row.name==self.live]
        taken,=[row for row in rows if row.name==self.taken]
        # One batch, inside the snapshot taken above (drain_changes would commit first).
        with patch.object(automation,'pending_batch',return_value=[taken,live]),\
             patch.object(automation,'sync_record',return_value=set()) as sync,\
             patch.object(automation,'schedule_dependents'):
            automation.drain_batch()
        sync.assert_called_once_with('Contact',self.live)
        frappe.db.commit()
        self.assertFalse(frappe.db.exists(self.PENDING,self.live))


class DrainHandshakeTest(TestCase):
    """At most one drain job: real Redis owner/dirty keys, mocked database and queue."""

    def setUp(self):
        mock_local(self)
        suffix=frappe.generate_hash(length=8)
        for name in ('DRAIN_OWNER_KEY','DRAIN_DIRTY_KEY'):
            patcher=patch.object(automation,name,f'{getattr(automation,name)}:test-{suffix}')
            patcher.start();self.addCleanup(patcher.stop)
        self.addCleanup(lambda:frappe.cache.delete(*(frappe.cache.make_key(getattr(automation,name))
                                                     for name in ('DRAIN_OWNER_KEY','DRAIN_DIRTY_KEY'))))
        for target,name in ((frappe,'enqueue'),(frappe,'set_user'),(automation,'schedule_dependents')):
            patcher=patch.object(target,name)
            setattr(self,name,patcher.start());self.addCleanup(patcher.stop)
        frappe.db.get_value.side_effect=lambda doctype,name,*args,**kwargs:name

    def owner(self):
        value=frappe.cache.get(frappe.cache.make_key(automation.DRAIN_OWNER_KEY))
        return value.decode() if value else None

    def dirty(self):
        return bool(frappe.cache.exists(frappe.cache.make_key(automation.DRAIN_DIRTY_KEY)))

    def rows(self,start,count):
        return [frappe._dict(name=f'P{n:05}',record_doctype='Contact',record_name=f'C{n:05}') for n in range(start,start+count)]

    def test_enqueue_changes_registers_one_after_commit_signal_per_transaction(self):
        callbacks=frappe.utils.CallbackManager()
        frappe.db.after_commit=callbacks
        frappe.db.table_exists.return_value=True
        for _ in range(600):
            automation.enqueue_changes()
        self.assertEqual(list(callbacks._functions),[automation.signal_changes])
        self.enqueue.assert_not_called()  # nothing is queued before the caller commits

    def test_burst_of_600_changes_queues_exactly_one_drain(self):
        """600 captures, each in its own transaction, while the drain works through 6 batches."""
        with patch.object(automation,'pending_batch',return_value=['pending']):
            for _ in range(200):
                automation.signal_changes()
        self.assertEqual(self.enqueue.call_count,1)
        token=self.enqueue.call_args.kwargs['token']
        self.assertEqual(self.owner(),token)
        batches=[self.rows(start,100) for start in range(0,600,100)]
        def next_batch(limit=automation.DRAIN_BATCH_SIZE):
            batch=batches.pop(0) if batches else []
            if batch:  # more captures commit while this batch runs
                with patch.object(automation,'pending_batch',return_value=['pending']):
                    for _ in range(80):
                        automation.signal_changes()
            return batch
        with patch.object(automation,'pending_batch',side_effect=next_batch),\
             patch.object(automation,'sync_record',return_value=set()) as sync:
            automation.drain_changes(token=token)
        self.assertEqual(sync.call_count,600)
        self.assertEqual(len({call.args[1] for call in sync.call_args_list}),600)  # none twice
        self.assertEqual(self.enqueue.call_count,1)
        self.assertIsNone(self.owner())

    def test_capture_during_drain_is_drained_by_the_running_job(self):
        self.assertTrue(automation._drain_script(automation._CLAIM,'T1',60))
        batches=[self.rows(0,1),[],self.rows(1,1),[]]
        def next_batch(limit=automation.DRAIN_BATCH_SIZE):
            batch=batches.pop(0)
            if not batch and len(batches)==2:
                # Worst case: a save commits right after the drain read an empty table,
                # before the drain could release. Its after-commit signal finds the owner held.
                with patch.object(automation,'pending_batch',return_value=['pending']):
                    automation.signal_changes()
            return batch
        with patch.object(automation,'pending_batch',side_effect=next_batch),\
             patch.object(automation,'sync_record',return_value=set()) as synced:
            automation.drain_changes(token='T1')
        self.assertEqual([call.args[1] for call in synced.call_args_list],['C00000','C00001'])
        self.enqueue.assert_not_called()
        self.assertIsNone(self.owner())
        self.assertFalse(batches)

    def test_capture_after_release_queues_a_new_drain(self):
        self.assertTrue(automation._drain_script(automation._CLAIM,'T1',60))
        with patch.object(automation,'pending_batch',return_value=[]):
            automation.drain_changes(token='T1')
        self.assertIsNone(self.owner())
        with patch.object(automation,'pending_batch',return_value=['pending']):
            automation.signal_changes()
        self.assertEqual(self.enqueue.call_count,1)
        self.assertEqual(self.owner(),self.enqueue.call_args.kwargs['token'])

    def test_time_budget_hands_over_to_one_continuation_job(self):
        self.assertTrue(automation._drain_script(automation._CLAIM,'T1',60))
        with patch.object(automation,'DRAIN_TIME_BUDGET',0),\
             patch.object(automation,'pending_batch',return_value=self.rows(0,100)),\
             patch.object(automation,'sync_record',return_value=set()) as sync:
            automation.drain_changes(token='T1')
        self.assertEqual(sync.call_count,100)
        self.assertEqual(self.enqueue.call_count,1)
        self.assertEqual(self.enqueue.call_args.kwargs['token'],'T1')
        self.assertEqual(self.owner(),'T1')

    def test_queue_overloaded_frees_owner_for_the_scheduler(self):
        self.enqueue.side_effect=frappe.QueueOverloaded
        with patch.object(automation,'pending_batch',return_value=['pending']),patch.object(frappe,'log_error'):
            automation.signal_changes()
        self.assertIsNone(self.owner())

    def test_failed_drain_frees_owner_and_keeps_rows(self):
        self.assertTrue(automation._drain_script(automation._CLAIM,'T1',60))
        with patch.object(automation,'pending_batch',return_value=self.rows(0,1)),\
             patch.object(automation,'sync_record',side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                automation.drain_changes(token='T1')
        self.assertIsNone(self.owner())
        frappe.db.delete.assert_not_called()

    def test_records_captured_inside_a_drain_do_not_enqueue(self):
        def fan_out(preference):
            for _ in range(5):
                automation.enqueue_changes()
        row=frappe._dict(name='P1',record_doctype='Email Subscription Preference',record_name='ESP-1')
        frappe.flags.in_reach_segment_drain=False
        with patch.object(automation,'pending_batch',side_effect=[[row],[]]),\
             patch('finbyzreach.subscriber_segments.queue_subscription_records',side_effect=fan_out) as fanned:
            automation.drain_changes()
        fanned.assert_called_once_with('ESP-1')
        frappe.db.after_commit.add.assert_not_called()
        self.assertFalse(frappe.flags.in_reach_segment_drain)
