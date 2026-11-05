"""Capacity and recovery regressions with mail and database mutations isolated."""
from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from frappe.query_builder.builder import MariaDB
from finbyzreach import email_marketing as mail
from finbyzreach import campaign_preparation as preparation


class BulkDeliveryTest(TestCase):
    def setUp(self):
        frappe.local.db = MagicMock()
        frappe.local.db.get_default.return_value = 0
        frappe.local.db.count.return_value = 0
        frappe.local.conf = frappe._dict(db_type='mariadb')
        frappe.local.qb = MariaDB
        frappe.local.flags = frappe._dict()
        frappe.local.session = frappe._dict(user='Administrator')
        self.campaign = frappe._dict(name='TEST-CAMPAIGN', custom_broadcast_status='Sending')
        self.campaign.check_permission = MagicMock()
    def dispatch_context(self, recipients, fail=False):
        from contextlib import ExitStack
        context = ExitStack()
        self.addCleanup(context.close)
        rows = [frappe._dict(name=f'REC-{i}', campaign_name=self.campaign.name) for i in range(recipients)]
        selections=[]
        def get_all(doctype, **kwargs):
            if doctype=='Campaign':
                return [self.campaign.name]
            selections.append(kwargs)
            return rows[:kwargs.get('limit',len(rows))]
        context.enter_context(patch.object(frappe,'are_emails_muted',return_value=False))
        context.enter_context(patch.object(mail,'_reset_stale_processing_recipients'))
        context.enter_context(patch.object(frappe,'get_all',side_effect=get_all))
        context.enter_context(patch.object(frappe,'get_doc',side_effect=lambda dt,*a,**kw:self.campaign if dt=='Campaign' else MagicMock(custom_delivery_status='Planned')))
        context.enter_context(patch.object(mail,'_current_recipient_exclusion',return_value=None))
        context.enter_context(patch.object(mail,'now_datetime',return_value=datetime(2026,11,4)))
        context.enter_context(patch.object(mail,'refresh_campaign_metrics'))
        context.enter_context(patch.object(frappe,'get_traceback',return_value='synthetic failure'))
        context.enter_context(patch.object(frappe,'log_error'))
        context.enter_context(patch.object(frappe,'enqueue'))
        dispatch = context.enter_context(patch.object(mail,'_dispatch_recipient',side_effect=RuntimeError('synthetic failure') if fail else None))
        return dispatch,selections
    def test_thirty_thousand_due_recipients_are_bounded(self):
        dispatch,selections=self.dispatch_context(30000)
        mail.dispatch_due_marketing_batches()
        self.assertEqual(dispatch.call_count,200)
        self.assertEqual(selections[0]['limit'],200)
    def test_twenty_thousand_failures_stop_after_eleven_attempts(self):
        dispatch,_=self.dispatch_context(20000,fail=True)
        mail.dispatch_due_marketing_batches()
        self.assertEqual(dispatch.call_count,11)
        self.assertIn(('Campaign',self.campaign.name,'custom_broadcast_status','Paused'),[c.args for c in frappe.db.set_value.call_args_list])
    def test_full_shared_queue_creates_no_marketing_email(self):
        dispatch,_=self.dispatch_context(30000)
        frappe.db.count.return_value=2000
        mail.dispatch_due_marketing_batches()
        dispatch.assert_not_called()
    def test_almost_full_queue_only_uses_available_capacity(self):
        dispatch,selections=self.dispatch_context(30000)
        frappe.db.count.return_value=1997
        mail.dispatch_due_marketing_batches()
        self.assertEqual(dispatch.call_count,3)
        self.assertEqual(selections[0]['limit'],3)
    def test_preparation_continues_from_remaining_rows(self):
        self.campaign.custom_broadcast_status='Preparing Audience'
        rows=[frappe._dict(name=f'ROW-{i}',payload='{"recipient":"L-'+str(i)+'"}') for i in range(200)]
        frappe.db.count.return_value=29800
        with patch.object(frappe,'get_doc',return_value=self.campaign),patch.object(frappe,'get_all',return_value=rows) as get_all,patch.object(mail,'_insert_scheduled_recipient') as insert,patch.object(frappe,'enqueue') as enqueue:
            result=preparation.process(self.campaign.name)
        self.assertEqual(insert.call_count,200)
        self.assertEqual(result['remaining'],29800)
        self.assertEqual(get_all.call_args.kwargs['limit_page_length'],200)
        self.assertTrue(enqueue.call_args.kwargs['enqueue_after_commit'])
        self.assertEqual(frappe.db.delete.call_count,200)
    def test_paused_preparation_creates_no_recipients(self):
        self.campaign.custom_broadcast_status='Paused'
        with patch.object(frappe,'get_doc',return_value=self.campaign),patch.object(mail,'_insert_scheduled_recipient') as insert:
            preparation.process(self.campaign.name)
        insert.assert_not_called()
    def test_preparation_finishes_only_after_staging_is_empty(self):
        self.campaign.custom_broadcast_status='Preparing Audience'
        with patch.object(frappe,'get_doc',return_value=self.campaign),patch.object(frappe,'get_all',return_value=[]),patch.object(frappe,'enqueue') as enqueue:
            preparation.process(self.campaign.name)
        enqueue.assert_not_called()
        self.assertIn(('Campaign',self.campaign.name,{'custom_broadcast_status':'Scheduled','custom_queued':0}),[c.args for c in frappe.db.set_value.call_args_list])

    def test_later_metrics_failure_restores_every_popped_campaign_on_rollback(self):
        from frappe.utils import CallbackManager
        frappe.db.after_rollback = CallbackManager()
        cache = MagicMock()
        cache.spop.side_effect = [b'FIRST', b'SECOND']
        with patch.object(frappe.local, 'site', 'test.local', create=True), patch.object(frappe, 'cache', cache), patch.object(mail, 'refresh_campaign_metrics', side_effect=[None, RuntimeError('later failure')]):
            with self.assertRaises(RuntimeError):
                mail.flush_dirty_campaign_metrics()
            frappe.db.after_rollback.run()
        restored = {call.args[1] for call in cache.sadd.call_args_list}
        self.assertEqual(restored, {'FIRST', 'SECOND'})

    def test_status_sync_finds_terminal_outcomes_after_five_hundred_stalled_rows(self):
        from finbyzreach.test_segment_service import MemoryDatabase
        database = MemoryDatabase()
        self.addCleanup(database.connection.close)
        connection = database.connection
        connection.execute('CREATE TABLE "tabEmail Campaign" (name TEXT, campaign_name TEXT, recipient TEXT, email_campaign_for TEXT, custom_email_queue TEXT, custom_communication TEXT, custom_opened INTEGER, custom_delivery_status TEXT, modified TEXT)')
        connection.execute('CREATE TABLE "tabEmail Queue" (name TEXT, status TEXT, error TEXT)')
        connection.execute('CREATE TABLE "tabCommunication" (name TEXT, read_by_recipient_on TEXT, read_by_recipient INTEGER, delivery_status TEXT, modified TEXT)')
        connection.execute("INSERT INTO `tabEmail Queue` VALUES ('WAIT','Not Sent',NULL),('DONE','Sent',NULL)")
        stalled = [(f'A{i:04d}','CAMPAIGN','LEAD','Lead','WAIT',None,0,'Queued','2026-01-01') for i in range(501)]
        terminal = [(name,'CAMPAIGN','LEAD','Lead',queue,None,0,'Queued','2026-01-01') for name,queue in [('Z-SENT','DONE'),('Z-MISSING','MISSING')]]
        connection.executemany('INSERT INTO "tabEmail Campaign" VALUES (?,?,?,?,?,?,?,?,?)', stalled+terminal)
        with patch.object(frappe.local, 'db', database), patch.object(database, 'table_exists', return_value=False, create=True), patch.object(database, 'set_value', create=True) as update, patch.object(frappe, 'get_all', return_value=[frappe._dict(name='DONE',status='Sent')]), patch.object(mail, 'refresh_campaign_metrics'):
            mail.sync_marketing_email_statuses()
        outcomes = {call.args[1]: call.args[2]['custom_delivery_status'] for call in update.call_args_list}
        self.assertEqual(outcomes, {'Z-SENT':'Sent', 'Z-MISSING':'Failed'})

    def test_thirty_thousand_candidates_stream_through_native_bulk_insert(self):
        rows = [frappe._dict(name=f'LEAD-{index}',eligible=index < 25000) for index in range(30000)]
        batch = frappe._dict(number=1,size=25000,scheduled_at='2026-11-05 10:00:00')
        counts = []
        def consume(doctype, fields, values, **kwargs):
            self.assertIs(iter(values), values)
            self.assertEqual(kwargs['chunk_size'], 500)
            counts.append(sum(1 for _ in values))
        frappe.db.bulk_insert.side_effect = consume
        with patch.object(mail, 'validate_schedule_preflight'), patch.object(mail, 'resolve_campaign_audience', return_value=rows), patch.object(mail, 'calculate_delivery_batches', return_value=[batch]), patch.object(mail, '_recipient_values', side_effect=lambda campaign,row,*args: {'recipient':row.name}), patch.object(mail, '_snapshot_values', return_value={}), patch.object(preparation, 'now_datetime', return_value=datetime(2026,11,4)):
            preparation.stage(self.campaign)
        self.assertEqual(counts, [30000])
        snapshot = frappe.db.set_value.call_args.args[2]
        self.assertEqual(snapshot['custom_eligible_count'],25000)
        self.assertEqual(snapshot['custom_excluded_count'],5000)
