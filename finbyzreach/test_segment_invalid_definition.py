"""Nightly segment jobs skip a segment whose filters no longer validate, and log it once."""
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from finbyzreach import segment_automation as automation, segment_history as history, segment_service as service


def segment():
    doc = frappe._dict(name='SEG-1', archived=0, snapshot_pending_generation=None,
                       last_definition_change='2026-10-05 10:00:00', excluded_count=0)
    return doc


class InvalidSegmentDefinitionTest(TestCase):
    def setUp(self):
        self.cache = {}
        fake_cache = MagicMock()
        fake_cache.get_value.side_effect = self.cache.get
        fake_cache.set_value.side_effect = lambda key, value, expires_in_sec=None: self.cache.__setitem__(key, value)
        for patcher in (patch.object(frappe, 'cache', fake_cache),
                        patch.object(frappe, 'get_doc', return_value=segment())):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log_error = patch.object(frappe, 'log_error').start()
        self.addCleanup(patch.stopall)
        self.invalid = frappe.ValidationError('Field Lead.custom_event_name is not available for audience filtering')

    def test_reconcile_skips_and_logs_once(self):
        with patch.object(service, 'member_names', side_effect=self.invalid):
            self.assertIsNone(automation.reconcile_segment('SEG-1'))
            self.assertIsNone(automation.reconcile_segment('SEG-1'))
        self.log_error.assert_called_once()
        self.assertIn('SEG-1', self.log_error.call_args.kwargs['title'])

    def test_size_sample_skips_and_logs_once(self):
        with patch.object(service, 'count_members', side_effect=self.invalid), \
                patch.object(frappe.db, 'table_exists', return_value=True, create=True):
            history.sample_one('SEG-1')
            history.sample_one('SEG-1')
        self.log_error.assert_called_once()

    def test_a_changed_definition_is_reported_again(self):
        service.report_invalid_definition(segment(), self.invalid)
        changed = segment()
        changed.last_definition_change = '2026-11-23 10:00:00'
        service.report_invalid_definition(changed, self.invalid)
        self.assertEqual(self.log_error.call_count, 2)
