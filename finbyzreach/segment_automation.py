"""Reach Segment adapters for FinbyzAI business events."""
import frappe

TOPIC = 'crm.segment.entered'


def referenced_segments(graph):
    from finbyzai.workflow_builder.schema import condition_predicates
    result = set()
    def visit(value):
        if isinstance(value, dict):
            if value.get('event_topic') == TOPIC:
                predicates = condition_predicates(value.get('event_filter'))
                selected = [p for p in predicates if p.get('field') == 'segment' and p.get('operator') in ('eq', 'in')]
                if not selected:
                    result.add('*')
                for predicate in selected:
                    names = predicate.get('value')
                    result.update(names if isinstance(names, list) else [str(names or '')])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(frappe.parse_json(graph or '{}'))
    return result


def emit_entry(segment, record_name, occurrence):
    from finbyzai.workflow_builder.configuration import automation_enabled
    if not automation_enabled():
        return
    from finbyzai.workflow_builder.events import signal_business_event
    signal_business_event(TOPIC, {'segment': segment.name, 'event_id': occurrence},
                          record_doctype=segment.audience_doctype, record_name=record_name,
                          idempotency_key=occurrence)


def sync_record(doctype, name):
    from finbyzreach.segment_service import member_query, MEMBER, _insert_members
    table = frappe.qb.DocType(doctype)
    affected = set()
    for segment_name in frappe.get_all('Reach Segment', filters={
        'audience_doctype': doctype, 'segment_type': 'Active', 'archived': 0}, pluck='name'):
        segment = frappe.get_doc('Reach Segment', segment_name, for_update=True)
        try:
            matches = bool(member_query(segment).select(table.name).where(table.name == name).limit(1).run())
        except (frappe.ValidationError, frappe.DoesNotExistError):
            # A removed custom field in one saved definition must not block all
            # pending CRM records. Explicit previews and mailings still fail.
            frappe.clear_last_message()
            frappe.logger('finbyzreach').warning('Invalid Reach Segment definition during change processing: %s', segment.name)
            continue
        affected.add(segment.name)
        previous = frappe.db.get_value(MEMBER, {'segment': segment.name, 'record_name': name}, ['name', 'source'], as_dict=True)
        if matches and not previous:
            _insert_members(segment.name, [name])
            emit_entry(segment, name, f'segment:{segment.name}:{name}:{frappe.generate_hash(length=16)}')
        elif not matches and previous and previous.source == 'Filtered':
            frappe.db.delete(MEMBER, {'name': previous.name})

    return affected


def capture_change(doc, method=None):
    if doc.doctype not in ('Lead', 'Contact', 'Customer') or not frappe.db.table_exists('Reach Segment Pending Record'):
        return
    from hashlib import sha256
    from frappe.utils import now_datetime
    key = sha256(f'{doc.doctype}\0{doc.name}'.encode()).hexdigest()
    now = now_datetime()
    user = frappe.session.user
    frappe.db.bulk_insert('Reach Segment Pending Record',
        ['name','creation','modified','owner','modified_by','record_doctype','record_name'],
        [(key,now,now,user,user,doc.doctype,doc.name)], ignore_duplicates=True)
    enqueue_changes()


def enqueue_changes():
    if not frappe.db.table_exists('Reach Segment Pending Record'):
        return
    first = frappe.get_all('Reach Segment Pending Record', pluck='name', order_by='creation asc, name asc', limit_page_length=1)
    if first:
        frappe.enqueue('finbyzreach.segment_automation.drain_changes', queue='short', enqueue_after_commit=True,
                       job_id=f'reach-segment-changes:{first[0]}', deduplicate=True)


def drain_changes():
    user = frappe.session.user
    try:
        frappe.set_user('Administrator')
        rows = frappe.get_all('Reach Segment Pending Record', fields=['name','record_doctype','record_name'],
                              order_by='creation asc, name asc', limit_page_length=100)
        affected = set()
        for row in rows:
            # Serialize a change with concurrent updates to the same pending key.
            if not frappe.db.exists('Reach Segment Pending Record', row.name):
                continue
            frappe.get_doc('Reach Segment Pending Record', row.name, for_update=True)
            affected.update(sync_record(row.record_doctype, row.record_name))
            frappe.db.delete('Reach Segment Pending Record', {'name':row.name})
        from finbyzreach.segment_service import count_members
        for name in affected:
            segment = frappe.get_doc('Reach Segment', name)
            frappe.db.set_value('Reach Segment', name, 'member_count', count_members(segment), update_modified=False)
        enqueue_changes()
    finally:
        frappe.set_user(user)


def capture_publication(doc, method=None):
    before = doc.get_doc_before_save()
    if (doc.status == 'ACTIVE' and doc.active_version and
        (not before or before.active_version != doc.active_version or before.status != 'ACTIVE')):
        frappe.enqueue('finbyzreach.segment_automation.enroll_current_members', workflow_name=doc.name,
                       version=doc.active_version, queue='long', enqueue_after_commit=True,
                       job_id=f'reach-publish:{doc.name}:{doc.active_version}', deduplicate=True)


def enroll_current_members(workflow_name, version, segment_name=None, after=None):
    from hashlib import sha256
    from finbyzreach.segment_service import member_names
    from finbyzai.workflow_builder.schema import event_trigger_entries, event_filter_matches, evaluate_expression
    from finbyzai.workflow_builder.engine import enroll
    workflow = frappe.get_doc('Automation Workflow', workflow_name)
    if workflow.status != 'ACTIVE' or workflow.active_version != version:
        return
    subscriptions = frappe.get_all('Automation Trigger Subscription',
        filters={'workflow': workflow.name, 'workflow_version': version, 'active':1, 'event_type':'EVENT'}, fields=['config_json'])
    configs = []
    for subscription in subscriptions:
        config = frappe.parse_json(subscription.config_json or '{}')
        for entry in event_trigger_entries(config, 2 if isinstance(config.get('events'), list) else 1):
            if entry.get('event_topic') == TOPIC:
                configs.append((config, entry))
    if not configs:
        return
    names = frappe.get_all('Reach Segment', filters={'audience_doctype':workflow.primary_doctype,'archived':0}, pluck='name', order_by='name asc')
    if segment_name:
        names = [name for name in names if name >= segment_name]
    for name in names:
        matching = [(config,entry) for config,entry in configs if event_filter_matches(entry.get('event_filter'), {'segment':name})]
        if not matching:
            continue
        segment = frappe.get_doc('Reach Segment', name)
        records = member_names(segment, after=after if name == segment_name else None, limit=200)
        for record_name in records:
            record = frappe.get_doc(workflow.primary_doctype, record_name)
            if any(evaluate_expression(config.get('condition'), record) for config,entry in matching):
                occurrence = sha256(f'{version}\0{record_name}'.encode()).hexdigest()
                enroll(workflow.name, workflow.primary_doctype, record_name, source=f'EVENT:{TOPIC}', occurrence_key=f'segment-publication:{occurrence}')
        if len(records) == 200:
            frappe.enqueue('finbyzreach.segment_automation.enroll_current_members', workflow_name=workflow.name,
                version=version, segment_name=name, after=records[-1], queue='long', enqueue_after_commit=True,
                job_id=f'reach-publish:{workflow.name}:{version}:{name}:{records[-1]}', deduplicate=True)
            return
        after = None


def reconcile_segment(segment_name, after=None):
    from finbyzreach.segment_service import member_names, member_query, MEMBER, _insert_members
    segment = frappe.get_doc('Reach Segment', segment_name, for_update=True)
    if segment.get('archived') or segment.segment_type != 'Active':
        return
    names = member_names(segment, after=after, limit=200)
    previous = set(frappe.get_all(MEMBER, filters={'segment':segment.name,'record_name':['in',names]}, pluck='record_name')) if names else set()
    _insert_members(segment.name, names)
    for name in set(names)-previous:
        emit_entry(segment, name, f'segment:{frappe.generate_hash(length=32)}')
    if len(names) == 200:
        frappe.enqueue('finbyzreach.segment_automation.reconcile_segment', segment_name=segment.name, after=names[-1],
                       queue='long', enqueue_after_commit=True)
    else:
        frappe.enqueue('finbyzreach.segment_automation.clean_segment_members', segment_name=segment.name,
                       queue='long', enqueue_after_commit=True)


def clean_segment_members(segment_name, after=None):
    from finbyzreach.segment_service import MEMBER, member_query
    segment = frappe.get_doc('Reach Segment', segment_name, for_update=True)
    if segment.get('archived') or segment.segment_type != 'Active':
        return
    filters = {'segment':segment.name,'source':'Filtered'}
    if after:
        filters['name'] = ['>',after]
    rows = frappe.get_all(MEMBER, filters=filters, fields=['name','record_name'], order_by='name asc', limit_page_length=200)
    if rows:
        table = frappe.qb.DocType(segment.audience_doctype)
        current = {row[0] for row in member_query(segment).select(table.name)
                   .where(table.name.isin([row.record_name for row in rows])).run()}
        stale = [row.name for row in rows if row.record_name not in current]
        if stale:
            frappe.db.delete(MEMBER, {'name':['in',stale]})
    if len(rows) == 200:
        frappe.enqueue('finbyzreach.segment_automation.clean_segment_members', segment_name=segment.name,
                       after=rows[-1].name, queue='long', enqueue_after_commit=True)
    else:
        from finbyzreach.segment_service import count_members
        frappe.db.set_value('Reach Segment', segment.name, 'member_count', count_members(segment), update_modified=False)


def refresh_time_segments():
    for name in frappe.get_all('Reach Segment', filters={'segment_type':'Active','archived':0}, pluck='name'):
        frappe.enqueue('finbyzreach.segment_automation.reconcile_segment', segment_name=name,
                       queue='long', enqueue_after_commit=True, job_id=f'reach-reconcile:{name}', deduplicate=True)


def validate_main_customer(doc, method=None):
    main = doc.get('custom_reach_main_customer')
    if main and not any(row.link_doctype == 'Customer' and row.link_name == main for row in doc.get('links') or []):
        frappe.throw(frappe._('The main Customer must be linked to this Contact'))


def queue_identity(doctype, name):
    if doctype not in ('Lead','Contact','Customer') or not name:
        return
    capture_change(frappe._dict(doctype=doctype,name=name))


def capture_related_change(doc, method=None):
    """A related document can change membership without editing the CRM record."""
    for value in (doc, doc.get_doc_before_save()):
        if not value:
            continue
        if value.doctype == 'Opportunity':
            queue_identity(value.get('opportunity_from'),value.get('party_name'))
        else:
            queue_identity('Customer',value.get('customer'))
        queue_identity('Contact',value.get('contact_person'))


def capture_activity(doc, method=None):
    queue_identity('Lead',doc.get('lead') or doc.get('linked_lead'))
    queue_identity('Contact',doc.get('contact') or doc.get('linked_contact'))
    recipient = doc.get('marketing_campaign_recipient')
    if recipient and not doc.get('lead'):
        reference = frappe.db.get_value('Email Campaign',recipient,['email_campaign_for','recipient'],as_dict=True)
        if reference:
            queue_identity(reference.email_campaign_for,reference.recipient)
    visitor = doc.get('visitor_id')
    if visitor:
        for doctype in ('Lead','Contact','Customer'):
            meta = frappe.get_meta(doctype)
            if not meta.has_field('custom_website_tracking_visitor_id'):
                continue
            conditions = [['custom_website_tracking_visitor_id','=',visitor]]
            if meta.has_field('custom_website_tracking_visitor_ids'):
                conditions.append(['custom_website_tracking_visitor_ids','like','%'+frappe.as_json(visitor)+'%'])
            for name in frappe.get_all(doctype,or_filters=conditions,pluck='name',limit_page_length=0):
                queue_identity(doctype,name)
