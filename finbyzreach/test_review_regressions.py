"""Regression coverage for the unpushed-commits review, with no outbound mail."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from jinja2 import DictLoader, Environment
from finbyzreach import consent, segment_automation, segment_snapshots, subscription_preferences as preferences
from finbyzreach.www.open_sms import sms_targets


class ConsentRegressionTest(TestCase):
    def test_optional_consent_never_overrides_an_explicit_unsubscribe(self):
        policy = frappe._dict(available=True, name="Updates", consent_required=0)
        for status in (None, "Pending", "Subscribed", "Unsubscribed"):
            with self.subTest(status=status):
                reason = consent.consent_exclusion("a@example.com", "Updates", policy=policy,
                    status=status, status_loaded=True, suppressions={})
                self.assertEqual(reason is not None, status == "Unsubscribed")

    def test_optional_consent_loads_the_real_preference(self):
        policy = frappe._dict(available=True, name="Updates", consent_required=0)
        with patch.object(frappe.db, "get_value", return_value="Unsubscribed") as read:
            self.assertIsNotNone(consent.consent_exclusion("a@example.com", "Updates", policy=policy, suppressions={}))
        read.assert_any_call("Email Subscription Preference", {"email": "a@example.com", "subscription_topic": "Updates"}, "status")

    def test_soft_bounce_lookup_is_exact_and_bounded(self):
        with patch.object(frappe, "get_all", return_value=[]) as lookup:
            self.assertFalse(consent._soft_bounce_limit_reached("AN@x.com"))
        self.assertEqual(lookup.call_args.args, (consent.BOUNCE_RECIPIENT,))
        self.assertEqual(lookup.call_args.kwargs["filters"]["email"], "an@x.com")
        self.assertEqual(lookup.call_args.kwargs["limit_page_length"], 3)

    def test_workflow_handoff_requires_confirmed_consent(self):
        class Base:
            def send(self, *a, **kw): raise AssertionError("SMTP must not run")
        class Queue(consent.ConsentQueueMixin, Base): pass
        queue = Queue()
        queue.unsubscribe_method = "/api/method/finbyzreach.subscription_preferences.unsubscribe_address"
        queue.unsubscribe_params = '{"email_type":"Updates"}'
        queue.recipients = [frappe._dict(status="Not Sent", recipient="a@example.com")]
        queue.db_set = MagicMock()
        with patch.object(consent, "email_policy", return_value=frappe._dict(available=True, name="Updates", consent_required=1)), \
                patch.object(consent, "suppressed_addresses", return_value={}), \
                patch.object(frappe.db, "get_value", return_value=None):
            queue.send()
        self.assertIn("No confirmed subscription", queue.db_set.call_args.args[0]["error"])


class SMSRegressionTest(TestCase):
    def test_payload_is_escaped_in_the_guest_template(self):
        source = (Path(__file__).parent / "www/open_sms.html").read_text()
        env = Environment(loader=DictLoader({"templates/web.html": "{% block page_content %}{% endblock %}"}))
        targets = sms_targets("+41 123 456", '<img src=x onerror="alert(1)">')
        html = env.from_string(source).render(**targets, _=lambda value: value)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img', html)
        self.assertIn('%3Cimg', html)


class SegmentRegressionTest(TestCase):
    def test_main_customer_is_reselected_after_a_customer_is_unlinked(self):
        doc = frappe._dict(custom_reach_main_customer="Deleted", links=[frappe._dict(link_doctype="Customer", link_name="Remaining")])
        doc.meta = SimpleNamespace(has_field=lambda field: True)
        segment_automation.validate_main_customer(doc)
        self.assertEqual(doc.custom_reach_main_customer, "Remaining")

    def test_main_customer_is_cleared_without_an_unambiguous_replacement(self):
        doc = frappe._dict(custom_reach_main_customer="Deleted", links=[])
        segment_automation.validate_main_customer(doc)
        self.assertIsNone(doc.custom_reach_main_customer)

    def test_unchanged_membership_does_not_lock_or_recount(self):
        segment = frappe._dict(name="SEG", audience_doctype="Lead")
        query = MagicMock(); query.select.return_value.where.return_value.limit.return_value.run.return_value = [("LEAD",)]
        with patch.object(frappe, "get_all", return_value=["SEG"]), \
                patch.object(frappe, "get_doc", return_value=segment) as get_doc, \
                patch.object(frappe.db, "get_value", return_value=frappe._dict(name="MEM", is_current=1)), \
                patch("finbyzreach.segment_service.member_query", return_value=query):
            self.assertEqual(segment_automation.sync_record("Lead", "LEAD"), set())
        get_doc.assert_called_once_with("Reach Segment", "SEG")

    def test_snapshot_initial_and_recovery_jobs_use_the_same_identity(self):
        with patch.object(frappe, "enqueue") as enqueue, \
                patch.object(frappe, "get_all", side_effect=[[frappe._dict(name="SEG", snapshot_pending_generation="GEN")], []]):
            segment_snapshots.enqueue_build("SEG", "GEN")
            initial = enqueue.call_args.kwargs
            segment_snapshots.recover()
            self.assertEqual(enqueue.call_args.kwargs, initial)
            self.assertTrue(initial["deduplicate"])

    def test_snapshot_recovery_does_not_duplicate_a_running_page(self):
        with patch.object(frappe, "enqueue") as enqueue, \
                patch.object(frappe, "get_all", side_effect=[[frappe._dict(name="SEG", snapshot_pending_generation="GEN")], ["LAST"], []]), \
                patch("frappe.utils.background_jobs.is_job_enqueued", return_value=True):
            segment_snapshots.recover()
        enqueue.assert_not_called()


class SubscriptionRegressionTest(TestCase):
    def test_unsubscribe_get_only_shows_confirmation(self):
        with patch.object(frappe.local, "request", SimpleNamespace(method="GET", query_string=b"signed"), create=True), \
                patch.object(preferences, "signed_address", return_value=("a@example.com", "Updates", {})), \
                patch.object(preferences, "confirm_unsubscribe_page", return_value="Confirm") as page, \
                patch.object(preferences, "unsubscribe") as unsubscribe:
            self.assertEqual(preferences.unsubscribe_address(), "Confirm")
        page.assert_called_once(); unsubscribe.assert_not_called()

    def test_multiple_topics_produce_one_confirmation_email(self):
        def request(email, topic, source, **kwargs):
            kwargs["confirmation_batch"].append(("Confirm", "Confirm " + topic))
            return "Pending"
        with patch.object(preferences, "request_subscription", side_effect=request), \
                patch.object(preferences, "_queue_confirmation") as send:
            self.assertEqual(preferences._request_public_address.__wrapped__("a@example.com", ["A", "B"], "de", "Alice", "One"), "Pending")
        send.assert_called_once_with("a@example.com", "Confirm", "Confirm A<hr>Confirm B")


class AdditionalBoundaryRegressions(TestCase):
    def test_template_membership_predicate_does_not_require_guest_segment_access(self):
        from finbyzreach import segments, segment_service
        query = MagicMock(); query.select.return_value.where.return_value.limit.return_value.run.return_value = [('LEAD',)]
        segment = frappe._dict(name='SEG', audience_doctype='Lead', archived=0)
        with patch.object(segments, '_segment', side_effect=AssertionError('Guest permission path')), \
                patch.object(frappe, 'get_doc', return_value=segment), \
                patch.object(segment_service, 'member_query', return_value=query):
            self.assertTrue(segments.is_segment_member('SEG', {'doctype':'Lead', 'name':'LEAD'}))

    def test_import_email_rows_respect_lead_do_not_contact(self):
        from finbyzreach import consent_import
        lead = frappe._dict(name='LEAD', email_id='person@example.com', unsubscribed=0, status='Do Not Contact')
        with patch.object(frappe, 'get_all', side_effect=[[lead], [], []]), \
                patch('finbyzreach.email_marketing._linked_unsubscribed_leads', return_value=set()), \
                patch('finbyzreach.email_marketing._reference_unsubscribed_pairs', return_value=set()):
            self.assertEqual(consent_import._address_record_optouts(['person@example.com']), {'person@example.com'})

    def test_public_names_are_bound_to_the_new_confirmation_token(self):
        import hashlib
        option = frappe._dict(category='Topic', double_opt_in=0)
        with patch.object(preferences, '_topic', return_value=option), \
                patch.object(preferences, 'is_subscribed', return_value=False), \
                patch.object(frappe.db, 'get_value', return_value=None), \
                patch.object(preferences, '_save', return_value=frappe._dict(name='PREF')), \
                patch.object(consent, 'suppressed_addresses', return_value={}), \
                patch.object(preferences.secrets, 'token_urlsafe', return_value='token'), \
                patch.object(preferences, 'remember_name') as remember, \
                patch.object(preferences, 'doi_message', return_value=('Confirm','Click')), \
                patch.object(preferences, 'get_url', side_effect=lambda value: value):
            preferences.request_subscription('a@example.com', 'News', 'Public registration',
                confirmation_batch=[], subscriber_names={'first_name':'Alice','last_name':'One'})
        remember.assert_called_once_with('PREF:' + hashlib.sha256(b'token').hexdigest(), first_name='Alice', last_name='One')
