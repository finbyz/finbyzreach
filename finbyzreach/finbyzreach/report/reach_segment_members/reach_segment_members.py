import frappe
from frappe import _


def execute(filters=None):
    from finbyzreach.segments import preview_segment_page
    filters = frappe._dict(filters or {})
    if not filters.segment:
        return [], []
    page = preview_segment_page(filters.segment, after=filters.get('after'), page_length=200)
    doctype = page['audience_doctype']
    meta = frappe.get_meta(doctype)
    columns = []
    for name in page['columns']:
        field = meta.get_field(name)
        columns.append(dict(fieldname=name, label=field.label if field else _('ID'),
            fieldtype='Link' if name == 'name' else 'Data', options=doctype if name == 'name' else None, width=180))
    message = _('Showing up to 200 members. Use After record for the next page, or export the segment for the complete list.')
    summary = [dict(value=page['count'],label=_('Total matching members'),datatype='Int')]
    return columns, page['rows'], message, None, summary
