"""Gmail and Outlook do not open sms: links. Point saved SMS buttons at the open_sms page (literal numbers only)."""
import hashlib
import html as html_lib
import re

import frappe
from frappe.utils import get_url

PATTERN = re.compile(r'href="sms:([^"{}]*)"')


def execute():
	from finbyzreach.email_template_builder.compiler import sms_landing_url

	def replace(match):
		return 'href="%s"' % html_lib.escape(sms_landing_url("sms:" + html_lib.unescape(match.group(1))), quote=True)

	for doctype in ("Email Template", "Email Template Master"):
		meta = frappe.get_meta(doctype)
		if not meta.has_field("response_html"):
			continue
		hash_field = "custom_builder_content_hash" if meta.has_field("custom_builder_content_hash") else None
		for name, content in frappe.db.sql(f"select name, response_html from `tab{doctype}` where response_html like %s", ('%href="sms:%',)):
			fixed = PATTERN.sub(replace, content or "")
			if fixed == content:
				continue
			values = {"response_html": fixed}
			if hash_field:
				values[hash_field] = hashlib.sha256(fixed.encode()).hexdigest()
			frappe.db.set_value(doctype, name, values, update_modified=False)
