from __future__ import annotations

import json

import frappe
from frappe import _

from finbyzreach import email_marketing


def _filters_for_segment(segment):
	if segment.segment_type == "Static":
		return []
	return frappe.parse_json(segment.filter_groups_json or "[]")

def _calculate_static_leads(filter_groups_json, exclude_filters_json, exclude_email_groups_json, audience_doctype="Lead"):
	include_leads = set(email_marketing._lead_names_from_filter_groups(filter_groups_json, audience_doctype=audience_doctype))
	exclude_leads = set()
	if exclude_filters_json and exclude_filters_json != "[]":
		exclude_leads.update(email_marketing._lead_names_from_filter_groups(exclude_filters_json, audience_doctype=audience_doctype))
	if exclude_email_groups_json and exclude_email_groups_json != "[]":
		exclude_emails = set()
		for group_name in email_marketing.validate_excluded_email_groups(exclude_email_groups_json):
			exclude_emails.update(email_marketing._email_group_addresses(group_name))
		if exclude_emails and audience_doctype in ("Lead", "Contact"):
			excluded_by_email = frappe.get_all(
				audience_doctype,
				filters={"email_id": ("in", list(exclude_emails))},
				pluck="name",
				limit_page_length=0
			)
			exclude_leads.update(excluded_by_email)
		elif exclude_emails and audience_doctype == "Customer" and include_leads:
			links = []
			for names in email_marketing._chunks(include_leads):
				links.extend(frappe.get_all("Dynamic Link", filters={
					"parenttype": "Contact", "link_doctype": "Customer", "link_name": ["in", names],
				}, fields=["parent", "link_name"], limit_page_length=0))
			contact_names = {row.parent for row in links}
			blocked_contacts = set()
			for names in email_marketing._chunks(contact_names):
				blocked_contacts.update(frappe.get_list("Contact", filters={
					"name": ["in", names], "email_id": ["in", list(exclude_emails)],
				}, pluck="name", limit_page_length=0))
			linked = {}
			for row in links:
				linked.setdefault(row.link_name, set()).add(row.parent)
			exclude_leads.update(name for name, contacts in linked.items()
				if contacts and contacts <= blocked_contacts)
	return sorted(list(include_leads - exclude_leads))

@frappe.whitelist(methods=["POST"])
def create_segment(segment_name, segment_type, filter_groups, exclude_filters="[]", exclude_email_groups="[]", audience_doctype="Lead"):
	frappe.has_permission("Reach Segment", "create", throw=True)
	segment_name = str(segment_name or "").strip()[:140]
	if not segment_name:
		frappe.throw(_("Segment name is required"))
	if segment_type not in ("Active", "Static"):
		frappe.throw(_("Segment type must be Active or Static"))
	from finbyzreach.segment_service import AUDIENCE_TYPES
	if audience_doctype not in AUDIENCE_TYPES:
		frappe.throw(_("Unsupported segment audience type"))
	if frappe.db.exists("Reach Segment", segment_name):
		frappe.throw(_("A segment named {0} already exists").format(frappe.bold(segment_name)))

	filter_groups_json = email_marketing.validate_lead_filter_groups(
		filter_groups, require_filters=segment_type == "Active", audience_doctype=audience_doctype
	)
	
	exclude_filters_json = exclude_filters
	exclude_email_groups_json = exclude_email_groups
	
	# The controller initializes static membership through the shared query service.
	doc = frappe.get_doc(
		{
			"doctype": "Reach Segment",
			"segment_name": segment_name,
			"segment_type": segment_type,
			"audience_doctype": audience_doctype,
			"filter_groups_json": filter_groups_json,
			"exclude_filters_json": exclude_filters_json,
			"exclude_email_groups_json": exclude_email_groups_json,
			"static_leads_json": "[]",
			"member_count": 0,
		}
	).insert()
	return {"name": doc.name, "segment_type": doc.segment_type, "member_count": doc.member_count}


@frappe.whitelist(methods=["GET"])
def get_segment_filters(segment_name):
	segment = frappe.get_doc("Reach Segment", segment_name)
	segment.check_permission("read")
	filters = _filters_for_segment(segment)
	exclude_filters = []
	if segment.segment_type != "Static":
		exclude_filters = frappe.parse_json(segment.exclude_filters_json or "[]")
	return {
		"name": segment.name,
		"segment_type": segment.segment_type,
		"audience_doctype": segment.get("audience_doctype") or "Lead",
		"filters": filters,
		"exclude_filters": exclude_filters,
		"exclude_email_groups": frappe.parse_json(segment.exclude_email_groups_json or "[]"),
		"member_count": segment.member_count,
	}

@frappe.whitelist(methods=["POST"])
def update_segment(segment_name, filter_groups, exclude_filters="[]", exclude_email_groups="[]"):
	frappe.has_permission("Reach Segment", "write", throw=True)
	doc = frappe.get_doc("Reach Segment", segment_name)
	doc.check_permission("write")
	filter_groups_json = email_marketing.validate_lead_filter_groups(
		filter_groups, require_filters=doc.segment_type == "Active", audience_doctype=doc.get("audience_doctype") or "Lead"
	)

	doc.filter_groups_json = filter_groups_json
	doc.exclude_filters_json = exclude_filters
	doc.exclude_email_groups_json = exclude_email_groups
	doc.save()

	return {"name": doc.name}

@frappe.whitelist(methods=["POST"])
def refresh_static_segment_leads(segment_name):
	frappe.has_permission("Reach Segment", "write", throw=True)
	doc = frappe.get_doc("Reach Segment", segment_name)
	doc.check_permission("write")
	
	if doc.segment_type != "Static":
		frappe.throw(_("Only Static segments can have their members refreshed from filters."))
		
	from finbyzreach.segment_service import refresh_static
	require_ready(doc)
	if doc.archived:
		frappe.throw(_("Restore the segment before refreshing its members"))
	doc.flags.reach_force_refresh = True
	doc.save()

	return {"name": doc.name, "member_count": doc.member_count}

@frappe.whitelist(methods=["GET"])
def preview_segment_audience(segment_name, limit=None):
	frappe.has_permission("Reach Segment", "read", throw=True)
	doc = frappe.get_doc("Reach Segment", segment_name)
	doc.check_permission("read")
	from finbyzreach.segment_service import member_names
	from frappe.utils import cint
	return member_names(doc, limit=max(1, min(cint(limit) or 200, 1000)))


def _segment(name, permission='read', lock=False):
    doc = frappe.get_doc('Reach Segment', name, for_update=lock)
    doc.check_permission(permission)
    frappe.has_permission(doc.audience_doctype or 'Lead', 'read', throw=True)
    return doc


def effective_columns(doc, selected=None):
    """One permission-aware selection for preview and exported files."""
    from frappe.model import get_permitted_fields
    from finbyzreach.segment_service import parsed_list
    doctype = doc.audience_doctype
    label = {'Lead':'lead_name', 'Contact':'full_name', 'Customer':'customer_name',
             'Opportunity':'title', 'Sales Order':'customer_name'}[doctype]
    email = 'contact_email' if doctype in ('Opportunity','Sales Order') else 'email_id'
    columns = parsed_list(selected if selected is not None else doc.get('columns_json')) or ['name', label, email]
    allowed = set(get_permitted_fields(doctype)) | {'name'}
    if selected is not None and any(not isinstance(field, str) or field not in allowed for field in columns):
        frappe.throw(_('One or more export columns are not permitted'))
    result = list(dict.fromkeys(field for field in columns if isinstance(field, str) and field in allowed))[:20]
    if selected is None and 'name' not in result:
        result.insert(0, 'name')
    return result


def require_ready(doc):
    if doc.get('snapshot_pending_generation') or doc.get('snapshot_status') == 'Failed':
        frappe.throw(_('Segment membership is still being prepared. Wait for it to finish or retry preparation.'))


@frappe.whitelist(methods=['GET'])
def segment_columns(segment_name):
    from frappe.model import get_permitted_fields
    doc = _segment(segment_name)
    meta = frappe.get_meta(doc.audience_doctype)
    allowed = get_permitted_fields(doc.audience_doctype)
    fields = [{'value':field,'description':meta.get_field(field).label if meta.get_field(field) else field}
              for field in allowed if field == 'name' or (meta.get_field(field) and meta.get_field(field).fieldtype not in ('Table','Table MultiSelect'))]
    return dict(columns=effective_columns(doc),fields=fields)


@frappe.whitelist(methods=['POST'])
def retry_segment_snapshot(segment_name):
    doc = _segment(segment_name,'write',lock=True)
    if doc.archived or not doc.snapshot_pending_generation:
        frappe.throw(_('There is no pending membership preparation to retry'))
    frappe.db.set_value('Reach Segment',doc.name,{'snapshot_status':'Queued','snapshot_error':None},update_modified=False)
    frappe.enqueue('finbyzreach.segment_snapshots.build',segment_name=doc.name,
        generation=doc.snapshot_pending_generation,queue='long',enqueue_after_commit=True)


@frappe.whitelist(methods=['POST'])
def preview_segment_page(segment_name=None, definition=None, after=None, page_length=50, search=None, include_count=1, sort_by=None, sort_order='asc'):
    """SQL pagination: never return/download the complete audience for a page."""
    from frappe.utils import cint
    from finbyzreach.segment_service import member_query, parsed_list
    if definition:
        frappe.has_permission('Reach Segment', 'create' if not segment_name else 'write', throw=True)
        base = _segment(segment_name, 'write') if segment_name else None
        if not base:
            frappe.new_doc('Reach Segment').check_permission('create')
        payload = frappe.parse_json(definition)
        if not isinstance(payload, dict):
            frappe.throw(_('Invalid segment definition'))
        data = base.as_dict() if base else {'name': '__preview__', 'segment_type': 'Active', 'audience_doctype': 'Lead'}
        for key in ('audience_doctype', 'filter_groups_json', 'filter_expression_json', 'exclude_filters_json', 'exclude_segments_json', 'exclude_email_groups_json'):
            if key in payload:
                data[key] = payload[key]
        if base and data['audience_doctype'] != base.audience_doctype:
            frappe.throw(_('Audience type cannot change after creation'))
        # An edited static filter preview shows the prospective recalculation.
        if not base or any(base.get(key) != data.get(key) for key in ('filter_groups_json','filter_expression_json')):
            data['segment_type'] = 'Active'
        doc = frappe._dict(data)
    else:
        doc = _segment(segment_name)
    doctype = doc.get('audience_doctype') or 'Lead'
    frappe.has_permission(doctype, 'read', throw=True)
    table = frappe.qb.DocType(doctype)
    query = member_query(doc)
    search_condition = None
    if search:
        label = {'Lead': 'lead_name', 'Contact': 'full_name', 'Customer': 'customer_name', 'Opportunity':'title','Sales Order':'customer_name'}[doctype]
        search_condition = table.name.like('%'+str(search)[:140]+'%') | table[label].like('%'+str(search)[:140]+'%')
        query = query.where(search_condition)
    total = None
    if cint(include_count):
        from frappe.query_builder.functions import Count
        total = cint(query.select(Count(table.name)).run()[0][0])
    page_length = max(1, min(cint(page_length) or 50, 200))
    columns = effective_columns(doc)
    sort_by = str(sort_by or '').strip()
    if sort_by:
        # EM-37: sort by a column header. Only shown, stored columns may be used; the cursor is an offset.
        field = frappe.get_meta(doctype).get_field(sort_by)
        from frappe.model import no_value_fields
        if sort_by not in columns or (sort_by != 'name' and (not field or field.fieldtype in no_value_fields or field.get('is_virtual'))):
            frappe.throw(_('This column cannot be sorted'))
        from pypika import Order
        direction = Order.desc if str(sort_order).lower() == 'desc' else Order.asc
        offset = max(0, cint(after))
        names = [row[0] for row in query.select(table.name).orderby(table[sort_by], order=direction).orderby(table.name).limit(page_length+1).offset(offset).run()]
        next_cursor = str(offset + page_length)
    else:
        if after:
            query = query.where(table.name > str(after))
        names = [row[0] for row in query.select(table.name).orderby(table.name).limit(page_length+1).run()]
        next_cursor = None
    has_more = len(names) > page_length
    names = names[:page_length]
    if next_cursor is None:
        next_cursor = names[-1] if has_more and names else None
    rows = frappe.get_list(doctype, filters={'name': ['in', names]}, fields=columns, order_by='name asc', limit_page_length=page_length) if names else []
    if sort_by:
        position = {name: index for index, name in enumerate(names)}
        rows.sort(key=lambda row: position.get(row.get('name'), 0))
    excluded_count = None
    if cint(include_count):
        from frappe.query_builder.functions import Count
        candidate_query = member_query(doc, apply_exclusions=False)
        if search_condition is not None:
            candidate_query = candidate_query.where(search_condition)
        candidate_count = cint(candidate_query.select(Count(table.name)).run()[0][0])
        excluded_count = max(0, candidate_count - total)
    return dict(rows=rows, columns=columns, count=total, excluded_count=excluded_count, has_more=has_more, next_cursor=next_cursor if has_more else None,
                audience_doctype=doctype, snapshot_status=doc.get('snapshot_status') or 'Ready', segment_type=doc.segment_type)


@frappe.whitelist(methods=['POST'])
def change_segment_members(segment_name, records, action):
    from finbyzreach.segment_service import MEMBER, EXCLUSION, _insert_members, initialize_static
    doc = _segment(segment_name, 'write', lock=True)
    require_ready(doc)
    if doc.archived:
        frappe.throw(_('Restore the segment before changing members'))
    records = frappe.parse_json(records)
    if not isinstance(records, list) or not records or len(records) > 500:
        frappe.throw(_('Select between 1 and 500 records'))
    if any(not isinstance(record,str) or not record for record in records):
        frappe.throw(_('Invalid record name'))
    visible = set(frappe.get_list(doc.audience_doctype,filters={'name':['in',records]},pluck='name',limit_page_length=500))
    if set(records) - visible:
        frappe.throw(_('One or more selected records are not readable'),frappe.PermissionError)
    if action not in ('add', 'exclude', 'restore'):
        frappe.throw(_('Invalid membership action'))
    if action == 'add' and doc.segment_type != 'Static':
        frappe.throw(_('Manual additions are only allowed for Static segments'))
    initialize_static(doc)
    from finbyzreach.segment_service import member_query
    table = frappe.qb.DocType(doc.audience_doctype)
    previous_members = {row[0] for row in member_query(doc).select(table.name).where(table.name.isin(records)).run()}
    for record in set(records):
        if not isinstance(record, str):
            frappe.throw(_('Invalid record name'))
        if action == 'add':
            _insert_members(doc.name, [record], source='Manual',is_current=0)
            frappe.db.set_value(MEMBER, {'segment': doc.name, 'record_name': record}, 'source', 'Manual')
            # Exclusions take precedence; adding does not silently restore.
        elif action == 'exclude':
            if not frappe.db.exists(EXCLUSION, {'segment': doc.name, 'record_name': record}):
                frappe.get_doc(dict(doctype=EXCLUSION, segment=doc.name, record_name=record)).insert(ignore_permissions=True)
                from finbyzreach.segment_history import record_event
                record_event(doc,record,'Excluded',frappe.generate_hash(length=32))
        else:
            if frappe.db.exists(EXCLUSION, {'segment':doc.name,'record_name':record}):
                frappe.db.delete(EXCLUSION, {'segment': doc.name, 'record_name': record})
                from finbyzreach.segment_history import record_event
                record_event(doc,record,'Restored',frappe.generate_hash(length=32))
    from frappe.utils import now_datetime
    if action in ('exclude','restore'):
        doc.last_definition_change = now_datetime()
        doc.last_definition_changed_by = frappe.session.user
        from finbyzreach.segment_service import assert_unused
        assert_unused(doc,blocking=False)
    doc.save()
    current_members = {row[0] for row in member_query(doc).select(table.name).where(table.name.isin(records)).run()}
    from finbyzreach.segment_automation import emit_entry
    for name in current_members-previous_members:
        emit_entry(doc,name,f'segment:{frappe.generate_hash(length=32)}')
    from finbyzreach.segment_automation import mark_left, schedule_reconciliation
    for name in previous_members-current_members:
        previous = frappe.db.get_value(MEMBER,{'segment':doc.name,'record_name':name},['name','source','is_current'],as_dict=True)
        if previous:
            mark_left(doc,previous,name)
    if current_members:
        _insert_members(doc.name,list(current_members))
        member = frappe.qb.DocType(MEMBER)
        frappe.qb.update(member).set(member.is_current,1).where(member.segment == doc.name).where(member.record_name.isin(list(current_members))).run()
    schedule_reconciliation(doc.name)
    # Exclusions win over manual additions; tell the caller instead of reporting success silently.
    still_excluded = frappe.db.count(EXCLUSION, {'segment': doc.name, 'record_name': ['in', list(set(records))]}) if action == 'add' else 0
    return dict(member_count=doc.member_count, excluded_count=doc.excluded_count, still_excluded=still_excluded)


def excluded_query(doc, search=None):
    """Records that would be members but are excluded (rules or manual), visible to the user."""
    from finbyzreach.segment_service import EXCLUSION, member_query
    table = frappe.qb.DocType(doc.audience_doctype)
    manual = frappe.qb.DocType(EXCLUSION)
    visible = frappe.qb.get_query(doc.audience_doctype, fields=['name'], ignore_permissions=False)
    candidates = member_query(doc, apply_exclusions=False).select(table.name)
    included = member_query(doc).select(table.name)
    manual_names = frappe.qb.from_(manual).select(manual.record_name).where(manual.segment == doc.name)
    query = (frappe.qb.from_(table).select(table.name)
        .where(table.name.isin(visible)).where(table.name.notin(included))
        .where(table.name.isin(candidates) | table.name.isin(manual_names)))
    if search:
        needle = '%' + str(search)[:140] + '%'
        query = query.where(table.name.like(needle) | table[_label_field(doc.audience_doctype)].like(needle))
    return query.orderby(table.name)


def _label_field(doctype):
    return {'Lead': 'lead_name', 'Contact': 'full_name', 'Customer': 'customer_name',
            'Opportunity': 'title', 'Sales Order': 'customer_name'}[doctype]


def _exclusion_reasons(doc, names, detailed=True):
    from finbyzreach.segment_service import EXCLUSION, member_query, parsed_list
    table = frappe.qb.DocType(doc.audience_doctype)
    details = {row.record_name: row for row in frappe.get_all(EXCLUSION,
        filters={'segment': doc.name, 'record_name': ['in', names]}, fields=['record_name', 'owner', 'creation'])} if names else {}
    by_segment = {}
    if detailed and names:
        # One query per excluded segment for the whole page, not per record.
        for other_name in parsed_list(doc.get('exclude_segments_json')):
            other = frappe.get_doc('Reach Segment', other_name)
            for row in member_query(other).select(table.name).where(table.name.isin(names)).run():
                by_segment.setdefault(row[0], []).append(other_name)
    result = {}
    for name in names:
        if name in details:
            result[name] = dict(details[name], reason=_('Manual exclusion'), manual=True)
        else:
            reasons = by_segment.get(name)
            result[name] = dict(record_name=name, owner='', creation='', manual=False,
                reason=_('Excluded by segment: {0}').format(', '.join(reasons)) if reasons else _('Exclusion filters or Email Group'))
    return result


@frappe.whitelist(methods=['GET'])
def excluded_segment_records(segment_name, start=0, with_paging=0, search=None):
    """Excluded tab: search, the segment's columns, reason, who and when."""
    from frappe.utils import cint
    doc = _segment(segment_name)
    all_names = [row[0] for row in excluded_query(doc, search).offset(max(0, cint(start))).limit(51).run()]
    names = all_names[:50]
    reasons = _exclusion_reasons(doc, names)
    columns = effective_columns(doc)
    values = {row.name: row for row in frappe.get_list(doc.audience_doctype, filters={'name': ['in', names]},
              fields=columns, limit_page_length=50)} if names else {}
    result = [dict(reasons[name], values=values.get(name) or {}) for name in names]
    return dict(rows=result, has_more=len(all_names) > 50, columns=columns) if cint(with_paging) else result


@frappe.whitelist(methods=['POST'])
def duplicate_segment(segment_name, new_name, copy_members=0):
    from frappe.utils import cint
    from finbyzreach.segment_service import MEMBER, EXCLUSION, _insert_members, member_names
    doc = _segment(segment_name)
    require_ready(doc)
    frappe.has_permission('Reach Segment', 'create', throw=True)
    duplicate = frappe.copy_doc(doc)
    duplicate.segment_name = str(new_name or '').strip()[:140]
    duplicate.archived = 0
    duplicate.members_initialized = 0
    duplicate.static_leads_json = '[]'
    duplicate.insert()
    for row in frappe.get_all(EXCLUSION, filters={'segment': doc.name}, fields=['record_name'], limit_page_length=0):
        frappe.get_doc(dict(doctype=EXCLUSION, segment=duplicate.name, record_name=row.record_name)).insert(ignore_permissions=True)
    if doc.segment_type == 'Static':
        from finbyzreach.segment_snapshots import prepare
        # SEG-35: "copy members" keeps the original members, manual additions included.
        # Otherwise the copy is a newly saved Static segment: insert already took a fresh
        # snapshot of the records matching its filters now (SEG-03), so keep that.
        if cint(copy_members):
            prepare(duplicate, source=doc)
        frappe.db.set_value('Reach Segment', duplicate.name, {key:duplicate.get(key) for key in (
            'snapshot_generation','snapshot_pending_generation','snapshot_status','snapshot_definition')},update_modified=False)
        from finbyzreach.segment_automation import schedule_reconciliation
        if not duplicate.snapshot_pending_generation:
            from finbyzreach.segment_automation import update_counts
            update_counts(duplicate)
            schedule_reconciliation(duplicate.name)
    return duplicate.name


@frappe.whitelist(methods=['GET'])
def record_segments(doctype, name, after=None, paginated=0):
    """Bounded widget lookup; one UNION query per page of readable definitions."""
    from finbyzreach.segment_service import member_query, AUDIENCE_TYPES
    from frappe.utils import cint
    from pypika.terms import ValueWrapper
    if doctype not in AUDIENCE_TYPES:
        frappe.throw(_('Unsupported segment audience'))
    frappe.get_doc(doctype, name).check_permission('read')
    filters = {'audience_doctype':doctype, 'archived':0}
    if after:
        filters['name'] = ['>',str(after)]
    names = frappe.get_list('Reach Segment', filters=filters, pluck='name', order_by='name asc',limit_page_length=51)
    candidates = names[:50]
    table = frappe.qb.DocType(doctype)
    combined = None
    for segment in candidates:
        doc = frappe.get_doc('Reach Segment', segment)
        try:
            query = member_query(doc).select(ValueWrapper(segment).as_('segment_name')).where(table.name == name)
            combined = query if combined is None else combined.union_all(query)
        except (frappe.ValidationError, frappe.DoesNotExistError):
            frappe.clear_last_message()
            frappe.logger('finbyzreach').warning('Invalid Reach Segment definition during record lookup: %s', segment)
    result = [row[0] for row in combined.run()] if combined is not None else []
    return dict(segments=result,next_cursor=candidates[-1] if len(names)>50 else None) if cint(paginated) else result


@frappe.whitelist(methods=['GET'])
def export_segment(segment_name, file_format='csv', columns=None, header_language=None, scope='members'):
    from finbyzreach.segment_service import member_names, parsed_list
    from frappe.model import get_permitted_fields
    from frappe.utils.csvutils import to_csv
    doc = _segment(segment_name)
    doc.check_permission('export')
    require_ready(doc)
    if scope not in ('members', 'excluded'):
        frappe.throw(_('Choose members or excluded records'))
    columns = effective_columns(doc, columns)
    data = [export_headers(doc.audience_doctype, columns, header_language) + ([_('Reason')] if scope == 'excluded' else [])]
    table = frappe.qb.DocType(doc.audience_doctype)
    cursor = None
    clean = lambda value: "'"+value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
    while True:
        if scope == 'excluded':
            page = excluded_query(doc)
            if cursor:
                page = page.where(table.name > cursor)
            names = [row[0] for row in page.limit(500).run()]
        else:
            names = member_names(doc, after=cursor, limit=500)
        if not names:
            break
        rows = frappe.get_list(doc.audience_doctype, filters={'name': ['in', names]}, fields=columns, order_by='name asc', limit_page_length=500)
        reasons = _exclusion_reasons(doc, names, detailed=False) if scope == 'excluded' else {}
        # Prevent spreadsheet formula execution from untrusted CRM text.
        data.extend([[clean(row.get(field)) for field in columns] + ([reasons[row.name]['reason']] if scope == 'excluded' else [])
                     for row in rows])
        cursor = names[-1]
    if file_format == 'xlsx':
        from frappe.utils.xlsxutils import make_xlsx
        frappe.response['filecontent'] = make_xlsx(data, 'Members').getvalue()
        frappe.response['type'] = 'binary'
    elif file_format == 'csv':
        frappe.response['filecontent'] = to_csv(data)
        frappe.response['type'] = 'download'
    else:
        frappe.throw(_('Choose csv or xlsx'))
    suffix = '_excluded' if scope == 'excluded' else ''
    frappe.response['filename'] = f'{frappe.scrub(doc.name)}{suffix}.{file_format}'


EXPORT_LANGUAGES = {'DE': 'de', 'FR': 'fr', 'IT': 'it', 'EN': 'en'}


def export_headers(doctype, columns, header_language=None):
    """Column labels in DE / FR / IT / EN. Without a language, keep field names (old behaviour)."""
    if not header_language:
        return list(columns)
    lang = EXPORT_LANGUAGES.get(str(header_language).upper())
    if not lang:
        frappe.throw(_('Choose DE, FR, IT or EN for the column headers'))
    meta = frappe.get_meta(doctype)
    headers = []
    for field in columns:
        label = 'ID' if field == 'name' else (meta.get_label(field) or field)
        headers.append(_(label, lang=lang))
    return headers


@frappe.whitelist(methods=['POST'])
def request_segment_export(segment_name, file_format='csv', columns=None, header_language=None, scope='members'):
    doc = _segment(segment_name)
    doc.check_permission('export')
    require_ready(doc)
    columns = effective_columns(doc, columns)
    if file_format not in ('csv','xlsx'):
        frappe.throw(_('Choose csv or xlsx'))
    if scope not in ('members', 'excluded'):
        frappe.throw(_('Choose members or excluded records'))
    if header_language and str(header_language).upper() not in EXPORT_LANGUAGES:
        frappe.throw(_('Choose DE, FR, IT or EN for the column headers'))
    job_id = f'reach-export:{frappe.generate_hash(length=20)}'
    frappe.enqueue('finbyzreach.segments.build_segment_export', segment_name=segment_name,
        file_format=file_format, columns=json.dumps(columns), requesting_user=frappe.session.user, queue='long',
        job_id=job_id, enqueue_after_commit=True, header_language=header_language, scope=scope)
    return {'job_id':job_id}


def build_segment_export(segment_name, file_format, requesting_user, columns=None, header_language=None, scope='members'):
    from frappe.utils.file_manager import save_file
    # Enqueue captures the user's identity; recheck access when the job runs.
    if frappe.session.user != requesting_user:
        frappe.throw(_('Export identity changed'), frappe.PermissionError)
    export_segment(segment_name, file_format, columns, header_language, scope)
    content = frappe.response.pop('filecontent')
    filename = frappe.response.pop('filename')
    frappe.response.pop('type', None)
    # Unattached private files are accessible to their owner, not every segment reader.
    saved = save_file(filename, content, None, None, is_private=1)
    frappe.publish_realtime('reach_segment_export_ready',
        {'segment':segment_name, 'file_url':saved.file_url}, user=requesting_user, after_commit=True)
    return saved.file_url


@frappe.whitelist(methods=['GET'])
def template_segments(audience_doctype):
    from finbyzreach.segment_service import AUDIENCE_TYPES
    if audience_doctype not in AUDIENCE_TYPES:
        return []
    return frappe.get_list('Reach Segment', filters={'audience_doctype':audience_doctype,'archived':0},
                           fields=['name'], order_by='name asc', limit_page_length=200)


def is_segment_member(segment_name, record):
    """Safe Jinja predicate for conditional email rows and blocks."""
    from finbyzreach.segment_service import member_query
    if not record or not record.get('name'):
        return False
    segment = _segment(segment_name)
    if segment.archived or segment.audience_doctype != record.get('doctype'):
        return False
    table = frappe.qb.DocType(segment.audience_doctype)
    return bool(member_query(segment).select(table.name).where(table.name == record['name']).limit(1).run())


@frappe.whitelist(methods=['GET'])
def segment_history(segment_name, after=None):
    from finbyzreach.segment_history import EVENT, SAMPLE
    from frappe.utils import add_days, today
    doc = _segment(segment_name)
    event = frappe.qb.DocType(EVENT)
    query = frappe.qb.from_(event).select(event.name,event.record_name,event.event,event.actor,event.event_time).where(event.segment == doc.name)
    if frappe.session.user != 'Administrator':
        visible = frappe.qb.get_query(doc.audience_doctype,fields=['name'],ignore_permissions=False)
        query = query.where(event.record_name.isin(visible))
    if after:
        previous = frappe.db.get_value(EVENT,{'name':after,'segment':doc.name},['creation','name'],as_dict=True)
        if not previous:
            frappe.throw(_('Invalid history cursor'))
        query = query.where((event.creation > previous.creation) | ((event.creation == previous.creation) & (event.name > previous.name)))
    rows = query.orderby(event.creation).orderby(event.name).limit(51).run(as_dict=True)
    samples = frappe.get_all(SAMPLE,filters={'segment':doc.name,'sample_date':['>=',add_days(today(),-365)]},
        fields=['sample_date','member_count'],order_by='sample_date asc',limit_page_length=366)
    return dict(events=rows[:50],next_cursor=rows[49].name if len(rows)>50 else None,samples=samples)


@frappe.whitelist(methods=['GET'])
def segment_usage(segment_name):
    """Everything that depends on this segment, for the "Used in" tab and edit warnings."""
    from finbyzreach.segment_service import workflow_usage, campaign_usage
    from finbyzreach.segment_automation import segment_references
    doc = _segment(segment_name)
    workflows = workflow_usage(doc)
    campaigns = campaign_usage(doc)
    can_read_campaigns = frappe.has_permission('Campaign', 'read')
    dependents = [row.name for row in frappe.get_all('Reach Segment',
                  fields=['name', 'exclude_segments_json', 'filter_expression_json'], limit_page_length=0)
                  if row.name != doc.name and doc.name in segment_references(row)]
    readable = set(frappe.get_list('Reach Segment', filters={'name': ['in', dependents]}, pluck='name',
                                   limit_page_length=0)) if dependents else set()
    return dict(
        workflows=workflows,
        # Titles of campaigns the user cannot read are not disclosed, only counted.
        campaigns=campaigns if can_read_campaigns else [],
        hidden_campaigns=0 if can_read_campaigns else len(campaigns),
        segments=[name for name in dependents if name in readable],
        hidden_segments=len(dependents) - len(readable),
        live=any(row['live'] for row in workflows) or any(row['live'] for row in campaigns),
    )


@frappe.whitelist(methods=['POST'])
def create_workflow_for_segment(segment_name):
    """New draft workflow whose trigger is "Record enters segment" for this segment."""
    from finbyzreach.segment_automation import TOPIC
    from finbyzai.workflow_builder import registry
    from finbyzai.workflow_builder.authoring import create_workflow_record, save_workflow_draft
    registry.require_builder()
    doc = _segment(segment_name)
    if doc.archived:
        frappe.throw(_('Restore the segment before using it in a workflow'))
    created = create_workflow_record(_('{0} workflow').format(doc.name)[:140], doc.audience_doctype,
                                     trigger_type='trigger.any')
    graph = created['graph']
    graph['nodes'][0]['config'] = {'triggers': [{'id': 'segment-entry', 'type': 'trigger.event', 'config': {
        'event_topic': TOPIC, 'condition': None,
        'event_filter': {'kind': 'predicate', 'field': 'segment', 'operator': 'eq', 'value': doc.name}}}]}
    save_workflow_draft(created['workflow'], created['draft_revision'], graph)
    return created['workflow']


SEGMENT_FILTER_LIMIT = 2000
NO_MEMBERS = '__reach_segment_has_no_members__'


@frappe.whitelist(methods=['GET'])
def segment_filter_names(segment_name):
    """SEG-46: record names for a List / Report View filter "ID in segment".

    Desk filters travel in the URL and saved report settings, so this is bounded;
    larger segments use the Reach Segment Members report or the export.
    """
    from finbyzreach.segment_service import member_names
    doc = _segment(segment_name)
    require_ready(doc)
    if doc.archived:
        frappe.throw(_('Restore the segment before using it as a filter'))
    names = member_names(doc, limit=SEGMENT_FILTER_LIMIT + 1)
    if len(names) > SEGMENT_FILTER_LIMIT:
        frappe.throw(_('{0} has more than {1} members. Open the Reach Segment Members report or export the segment instead.')
                     .format(frappe.bold(doc.name), SEGMENT_FILTER_LIMIT), title=_('Segment too large for a list filter'))
    # An empty IN list is ignored by Desk filters and would show every record.
    return dict(doctype=doc.audience_doctype, names=names or [NO_MEMBERS], count=len(names))
