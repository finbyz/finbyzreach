"""Readable change log of a segment's filters and exclusions (SEG-51).

Frappe's Version history stores filters as raw JSON. This turns each saved change into
plain sentences: which condition was added or removed, and by whom.
"""
import json

import frappe
from frappe import _
from frappe.utils import cint

DEFINITION_FIELDS = ('filter_groups_json', 'filter_expression_json', 'exclude_filters_json', 'exclude_segments_json')
OTHER_FIELDS = {'segment_type': 'Segment type', 'archived': 'Archived', 'folder': 'Folder', 'description': 'Description'}
OPERATORS = {'=': 'is', '!=': 'is not', 'like': 'contains', 'not like': 'does not contain', 'in': 'is one of',
             'not in': 'is not one of', '>': 'is greater than', '<': 'is less than', '>=': 'is at least', '<=': 'is at most',
             'between': 'is between', 'is': 'is', 'Timespan': 'is in'}


def _json(value):
    if value in (None, ''):
        return None
    try:
        return json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return None


def _label(doctype, fieldname):
    if fieldname == '__last_activity':
        return _('Last activity')
    if fieldname in ('creation', 'modified', 'name'):
        return {'creation': _('Created on'), 'modified': _('Last modified'), 'name': _('ID')}[fieldname]
    try:
        return _(frappe.get_meta(doctype).get_label(fieldname) or fieldname)
    except Exception:
        return fieldname


def _value(value):
    if isinstance(value, (list, tuple)):
        return ', '.join(str(v) for v in value)
    return str(value)


def _condition(doctype, condition):
    """One Frappe filter row [doctype, field, operator, value]."""
    _doctype, field, operator, value = (list(condition) + [None] * 4)[:4]
    if operator == 'is':
        return _('{0} {1}').format(_label(_doctype or doctype, field), _('contains data') if value == 'set' else _('does not contain data'))
    return '{0} {1} {2}'.format(_label(_doctype or doctype, field), _(OPERATORS.get(operator, operator)), _value(value))


def _special(doctype, node):
    kind = node.get('kind')
    if kind == 'subscription':
        return _('Subscription {0}: {1}').format(node.get('topic'), _(node.get('status') or 'Subscribed'))
    if kind == 'segment':
        return _('{0} segment {1}').format(_('Is member of') if node.get('operator') != 'not in' else _('Is not member of'), node.get('segment'))
    if kind == 'related':
        return _('Connected {0} ({1})').format(node.get('doctype'), _(node.get('quantifier') or 'any'))
    if kind == 'activity':
        return _('{0} in the last {1} days').format(node.get('event'), node.get('days'))
    if kind == 'relative_date':
        unit = _(node.get('unit') or 'days')
        rule = {'older_than': _('more than {0} {1} ago'), 'within_next': _('in the next {0} {1}')}.get(node.get('comparison'), _('in the last {0} {1}'))
        return '{0}: {1}'.format(_label(doctype, node.get('field')), rule.format(node.get('amount'), unit))
    if kind == 'multiselect':
        mode = {'any': _('has any of'), 'all': _('has all of'), 'none': _('has none of')}.get(node.get('mode'), node.get('mode'))
        return '{0} {1}: {2}'.format(_label(doctype, node.get('field')), mode, _value(node.get('values') or []))
    return str(kind)


def _tree(doctype, node, prefix=''):
    if isinstance(node, list):
        if node and isinstance(node[0], list):
            return [line for group in node for line in _tree(doctype, group, prefix)]
        if node and isinstance(node[0], str):
            return [prefix + _condition(doctype, node)]
        return [prefix + _condition(doctype, row) for row in node]
    if isinstance(node, dict) and node.get('kind'):
        return [prefix + _special(doctype, node)]
    if isinstance(node, dict):
        lines = []
        for child in node.get('conditions') or []:
            lines.extend(_tree(doctype, child, prefix))
        return lines
    return []


def describe(doctype, values):
    """Set of sentences describing a definition; values maps field name to its JSON text."""
    lines = []
    expression = _json(values.get('filter_expression_json'))
    if expression:
        lines += _tree(doctype, expression)
    else:
        lines += _tree(doctype, _json(values.get('filter_groups_json')) or [])
    prefix = _('Exclude: ')
    lines += _tree(doctype, _json(values.get('exclude_filters_json')) or [], prefix)
    lines += [prefix + _('segment {0}').format(name) for name in _json(values.get('exclude_segments_json')) or []]
    return lines


@frappe.whitelist()
def definition_changes(segment_name, start=0, page_length=20):
    """Newest first. Each entry lists the conditions added and removed, plus other settings that changed."""
    segment = frappe.get_doc('Reach Segment', segment_name)
    segment.check_permission('read')
    doctype = segment.audience_doctype or 'Lead'
    page_length = min(max(cint(page_length), 1), 100)
    rows = frappe.get_all('Version', filters={'ref_doctype': 'Reach Segment', 'docname': segment_name},
                          fields=['creation', 'owner', 'data'], order_by='creation desc',
                          start=max(cint(start), 0), limit_page_length=page_length + 1)
    entries = []
    for row in rows[:page_length]:
        data = _json(row.data) or {}
        changed = {item[0]: (item[1], item[2]) for item in data.get('changed') or [] if len(item) == 3}
        if not any(field in changed for field in (*DEFINITION_FIELDS, *OTHER_FIELDS)):
            continue
        before = {f: changed[f][0] for f in DEFINITION_FIELDS if f in changed}
        after = {f: changed[f][1] for f in DEFINITION_FIELDS if f in changed}
        # Only the parts that changed are compared, so an unchanged exclusion is not reported.
        old_lines, new_lines = describe(doctype, before), describe(doctype, after)
        changes = [{'type': 'removed', 'text': t} for t in old_lines if t not in new_lines]
        changes += [{'type': 'added', 'text': t} for t in new_lines if t not in old_lines]
        for field, label in OTHER_FIELDS.items():
            if field in changed:
                changes.append({'type': 'changed', 'text': _('{0}: {1} to {2}').format(_(label), changed[field][0] or _('empty'), changed[field][1] or _('empty'))})
        entries.append({'when': row.creation, 'by': row.owner, 'changes': changes})
    return {'entries': entries, 'has_more': len(rows) > page_length}
