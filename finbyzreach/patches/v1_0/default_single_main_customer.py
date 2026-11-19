"""SEG-14: contacts linked to exactly one Customer get it as main customer.

Contacts linked to several customers stay empty, the user picks one. Only
the one field is written, without touching ``modified``.
"""
import frappe


def execute():
    if not frappe.db.has_column('Contact', 'custom_reach_main_customer'):
        return
    frappe.db.sql("""
        update `tabContact` c
        join (
            select parent, min(link_name) customer
            from `tabDynamic Link`
            where parenttype = 'Contact' and parentfield = 'links' and link_doctype = 'Customer'
            group by parent
            having count(distinct link_name) = 1
        ) one on one.parent = c.name
        set c.custom_reach_main_customer = one.customer
        where ifnull(c.custom_reach_main_customer, '') = ''
    """)
    for name in frappe.get_all('Reach Segment', filters={'audience_doctype':'Contact','segment_type':'Active','archived':0}, pluck='name'):
        frappe.enqueue('finbyzreach.segment_automation.reconcile_segment', segment_name=name,
                       queue='long', enqueue_after_commit=True, job_id=f'reach-reconcile:{name}', deduplicate=True)
