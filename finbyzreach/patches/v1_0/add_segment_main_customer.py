"""An explicit main Customer makes related segment filters unambiguous."""
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({'Contact': [{
        'fieldname':'custom_reach_main_customer', 'fieldtype':'Link', 'options':'Customer',
        'label':'Main Customer for Segments', 'insert_after':'links', 'module':'Finbyzreach',
        'description':'Used by connected Customer filters in contact segments. Select a linked Customer.',
    }]})
