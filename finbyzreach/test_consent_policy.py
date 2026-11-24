"""Consent decisions and delivery boundaries; no live mail or schema changes."""
from email.parser import Parser
from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import frappe

from finbyzreach import consent, subscription_preferences as preferences


def policy(**values):
	return frappe._dict(available=True, name="Updates", category="Mailing Type", disabled=0,
		consent_required=1, double_opt_in=1, deliver_while_pending=0, **values)


class TestConsentPolicy(TestCase):
	def setUp(self):
		for module in (consent, preferences):
			clock = patch.object(module, "now_datetime", return_value=datetime(2026, 11, 24, 12))
			clock.start()
			self.addCleanup(clock.stop)

	def test_required_consent_and_pending_policy_matrix(self):
		for pending in (0, 1):
			for state in (None, "Unsubscribed", "Pending", "Subscribed"):
				with self.subTest(pending=pending, status=state):
					p = policy(); p.deliver_while_pending = pending
					reason = consent.consent_exclusion("PERSON@EXAMPLE.COM", "Updates", policy=p,
						status=state, status_loaded=True, suppressions={})
					self.assertEqual(reason is None, state == "Subscribed" or (state == "Pending" and pending == 1))

	def test_nonrequired_consent_still_blocks_hard_bounce_and_spam(self):
		p = policy(); p.consent_required = 0
		for kind in (None, "Hard bounce", "Spam complaint"):
			with self.subTest(reason=kind):
				blocks = {"person@example.com": kind} if kind else {}
				reason = consent.consent_exclusion("person@example.com", "Transactional", policy=p,
					status="Unsubscribed", status_loaded=True, suppressions=blocks)
				self.assertEqual(reason, kind)

	def test_missing_or_disabled_email_type_fails_closed(self):
		with patch.object(consent.frappe.db, "get_value", return_value=None), patch.object(consent, "policy_ready", return_value=True):
			self.assertFalse(consent.email_policy("Unknown").available)
			self.assertIsNotNone(consent.consent_exclusion("person@example.com", "Unknown", suppressions={}))
		for row in (frappe._dict(name="Updates", category="Mailing Type", disabled=1, consent_required=1),
			frappe._dict(name="BIPV", category="Topic", disabled=0, consent_required=0),
			frappe._dict(name="Other system", category="System", disabled=0, consent_required=0)):
			with self.subTest(option=row.name), patch.object(consent, "policy_ready", return_value=True), patch.object(consent.frappe.db, "get_value", return_value=row):
				self.assertFalse(consent.email_policy(row.name).available)

	def test_bulk_decisions_for_thirty_thousand_addresses_do_not_query_per_person(self):
		p = policy()
		with patch.object(consent.frappe.db, "get_value", side_effect=AssertionError("Unexpected per-address query")):
			for i in range(30000):
				self.assertIsNone(consent.consent_exclusion(f"person{i}@example.com", "Updates", policy=p,
					status="Subscribed", status_loaded=True, suppressions={}))

	def test_suppression_lookup_uses_bounded_indexed_address_batches(self):
		with patch.object(consent.frappe.db, "table_exists", return_value=True), patch.object(frappe, "get_all", return_value=[]) as get_all:
			self.assertEqual(consent.suppressed_addresses([f"PERSON{i}@EXAMPLE.COM" for i in range(20000)]), {})
		self.assertEqual(get_all.call_count, 40)
		self.assertTrue(all(len(call.kwargs["filters"]["email"][1]) <= 500 for call in get_all.call_args_list))

	def test_feedback_blocks_each_normalized_address_and_ignores_soft_bounces(self):
		doc = frappe._dict(name="COMM-1", sent_or_received="Sent", delivery_status="Bounced",
			recipients="Alice <ALICE@example.com>, Bob <bob@example.com>")
		with patch.object(consent, "sync_soft_bounce_recipients"), patch.object(frappe.db, "table_exists", return_value=True), patch.object(frappe.db, "get_value", return_value=None), patch.object(frappe, "get_doc") as get_doc:
			consent.capture_delivery_failure(doc)
			self.assertEqual({call.args[0]["email"] for call in get_doc.call_args_list}, {"alice@example.com", "bob@example.com"})
			get_doc.reset_mock(); doc.delivery_status = "Soft-Bounced"
			with patch.object(consent, "_soft_bounce_limit_reached", return_value=False):
				consent.capture_delivery_failure(doc)
			get_doc.assert_not_called()

	def test_list_unsubscribe_headers_are_standard_idempotent_and_preserve_body(self):
		queue = SimpleNamespace(message="Subject: Example\r\nContent-Type: text/html\r\n\r\n<p>Hello</p>")
		queue.db_set = lambda field, value, **kwargs: setattr(queue, field, value)
		url = "https://example.com/unsubscribe?_signature=one"
		consent.add_list_headers(queue, url); original = queue.message
		consent.add_list_headers(queue, url)
		self.assertEqual(queue.message, original)
		parsed = Parser().parsestr(queue.message)
		self.assertEqual(parsed["List-Unsubscribe"], "<" + url + ">")
		self.assertEqual(parsed["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
		self.assertIsNone(parsed["X-List-Unsubscribe"])
		self.assertEqual(parsed.get_payload(), "<p>Hello</p>")

	def test_address_links_bind_email_type_and_scope_against_tampering(self):
		with patch("frappe.utils.verified_command.get_secret", return_value="isolated-test-secret"), patch.object(preferences, "get_url", side_effect=lambda path: "https://example.com" + path):
			url = preferences.address_urls("PERSON@example.com", "Updates")["unsubscribe_all_url"]
			query = urlsplit(url).query
			email, email_type, params = preferences.signed_address(query)
			self.assertEqual((email, email_type, params["scope"]), ("person@example.com", "Updates", ["all"]))
			for invalid in (query.replace("person%40example.com", "other%40example.com"), query.replace("Updates", "Transactional"), query.replace("scope=all", "scope=one")):
				with self.assertRaises(frappe.PermissionError):
					preferences.signed_address(invalid)

	def test_doi_off_subscribes_without_sending_confirmation(self):
		option = policy(); option.double_opt_in = 0
		with patch.object(preferences, "_topic", return_value=option), patch.object(preferences, "is_subscribed", return_value=False), patch.object(preferences, "_save") as save, patch.object(frappe, "sendmail") as send:
			self.assertEqual(preferences.request_subscription("person@example.com", "Updates"), "Subscribed")
			save.assert_called_once_with("person@example.com", "Updates", "Subscribed", "Preference center")
			send.assert_not_called()

	def test_doi_on_schedules_confirmation_only_after_transaction_commit(self):
		option = policy()
		with patch.object(preferences, "_topic", return_value=option), patch.object(preferences, "is_subscribed", return_value=False), patch.object(frappe.db, "get_value", return_value=None), patch.object(preferences, "_save", return_value=frappe._dict(name="PREF-1")) as save, patch.object(frappe, "sendmail", return_value=SimpleNamespace(name="QUEUE-1")) as send, patch.object(frappe, "enqueue_doc") as enqueue, patch.object(preferences, "get_url", side_effect=lambda value: "https://example.com" + value), patch.object(consent, "suppressed_addresses", return_value={}), patch.object(consent, "policy_ready", return_value=True):
			self.assertEqual(preferences.request_subscription("person@example.com", "Updates"), "Pending")
			self.assertEqual(save.call_args.args[2], "Pending")
			self.assertEqual(len(save.call_args.kwargs["token_hash"]), 64)
			self.assertTrue(send.call_args.kwargs["delayed"])
			self.assertEqual(send.call_args.kwargs["unsubscribe_params"], {"email_type": "Transactional"})
			enqueue.assert_called_once_with("Email Queue", "QUEUE-1", "send", queue="short", enqueue_after_commit=True)

	def test_topic_preferences_do_not_need_confirmation(self):
		option = policy(); option.category = "Topic"
		with patch.object(preferences, "_topic", return_value=option), patch.object(preferences, "is_subscribed", return_value=False), patch.object(preferences, "_save") as save, patch.object(frappe, "sendmail") as send:
			self.assertEqual(preferences.request_subscription("person@example.com", "BIPV"), "Subscribed")
			self.assertEqual(save.call_args.args[2], "Subscribed"); send.assert_not_called()

	def test_confirmation_keeps_the_original_consent_text_revision(self):
		doc = frappe._dict(email="person@example.com", subscription_topic="Updates", status="Pending",
			consent_version="v1", consent_text="Original consent", is_new=lambda: False, save=MagicMock())
		option = policy(); option.description = "New consent"; option.modified = "v2"
		event = MagicMock()
		with patch.object(preferences, "_topic", return_value=option), patch.object(frappe.db, "exists", return_value=True), patch.object(frappe, "get_doc", side_effect=lambda target, *args, **kwargs: doc if target == preferences.PREFERENCE_DOCTYPE else event) as get_doc:
			preferences._save("person@example.com", "Updates", "Subscribed", "Double opt-in confirmation")
			self.assertEqual((doc.consent_version, doc.consent_text), ("v1", "Original consent"))
			self.assertEqual(get_doc.call_args.args[0]["consent_text"], "Original consent")

	def test_queue_rechecks_unsubscribe_before_smtp_and_retains_skipped_reason(self):
		from finbyzreach import email_marketing
		class Base:
			def send(self, *args, **kwargs): raise AssertionError("SMTP must not be reached")
		class Queue(consent.ConsentQueueMixin, Base): pass
		q = Queue(); q.unsubscribe_method = "/api/method/" + email_marketing.UNSUBSCRIBE_METHOD
		q.unsubscribe_params = '{"campaign_recipient":"REC-1"}'
		q.recipients = [frappe._dict(status="Not Sent", recipient="person@example.com")]
		q.db_set = MagicMock()
		recipient = frappe._dict(name="REC-1", custom_recipient_email="person@example.com", campaign_name="CAM-1")
		with patch.object(frappe, "get_doc", side_effect=[recipient, frappe._dict(name="CAM-1")]), patch.object(email_marketing, "_current_recipient_exclusion", return_value="Recipient unsubscribed"), patch.object(email_marketing, "mark_campaign_metrics_dirty"), patch.object(frappe.db, "set_value") as set_value:
			q.send(force_send=True)
			self.assertEqual(q.db_set.call_args.args[0]["status"], "Error")
			self.assertEqual(set_value.call_args.args[2]["custom_delivery_status"], "Skipped")

	def test_queue_without_email_type_is_suppressed_before_smtp(self):
		class Base:
			def send(self, *args, **kwargs): raise AssertionError("SMTP must not be reached")
		class Queue(consent.ConsentQueueMixin, Base): pass
		q = Queue(); q.unsubscribe_method = "/api/method/finbyzreach.subscription_preferences.unsubscribe_address"
		q.unsubscribe_params = '{"email_type": ""}'
		q.recipients = [frappe._dict(status="Not Sent", recipient="person@example.com")]
		q.db_set = MagicMock()
		q.send(force_send=True)
		values = q.db_set.call_args.args[0]
		self.assertEqual(values["status"], "Error")
		self.assertIn("No email type", values["error"])

	def test_untyped_test_recipient_still_blocks_hard_bounce(self):
		from finbyzreach import email_marketing
		with patch.object(email_marketing, "suppressed_addresses", return_value={"person@example.com": "Hard bounce"}):
			self.assertEqual(email_marketing.test_recipient_exclusion("Person@Example.com", None), "Hard bounce")

	def test_queue_does_not_reclassify_already_sent_messages(self):
		class Base:
			def send(self, *args, **kwargs): return "native-no-op"
		class Queue(consent.ConsentQueueMixin, Base): pass
		q = Queue(); q.unsubscribe_method = "/api/method/finbyzreach.subscription_preferences.unsubscribe_address"
		q.unsubscribe_params = "invalid old data"; q.recipients = [frappe._dict(status="Sent")]
		q.db_set = MagicMock()
		self.assertEqual(q.send(), "native-no-op"); q.db_set.assert_not_called()
