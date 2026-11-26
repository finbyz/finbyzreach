"""Recover a stale Sending summary without replaying deliveries."""
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.query_builder.builder import MariaDB
from finbyzreach import campaign_metrics as recovery
from finbyzreach.test_segment_service import MemoryDatabase


class CampaignDatabase(MemoryDatabase):
    def sql(self, query, *args, **kwargs):
        # SQLite exercises selection/transaction behavior; MariaDB validates locks.
        return super().sql(query.replace(' FOR UPDATE', ''), *args, **kwargs)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def get_value(self, doctype, name, fields, as_dict=False, **kwargs):
        columns = [fields] if isinstance(fields, str) else fields
        cursor = self.connection.execute(f'SELECT {",".join(columns)} FROM "tab{doctype}" WHERE name=?', (name,))
        row = cursor.fetchone()
        if row is None:
            return None
        return frappe._dict(zip(columns, row)) if as_dict else row[0]

    def _where(self, filters):
        clauses, values = [], []
        for key, value in filters.items():
            if isinstance(value, list):
                operator, items = value
                assert operator == 'in'
                clauses.append(f'{key} IN ({",".join("?" for _ in items)})')
                values.extend(items)
            else:
                clauses.append(f'{key}=?')
                values.append(value)
        return ' AND '.join(clauses), values

    def count(self, doctype, filters):
        where, values = self._where(filters)
        return self.connection.execute(f'SELECT COUNT(*) FROM "tab{doctype}" WHERE {where}', values).fetchone()[0]

    def exists(self, doctype, filters):
        return bool(self.count(doctype, filters if isinstance(filters, dict) else {'name': filters}))

    def set_value(self, doctype, name, field, value=None, **kwargs):
        values = field if isinstance(field, dict) else {field: value}
        self.connection.execute(f'UPDATE "tab{doctype}" SET '+','.join(f'{key}=?' for key in values)+' WHERE name=?',
                                [*values.values(), name])


class CampaignSummaryRecoveryTest(TestCase):
    def setUp(self):
        self.db = CampaignDatabase()
        self.addCleanup(self.db.connection.close)
        counters = 'custom_queued_count,custom_sent_count,custom_failed_count,custom_opened_count,custom_clicked_count,custom_replied_count,custom_unsubscribed_count'
        self.db.connection.execute('CREATE TABLE "tabCampaign" (name TEXT PRIMARY KEY, custom_broadcast_status TEXT, custom_queued INTEGER DEFAULT 0, custom_email_template TEXT, modified TEXT,'+
                                   ','.join(f'{field} INTEGER DEFAULT 0' for field in counters.split(','))+')')
        self.db.connection.execute('CREATE TABLE "tabEmail Campaign" (name TEXT PRIMARY KEY, campaign_name TEXT, custom_delivery_status TEXT, custom_opened INTEGER DEFAULT 0, custom_clicked INTEGER DEFAULT 0, custom_replied INTEGER DEFAULT 0, custom_unsubscribed INTEGER DEFAULT 0)')
        for item in (patch.object(frappe.local, 'db', self.db, create=True),
                     patch.object(frappe.local, 'qb', MariaDB, create=True)):
            item.start()
            self.addCleanup(item.stop)

    def campaign(self, name='STALE', status='Sending', deliveries=('Sent',), preparing=0, template='EMAIL'):
        self.db.connection.execute('INSERT INTO "tabCampaign" (name,custom_broadcast_status,custom_queued,custom_email_template,modified,custom_queued_count) VALUES (?,?,?,?,?,1)',
                                   (name, status, preparing, template, '2026-11-18'))
        for index, delivery in enumerate(deliveries):
            self.db.connection.execute('INSERT INTO "tabEmail Campaign" (name,campaign_name,custom_delivery_status) VALUES (?,?,?)',
                                       (f'{name}-{index}', name, delivery))
        self.db.commit()

    def state(self, name='STALE'):
        return self.db.get_value('Campaign', name,
            ['custom_broadcast_status','custom_queued_count','custom_sent_count','custom_failed_count'], as_dict=True)

    def test_sent_and_skipped_recipients_complete_stale_summary_without_resending(self):
        self.campaign(deliveries=('Sent', *('Skipped',) * 5))
        with patch.object(frappe, 'sendmail') as send, patch('finbyzreach.email_marketing._dispatch_recipient') as dispatch:
            recovery.reconcile_campaign_metrics()
            recovery.reconcile_campaign_metrics()
        self.assertEqual(self.state(), dict(custom_broadcast_status='Completed',custom_queued_count=0,custom_sent_count=1,custom_failed_count=0))
        send.assert_not_called()
        dispatch.assert_not_called()

    def test_failures_produce_failed_summary(self):
        self.campaign(deliveries=('Sent','Failed'))
        recovery.reconcile_campaign_metrics()
        self.assertEqual(self.state().custom_broadcast_status, 'Failed')
        self.assertEqual(self.state().custom_failed_count, 1)

    def test_filtering_before_limit_prevents_live_campaigns_starving_finished_ones(self):
        for number in range(55):
            self.campaign(f'A{number:03}', deliveries=('Queued',))
        self.campaign('Z-FINISHED', deliveries=('Sent',))
        self.assertEqual([r.name for r in recovery.finished_campaign_candidates()], ['Z-FINISHED'])

    def test_pending_unknown_preparing_and_empty_campaigns_are_not_completed(self):
        cases=[('Planned',),('Processing',),('Queued',),(None,),('',),('Unknown',),()]
        for index, deliveries in enumerate(cases):
            self.campaign(f'LIVE-{index}', deliveries=deliveries)
        for status in ('Draft','Preparing Audience','Completed','Cancelled','Failed'):
            self.campaign(status, status=status)
        self.campaign('PREPARING-FLAG', preparing=1)
        self.campaign('LEGACY', template=None)
        self.assertEqual(recovery.finished_campaign_candidates(), [])

    def test_candidate_batch_is_bounded(self):
        for number in range(55):
            self.campaign(f'DONE-{number:03}')
        self.assertEqual(len(recovery.finished_campaign_candidates()), recovery.RECONCILE_LIMIT)
        recovery.reconcile_campaign_metrics()
        self.assertEqual(len(recovery.finished_campaign_candidates()), 5)

    def test_changed_state_and_new_work_are_rechecked_after_candidate_scan(self):
        self.campaign('NEW-WORK', deliveries=('Sent','Planned'))
        self.campaign('PREPARING', preparing=1)
        self.campaign('CANCELLED', status='Cancelled')
        with patch.object(recovery, 'finished_campaign_candidates', return_value=[frappe._dict(name=n) for n in ['NEW-WORK','PREPARING','CANCELLED','DELETED']]):
            recovery.reconcile_campaign_metrics()
        self.assertEqual(self.state('NEW-WORK').custom_broadcast_status, 'Sending')
        self.assertEqual(self.state('PREPARING').custom_broadcast_status, 'Sending')
        self.assertEqual(self.state('CANCELLED').custom_broadcast_status, 'Cancelled')

    def test_failed_refresh_rolls_back_and_does_not_block_next_campaign(self):
        self.campaign('A-FAIL')
        self.campaign('B-OK')
        write = self.db.set_value
        def fail(doctype, name, *args, **kwargs):
            if name == 'A-FAIL':
                raise frappe.QueryDeadlockError('1020')
            return write(doctype, name, *args, **kwargs)
        with patch.object(self.db, 'set_value', side_effect=fail), patch.object(frappe, 'log_error') as log:
            recovery.reconcile_campaign_metrics()
        self.assertEqual(self.state('A-FAIL').custom_broadcast_status, 'Sending')
        self.assertEqual(self.state('B-OK').custom_broadcast_status, 'Completed')
        log.assert_called_once()
