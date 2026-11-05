import frappe
from frappe.model.document import Document


class ReachSegment(Document):
    def validate(self):
        from finbyzreach.segment_service import validate_segment
        validate_segment(self)

    def on_update(self):
        before = self.get_doc_before_save()
        if self.segment_type == 'Active' and not self.archived and (not before or any(
            before.get(key) != self.get(key) for key in ('segment_type','filter_groups_json','filter_expression_json',
                'exclude_filters_json','exclude_segments_json','exclude_email_groups_json','archived'))):
            frappe.enqueue('finbyzreach.segment_automation.reconcile_segment', segment_name=self.name,
                           queue='long', enqueue_after_commit=True)

    def on_trash(self):
        from finbyzreach.segment_service import assert_unused, MEMBER, EXCLUSION
        assert_unused(self, blocking=True)
        frappe.db.delete(MEMBER, {'segment': self.name})
        frappe.db.delete(EXCLUSION, {'segment': self.name})
