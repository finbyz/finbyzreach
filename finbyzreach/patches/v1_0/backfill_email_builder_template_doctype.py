import frappe


def execute():
	for doctype in (
		"Email Builder Revision",
		"Email Builder AI Chat",
		"Email Builder AI Run",
	):
		if not frappe.db.exists("DocType", doctype):
			continue
		table = frappe.qb.DocType(doctype)
		(
			frappe.qb.update(table)
			.set(table.template_doctype, "Email Template")
			.where((table.template_doctype.isnull()) | (table.template_doctype == ""))
		).run()
