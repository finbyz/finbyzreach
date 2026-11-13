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
	if audience_doctype not in ("Lead", "Contact", "Customer"):
		frappe.throw(_("Audience type must be Lead, Contact or Customer"))
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
	refresh_static(doc)
	doc.save()

	return {"name": doc.name, "member_count": doc.member_count}

@frappe.whitelist(methods=["GET"])
def preview_segment_audience(segment_name, limit=None):
	frappe.has_permission("Reach Segment", "read", throw=True)
	doc = frappe.get_doc("Reach Segment", segment_name)
	doc.check_permission("read")
	from finbyzreach.segment_service import member_names
	from frappe.utils import cint
	return member_names(doc, limit=min(cint(limit) or 200, 1000))


def _segment(name, permission='read', lock=False):
    doc = frappe.get_doc('Reach Segment', name, for_update=lock)
    doc.check_permission(permission)
    frappe.has_permission(doc.audience_doctype or 'Lead', 'read', throw=True)
    return doc


@frappe.whitelist(methods=['POST'])
def preview_segment_page(segment_name=None, definition=None, after=None, page_length=50, search=None, include_count=1):
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
    if search:
        label = {'Lead': 'lead_name', 'Contact': 'full_name', 'Customer': 'customer_name'}[doctype]
        query = query.where(table.name.like('%'+str(search)[:140]+'%') | table[label].like('%'+str(search)[:140]+'%'))
    total = None
    if cint(include_count):
        from frappe.query_builder.functions import Count
        total = cint(query.select(Count(table.name)).run()[0][0])
    page_length = max(1, min(cint(page_length) or 50, 200))
    if after:
        query = query.where(table.name > str(after))
    names = [row[0] for row in query.select(table.name).orderby(table.name).limit(page_length+1).run()]
    has_more = len(names) > page_length
    names = names[:page_length]
    columns = parsed_list(doc.get('columns_json')) or ['name', {'Lead': 'lead_name', 'Contact': 'full_name', 'Customer': 'customer_name'}[doctype], 'email_id']
    from frappe.model import get_permitted_fields
    allowed = set(get_permitted_fields(doctype)) | {'name'}
    columns = [name for name in columns if isinstance(name, str) and name in allowed][:20]
    if 'name' not in columns:
        columns.insert(0, 'name')
    rows = frappe.get_list(doctype, filters={'name': ['in', names]}, fields=columns, order_by='name asc', limit_page_length=page_length) if names else []
    excluded_count = None
    if cint(include_count):
        from frappe.query_builder.functions import Count
        candidate_count = cint(member_query(doc, apply_exclusions=False).select(Count(table.name)).run()[0][0])
        excluded_count = max(0, candidate_count - total)
    return dict(rows=rows, columns=columns, count=total, excluded_count=excluded_count, has_more=has_more, next_cursor=names[-1] if has_more else None,
                audience_doctype=doctype)


@frappe.whitelist(methods=['POST'])
def change_segment_members(segment_name, records, action):
    from finbyzreach.segment_service import MEMBER, EXCLUSION, _insert_members, initialize_static
    doc = _segment(segment_name, 'write', lock=True)
    records = frappe.parse_json(records)
    if not isinstance(records, list) or not records or len(records) > 500:
        frappe.throw(_('Select between 1 and 500 records'))
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
        frappe.get_doc(doc.audience_doctype, record).check_permission('read')
        if action == 'add':
            _insert_members(doc.name, [record], source='Manual')
            frappe.db.set_value(MEMBER, {'segment': doc.name, 'record_name': record}, 'source', 'Manual')
            # Exclusions take precedence; adding does not silently restore.
        elif action == 'exclude':
            if not frappe.db.exists(EXCLUSION, {'segment': doc.name, 'record_name': record}):
                frappe.get_doc(dict(doctype=EXCLUSION, segment=doc.name, record_name=record)).insert(ignore_permissions=True)
        else:
            frappe.db.delete(EXCLUSION, {'segment': doc.name, 'record_name': record})
    doc.save()
    current_members = {row[0] for row in member_query(doc).select(table.name).where(table.name.isin(records)).run()}
    from finbyzreach.segment_automation import emit_entry
    for name in current_members-previous_members:
        emit_entry(doc,name,f'segment:{frappe.generate_hash(length=32)}')
    return dict(member_count=doc.member_count, excluded_count=doc.excluded_count)


@frappe.whitelist(methods=['GET'])
def excluded_segment_records(segment_name, start=0):
    from frappe.utils import cint
    from finbyzreach.segment_service import EXCLUSION, member_query, parsed_list
    doc = _segment(segment_name)
    table = frappe.qb.DocType(doc.audience_doctype)
    manual = frappe.qb.DocType(EXCLUSION)
    visible = frappe.qb.get_query(doc.audience_doctype, fields=['name'], ignore_permissions=False)
    candidates = member_query(doc, apply_exclusions=False).select(table.name)
    included = member_query(doc).select(table.name)
    manual_names = frappe.qb.from_(manual).select(manual.record_name).where(manual.segment == doc.name)
    excluded = (frappe.qb.from_(table).select(table.name)
        .where(table.name.isin(visible)).where(table.name.notin(included))
        .where(table.name.isin(candidates) | table.name.isin(manual_names))
        .orderby(table.name).offset(max(0,cint(start))).limit(50))
    names = [row[0] for row in excluded.run()]
    details = {row.record_name:row for row in frappe.get_all(EXCLUSION,
        filters={'segment':doc.name,'record_name':['in',names]}, fields=['record_name','owner','creation'])} if names else {}
    result = []
    for name in names:
        if name in details:
            result.append(dict(details[name],reason=_('Manual exclusion'),manual=True))
            continue
        reasons = []
        for other_name in parsed_list(doc.get('exclude_segments_json')):
            other = frappe.get_doc('Reach Segment',other_name)
            if member_query(other).select(table.name).where(table.name == name).limit(1).run():
                reasons.append(other_name)
        result.append(dict(record_name=name,owner='',creation='',manual=False,
                           reason=_('Excluded by segment: {0}').format(', '.join(reasons)) if reasons else _('Exclusion filters or Email Group')))
    return result


@frappe.whitelist(methods=['POST'])
def duplicate_segment(segment_name, new_name, copy_members=0):
    from frappe.utils import cint
    from finbyzreach.segment_service import MEMBER, EXCLUSION, _insert_members, member_names
    doc = _segment(segment_name)
    frappe.has_permission('Reach Segment', 'create', throw=True)
    duplicate = frappe.copy_doc(doc)
    duplicate.segment_name = str(new_name or '').strip()[:140]
    duplicate.archived = 0
    duplicate.members_initialized = 0
    duplicate.static_leads_json = '[]'
    duplicate.insert()
    for row in frappe.get_all(EXCLUSION, filters={'segment': doc.name}, fields=['record_name'], limit_page_length=0):
        frappe.get_doc(dict(doctype=EXCLUSION, segment=duplicate.name, record_name=row.record_name)).insert(ignore_permissions=True)
    if doc.segment_type == 'Static' and cint(copy_members):
        frappe.db.delete(MEMBER, {'segment': duplicate.name})
        _insert_members(duplicate.name, member_names(doc))
    elif doc.segment_type == 'Static' and not cint(copy_members):
        frappe.db.delete(MEMBER, {'segment': duplicate.name})
    duplicate.save()
    return duplicate.name


@frappe.whitelist(methods=['GET'])
def record_segments(doctype, name):
    from finbyzreach.segment_service import member_query, AUDIENCE_TYPES
    if doctype not in AUDIENCE_TYPES:
        frappe.throw(_('Unsupported segment audience'))
    frappe.get_doc(doctype, name).check_permission('read')
    table = frappe.qb.DocType(doctype)
    result = []
    for segment in frappe.get_list('Reach Segment', filters={'audience_doctype': doctype, 'archived': 0}, pluck='name', limit_page_length=0):
        doc = frappe.get_doc('Reach Segment', segment)
        try:
            if member_query(doc).select(table.name).where(table.name == name).limit(1).run():
                result.append(segment)
        except (frappe.ValidationError, frappe.DoesNotExistError):
            # Old definitions can refer to a removed custom field. A compact
            # record widget must not stop the CRM form from loading. Explicit
            # segment previews and mailing selection still fail validation.
            frappe.clear_last_message()
            frappe.logger('finbyzreach').warning('Invalid Reach Segment definition during record lookup: %s', segment)
    return result


@frappe.whitelist(methods=['GET'])
def export_segment(segment_name, file_format='csv'):
    from finbyzreach.segment_service import member_names, parsed_list
    from frappe.model import get_permitted_fields
    from frappe.utils.csvutils import to_csv
    doc = _segment(segment_name, 'write')
    columns = parsed_list(doc.get('columns_json')) or ['name', 'email_id']
    allowed = set(get_permitted_fields(doc.audience_doctype)) | {'name'}
    if any(not isinstance(field, str) or field not in allowed for field in columns):
        frappe.throw(_('One or more export columns are not permitted'))
    data = [columns]
    cursor = None
    while True:
        names = member_names(doc, after=cursor, limit=500)
        if not names:
            break
        rows = frappe.get_list(doc.audience_doctype, filters={'name': ['in', names]}, fields=columns, order_by='name asc', limit_page_length=500)
        # Prevent spreadsheet formula execution from untrusted CRM text.
        data.extend([["'"+value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
                      for value in (row.get(field) for field in columns)] for row in rows])
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
    frappe.response['filename'] = f'{frappe.scrub(doc.name)}.{file_format}'


@frappe.whitelist(methods=['POST'])
def request_segment_export(segment_name, file_format='csv'):
    _segment(segment_name, 'write')
    if file_format not in ('csv','xlsx'):
        frappe.throw(_('Choose csv or xlsx'))
    job_id = f'reach-export:{frappe.generate_hash(length=20)}'
    frappe.enqueue('finbyzreach.segments.build_segment_export', segment_name=segment_name,
        file_format=file_format, requesting_user=frappe.session.user, queue='long',
        job_id=job_id, enqueue_after_commit=True)
    return {'job_id':job_id}


def build_segment_export(segment_name, file_format, requesting_user):
    from frappe.utils.file_manager import save_file
    # Enqueue captures the user's identity; recheck access when the job runs.
    if frappe.session.user != requesting_user:
        frappe.throw(_('Export identity changed'), frappe.PermissionError)
    export_segment(segment_name, file_format)
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
