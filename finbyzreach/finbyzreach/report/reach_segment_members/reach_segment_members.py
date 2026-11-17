import frappe
from frappe import _

# Query reports render every row in the browser; larger audiences use the export.
REPORT_LIMIT = 5000
PAGE = 500


def execute(filters=None):
    """SEG-46: a report filtered by segment, using the segment's saved columns."""
    from finbyzreach.segment_service import member_query
    from finbyzreach.segments import _segment, effective_columns, require_ready
    filters = frappe._dict(filters or {})
    if not filters.segment:
        return [], []
    doc = _segment(filters.segment)
    require_ready(doc)
    doctype = doc.audience_doctype
    table = frappe.qb.DocType(doctype)
    query = member_query(doc)
    if filters.get('search'):
        label = {'Lead': 'lead_name', 'Contact': 'full_name', 'Customer': 'customer_name',
                 'Opportunity': 'title', 'Sales Order': 'customer_name'}[doctype]
        needle = '%' + str(filters.search)[:140] + '%'
        query = query.where(table.name.like(needle) | table[label].like(needle))
    from frappe.query_builder.functions import Count
    total = int(query.select(Count(table.name)).run()[0][0] or 0)
    columns = effective_columns(doc)
    rows, cursor = [], None
    while len(rows) < REPORT_LIMIT:
        page = query.select(table.name).orderby(table.name)
        if cursor:
            page = page.where(table.name > cursor)
        names = [row[0] for row in page.limit(min(PAGE, REPORT_LIMIT - len(rows))).run()]
        if not names:
            break
        rows.extend(frappe.get_list(doctype, filters={'name': ['in', names]}, fields=columns,
                                    order_by='name asc', limit_page_length=len(names)))
        cursor = names[-1]
    meta = frappe.get_meta(doctype)
    report_columns = []
    for name in columns:
        field = meta.get_field(name)
        report_columns.append(dict(fieldname=name, label=field.label if field else _('ID'),
            fieldtype='Link' if name == 'name' else (field.fieldtype if field and field.fieldtype in
                ('Data', 'Link', 'Select', 'Date', 'Datetime', 'Int', 'Float', 'Currency', 'Check') else 'Data'),
            options=doctype if name == 'name' else (field.options if field and field.fieldtype == 'Link' else None),
            width=180))
    message = None
    if total > len(rows):
        message = _('Showing the first {0} of {1} members. Export the segment for the complete list.').format(len(rows), total)
    summary = [dict(value=total, label=_('Members'), datatype='Int'),
               dict(value=doc.excluded_count or 0, label=_('Excluded'), datatype='Int')]
    return report_columns, rows, message, None, summary
