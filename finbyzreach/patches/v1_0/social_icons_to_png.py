"""Gmail and Outlook do not show SVG images. Point saved emails at the hosted PNG icons (EM-08)."""
import hashlib
import re

import frappe

PATTERN = re.compile(r"(/assets/finbyzreach/email_builder/social/[a-z]+)\.svg")


def execute():
	for doctype in ("Email Template", "Email Template Master"):
		meta = frappe.get_meta(doctype)
		if not meta.has_field("response_html"):
			continue
		has_hash = meta.has_field("custom_builder_content_hash") or meta.has_field("builder_content_hash")
		hash_field = "custom_builder_content_hash" if meta.has_field("custom_builder_content_hash") else "builder_content_hash"
		for name, html in frappe.db.sql(
			f"select name, response_html from `tab{doctype}` where response_html like %s", ("%email_builder/social/%.svg%",)
		):
			fixed = PATTERN.sub(r"\1.png", html or "")
			if fixed == html:
				continue
			values = {"response_html": fixed}
			if has_hash:
				# The hash tells the builder the HTML was not edited by hand; keep it matching.
				values[hash_field] = hashlib.sha256(fixed.encode()).hexdigest()
			frappe.db.set_value(doctype, name, values, update_modified=False)
