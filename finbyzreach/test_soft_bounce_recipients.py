"""Transactional regression tests for the indexed soft-bounce projection."""
from datetime import timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import now_datetime

from finbyzreach import consent
from finbyzreach.patches.v1_0 import index_soft_bounce_recipients as migration


class SoftBounceRecipientsTest(TestCase):
	def setUp(self):
		self.prefix = frappe.generate_hash(length=12)
		self.now = now_datetime()
		self.original_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user(self.original_user)

	def communication(self, suffix, recipients, age=0, status="Soft-Bounced"):
		return frappe._dict(name=f"bounce-test-{self.prefix}-{suffix}", recipients=recipients,
			creation=self.now - timedelta(days=age), sent_or_received="Sent", delivery_status=status)

	def test_exact_mailboxes_threshold_and_repeat_saves(self):
		email = f"jan-{self.prefix}@example.com"
		other = f"an-{self.prefix}@example.com"
		for i in range(3):
			doc = self.communication(str(i), f'Jan <{email.upper()}>, {email}')
			consent.sync_soft_bounce_recipients(doc)
			consent.sync_soft_bounce_recipients(doc)
			self.assertEqual(consent._soft_bounce_limit_reached(email), i == 2)
		self.assertFalse(consent._soft_bounce_limit_reached(other))
		self.assertEqual(frappe.db.count(consent.BOUNCE_RECIPIENT, {"email": email}), 3)

	def test_window_and_configured_threshold(self):
		email = f"window-{self.prefix}@example.com"
		for i, age in enumerate((0, 1, 91)):
			consent.sync_soft_bounce_recipients(self.communication(str(i), email, age=age))
		self.assertFalse(consent._soft_bounce_limit_reached(email))
		with patch.dict(frappe.conf, {"soft_bounce_limit": 2}):
			self.assertTrue(consent._soft_bounce_limit_reached(email.upper()))

	def test_recipient_edits_status_changes_and_deletion_remove_old_matches(self):
		one, two = f"one-{self.prefix}@example.com", f"two-{self.prefix}@example.com"
		doc = self.communication("edit", f"{one}, {two}")
		consent.sync_soft_bounce_recipients(doc)
		doc.recipients = two
		consent.sync_soft_bounce_recipients(doc)
		self.assertEqual(frappe.db.count(consent.BOUNCE_RECIPIENT, {"communication": doc.name}), 1)
		self.assertFalse(frappe.db.exists(consent.BOUNCE_RECIPIENT, {"email": one}))
		doc.delivery_status = "Sent"
		consent.capture_delivery_failure(doc)
		self.assertFalse(frappe.db.exists(consent.BOUNCE_RECIPIENT, {"communication": doc.name}))
		doc.delivery_status = "Soft-Bounced"
		consent.sync_soft_bounce_recipients(doc)
		consent.sync_soft_bounce_recipients(doc, "after_delete")
		self.assertFalse(frappe.db.exists(consent.BOUNCE_RECIPIENT, {"communication": doc.name}))

	def test_inbound_and_invalid_addresses_do_not_count(self):
		doc = self.communication("invalid", "invalid, Valid <VALID@example.com>, valid@example.com")
		consent.sync_soft_bounce_recipients(doc)
		self.assertEqual(frappe.get_all(consent.BOUNCE_RECIPIENT,
			filters={"communication": doc.name}, pluck="email"), ["valid@example.com"])
		doc.sent_or_received = "Received"
		consent.sync_soft_bounce_recipients(doc)
		self.assertFalse(frappe.db.exists(consent.BOUNCE_RECIPIENT, {"communication": doc.name}))

	def test_current_bounce_is_counted_before_suppression_and_saves_are_idempotent(self):
		email = f"suppress-{self.prefix}@example.com"
		for i in range(2):
			consent.sync_soft_bounce_recipients(self.communication(str(i), email))
		doc = self.communication("last", email)
		with patch.object(frappe, "get_doc", return_value=MagicMock()) as insert:
			consent.capture_delivery_failure(doc)
		insert.assert_called_once()
		self.assertEqual(insert.call_args.args[0]["reason"], "Repeated soft bounce")
		with patch.object(frappe.db, "get_value", return_value="existing-suppression"), \
				patch.object(frappe, "get_doc") as insert:
			consent.capture_delivery_failure(doc)
		insert.assert_not_called()
		self.assertEqual(frappe.db.count(consent.BOUNCE_RECIPIENT, {"email": email}), 3)

	def test_migration_populates_all_rows_before_threshold_checks_and_is_idempotent(self):
		email = f"backfill-{self.prefix}@example.com"
		rows = [self.communication(str(i), email) for i in range(3)]
		checked = []
		def capture(doc):
			checked.append(consent._soft_bounce_limit_reached(email))
		with patch.object(frappe, "reload_doc"), \
				patch.object(migration, "recent_bounces", side_effect=lambda since: iter(rows)), \
				patch.object(migration, "capture_delivery_failure", side_effect=capture):
			migration.execute()
			migration.execute()
		self.assertEqual(checked, [True] * 6)
		self.assertEqual(frappe.db.count(consent.BOUNCE_RECIPIENT, {"email": email}), 3)

	def test_backfill_uses_keyset_pages(self):
		first = [self.communication(f"{i:04}", "a@example.com") for i in range(500)]
		with patch.object(frappe, "get_all", side_effect=[first, []]) as fetch:
			self.assertEqual(len(list(migration.recent_bounces(self.now))), 500)
		self.assertEqual(fetch.call_args.kwargs["filters"]["name"], [">", first[-1].name])
		self.assertEqual(fetch.call_args.kwargs["limit_page_length"], 500)

	def test_large_unrelated_history_does_not_expand_the_mailbox_lookup(self):
		for i in range(300):
			consent.sync_soft_bounce_recipients(self.communication(str(i), f"other-{i}-{self.prefix}@example.com"))
		lookup = frappe.get_all
		with patch.object(frappe, "get_all", wraps=lookup) as fetch:
			self.assertFalse(consent._soft_bounce_limit_reached(f"missing-{self.prefix}@example.com"))
		fetch.assert_called_once()
		self.assertEqual(fetch.call_args.args, (consent.BOUNCE_RECIPIENT,))
		self.assertEqual(fetch.call_args.kwargs["limit_page_length"], 3)

	def test_real_communication_hooks_track_db_set_and_delete(self):
		email = f"lifecycle-{self.prefix}@example.com"
		doc = frappe.get_doc({"doctype": "Communication", "communication_type": "Communication",
			"communication_medium": "Email", "sent_or_received": "Sent", "subject": "Bounce lifecycle test",
			"sender": "sender@example.com", "recipients": email, "content": "Test", "delivery_status": "Sent"}).insert(ignore_permissions=True)
		self.assertFalse(frappe.db.exists(consent.BOUNCE_RECIPIENT, {"communication": doc.name}))
		doc.db_set("delivery_status", "Soft-Bounced")
		self.assertEqual(frappe.db.count(consent.BOUNCE_RECIPIENT, {"communication": doc.name}), 1)
		doc.db_set("delivery_status", "Sent")
		self.assertFalse(frappe.db.exists(consent.BOUNCE_RECIPIENT, {"communication": doc.name}))
		doc.db_set("delivery_status", "Soft-Bounced")
		doc.delete(ignore_permissions=True)
		self.assertFalse(frappe.db.exists(consent.BOUNCE_RECIPIENT, {"communication": doc.name}))
