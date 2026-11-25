"""SQL behavior checks using an isolated in-memory database; no site or mail."""
import json
import re
import sqlite3
from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.query_builder.builder import MariaDB
from finbyzreach import segment_service as service


class MemoryDatabase:
    def __init__(self):
        self.connection = sqlite3.connect(':memory:')
        self.db_type = 'mariadb'
        self.queries = []
    def sql(self, query, params=None, as_dict=False, **kwargs):
        self.queries.append(query)
        query = re.sub(r'%\(([^)]+)\)s', r':\1', query)
        cursor = self.connection.execute(query, params or {})
        rows = cursor.fetchall()
        return [frappe._dict(zip([c[0] for c in cursor.description], row)) for row in rows] if as_dict else rows
    def format_datetime(self, value):
        return value.isoformat(sep=" ")
    def bulk_insert(self, doctype, fields, values, **kwargs):
        self.connection.executemany(f'INSERT OR IGNORE INTO "tab{doctype}" ({",".join(fields)}) VALUES ({",".join("?" for f in fields)})', values)
    def delete(self, doctype, filters):
        self.connection.execute(f'DELETE FROM "tab{doctype}" WHERE '+ ' AND '.join(f'"{key}"=?' for key in filters), tuple(filters.values()))


class SegmentSQLTest(TestCase):
    def setUp(self):
        # Restore the real site state so the test runner can still commit/clean up.
        saved = {key: getattr(frappe.local, key, None) for key in ('db', 'qb', 'conf', 'flags', 'session')}
        self.addCleanup(lambda: [setattr(frappe.local, key, value) for key, value in saved.items()])
        self.database = MemoryDatabase()
        frappe.local.db = self.database
        frappe.local.qb = MariaDB
        frappe.local.conf = frappe._dict(db_type='mariadb')
        frappe.local.flags = frappe._dict()
        frappe.local.session = frappe._dict(user='Administrator')
        for doctype in ('Lead', 'Contact', 'Customer'):
            self.database.connection.execute(f'CREATE TABLE "tab{doctype}" (name TEXT PRIMARY KEY, email_id TEXT, city TEXT, unsubscribed INTEGER DEFAULT 0)')
        for doctype in (service.MEMBER, service.EXCLUSION):
            self.database.connection.execute(f'CREATE TABLE "tab{doctype}" (name TEXT PRIMARY KEY, segment TEXT, record_name TEXT, source TEXT, is_current INTEGER DEFAULT 1, creation TEXT, modified TEXT, owner TEXT, modified_by TEXT, UNIQUE(segment,record_name))')
        self.database.connection.execute('CREATE TABLE "tabEmail Group Member" (email_group TEXT, email TEXT)')
        self.database.connection.execute('CREATE TABLE "tabReach Segment Snapshot Row" (name TEXT PRIMARY KEY, segment TEXT, generation TEXT, record_name TEXT, creation TEXT, modified TEXT, owner TEXT, modified_by TEXT)')
        self.docs = {}
        self.patches = [
            patch.object(service, 'now_datetime', return_value=datetime(2026,11,4)),
            patch('finbyzreach.segment_snapshots.now_datetime', return_value=datetime(2026,11,4)),
            patch('finbyzreach.email_marketing.validate_lead_filter_groups', side_effect=self.validate_groups),
            patch.object(MariaDB, 'get_query', side_effect=self.query),
            patch.object(frappe, 'get_doc', side_effect=lambda dt, name, **kw: self.docs[name]),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.database.connection.close)
    def validate_groups(self, value, **kwargs):
        groups = frappe.parse_json(value or '[]')
        if groups and isinstance(groups[0], list) and isinstance(groups[0][0], str):
            groups = [groups]
        return json.dumps(groups)
    def query(self, doctype, fields=None, filters=None, **kwargs):
        table = frappe.qb.DocType(doctype)
        query = frappe.qb.from_(table).select(table.name)
        # Model record-level visibility to verify it survives all set operations.
        query = query.where(table.name != 'HIDDEN')
        for _, field, operator, value in filters or []:
            if operator == '=':
                query = query.where(table[field] == value)
            elif operator == '!=':
                query = query.where(table[field] != value)
            elif operator == 'in':
                query = query.where(table[field].isin(value))
            else:
                raise AssertionError(operator)
        return query
    def segment(self, name='Bern', **kwargs):
        doc = frappe._dict(name=name, audience_doctype='Lead', segment_type='Active',
                           filter_groups_json='[[["Lead","city","=","Bern"]]]',
                           exclude_filters_json='[]', exclude_email_groups_json='[]', exclude_segments_json='[]')
        doc.update(kwargs)
        doc.check_permission = lambda permission: None
        doc.as_dict = lambda: dict(doc)
        self.docs[name] = doc
        return doc
    def insert(self, name, city='Bern', doctype='Lead'):
        self.database.connection.execute(f'INSERT INTO "tab{doctype}" (name,email_id,city) VALUES (?,?,?)', (name,name+'@example.com',city))
    def test_read_permission_is_checked(self):
        with patch.object(frappe, 'has_permission', return_value=True) as permission:
            service._require_read('Communication')
        permission.assert_called_once_with('Communication', 'read', throw=True)

    def test_read_permission_denial_is_propagated(self):
        with patch.object(frappe, 'has_permission', side_effect=frappe.PermissionError) as permission:
            with self.assertRaises(frappe.PermissionError):
                service._require_read('Communication')
        permission.assert_called_once_with('Communication', 'read', throw=True)

    def test_trusted_render_bypasses_read_check_and_restores_it(self):
        with patch.object(frappe, 'has_permission', return_value=True) as permission:
            with service.trusted_render():
                service._require_read('Communication')
                permission.assert_not_called()
            service._require_read('Communication')
        permission.assert_called_once_with('Communication', 'read', throw=True)

    def test_last_activity_segment_checks_permission_and_returns_members(self):
        self.insert('ACTIVE')
        self.insert('QUIET')
        self.database.connection.execute(
            'CREATE TABLE "tabCommunication" (name TEXT, reference_doctype TEXT, reference_name TEXT, communication_date TEXT)')
        self.database.connection.execute(
            "INSERT INTO tabCommunication VALUES ('C', 'Lead', 'ACTIVE', '2026-11-03')")
        node = {'operator': 'AND', 'conditions': [{
            'kind': 'relative_date', 'field': service.LAST_ACTIVITY,
            'comparison': 'within_last', 'amount': 30, 'unit': 'days',
        }]}
        segment = self.segment(filter_expression_json=json.dumps(node))
        with patch.object(frappe, 'has_permission', return_value=True) as permission:
            self.assertEqual(service.member_names(segment), ['ACTIVE'])
        permission.assert_called_once_with('Communication', 'read', throw=True)
        with patch.object(frappe, 'has_permission', side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                service.member_names(segment)

    def test_active_rechecks_saved_filters_without_unsubscribing(self):
        self.insert('A')
        segment = self.segment()
        self.assertEqual(service.member_names(segment), ['A'])
        self.database.connection.execute('UPDATE tabLead SET city="Zurich" WHERE name="A"')
        self.assertEqual(service.member_names(segment), [])
        self.assertEqual(self.database.connection.execute('SELECT unsubscribed FROM tabLead').fetchone()[0], 0)
    def test_static_snapshot_ignores_new_matches(self):
        self.insert('A'); self.insert('B')
        segment = self.segment(segment_type='Static', members_initialized=1)
        service._insert_members(segment.name, ['A'])
        self.assertEqual(service.member_names(segment), ['A'])
    def test_manual_member_survives_static_refresh(self):
        self.insert('A'); self.insert('X', 'Zurich')
        segment = self.segment(segment_type='Static', members_initialized=1)
        service._insert_members(segment.name, ['X'], source='Manual')
        service.refresh_static(segment)
        self.assertEqual(service.member_names(segment), ['A', 'X'])
    def test_exclusions_override_manual_additions(self):
        self.insert('X', 'Zurich')
        segment = self.segment()
        service._insert_members(segment.name, ['X'], source='Manual')
        self.database.connection.execute('INSERT INTO "tabReach Segment Exclusion" (name,segment,record_name) VALUES ("EX", "Bern", "X")')
        self.assertEqual(service.member_names(segment), [])
    def test_filter_exclusions_override_inclusion(self):
        self.insert('A'); self.insert('B')
        segment = self.segment(exclude_filters_json='[[["Lead","name","=","B"]]]')
        self.assertEqual(service.member_names(segment), ['A'])
    def test_segment_exclusions_use_current_filters(self):
        self.insert('A'); self.insert('B')
        blocked = self.segment('Blocked', filter_groups_json='[[["Lead","name","=","A"]]]')
        segment = self.segment(exclude_segments_json='["Blocked"]')
        self.assertEqual(service.member_names(segment), ['B'])
        blocked.filter_groups_json='[[["Lead","name","=","B"]]]'
        self.assertEqual(service.member_names(segment), ['A'])
    def test_record_permissions_apply_to_manual_members(self):
        self.insert('HIDDEN')
        segment = self.segment()
        service._insert_members(segment.name, ['HIDDEN'], source='Manual')
        self.assertEqual(service.member_names(segment), [])
    def test_nested_boolean_groups(self):
        self.insert('A'); self.insert('B'); self.insert('C', 'Zurich')
        expression = {'operator':'AND','conditions':[{'operator':'OR','conditions':[['Lead','name','=','A'],['Lead','name','=','C']]},['Lead','city','=','Bern']]}
        segment = self.segment(filter_expression_json=json.dumps(expression))
        self.assertEqual(service.member_names(segment), ['A'])
    def test_contact_audience(self):
        self.insert('C', doctype='Contact')
        segment = self.segment(audience_doctype='Contact', filter_groups_json='[[["Contact","city","=","Bern"]]]')
        self.assertEqual(service.member_names(segment), ['C'])

    def test_related_any_and_all_distinguish_mixed_and_missing_relations(self):
        for name in ('A', 'B', 'C'):
            self.insert(name)
        self.database.connection.execute('CREATE TABLE "tabOpportunity" (name TEXT, party_name TEXT, opportunity_from TEXT)')
        self.database.connection.executemany('INSERT INTO "tabOpportunity" VALUES (?,?,?)', [
            ('MATCH-A', 'A', 'Lead'), ('OTHER', 'A', 'Lead'), ('MATCH-B', 'B', 'Lead'),
            ('MATCH-C', 'C', 'Customer')])
        node = {'kind':'related', 'doctype':'Opportunity', 'filters':[[['Opportunity','name','in',['MATCH-A','MATCH-B','MATCH-C']]]]}
        segment = self.segment(filter_expression_json=json.dumps(node))
        with patch.object(frappe, 'has_permission', return_value=True), patch.object(frappe, 'get_meta', return_value=frappe._dict(fields=[])):
            self.assertEqual(service.member_names(segment), ['A','B'])
            node['quantifier'] = 'all'
            segment.filter_expression_json = json.dumps(node)
            self.assertEqual(service.member_names(segment), ['B'])

    def test_related_all_ignores_inaccessible_relations(self):
        self.insert('A')
        self.database.connection.execute('CREATE TABLE "tabOpportunity" (name TEXT, party_name TEXT, opportunity_from TEXT)')
        self.database.connection.executemany('INSERT INTO "tabOpportunity" VALUES (?,?,?)', [
            ('MATCH', 'A', 'Lead'), ('HIDDEN', 'A', 'Lead')])
        node = {'kind':'related','doctype':'Opportunity','quantifier':'all','filters':[[['Opportunity','name','=','MATCH']]]}
        segment = self.segment(filter_expression_json=json.dumps(node))
        with patch.object(frappe, 'has_permission', return_value=True), patch.object(frappe, 'get_meta', return_value=frappe._dict(fields=[])):
            self.assertEqual(service.member_names(segment), ['A'])
    def test_thirty_thousand_members_use_bounded_cursor_pages(self):
        self.database.connection.executemany('INSERT INTO tabLead (name,email_id,city) VALUES (?,?,?)',
            ((f'L{i:05}',f'l{i}@example.com','Bern') for i in range(30000)))
        segment = self.segment()
        self.assertEqual(service.count_members(segment), 30000)
        first = service.member_names(segment, limit=50)
        second = service.member_names(segment, after=first[-1], limit=50)
        self.assertEqual(len(first), 50)
        self.assertEqual(len(second), 50)
        self.assertFalse(set(first) & set(second))
        self.assertIn('LIMIT 50', self.database.queries[-1].upper())
    def test_retried_member_insert_is_idempotent(self):
        segment = self.segment()
        service._insert_members(segment.name, ['A'])
        service._insert_members(segment.name, ['A'])
        self.assertEqual(self.database.connection.execute('SELECT COUNT(*) FROM "tabReach Segment Member"').fetchone()[0], 1)

    def test_email_activity_honors_source_record_permissions(self):
        self.insert('A')
        self.database.connection.execute('CREATE TABLE "tabEmail Tracking Event" (name TEXT, event_type TEXT, event_time TEXT, lead TEXT, contact TEXT)')
        self.database.connection.execute("INSERT INTO `tabEmail Tracking Event` VALUES ('HIDDEN','Opened','2099-01-01','A',NULL)")
        segment = self.segment(filter_expression_json=json.dumps({'kind':'activity','event':'Opened','days':30}))
        with patch('frappe.utils.now_datetime', return_value=datetime(2026,11,4)), patch.object(frappe, 'has_permission', return_value=True), patch.object(self.database, 'table_exists', return_value=True, create=True):
            self.assertEqual(service.member_names(segment), [])
            self.database.connection.execute("INSERT INTO `tabEmail Tracking Event` VALUES ('VISIBLE','Opened','2099-01-01','A',NULL)")
            self.assertEqual(service.member_names(segment), ['A'])
