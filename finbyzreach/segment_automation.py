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
    from finbyzreach.segment_history import record_event
    record_event(segment, record_name, 'Entered', occurrence)
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
        'audience_doctype': doctype, 'archived': 0}, pluck='name',order_by='name asc'):
        segment = frappe.get_doc('Reach Segment', segment_name)
        if segment.get('snapshot_pending_generation'):
            continue
        try:
            matches = bool(member_query(segment).select(table.name).where(table.name == name).limit(1).run())
        except (frappe.ValidationError, frappe.DoesNotExistError):
            # A removed custom field in one saved definition must not block all
            # pending CRM records. Explicit previews and mailings still fail.
            frappe.clear_last_message()
            frappe.logger('finbyzreach').warning('Invalid Reach Segment definition during change processing: %s', segment.name)
            continue
        previous = frappe.db.get_value(MEMBER, {'segment': segment.name, 'record_name': name}, ['name', 'source','is_current'], as_dict=True)
        if matches == bool(previous and previous.get('is_current', 1)):
            continue
        segment = frappe.get_doc('Reach Segment', segment_name, for_update=True)
        if segment.get('snapshot_pending_generation'):
            continue
        matches = bool(member_query(segment).select(table.name).where(table.name == name).limit(1).run())
        previous = frappe.db.get_value(MEMBER, {'segment': segment.name, 'record_name': name}, ['name', 'source', 'is_current'], as_dict=True, for_update=True)
        if matches and (not previous or not previous.get('is_current', 1)):
            affected.add(segment.name)
            if not previous:
                _insert_members(segment.name, [name])
            else:
                frappe.db.set_value(MEMBER, previous.name, 'is_current', 1, update_modified=False)
            emit_entry(segment, name, f'segment:{segment.name}:{name}:{frappe.generate_hash(length=16)}')
        elif not matches and previous and previous.get('is_current', 1):
            affected.add(segment.name)
            mark_left(segment, previous, name)

    return affected


def capture_change(doc, method=None, enqueue=True):
    from finbyzreach.segment_service import AUDIENCE_TYPES
    if doc.doctype not in (*AUDIENCE_TYPES, 'Email Subscription Preference') or not frappe.db.table_exists('Reach Segment Pending Record'):
        return
    if not frappe.db.exists('Reach Segment', {'archived': 0} if doc.doctype == 'Email Subscription Preference' else {'audience_doctype': doc.doctype, 'archived': 0}):
        return
    from uuid import uuid4
    from frappe.utils import now_datetime
    # Each committed change owns its row. A deterministic identity key races
    # with a drain deleting that key, and can abort the caller with MariaDB 1020.
    # Append in the caller's transaction, so rollback also removes the change.
    key = uuid4().hex
    now = now_datetime()
    user = frappe.session.user
    frappe.db.bulk_insert('Reach Segment Pending Record',
        ['name','creation','modified','owner','modified_by','record_doctype','record_name'],
        [(key,now,now,user,user,doc.doctype,doc.name)])
    if enqueue:
        enqueue_changes()


def capture_customer_change(doc, method=None):
    """Main-customer fields affect Contacts and the Customer's source Lead."""
    from finbyzreach.segment_service import AUDIENCE_TYPES
    if not frappe.db.table_exists('Reach Segment'):
        return
    for value in (doc, doc.get_doc_before_save()):
        if value:
            queue_identity('Lead',value.get('lead_name'))
    # Stream contacts; enqueue only a cursor job from the Customer save request.
    for doctype in ('Contact','Opportunity','Sales Order'):
        frappe.enqueue('finbyzreach.segment_automation.queue_customer_contacts',customer=doc.name,doctype=doctype,
                       queue='short',enqueue_after_commit=True)


def queue_customer_contacts(customer, after=None, doctype='Contact'):
    if doctype not in ('Contact','Opportunity','Sales Order'):
        frappe.throw('Unsupported customer dependency')
    filters = ({'custom_reach_main_customer':customer} if doctype == 'Contact' else
               {'party_name':customer,'opportunity_from':'Customer'} if doctype == 'Opportunity' else {'customer':customer})
    if after:
        filters['name'] = ['>',after]
    names = frappe.get_all(doctype,filters=filters,pluck='name',order_by='name asc',limit_page_length=200)
    for name in names:
        capture_change(frappe._dict(doctype=doctype,name=name),enqueue=False)
    enqueue_changes()
    if len(names) == 200:
        frappe.enqueue('finbyzreach.segment_automation.queue_customer_contacts',customer=customer,
                       after=names[-1],doctype=doctype,queue='short',enqueue_after_commit=True)


# One drain job at a time. A Redis owner key is held from the moment a drain job is queued
# until that job finds nothing left to do. A capture that commits while the key is held only
# sets the dirty bit, and the running drain loops again instead of a new job being queued.
# Frappe's own deduplicate=True cannot do this: it is checked when enqueue() is called, before
# the caller commits, and it blocks a follow-up while the current job is still STARTED.
DRAIN_OWNER_KEY = 'finbyzreach:segment-drain:owner'
DRAIN_DIRTY_KEY = 'finbyzreach:segment-drain:dirty'
DRAIN_KEY_TTL = 900  # seconds; frees the owner key if a worker dies mid-drain
DRAIN_BATCH_SIZE = 100
DRAIN_TIME_BUDGET = 120  # seconds per job; the short queue times jobs out at 300

_CLAIM = """
redis.call('set', KEYS[2], '1', 'EX', ARGV[2])
if redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then return 1 end
return 0
"""
# Release only when nothing was signalled since the dirty bit was last cleared.
_RELEASE = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then return 1 end
if redis.call('exists', KEYS[2]) == 1 then return 0 end
redis.call('del', KEYS[1])
return 1
"""
_TOUCH = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('expire', KEYS[1], ARGV[2])
if ARGV[3] == '1' then redis.call('del', KEYS[2]) end
return 1
"""
_DROP = """
if redis.call('get', KEYS[1]) == ARGV[1] then redis.call('del', KEYS[1]) end
return 1
"""


def _drain_script(script, token, *args):
    keys = (frappe.cache.make_key(DRAIN_OWNER_KEY), frappe.cache.make_key(DRAIN_DIRTY_KEY))
    return int(frappe.cache.eval(script, 2, *keys, token, *args) or 0)


def enqueue_changes():
    """Ask for a drain after the current transaction commits. Safe to call once per record."""
    if frappe.flags.in_reach_segment_drain or not frappe.db.table_exists('Reach Segment Pending Record'):
        return
    if signal_changes not in frappe.db.after_commit._functions:
        frappe.db.after_commit.add(signal_changes)


def signal_changes():
    """Runs after commit, so a drain that reads after this point sees the committed records."""
    try:
        if not pending_batch(limit=1):
            return
        token = frappe.generate_hash(length=16)
        if not _drain_script(_CLAIM, token, DRAIN_KEY_TTL):
            return  # a drain is queued or running; the dirty bit makes it look again
    except Exception:
        # The caller has already committed. The scheduler's enqueue_changes tick retries.
        frappe.log_error('Reach Segment drain could not be signalled')
        return
    _queue_drain(token)


def _queue_drain(token):
    try:
        frappe.enqueue('finbyzreach.segment_automation.drain_changes', queue='short', token=token,
                       job_id=f'reach-segment-changes:{token}:{frappe.generate_hash(length=6)}')
    except Exception:
        # QueueOverloaded or Redis trouble: free the owner key so the scheduler's next
        # enqueue_changes tick queues a drain. Pending records stay in the table.
        _drain_script(_DROP, token)
        frappe.log_error('Reach Segment drain could not be queued')


def drain_changes(token=None):
    """Drain pending records in committed batches until none are left or the time budget runs out.

    `token` is the owner key value from signal_changes. A call without it, such as a manual
    run from the console, drains too but never takes or releases the owner key.
    """
    from time import monotonic
    user = frappe.session.user
    deadline = monotonic() + DRAIN_TIME_BUDGET
    try:
        frappe.set_user('Administrator')
        frappe.flags.in_reach_segment_drain = True
        while True:
            if token:
                # Clear the dirty bit before the fresh read below; a capture that commits after
                # this sets it again, and _RELEASE then refuses to let go.
                _drain_script(_TOUCH, token, DRAIN_KEY_TTL, 1)
            frappe.db.commit()
            if not drain_batch():
                if not token or _drain_script(_RELEASE, token):
                    return
                continue
            frappe.db.commit()
            if monotonic() >= deadline:
                if token:
                    _queue_drain(token)  # keep the owner key; the next job continues
                return
    except Exception:
        if token:
            _drain_script(_DROP, token)
        raise
    finally:
        frappe.flags.in_reach_segment_drain = False
        frappe.set_user(user)


def pending_batch(limit=DRAIN_BATCH_SIZE):
    return frappe.get_all('Reach Segment Pending Record', fields=['name','record_doctype','record_name'],
                          order_by='creation asc, name asc', limit_page_length=limit)


def drain_batch():
    """Apply one batch of pending records. Returns how many rows the batch read."""
    rows = pending_batch()
    affected = set()
    processed = set()
    for row in rows:
        # Lock the pending key with one locking read. A plain exists() check reads this
        # transaction's snapshot, so it still sees a row a concurrent drain has already
        # taken and deleted; the locking read sees the latest committed state, waits for
        # that drain to commit and then returns None, so the record is skipped, not redone.
        if not frappe.db.get_value('Reach Segment Pending Record', row.name, 'name', for_update=True):
            continue
        identity = (row.record_doctype, row.record_name)
        if identity not in processed:
            if row.record_doctype == 'Email Subscription Preference':
                from finbyzreach.subscriber_segments import queue_subscription_records
                queue_subscription_records(row.record_name)
            else:
                affected.update(sync_record(row.record_doctype, row.record_name))
            processed.add(identity)
        frappe.db.delete('Reach Segment Pending Record', {'name':row.name})
    for name in affected:
        segment = frappe.get_doc('Reach Segment', name)
        update_counts(segment)
    schedule_dependents(affected)
    return len(rows)


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
    from finbyzreach.segment_service import member_names, member_query, MEMBER, _insert_members, report_invalid_definition
    segment = frappe.get_doc('Reach Segment', segment_name, for_update=True)
    if segment.get('archived') or segment.get('snapshot_pending_generation'):
        return
    try:
        names = member_names(segment, after=after, limit=200)
    except frappe.ValidationError as exc:
        return report_invalid_definition(segment, exc)
    previous = set(frappe.get_all(MEMBER, filters={'segment':segment.name,'is_current':1,'record_name':['in',names]}, pluck='record_name')) if names else set()
    _insert_members(segment.name, names)
    if names:
        table = frappe.qb.DocType(MEMBER)
        frappe.qb.update(table).set(table.is_current,1).where(table.segment == segment.name).where(table.record_name.isin(names)).run()
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
    if segment.get('archived') or segment.get('snapshot_pending_generation'):
        return
    filters = {'segment':segment.name}
    if after:
        filters['name'] = ['>',after]
    rows = frappe.get_all(MEMBER, filters=filters, fields=['name','record_name','source','is_current'], order_by='name asc', limit_page_length=200)
    if rows:
        table = frappe.qb.DocType(segment.audience_doctype)
        current = {row[0] for row in member_query(segment).select(table.name)
                   .where(table.name.isin([row.record_name for row in rows])).run()}
        for row in rows:
            if row.record_name not in current:
                mark_left(segment,row,row.record_name)
    if len(rows) == 200:
        frappe.enqueue('finbyzreach.segment_automation.clean_segment_members', segment_name=segment.name,
                       after=rows[-1].name, queue='long', enqueue_after_commit=True)
    else:
        update_counts(segment)
        from finbyzreach.segment_history import sample_size
        sample_size(segment)
        from finbyzreach.segment_snapshots import clean_old_rows
        clean_old_rows(segment.name)


def refresh_time_segments():
    for name in frappe.get_all('Reach Segment', filters={'segment_type':'Active','archived':0}, pluck='name'):
        frappe.enqueue('finbyzreach.segment_automation.reconcile_segment', segment_name=name,
                       queue='long', enqueue_after_commit=True, job_id=f'reach-reconcile:{name}', deduplicate=True)


def validate_main_customer(doc, method=None):
    customers = {row.link_name for row in doc.get('links') or [] if row.link_doctype == 'Customer' and row.link_name}
    if not doc.get('custom_reach_main_customer') and len(customers) == 1 and doc.meta.has_field('custom_reach_main_customer'):
        # SEG-14: a contact with exactly one Customer has an unambiguous main customer.
        doc.custom_reach_main_customer = next(iter(customers))
    main = doc.get('custom_reach_main_customer')
    if main and main not in customers:
        # Customer deletion unlinks Contacts through their normal validation hook.
        doc.custom_reach_main_customer = next(iter(customers)) if len(customers) == 1 else None


def queue_identity(doctype, name):
    from finbyzreach.segment_service import AUDIENCE_TYPES
    if doctype not in AUDIENCE_TYPES or not name:
        return
    capture_change(frappe._dict(doctype=doctype,name=name))


def capture_related_change(doc, method=None):
    """A related document can change membership without editing the CRM record."""
    for value in (doc, doc.get_doc_before_save()):
        if not value:
            continue
        if value.doctype == 'Opportunity':
            queue_identity(value.get('opportunity_from'),value.get('party_name'))
        elif value.doctype == 'Quotation':
            queue_identity(value.get('quotation_to'),value.get('party_name'))
        else:
            queue_identity('Customer',value.get('customer'))
        queue_identity('Contact',value.get('contact_person'))


def mark_left(segment, previous, record_name):
    from finbyzreach.segment_service import MEMBER
    if previous.get('is_current',1):
        from finbyzreach.segment_history import record_event
        record_event(segment,record_name,'Left',frappe.generate_hash(length=32))
    if previous.source == 'Filtered':
        frappe.db.delete(MEMBER,{'name':previous.name})
    else:
        frappe.db.set_value(MEMBER,previous.name,'is_current',0,update_modified=False)


def update_counts(segment):
    from finbyzreach.segment_service import member_query, count_members
    from frappe.query_builder.functions import Count
    table = frappe.qb.DocType(segment.audience_doctype)
    included = count_members(segment)
    candidates = member_query(segment,apply_exclusions=False).select(Count(table.name)).run()[0][0]
    segment.member_count = included
    segment.excluded_count = max(0,candidates-included)
    frappe.db.set_value('Reach Segment',segment.name,{'member_count':included,'excluded_count':segment.excluded_count},update_modified=False)


def segment_references(row):
    names = set(frappe.parse_json(row.get('exclude_segments_json') or '[]'))
    def visit(node):
        if isinstance(node, dict):
            if node.get('kind') == 'segment' and node.get('segment'):
                names.add(node['segment'])
            for child in node.get('conditions') or []:
                visit(child)
    visit(frappe.parse_json(row.get('filter_expression_json') or 'null'))
    return names


def schedule_reconciliation(segment_name):
    frappe.enqueue('finbyzreach.segment_automation.reconcile_segment',segment_name=segment_name,
                   queue='long',enqueue_after_commit=True)
    schedule_dependents({segment_name})


def schedule_dependents(changed):
    """Definitions form an acyclic graph; visit each dependent only once."""
    rows = frappe.get_all('Reach Segment',filters={'archived':0},
        fields=['name','exclude_segments_json','filter_expression_json'])
    seen = set(changed)
    frontier = set(changed)
    while frontier:
        next_frontier = {row.name for row in rows if row.name not in seen and segment_references(row) & frontier}
        for name in sorted(next_frontier):
            frappe.enqueue('finbyzreach.segment_automation.reconcile_segment',segment_name=name,
                           queue='long',enqueue_after_commit=True)
        seen.update(next_frontier)
        frontier = next_frontier


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
        from finbyzreach.segment_service import AUDIENCE_TYPES
        for doctype in AUDIENCE_TYPES:
            if frappe.get_meta(doctype).has_field('custom_website_tracking_visitor_id'):
                frappe.enqueue('finbyzreach.segment_automation.queue_visitor_records',
                    doctype=doctype,visitor=visitor,queue='short',enqueue_after_commit=True)


def queue_visitor_records(doctype, visitor, after=None):
    """Keep tracking inserts independent of the number of matching CRM records."""
    from finbyzreach.segment_service import AUDIENCE_TYPES
    if doctype not in AUDIENCE_TYPES:
        frappe.throw('Unsupported visitor audience')
    meta = frappe.get_meta(doctype)
    if not meta.has_field('custom_website_tracking_visitor_id'):
        return
    conditions = [['custom_website_tracking_visitor_id','=',visitor]]
    if meta.has_field('custom_website_tracking_visitor_ids'):
        conditions.append(['custom_website_tracking_visitor_ids','like','%'+frappe.as_json(visitor)+'%'])
    names = frappe.get_all(doctype,filters={'name':['>',after]} if after else {},
        or_filters=conditions,pluck='name',order_by='name asc',limit_page_length=200)
    for name in names:
        capture_change(frappe._dict(doctype=doctype,name=name),enqueue=False)
    enqueue_changes()
    if len(names) == 200:
        frappe.enqueue('finbyzreach.segment_automation.queue_visitor_records',
            doctype=doctype,visitor=visitor,after=names[-1],queue='short',enqueue_after_commit=True)
