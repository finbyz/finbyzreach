"""Remove obsolete User controls; role permissions remain unchanged."""
from frappe.custom.doctype.custom_field.custom_field import delete_custom_fields


def execute():
    # Native deletion clears metadata/property setters and tolerates absent fields.
    # Frappe retains physical columns; this patch does not drop User data columns.
    delete_custom_fields({'User': [
        'custom_segment_delete',
        'custom_segment_edit',
        'custom_segment_read',
        'custom_segment_permissions_enabled',
        'custom_segment_permissions_section',
    ]})
