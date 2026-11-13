import frappe
from frappe.model.document import Document


class ReachSegment(Document):
    def validate(self):
        from finbyzreach.segment_service import validate_segment
        validate_segment(self)

    def on_update(self):
        before = self.get_doc_before_save()
        if not self.archived and self.snapshot_pending_generation and before and before.archived:
            frappe.enqueue('finbyzreach.segment_snapshots.build',segment_name=self.name,
                generation=self.snapshot_pending_generation,queue='long',enqueue_after_commit=True)
        if not self.archived and not self.snapshot_pending_generation and (not before or any(
            before.get(key) != self.get(key) for key in ('segment_type','filter_groups_json','filter_expression_json',
                'exclude_filters_json','exclude_segments_json','exclude_email_groups_json','archived','snapshot_generation'))):
            from finbyzreach.segment_automation import schedule_reconciliation
            schedule_reconciliation(self.name)

    def on_trash(self):
        from finbyzreach.segment_service import assert_unused, MEMBER, EXCLUSION
        assert_unused(self, blocking=True)
        from finbyzreach.segment_automation import segment_references
        dependent = [row.name for row in frappe.get_all('Reach Segment',fields=['name','exclude_segments_json','filter_expression_json'])
                     if row.name != self.name and self.name in segment_references(row)]
        if dependent:
            frappe.throw(frappe._('Segment is referenced by: {0}').format(', '.join(dependent)))
        frappe.db.delete(MEMBER, {'segment': self.name})
        frappe.db.delete(EXCLUSION, {'segment': self.name})
        for doctype in ('Reach Segment Snapshot Row','Reach Segment Membership Event','Reach Segment Size Sample'):
            frappe.db.delete(doctype,{'segment':self.name})
