"""Composite indexes for bounded recipient scans and membership lookups."""
import frappe

INDEXES = (
    ('Email Tracking Event', ['event_type','event_time','lead'], 'reach_lead_activity'),
    ('Email Tracking Event', ['event_type','event_time','contact'], 'reach_contact_activity'),
    ('Contrast Engagement Event', ['engagement_type','activity_datetime','linked_contact'], 'reach_webinar_activity'),
    ('Tracker Pageview', ['visitor_id','received_at'], 'reach_pageview_activity'),
    ('Tracker Conversion', ['visitor_id','received_at'], 'reach_purchase_activity'),
    ('Email Campaign', ['custom_delivery_status', 'custom_scheduled_at', 'custom_batch_number', 'name'], 'reach_due_recipients'),
    ('Email Campaign', ['campaign_name', 'custom_delivery_status', 'name'], 'reach_campaign_status'),
    ('Email Campaign', ['custom_delivery_status', 'custom_email_queue'], 'reach_queue_outcome'),
    ('Dynamic Link', ['link_doctype', 'link_name', 'parenttype', 'parent'], 'reach_customer_contacts'),
    ('Email Subscription Preference', ['email', 'subscription_topic', 'status'], 'reach_subscription_lookup'),
)


def execute():
    for doctype, fields, name in INDEXES:
        if frappe.db.table_exists(doctype) and all(frappe.db.has_column(doctype, f) for f in fields):
            frappe.db.add_index(doctype, fields, name)
