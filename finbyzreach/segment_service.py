"""Permission-aware segment queries; Active membership always uses saved criteria.

Materialized members support static snapshots and change notifications. They are
never the authority for an Active preview or mailing: current criteria are.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Count
from frappe.utils import cint, now_datetime

AUDIENCE_TYPES = ('Lead', 'Contact', 'Customer', 'Opportunity', 'Sales Order')
MEMBER = 'Reach Segment Member'
EXCLUSION = 'Reach Segment Exclusion'
CHUNK_SIZE = 500
LIVE_WORKFLOW_STATUSES = ('ACTIVE', 'PAUSED')
LIVE_CAMPAIGN_STATUSES = ('Preparing Audience', 'Scheduled', 'Sending', 'Paused')
SEGMENT_MARKERS = ('#REACH_SEGMENT#', '#STATIC_SEGMENT#')


def parsed_list(value):
    result = frappe.parse_json(value or '[]')
    if not isinstance(result, list):
        frappe.throw(_('Expected a JSON list'))
    return result


def _empty(table):
    return table.name.isnull()


def _group_condition(doctype, value):
    from finbyzreach.email_marketing import validate_lead_filter_groups
    if doctype in AUDIENCE_TYPES:
        groups = frappe.parse_json(validate_lead_filter_groups(value, audience_doctype=doctype))
    else:
        from finbyzreach.email_marketing import FILTER_OPERATORS
        groups = parsed_list(value)
        if groups and isinstance(groups[0][0], str):
            groups = [groups]
        if len(groups) > 25 or sum(len(group) for group in groups) > 50:
            frappe.throw(_('Too many related-object filters'))
        allowed = {'name','creation','modified','owner','modified_by'} | {df.fieldname for df in frappe.get_meta(doctype).fields}
        for group in groups:
            for condition in group:
                if (not isinstance(condition, list) or len(condition) != 4 or condition[0] != doctype
                    or condition[1] not in allowed or condition[2] not in FILTER_OPERATORS):
                    frappe.throw(_('Invalid related-object filter'))
    table = frappe.qb.DocType(doctype)
    conditions = []
    for group in groups:
        # Keep Frappe's own field, date, child-table and permission semantics.
        subquery = frappe.qb.get_query(doctype, fields=['name'], filters=group,
                                      ignore_permissions=False, distinct=True)
        conditions.append(table.name.isin(subquery))
    return Criterion.any(conditions) if conditions else _empty(table)


def expression_condition(doctype, expression, seen=()):
    """Bounded AND/OR tree. Legacy arrays keep AND-within / OR-between."""
    table = frappe.qb.DocType(doctype)
    if not expression:
        return _empty(table)
    count = [0]
    def visit(node, depth=0):
        count[0] += 1
        if depth > 8 or count[0] > 100:
            frappe.throw(_('Use at most 100 conditions and 8 levels'))
        if isinstance(node, list):
            return _group_condition(doctype, [node])
        if not isinstance(node, dict):
            frappe.throw(_('Invalid segment condition'))
        if node.get('kind') == 'subscription':
            from finbyzreach.subscriber_segments import subscription_condition
            return subscription_condition(doctype, node)
        if node.get('kind') == 'related':
            return related_condition(doctype, node)
        if node.get('kind') == 'activity':
            return activity_condition(doctype, node)
        if node.get('kind') == 'relative_date':
            return relative_date_condition(doctype, node)
        if node.get('kind') == 'multiselect':
            return multiselect_condition(doctype, node)
        if node.get('kind') == 'segment':
            other = frappe.get_doc('Reach Segment', node.get('segment'))
            other.check_permission('read')
            if other.audience_doctype != doctype:
                frappe.throw(_('Segment conditions must use the same audience type'))
            criterion = table.name.isin(member_query(other, seen=seen).select(table.name))
            return ~criterion if node.get('operator') == 'not in' else criterion
        operator = node.get('operator')
        children = node.get('conditions')
        if operator not in ('AND', 'OR') or not isinstance(children, list) or not children:
            frappe.throw(_('A filter group needs AND or OR and at least one condition'))
        items = [visit(child, depth+1) for child in children]
        return Criterion.all(items) if operator == 'AND' else Criterion.any(items)
    return visit(expression)


def related_condition(doctype, node):
    target = node.get('doctype')
    if target not in ('Customer', 'Opportunity', 'Sales Order', 'Quotation'):
        frappe.throw(_('Unsupported connected object'))
    frappe.has_permission(target, 'read', throw=True)
    table = frappe.qb.DocType(doctype)
    related = frappe.qb.DocType(target)
    match = _group_condition(target, node.get('filters'))
    permitted = frappe.qb.get_query(target, fields=['name'], ignore_permissions=False)
    base = frappe.qb.from_(related).where(related.name.isin(permitted))
    if doctype == 'Contact' and target == 'Customer':
        # Explicitly selected main customer; never choose an arbitrary link.
        return table.custom_reach_main_customer.isin(base.where(match).select(related.name))
    if doctype == 'Opportunity' and target == 'Customer':
        return (table.opportunity_from == 'Customer') & table.party_name.isin(base.where(match).select(related.name))
    if doctype == 'Sales Order' and target == 'Customer':
        return table.customer.isin(base.where(match).select(related.name))
    if doctype == 'Lead' and target == 'Customer':
        key = related.lead_name
    elif target == 'Opportunity' and doctype in ('Lead', 'Customer'):
        key = related.party_name
        base = base.where(related.opportunity_from == doctype)
    elif target in ('Opportunity', 'Sales Order') and doctype == 'Contact':
        key = related.contact_person
    elif target == 'Sales Order' and doctype == 'Customer':
        key = related.customer
    elif target == 'Quotation' and doctype in ('Lead', 'Customer'):
        key = related.party_name
        base = base.where(related.quotation_to == doctype)
    elif target == 'Quotation' and doctype == 'Contact':
        key = related.contact_person
    else:
        frappe.throw(_('This object relationship is not supported'))
    base = base.where(key.isnotnull())
    exists = table.name.isin(base.select(key))
    if node.get('quantifier', 'any') == 'all':
        return exists & table.name.notin(base.where(~match).select(key))
    return table.name.isin(base.where(match).select(key))


RELATIVE_COMPARISONS = ('within_last', 'older_than', 'within_next')
RELATIVE_UNITS = ('days', 'weeks', 'months', 'years')
RELATIVE_LIMITS = {'days': 36500, 'weeks': 5200, 'months': 1200, 'years': 100}
LAST_ACTIVITY = '__last_activity'


def relative_date_condition(doctype, node):
    """A date field relative to today: in the last N days, more than N months ago, or in the next N weeks.

    ``__last_activity`` is the most recent Communication (e-mail or call note) on the record;
    "more than N ago" then also matches records that never had any activity.
    """
    from frappe.utils import add_to_date, getdate
    from pypika.terms import ExistsCriterion
    comparison = node.get('comparison')
    unit = node.get('unit') or 'days'
    amount = cint(node.get('amount'))
    if comparison not in RELATIVE_COMPARISONS or unit not in RELATIVE_UNITS:
        frappe.throw(_('Choose a valid relative date rule'))
    if not 1 <= amount <= RELATIVE_LIMITS[unit]:
        frappe.throw(_('Enter a number between 1 and {0} {1}').format(RELATIVE_LIMITS[unit], _(unit)))
    now = now_datetime()
    table = frappe.qb.DocType(doctype)
    field = node.get('field')
    if field == LAST_ACTIVITY:
        if comparison == 'within_next':
            frappe.throw(_('Last activity can only look back in time'))
        frappe.has_permission('Communication', 'read', throw=True)
        communication = frappe.qb.DocType('Communication')
        cutoff = add_to_date(now, **{unit: -amount})
        newer = (frappe.qb.from_(communication).select(communication.name)
                 .where(communication.reference_doctype == doctype)
                 .where(communication.reference_name == table.name)
                 .where(communication.communication_date >= cutoff))
        return ~ExistsCriterion(newer) if comparison == 'older_than' else ExistsCriterion(newer)
    df = frappe.get_meta(doctype).get_field(field) if field not in ('creation', 'modified') else None
    if field not in ('creation', 'modified') and not (df and df.fieldtype in ('Date', 'Datetime')):
        frappe.throw(_('{0} is not a date field').format(field))
    column = table[field]
    is_date = bool(df and df.fieldtype == 'Date')
    shift = lambda value: getdate(value) if is_date else value
    if comparison == 'older_than':
        return column < shift(add_to_date(now, **{unit: -amount}))
    if comparison == 'within_last':
        return (column >= shift(add_to_date(now, **{unit: -amount}))) & (column <= shift(now))
    return (column >= shift(now)) & (column <= shift(add_to_date(now, **{unit: amount})))


def multiselect_condition(doctype, node):
    """Several values stored in a Table MultiSelect field (interests, topics): any, all or none of them."""
    field = node.get('field')
    mode = node.get('mode') or 'any'
    values = [str(v) for v in (node.get('values') or []) if str(v or '').strip()]
    meta = frappe.get_meta(doctype)
    df = meta.get_field(field)
    if mode not in ('any', 'all', 'none') or not values or len(values) > 50:
        frappe.throw(_('Choose any, all or none and between 1 and 50 values'))
    if not df or df.fieldtype != 'Table MultiSelect':
        frappe.throw(_('{0} is not a multi-value field').format(field))
    link = next((f for f in frappe.get_meta(df.options).fields if f.fieldtype == 'Link'), None)
    if not link:
        frappe.throw(_('{0} has no value column').format(field))
    table = frappe.qb.DocType(doctype)
    child = frappe.qb.DocType(df.options)
    base = (frappe.qb.from_(child).where(child.parenttype == doctype).where(child.parentfield == field))
    value = child[link.fieldname]
    any_of = table.name.isin(base.where(value.isin(values)).select(child.parent))
    if mode == 'any':
        return any_of
    if mode == 'none':
        return ~any_of
    return Criterion.all([table.name.isin(base.where(value == item).select(child.parent)) for item in values])


def activity_condition(doctype, node):
    from frappe.utils import add_days, now_datetime
    event = str(node.get('event') or '')
    if event in ('Website visit', 'Store purchase'):
        return visitor_activity_condition(doctype, node)
    if event == 'Webinar attended':
        return webinar_activity_condition(doctype, node)
    if event not in ('Opened', 'Clicked', 'Replied', 'Sent', 'Unsubscribed'):
        frappe.throw(_('Unsupported email activity'))
    if not frappe.db.table_exists('Email Tracking Event'):
        frappe.throw(_('Email tracking is not installed on this site'))
    frappe.has_permission('Email Tracking Event', 'read', throw=True)
    table = frappe.qb.DocType(doctype)
    tracking = frappe.qb.DocType('Email Tracking Event')
    days = max(1, min(cint(node.get('days')) or 30, 3650))
    permitted = frappe.qb.get_query('Email Tracking Event', fields=['name'], ignore_permissions=False)
    query = (frappe.qb.from_(tracking).where(tracking.name.isin(permitted)).where(tracking.event_type == event)
             .where(tracking.event_time >= add_days(now_datetime(), -days)))
    if node.get('campaign'):
        query = query.where(tracking.marketing_email_campaign == node['campaign'])
    if doctype in ('Lead','Contact'):
        return table.name.isin(query.select(tracking.lead if doctype == 'Lead' else tracking.contact))
    if doctype in ('Opportunity','Sales Order'):
        return table.contact_person.isin(query.select(tracking.contact))
    recipient = frappe.qb.DocType('Email Campaign')
    return table.name.isin(query.join(recipient).on(recipient.name == tracking.marketing_campaign_recipient)
                          .where(recipient.email_campaign_for == 'Customer').select(recipient.recipient))


def visitor_activity_condition(doctype, node):
    from pypika.terms import ExistsCriterion
    from frappe.query_builder import CustomFunction, Case
    from frappe.query_builder.functions import Coalesce
    from frappe.utils import add_days
    source = 'Tracker Pageview' if node['event'] == 'Website visit' else 'Tracker Conversion'
    if not frappe.db.table_exists(source):
        frappe.throw(_('{0} is not installed').format(source))
    frappe.has_permission(source, 'read', throw=True)
    meta = frappe.get_meta(doctype)
    if not meta.has_field('custom_website_tracking_visitor_id'):
        frappe.throw(_('Visitor identity tracking is not configured for this object'))
    table = frappe.qb.DocType(doctype)
    activity = frappe.qb.DocType(source)
    identity = activity.visitor_id == table.custom_website_tracking_visitor_id
    if meta.has_field('custom_website_tracking_visitor_ids'):
        valid = CustomFunction('JSON_VALID', ['value'])
        contains = CustomFunction('JSON_CONTAINS', ['document','value'])
        quote = CustomFunction('JSON_QUOTE', ['value'])
        ids = Case().when(valid(table.custom_website_tracking_visitor_ids), table.custom_website_tracking_visitor_ids).else_('[]')
        identity |= contains(ids, quote(activity.visitor_id)) == 1
    days = max(1,min(cint(node.get('days')) or 30,3650))
    permitted = frappe.qb.get_query(source, fields=['name'], ignore_permissions=False)
    query = (frappe.qb.from_(activity).select(activity.name).where(activity.name.isin(permitted))
             .where(identity).where(activity.received_at >= add_days(now_datetime(),-days)))
    if source == 'Tracker Pageview':
        query = query.where(activity.action_type == 'pageview')
    else:
        # Tracker Conversion also contains ordinary goals. Only an ecommerce
        # order with an order identity represents a completed store purchase.
        query = query.where(activity.goal_id == 0).where(activity.order_id.isnotnull()).where(activity.order_id != '')
    if node.get('site'):
        query = query.where(activity.site_id == node['site'])
    return ExistsCriterion(query)


def webinar_activity_condition(doctype, node):
    from frappe.utils import add_days
    source = 'Contrast Engagement Event'
    if not frappe.db.table_exists(source):
        frappe.throw(_('Webinar tracking is not installed'))
    frappe.has_permission(source, 'read', throw=True)
    table = frappe.qb.DocType(doctype)
    event = frappe.qb.DocType(source)
    days = max(1,min(cint(node.get('days')) or 30,3650))
    permitted = frappe.qb.get_query(source, fields=['name'], ignore_permissions=False)
    query = (frappe.qb.from_(event).where(event.name.isin(permitted))
             .where(event.engagement_type.isin(['Live Attendance','Replay View']))
             .where(event.activity_datetime >= add_days(now_datetime(),-days)))
    if doctype in ('Lead','Contact'):
        return table.name.isin(query.select(event.linked_lead if doctype == 'Lead' else event.linked_contact))
    if doctype in ('Opportunity','Sales Order'):
        return table.contact_person.isin(query.select(event.linked_contact))
    link = frappe.qb.DocType('Dynamic Link')
    contacts = query.select(event.linked_contact)
    linked_customers = (frappe.qb.from_(link).select(link.link_name)
                        .where((link.parenttype == 'Contact') & (link.link_doctype == 'Customer'))
                        .where(link.parent.isin(contacts)))
    return table.name.isin(linked_customers) | table.lead_name.isin(query.select(event.linked_lead))


def member_query(segment, *, seen=(), apply_exclusions=True):
    if segment.name in seen:
        frappe.throw(_('Circular segment dependency: {0}').format(segment.name))
    seen = (*seen, segment.name)
    doctype = segment.get('audience_doctype') or 'Lead'
    if doctype not in AUDIENCE_TYPES:
        frappe.throw(_('Unsupported segment audience'))
    table = frappe.qb.DocType(doctype)
    member = frappe.qb.DocType(MEMBER)
    stored = frappe.qb.from_(member).select(member.record_name).where(member.segment == segment.name)
    if segment.get('archived'):
        included = table.name.isin(stored.where(member.is_current == 1))
    elif segment.segment_type == 'Static':
        if segment.get('snapshot_generation'):
            snapshot = frappe.qb.DocType('Reach Segment Snapshot Row')
            snapshot_names = (frappe.qb.from_(snapshot).select(snapshot.record_name)
                              .where(snapshot.segment == segment.name)
                              .where(snapshot.generation == segment.snapshot_generation))
            included = table.name.isin(snapshot_names) | table.name.isin(stored.where(member.source == 'Manual'))
        elif segment.get('members_initialized'):
            included = table.name.isin(stored)
        else:
            names = parsed_list(segment.get('static_leads_json'))
            included = table.name.isin(names) if names else _empty(table)
    else:
        expression = frappe.parse_json(segment.get('filter_expression_json') or 'null')
        included = (expression_condition(doctype, expression, seen) if expression else
                    _group_condition(doctype, segment.get('filter_groups_json')))
        manual = stored.where(member.source == 'Manual')
        included |= table.name.isin(manual)
    visible = frappe.qb.get_query(doctype, fields=['name'], ignore_permissions=False)
    query = frappe.qb.from_(table).where(included).where(table.name.isin(visible))
    if not apply_exclusions or segment.get('archived'):
        return query
    if parsed_list(segment.get('exclude_filters_json')):
        query = query.where(~_group_condition(doctype, segment.exclude_filters_json))
    exclusion = frappe.qb.DocType(EXCLUSION)
    query = query.where(table.name.notin(frappe.qb.from_(exclusion).select(exclusion.record_name)
                                        .where(exclusion.segment == segment.name)))
    for name in parsed_list(segment.get('exclude_segments_json')):
        other = frappe.get_doc('Reach Segment', name)
        other.check_permission('read')
        if other.audience_doctype != doctype:
            frappe.throw(_('Excluded segments must use the same audience type'))
        query = query.where(table.name.notin(member_query(other, seen=seen).select(table.name)))
    # Email groups remain an additional suppression source for existing segments.
    groups = parsed_list(segment.get('exclude_email_groups_json'))
    if groups:
        email_member = frappe.qb.DocType('Email Group Member')
        blocked_emails = frappe.qb.from_(email_member).select(email_member.email).where(email_member.email_group.isin(groups))
        if doctype != 'Customer':
            email = table.email_id if doctype in ('Lead','Contact') else table.contact_email
            query = query.where(email.isnull() | email.notin(blocked_emails))
        else:
            # Match existing Customer semantics: exclude only when every linked
            # contact is blocked. Evaluate relationally without fetching all IDs.
            link = frappe.qb.DocType('Dynamic Link')
            contact = frappe.qb.DocType('Contact')
            links = (frappe.qb.from_(link).select(link.link_name)
                     .where((link.parenttype == 'Contact') & (link.link_doctype == 'Customer')))
            allowed = (frappe.qb.from_(link).join(contact).on(contact.name == link.parent)
                       .select(link.link_name).where((link.parenttype == 'Contact') & (link.link_doctype == 'Customer'))
                       .where(contact.email_id.isnull() | contact.email_id.notin(blocked_emails)))
            query = query.where(table.name.notin(links) | table.name.isin(allowed))
    return query


def member_names(segment, *, after=None, limit=None, apply_exclusions=True):
    table = frappe.qb.DocType(segment.get('audience_doctype') or 'Lead')
    query = member_query(segment,apply_exclusions=apply_exclusions).select(table.name).orderby(table.name)
    if after:
        query = query.where(table.name > after)
    if limit:
        query = query.limit(limit)
    return [row[0] for row in query.run()]


def count_members(segment):
    table = frappe.qb.DocType(segment.get('audience_doctype') or 'Lead')
    return cint(member_query(segment).select(Count(table.name)).run()[0][0])


def _insert_members(segment, names, source='Filtered', is_current=1):
    """Deterministic keys make retrying a chunk idempotent."""
    from hashlib import sha256
    now = now_datetime()
    user = frappe.session.user
    for start in range(0, len(names), CHUNK_SIZE):
        values = [(sha256(f'{segment}\0{name}'.encode()).hexdigest(), now, now, user, user, segment, name, source, is_current)
                  for name in names[start:start+CHUNK_SIZE]]
        frappe.db.bulk_insert(MEMBER, ['name', 'creation', 'modified', 'owner', 'modified_by',
                                     'segment', 'record_name', 'source','is_current'], values, ignore_duplicates=True)


def initialize_static(segment):
    if segment.segment_type == 'Static' and not segment.get('members_initialized'):
        _insert_members(segment.name, parsed_list(segment.get('static_leads_json')))
        segment.members_initialized = 1


def refresh_static(segment):
    initialize_static(segment)
    from finbyzreach.segment_snapshots import prepare
    prepare(segment)
    segment.member_count = count_members(segment)


def validate_segment(segment):
    from finbyzreach.email_marketing import validate_lead_filter_groups, validate_excluded_email_groups
    doctype = segment.get('audience_doctype') or 'Lead'
    if doctype not in AUDIENCE_TYPES:
        frappe.throw(_('Unsupported segment audience type'))
    if segment.segment_type not in ('Active', 'Static'):
        frappe.throw(_('Segment type must be Active or Static'))
    before = segment.get_doc_before_save()
    # Snapshot pointers are server-owned, including for RPC document saves.
    for key in ('snapshot_generation','snapshot_pending_generation','snapshot_definition','snapshot_status','snapshot_error'):
        segment.set(key, before.get(key) if before else None)
    if before and before.audience_doctype != doctype:
        frappe.throw(_('Audience type cannot change after creation'))
    segment.filter_groups_json = validate_lead_filter_groups(segment.get('filter_groups_json'),
        require_filters=segment.segment_type == 'Active' and not segment.get('filter_expression_json'), audience_doctype=doctype)
    segment.exclude_filters_json = validate_lead_filter_groups(segment.get('exclude_filters_json'), audience_doctype=doctype)
    segment.exclude_email_groups_json = json.dumps(validate_excluded_email_groups(segment.get('exclude_email_groups_json')))
    parsed_list(segment.get('columns_json'))
    # Compile without executing; this validates nested criteria and cycles.
    member_query(segment)
    changed = not before or any(before.get(key) != segment.get(key) for key in (
        'filter_groups_json', 'filter_expression_json', 'exclude_filters_json',
        'exclude_email_groups_json', 'exclude_segments_json', 'segment_type'))
    if before and before.get('snapshot_pending_generation') and changed:
        frappe.throw(_('Wait for membership preparation before changing the segment definition'))
    if before and before.get('archived') and segment.get('archived') and changed:
        frappe.throw(_('Restore the segment before changing its definition'))
    if changed:
        segment.last_definition_change = now_datetime()
        segment.last_definition_changed_by = frappe.session.user
    if before and before.segment_type == 'Active' and segment.segment_type == 'Static':
        from finbyzreach.segment_snapshots import prepare
        prepare(segment, source=before)
    elif segment.segment_type == 'Static':
        initialize_static(segment)
        filters_changed = not before or any(before.get(key) != segment.get(key) for key in ('filter_groups_json', 'filter_expression_json'))
        if (filters_changed or segment.flags.get('reach_force_refresh')) and not segment.get('archived'):
            refresh_static(segment)
    else:
        segment.snapshot_pending_generation = None
        segment.snapshot_status = 'Ready'
    if segment.get('archived'):
        if before and not before.get('archived'):
            assert_unused(segment, blocking=True)
        segment.member_count = before.member_count if before else 0
        segment.excluded_count = before.get('excluded_count') if before else 0
        return
    segment.member_count = count_members(segment)
    table = frappe.qb.DocType(doctype)
    candidates = member_query(segment, apply_exclusions=False).select(Count(table.name)).run()[0][0]
    segment.excluded_count = max(0, cint(candidates) - segment.member_count)
    if before and (changed or any(before.get(key) != segment.get(key) for key in (
        'segment_name', 'description', 'folder', 'columns_json'))):
        assert_unused(segment, blocking=False)


def workflow_usage(segment):
    if not frappe.db.table_exists('Automation Workflow Draft'):
        return []
    # Definition references, not a LIKE match (names can contain punctuation).
    from finbyzreach.segment_automation import referenced_segments
    result = []
    for workflow in frappe.get_all('Automation Workflow', fields=['name', 'title', 'status', 'active_version']):
        if workflow.active_version:
            graph = frappe.db.get_value('Automation Workflow Version', workflow.active_version, 'graph_json')
            if segment.name in referenced_segments(graph) or '*' in referenced_segments(graph):
                # A paused workflow keeps enrolled records that resume later.
                result.append(dict(name=workflow.name, title=workflow.title, status=workflow.status,
                                   live=workflow.status in LIVE_WORKFLOW_STATUSES))
        if not any(row['name'] == workflow.name for row in result):
            graph = frappe.db.get_value('Automation Workflow Draft', {'workflow': workflow.name}, 'graph_json')
            if segment.name in referenced_segments(graph) or '*' in referenced_segments(graph):
                result.append(dict(name=workflow.name, title=workflow.title, status=workflow.status, live=False))
    return result


def segment_refs_in_filters(value):
    """Segment names referenced by a stored Campaign filter JSON."""
    found = set()
    def visit(node):
        if isinstance(node, list):
            if len(node) == 2 and node[0] in SEGMENT_MARKERS and isinstance(node[1], str):
                found.add(node[1])
                return
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            for child in node.values():
                visit(child)
    try:
        visit(frappe.parse_json(value or '[]'))
    except Exception:
        pass
    return found


def campaign_usage(segment):
    """Email campaigns whose saved audience or exclusions reference this segment."""
    if not frappe.db.has_column('Campaign', 'custom_lead_filters_json'):
        return []
    fields = ['name', 'campaign_name', 'custom_lead_filters_json', 'custom_exclude_filters_json']
    has_status = frappe.db.has_column('Campaign', 'custom_broadcast_status')
    if has_status:
        fields.append('custom_broadcast_status')
    rows = frappe.get_all('Campaign', or_filters=[['custom_lead_filters_json', 'like', '%SEGMENT#%'],
                                                  ['custom_exclude_filters_json', 'like', '%SEGMENT#%']],
                          fields=fields, limit_page_length=0)
    result = []
    for row in rows:
        include = segment.name in segment_refs_in_filters(row.custom_lead_filters_json)
        exclude = segment.name in segment_refs_in_filters(row.custom_exclude_filters_json)
        if not (include or exclude):
            continue
        status = (row.get('custom_broadcast_status') if has_status else None) or 'Draft'
        result.append(dict(name=row.name, title=row.campaign_name or row.name, status=status,
                           role='exclude' if exclude and not include else 'include',
                           # Resume and scheduling re-resolve the audience from the segment.
                           live=status in LIVE_CAMPAIGN_STATUSES))
    return result


def assert_unused(segment, blocking):
    usage = workflow_usage(segment)
    campaigns = [row for row in campaign_usage(segment) if row['live'] or row['status'] == 'Draft']
    live = [row['title'] for row in usage if row['live']]
    live_campaigns = [row['title'] for row in campaigns if row['live']]
    if blocking and (live or live_campaigns):
        parts = []
        if live:
            parts.append(_('live automations: {0}').format(', '.join(live)))
        if live_campaigns:
            parts.append(_('scheduled or sending emails: {0}').format(', '.join(live_campaigns)))
        frappe.throw(_('Segment is used by {0}').format('; '.join(parts)))
    if usage:
        frappe.msgprint(_('Segment is used by automations: {0}').format(', '.join(row['title'] for row in usage)), indicator='orange')
    if campaigns:
        frappe.msgprint(_('Segment is used by emails: {0}').format(', '.join(row['title'] for row in campaigns)), indicator='orange')
