"""Transactional capture must not share a key with a row being drained."""
import sqlite3
from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from finbyzreach import segment_automation as automation


class PendingRecordCaptureTest(TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.connection.execute('CREATE TABLE pending (name TEXT PRIMARY KEY, creation TEXT, modified TEXT, owner TEXT, modified_by TEXT, record_doctype TEXT, record_name TEXT)')
        self.db = MagicMock()
        self.db.bulk_insert.side_effect = lambda doctype, fields, rows: self.connection.executemany(
            'INSERT INTO pending VALUES (?,?,?,?,?,?,?)', rows)
        self.db.get_value.side_effect = lambda doctype, name, *a, **k: name
        self.db.delete.side_effect = lambda doctype, filters: self.connection.execute(
            'DELETE FROM pending WHERE name=?', (filters['name'],))
        for item in (patch.object(frappe.local, 'db', self.db, create=True),
                     patch.object(frappe.local, 'session', frappe._dict(user='Administrator'), create=True),
                     patch.object(automation, 'enqueue_changes'),
                     patch.object(frappe.utils, 'now_datetime', return_value=datetime(2026, 11, 26, 12))):
            item.start()
            self.addCleanup(item.stop)
        self.doc = frappe._dict(doctype='Contact', name='CONTACT-1')

    def rows(self):
        return [frappe._dict(name=r[0], record_doctype=r[1], record_name=r[2]) for r in
                self.connection.execute('SELECT name,record_doctype,record_name FROM pending')]

    def test_same_identity_appends_independent_rows_in_parent_transaction(self):
        automation.capture_change(self.doc)
        automation.capture_change(self.doc)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].name, rows[1].name)
        self.db.commit.assert_not_called()
        self.db.rollback.assert_not_called()
        self.connection.rollback()
        self.assertEqual(self.rows(), [])

    def test_capture_during_drain_is_not_deleted_with_the_old_change(self):
        automation.capture_change(self.doc)
        batch = self.rows()
        with (patch.object(automation, 'pending_batch', return_value=batch),
              patch.object(automation, 'sync_record', side_effect=lambda *a: automation.capture_change(self.doc) or set()),
              patch.object(automation, 'schedule_dependents')):
            automation.drain_batch()
        remaining = self.rows()
        self.assertEqual(len(remaining), 1)
        self.assertNotEqual(remaining[0].name, batch[0].name)
        self.assertEqual(remaining[0].record_name, self.doc.name)

    def test_drain_coalesces_same_identity_but_consumes_every_captured_row(self):
        automation.capture_change(self.doc)
        automation.capture_change(self.doc)
        with (patch.object(automation, 'pending_batch', return_value=self.rows()),
              patch.object(automation, 'sync_record', return_value=set()) as sync,
              patch.object(automation, 'schedule_dependents')):
            self.assertEqual(automation.drain_batch(), 2)
        sync.assert_called_once_with('Contact', 'CONTACT-1')
        self.assertEqual(self.rows(), [])

    def test_capture_does_not_hide_database_failures_or_commit_the_parent(self):
        self.db.bulk_insert.side_effect = frappe.QueryDeadlockError('database unavailable')
        with self.assertRaises(frappe.QueryDeadlockError):
            automation.capture_change(self.doc)
        self.db.commit.assert_not_called()
        self.db.rollback.assert_not_called()


class PendingRecordCaptureDatabaseTest(TestCase):
    """Run against a test-enabled MariaDB site, with two actual transactions."""
    def test_capture_does_not_wait_on_the_row_a_drain_has_locked(self):
        if frappe.db.db_type != 'mariadb':
            self.skipTest('Requires a MariaDB site')
        from uuid import uuid4
        from frappe.database import get_db
        identity = 'test-capture-race-' + uuid4().hex
        conf = frappe.conf
        other = get_db(socket=conf.db_socket, host=conf.db_host, port=conf.db_port,
                       user=conf.db_user or conf.db_name, password=conf.db_password, cur_db_name=conf.db_name)
        doctype = 'Reach Segment Pending Record'
        doc = frappe._dict(doctype='Contact', name=identity)
        original = frappe.db
        try:
            with patch.object(original, 'exists', return_value=True):
                automation.capture_change(doc, enqueue=False)
            original.commit()
            old = original.get_value(doctype, {'record_name': identity}, 'name')
            original.get_value(doctype, old, 'name', for_update=True)
            other.sql('SET SESSION innodb_lock_wait_timeout=1')
            # The old deterministic key blocks here until the drain releases it.
            with patch.object(frappe.local, 'db', other), patch.object(other, 'exists', return_value=True):
                automation.capture_change(doc, enqueue=False)
                other.commit()
            original.delete(doctype, {'name': old})
            original.commit()
            remaining = frappe.get_all(doctype, filters={'record_name': identity}, pluck='name')
            self.assertEqual(len(remaining), 1)
            self.assertNotEqual(remaining[0], old)
        finally:
            other.rollback()
            other.close()
            original.rollback()
            original.delete(doctype, {'record_name': identity})
            original.commit()
