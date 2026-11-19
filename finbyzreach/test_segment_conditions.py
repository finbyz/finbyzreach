"""Date rules and multi-value conditions of Reach Segments (SEG-13, SEG-18)."""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from finbyzreach import segment_service as service


class TestSegmentConditions(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.old = self._lead("Old", months=-8)
		self.recent = self._lead("Recent", days=-2)
		self.fresh = self._lead("Fresh")
		self.ours = {self.old.name, self.recent.name, self.fresh.name}

	def _lead(self, tag, **age):
		lead = frappe.get_doc({"doctype": "Lead", "first_name": f"ZZTEST Seg {tag}"})
		lead.flags.skip_automation = True
		lead.insert(ignore_permissions=True)
		if age:
			frappe.db.set_value("Lead", lead.name, "creation", add_to_date(now_datetime(), **age), update_modified=False)
		return lead

	def _members(self, node):
		table = frappe.qb.DocType("Lead")
		condition = service.expression_condition("Lead", {"operator": "AND", "conditions": [node]})
		found = frappe.qb.from_(table).select(table.name).where(condition).run(pluck=True)
		return set(found) & self.ours

	def test_created_more_than_six_months_ago(self):
		node = {"kind": "relative_date", "field": "creation", "comparison": "older_than", "amount": 6, "unit": "months"}
		self.assertEqual(self._members(node), {self.old.name})

	def test_created_in_the_last_seven_days(self):
		node = {"kind": "relative_date", "field": "creation", "comparison": "within_last", "amount": 7, "unit": "days"}
		self.assertEqual(self._members(node), {self.recent.name, self.fresh.name})

	def test_last_activity_more_than_thirty_days_ago_includes_records_without_activity(self):
		frappe.get_doc({
			"doctype": "Communication", "communication_type": "Communication", "communication_medium": "Email",
			"sent_or_received": "Sent", "subject": "ZZTEST activity", "content": "x",
			"reference_doctype": "Lead", "reference_name": self.recent.name,
			"communication_date": add_to_date(now_datetime(), days=-3),
		}).insert(ignore_permissions=True)
		quiet = {"kind": "relative_date", "field": "__last_activity", "comparison": "older_than", "amount": 30, "unit": "days"}
		active = {"kind": "relative_date", "field": "__last_activity", "comparison": "within_last", "amount": 30, "unit": "days"}
		self.assertEqual(self._members(quiet), {self.old.name, self.fresh.name})
		self.assertEqual(self._members(active), {self.recent.name})

	def test_invalid_date_rules_are_rejected(self):
		for node in (
			{"kind": "relative_date", "field": "first_name", "comparison": "older_than", "amount": 1, "unit": "days"},
			{"kind": "relative_date", "field": "creation", "comparison": "sometime", "amount": 1, "unit": "days"},
			{"kind": "relative_date", "field": "creation", "comparison": "older_than", "amount": 0, "unit": "days"},
			{"kind": "relative_date", "field": "__last_activity", "comparison": "within_next", "amount": 1, "unit": "days"},
		):
			with self.subTest(node=node), self.assertRaises(frappe.ValidationError):
				self._members(node)

	def test_multi_value_field_any_all_none(self):
		field = next((f for f in frappe.get_meta("Lead").fields if f.fieldtype == "Table MultiSelect"), None)
		if not field:
			self.skipTest("Lead has no multi-value field on this site")
		link = next(f for f in frappe.get_meta(field.options).fields if f.fieldtype == "Link")
		values = frappe.get_all(link.options, pluck="name", limit=2)
		if len(values) < 2:
			self.skipTest("Need two selectable values")
		first, second = values
		self.old.reload()
		self.recent.reload()
		self.old.append(field.fieldname, {link.fieldname: first})
		self.old.append(field.fieldname, {link.fieldname: second})
		self.old.flags.ignore_validate = True
		self.old.save(ignore_permissions=True)
		self.recent.append(field.fieldname, {link.fieldname: first})
		self.recent.flags.ignore_validate = True
		self.recent.save(ignore_permissions=True)
		node = lambda mode, *vals: {"kind": "multiselect", "field": field.fieldname, "mode": mode, "values": list(vals)}
		self.assertEqual(self._members(node("any", first)), {self.old.name, self.recent.name})
		self.assertEqual(self._members(node("all", first, second)), {self.old.name})
		self.assertEqual(self._members(node("none", second)), {self.recent.name, self.fresh.name})

	def test_multi_value_condition_rejects_a_normal_field(self):
		with self.assertRaises(frappe.ValidationError):
			self._members({"kind": "multiselect", "field": "first_name", "mode": "any", "values": ["x"]})


class TestSegmentPreviewPermission(IntegrationTestCase):
	def test_read_only_user_sees_the_saved_segment_instead_of_a_permission_error(self):
		import json

		from finbyzreach import segments

		frappe.set_user("Administrator")
		email = f"zztest-reader-{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "ZZTest", "send_welcome_email": 0,
			"roles": [{"role": "Sales User"}]}).insert(ignore_permissions=True)
		name = f"ZZTEST Preview {frappe.generate_hash(length=5)}"
		frappe.get_doc({"doctype": "Reach Segment", "segment_name": name, "audience_doctype": "Lead", "segment_type": "Active",
			"filter_groups_json": json.dumps([[["Lead", "status", "=", "Open"]]])}).insert()
		frappe.set_user(email)
		try:
			if frappe.has_permission("Reach Segment", "write", doc=name):
				self.skipTest("Sales User can edit segments on this site")
			edited = json.dumps({"audience_doctype": "Lead", "filter_groups_json": json.dumps([[["Lead", "status", "=", "Replied"]]])})
			result = segments.preview_segment_page(segment_name=name, definition=edited)
			self.assertIn("rows", result)
		finally:
			frappe.set_user("Administrator")


class TestStaticSegmentWithoutFilter(IntegrationTestCase):
	def test_static_segment_without_any_filter_saves_and_starts_empty(self):
		frappe.set_user("Administrator")
		name = f"ZZTEST Static Empty {frappe.generate_hash(length=5)}"
		segment = frappe.get_doc({"doctype": "Reach Segment", "segment_name": name, "audience_doctype": "Lead", "segment_type": "Static"}).insert()
		self.assertEqual(frappe.db.get_value("Reach Segment", segment.name, "member_count") or 0, 0)

	def test_active_segment_still_needs_a_filter(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Reach Segment", "segment_name": f"ZZTEST Active Empty {frappe.generate_hash(length=5)}",
				"audience_doctype": "Lead", "segment_type": "Active"}).insert()


class TestBounceSegmentFilter(IntegrationTestCase):
	def test_bounced_is_an_accepted_email_activity_for_segment_filters(self):
		from finbyzreach import segment_service as service

		frappe.set_user("Administrator")
		if not frappe.db.table_exists("Email Tracking Event"):
			self.skipTest("Email tracking is not installed")
		for event in ("Bounced", "Soft-Bounced"):
			service.activity_condition("Lead", {"kind": "activity", "event": event, "days": 30})
		with self.assertRaises(frappe.ValidationError):
			service.activity_condition("Lead", {"kind": "activity", "event": "Nonsense", "days": 30})
