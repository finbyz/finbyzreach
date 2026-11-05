from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    fields = [dict(fieldname='custom_segment_permissions_section',fieldtype='Section Break',label='Segments',insert_after='roles',permlevel=1)]
    previous = fields[0]['fieldname']
    for name,label,default in [('permissions_enabled','Use specific segment permissions','0'),('read','Read segments','1'),('edit','Edit segments and export','0'),('delete','Delete segments','0')]:
        fieldname='custom_segment_'+name
        fields.append(dict(fieldname=fieldname,fieldtype='Check',label=label,default=default,insert_after=previous,module='Finbyzreach',permlevel=1))
        previous=fieldname
    create_custom_fields({'User':fields})
