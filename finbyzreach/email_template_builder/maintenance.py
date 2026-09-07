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

from .api import _compiled_subject, _content_hash, _render_builder_request, _subject_source


def recompile(dry_run=False, name=None):
	"""Recompile every visual-mode Email Template, or just ``name``.

	Only writes where the compiled HTML actually differs, so a no-op run leaves
	``modified`` untouched and the report stays readable.
	"""
	filters = {"custom_builder_mode": "Visual"}
	if name:
		filters["name"] = name

	report = []
	changed = 0
	for row in frappe.get_all("Email Template", filters=filters, pluck="name"):
		doc = frappe.get_doc("Email Template", row)
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
			report.append(f"ERROR  {row}: {str(exc)[:120]}")
			continue

		compiled = state["compiled"]
		if compiled["html"] == doc.response_html:
			report.append(f"OK     {row} (unchanged)")
			continue

		changed += 1
		before_zero = "font-size:0px" in (doc.response_html or "")
		note = " [fixed invisible text]" if before_zero and "font-size:0px" not in compiled["html"] else ""
		report.append(f"{'WOULD  ' if dry_run else 'UPDATED'} {row}{note}")
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
