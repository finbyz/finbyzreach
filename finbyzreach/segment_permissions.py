"""Optional per-user segment restrictions, layered on Frappe role permissions."""
import frappe
from frappe.utils import cint


def setting(permission, user=None):
    user = user or frappe.session.user
    if user == 'Administrator' or not frappe.get_meta('User').has_field('custom_segment_permissions_enabled'):
        return None
    values = frappe.get_cached_value('User', user,
        ['custom_segment_permissions_enabled','custom_segment_read','custom_segment_edit','custom_segment_delete'], as_dict=True)
    if not values or not cint(values.custom_segment_permissions_enabled):
        return None
    if not cint(values.custom_segment_read):
        return False
    if permission in ('write','create','export','email','share'):
        return bool(cint(values.custom_segment_edit))
    if permission == 'delete':
        return bool(cint(values.custom_segment_delete))
    return True


def has_permission(doc, user=None, permission_type=None, ptype=None):
    # Frappe treats a falsy hook result (including None) as a denial.
    return setting(permission_type or ptype or 'read', user) is not False


def query_conditions(user=None):
    return '1=0' if setting('read', user) is False else ''


def folder_permission(doc, user=None, permission_type=None, ptype=None):
    permission = permission_type or ptype or 'read'
    if permission == 'delete':
        return setting('delete', user) is not False
    if permission in ('write','create'):
        return setting('write', user) is not False and frappe.has_permission('Reach Segment', 'write', user=user)
    return setting('read', user) is not False


def filter_boot_permissions(bootinfo):
    for permission, key in (('read','can_read'),('read','all_read'),('write','can_write'),('create','can_create'),('delete','can_delete')):
        if setting(permission) is False and bootinfo.get('user'):
            bootinfo.user[key] = [name for name in bootinfo.user.get(key, []) if name not in ('Reach Segment','Reach Segment Folder')]
