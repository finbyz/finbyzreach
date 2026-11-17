"""Real Campaign lifecycle regression, contained in a rollback-only savepoint."""
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

import frappe
from finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio import (
	check_campaign_title,
	create_campaign,
)


class TestStudioDraftPersistence(TestCase):
	def test_draft_insert_reload_update_and_duplicate_use_native_utm_mirror(self):
		database = frappe.local.db
		self.assertTrue(database.has_column("UTM Campaign", "crm_campaign"),
			"Run restore_campaign_utm_link before saving Campaign documents")
		savepoint = "studio_draft_" + uuid4().hex
		database.savepoint(savepoint)
		try:
			with ExitStack() as stack:
				for owner, method in ((database, "commit"), (frappe, "sendmail"), (frappe, "enqueue")):
					stack.enter_context(patch.object(owner, method, side_effect=AssertionError("No commits, mail or jobs in draft verification")))
				title = "Studio draft regression " + uuid4().hex[:12]
				payload = {"campaign_title": title, "audience_doctype": "Lead", "filters": []}
				result = create_campaign(payload, launch="draft")
				name = result["campaign"]
				doc = frappe.get_doc("Campaign", name)
				self.assertEqual(doc.custom_broadcast_status, "Draft")
				self.assertEqual(doc.campaign_name, title)
				self.assertTrue(database.get_value("UTM Campaign", {"crm_campaign": name}))
				self.assertFalse(check_campaign_title(title)["available"])
				self.assertTrue(check_campaign_title(title, name)["available"])
				payload.update(source_campaign=name, sender_name="Updated sender")
				self.assertEqual(create_campaign(payload, launch="draft")["campaign"], name)
				self.assertEqual(database.get_value("Campaign", name, "custom_sender_name"), "Updated sender")
				payload.pop("source_campaign")
				with self.assertRaises(frappe.ValidationError):
					create_campaign(payload, launch="draft")
		finally:
			database.rollback(save_point=savepoint)
