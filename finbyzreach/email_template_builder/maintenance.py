from __future__ import annotations

"""Re-run stored visual templates through the current validator and compiler.

``response_html`` is compiled once, at save time, and then sent as-is. So a fix
to ``schema.py`` or ``compiler.py`` only reaches templates saved after it — every
template already in the database keeps whatever the old code produced.

Run this after any change to validation or compilation:

    bench --site <site> execute finbyzreach.email_template_builder.maintenance.recompile --kwargs "{'dry_run': True}"
    bench --site <site> execute finbyzreach.email_template_builder.maintenance.recompile
"""

import json

import frappe

from .api import _content_hash, _render_builder_request, _subject_source
from .constants import BUILDER_TARGET_DOCTYPES
from .targets import normalize_template_doctype


def recompile(dry_run=False, name=None, template_doctype=None):
	"""Recompile visual Email Templates and Email Template Masters.

	Only writes where the compiled HTML actually differs, so a no-op run leaves
	``modified`` untouched and the report stays readable.
	"""
	doctypes = (
		[normalize_template_doctype(template_doctype)]
		if template_doctype
		else sorted(BUILDER_TARGET_DOCTYPES)
	)

	report = []
	changed = 0
	for doctype in doctypes:
		filters = {"custom_builder_mode": "Visual"}
		if name:
			filters["name"] = name
		for row in frappe.get_all(doctype, filters=filters, pluck="name"):
			doc = frappe.get_doc(doctype, row)
			if not (doc.custom_builder_schema or "").strip():
				continue
			try:
				state = _render_builder_request(
					json.loads(doc.custom_builder_schema),
					{
						"subject": _subject_source(doc) or doc.subject or "",
						"preheader": doc.custom_preheader_text or "",
						"validate_dynamic_fields": 0,
					},
				)
			except Exception as exc:
				report.append(f"ERROR  {doctype} / {row}: {str(exc)[:120]}")
				continue

			compiled = state["compiled"]
			if compiled["html"] == doc.response_html:
				report.append(f"OK     {doctype} / {row} (unchanged)")
				continue

			changed += 1
			before_zero = "font-size:0px" in (doc.response_html or "")
			note = " [fixed invisible text]" if before_zero and "font-size:0px" not in compiled["html"] else ""
			report.append(f"{'WOULD  ' if dry_run else 'UPDATED'} {doctype} / {row}{note}")
			if dry_run:
				continue

			doc.response_html = compiled["html"]
			doc.custom_builder_schema = json.dumps(compiled["schema"], separators=(",", ":"))
			doc.custom_builder_content_hash = _content_hash(compiled["html"])
			doc.save(ignore_permissions=True)

	if not dry_run:
		frappe.db.commit()
	report.append(f"\n{changed} template(s) {'would change' if dry_run else 'updated'}")
	output = "\n".join(report)
	print(output)
	return output
