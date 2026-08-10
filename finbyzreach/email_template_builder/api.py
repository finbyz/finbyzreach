from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe.email.email_body import get_formatted_html
from frappe import _
from frappe.utils import cint, get_datetime, get_system_timezone, validate_email_address
from frappe.utils.jinja import validate_template

from .compiler import compile_schema
from .constants import MAX_COMPONENT_BYTES, MAX_METADATA_BYTES
from .reference_fields import (
	is_permitted_reference_path,
	link_target_doctype,
	permitted_reference_fields,
	reference_field_rows,
)
from .realtime import publish_builder_revision_created, publish_builder_saved
from .schema import validate_component, validate_schema
from .tokens import compile_tokens, token_fields, validate_semantic_tokens


def _require_designer():
	if not {"Email Designer", "System Manager"}.intersection(frappe.get_roles()):
		frappe.throw(_("The Email Designer role is required"), frappe.PermissionError)


def _template(name, ptype="read", for_update=False):
	_require_designer()
	doc = frappe.get_doc("Email Template", name, for_update=for_update)
	doc.check_permission(ptype)
	return doc


def _check_modified(doc, expected_modified):
	if not expected_modified:
		frappe.throw(_("The template version is required. Reload the builder and try again."), frappe.TimestampMismatchError)
	if str(doc.modified) != str(expected_modified):
		frappe.throw(_("This template changed in another window. Reload before continuing."), frappe.TimestampMismatchError)


def _payload(value, max_bytes=None, label="builder request payload"):
	if isinstance(value, dict):
		if max_bytes is not None and len(json.dumps(value, separators=(",", ":")).encode()) > max_bytes:
			frappe.throw(_("{0} is too large").format(label.title()))
		return dict(value)
	raw = "" if value is None else str(value)
	if max_bytes is not None and len(raw.encode()) > max_bytes:
		frappe.throw(_("{0} is too large").format(label.title()))
	try:
		parsed = json.loads(raw or "{}")
	except (TypeError, ValueError):
		frappe.throw(_("Invalid {0}").format(label))
	if not isinstance(parsed, dict):
		frappe.throw(_("{0} must be an object").format(label.title()))
	return parsed


def _metadata_payload(value):
	return _payload(value, max_bytes=MAX_METADATA_BYTES, label="builder metadata")


def _builder_timezone():
	return get_system_timezone() or "UTC"


def _timezone_payload(value):
	timezone = _builder_timezone()
	try:
		tzinfo = ZoneInfo(timezone)
	except ZoneInfoNotFoundError:
		timezone = "UTC"
		tzinfo = ZoneInfo("UTC")
	if not value:
		return {"creation": "", "creation_epoch": 0, "timezone": timezone}
	dt = get_datetime(value)
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=tzinfo)
	else:
		dt = dt.astimezone(tzinfo)
	return {"creation": dt.isoformat(), "creation_epoch": int(dt.timestamp() * 1000), "timezone": timezone}


def _permitted_reference_fields(doctype):
	return permitted_reference_fields(doctype)


def _reference_context(doctype, name=None):
	if not doctype:
		return {}
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("You do not have permission to inspect this DocType"), frappe.PermissionError)
	if name:
		doc = frappe.get_doc(doctype, name)
		doc.check_permission("read")
		values = frappe._dict({fieldname: doc.get(fieldname) for fieldname in _permitted_reference_fields(doctype)})
		values.update({"name": doc.name, "doctype": doc.doctype})
	else:
		values = frappe._dict(doctype=doctype)
	return frappe._dict({**values, "doc": values})


def _collect_token_fields(value):
	fields = set()
	if isinstance(value, dict):
		items = value.values()
	elif isinstance(value, list):
		items = value
	elif isinstance(value, str):
		return token_fields(value)
	else:
		return fields
	for item in items:
		fields.update(_collect_token_fields(item))
	return fields


def _validate_reference_usage(schema, subject, preheader, reference_doctype, validate_dynamic_fields=True):
	fields = _collect_token_fields(schema) | token_fields(subject) | token_fields(preheader)
	condition_fields = set()
	for section in schema.get("sections", []):
		visibility = section.get("visibility") or {}
		for condition in visibility.get("conditions") or []:
			fieldname = condition.get("fieldname") if isinstance(condition, dict) else None
			if fieldname:
				condition_fields.add(fieldname)
		for column in section.get("columns", []):
			for block in column.get("blocks", []):
				visibility = block.get("visibility") or {}
				for condition in visibility.get("conditions") or []:
					fieldname = condition.get("fieldname") if isinstance(condition, dict) else None
					if fieldname:
						condition_fields.add(fieldname)
	fields |= condition_fields
	if not validate_dynamic_fields:
		return
	if fields and not reference_doctype:
		frappe.throw(_("Choose a Reference DocType before validating personalization or record conditions."))
	if not reference_doctype:
		return
	denied = sorted(fieldname for fieldname in fields if not is_permitted_reference_path(reference_doctype, fieldname))
	if denied:
		frappe.local.response["builder_validation"] = {
			"code": "invalid_dynamic_fields",
			"reference_doctype": reference_doctype,
			"invalid_fields": denied,
		}
		frappe.throw(_("These dynamic fields are not readable for {0}: {1}").format(reference_doctype, ", ".join(denied)))


def _content_hash(value):
	return hashlib.sha256(str(value or "").encode()).hexdigest()


def _subject_source(doc):
	return doc.get("custom_builder_subject_source") or doc.subject or ""


def _compiled_subject(value):
	value = validate_semantic_tokens(str(value or ""))
	if len(value) > 140:
		frappe.throw(_("Email subjects cannot exceed 140 characters"))
	compiled = compile_tokens(value, "ebt")
	if len(compiled) > 140:
		frappe.throw(_("Subject personalization is too complex; use fewer or shorter merge fields"))
	return compiled


def _compile_builder_request(schema, metadata=None, *, fallback_subject="", reference_doctype=None, reference_name=None):
	metadata = _metadata_payload(metadata)
	preheader = validate_semantic_tokens(str(metadata.get("preheader") or "")[:500])
	subject_source = validate_semantic_tokens(str(metadata.get("subject") or fallback_subject or "")[:500])
	validated = validate_schema(schema)
	resolved_reference_doctype = str(reference_doctype if reference_doctype is not None else metadata.get("reference_doctype") or "").strip()
	resolved_reference_name = str(reference_name if reference_name is not None else metadata.get("preview_document") or "").strip()
	if not resolved_reference_doctype:
		resolved_reference_name = ""
	validate_dynamic_fields = bool(cint(metadata.get("validate_dynamic_fields", 1 if resolved_reference_doctype else 0)))
	context = frappe._dict()
	if resolved_reference_doctype:
		context = _reference_context(resolved_reference_doctype, resolved_reference_name or None)
	_validate_reference_usage(validated, subject_source, preheader, resolved_reference_doctype, validate_dynamic_fields)
	compiled = compile_schema(validated, preheader, normalized=True)
	compiled_subject = _compiled_subject(subject_source)
	validate_template(compiled_subject)
	validate_template(compiled["html"])
	return {
		"schema": validated,
		"compiled": compiled,
		"compiled_subject": compiled_subject,
		"subject_source": subject_source,
		"preheader": preheader,
		"reference_doctype": resolved_reference_doctype,
		"preview_document": resolved_reference_name,
		"validate_dynamic_fields": validate_dynamic_fields,
		"context": context,
	}


def _render_builder_request(schema, metadata=None, *, fallback_subject="", reference_doctype=None, reference_name=None):
	state = _compile_builder_request(
		schema,
		metadata,
		fallback_subject=fallback_subject,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)
	context = state["context"]
	state["subject"] = frappe.render_template(state["compiled_subject"], context)
	state["html_content"] = frappe.render_template(state["compiled"]["html"], context)
	state["plain_text"] = frappe.render_template(state["compiled"]["plain_text"], context)
	return state


def _revision_compiled(revision):
	schema = validate_schema(revision.schema_json)
	compiled = compile_schema(schema, revision.preheader, normalized=True)
	stored_html = revision.compiled_html or ""
	if not stored_html:
		frappe.throw(_("This revision has no compiled HTML to restore."))
	if revision.content_hash and revision.content_hash != _content_hash(stored_html):
		frappe.throw(_("This revision's compiled HTML does not match its stored hash."))
	issues = list(compiled.get("issues") or [])
	if _content_hash(compiled["html"]) != _content_hash(stored_html):
		issues.append(
			{
				"severity": "warning",
				"code": "revision_html_mismatch",
				"node_id": None,
				"message": _("This older revision uses stored HTML that differs from the current compiler output."),
			}
		)
	compiled["html"] = stored_html
	compiled["bytes"] = len(stored_html.encode())
	compiled["issues"] = issues
	compiled["warnings"] = [issue["message"] for issue in issues if issue.get("severity") == "warning"]
	compiled_subject = _compiled_subject(revision.subject)
	validate_template(compiled_subject)
	validate_template(compiled["html"])
	return schema, compiled, compiled_subject


def _normalized_component_payload(doc):
	definition = validate_component(doc.definition_json)
	return {
		"name": doc.name,
		"component_name": doc.component_name,
		"component_type": doc.component_type,
		"category": doc.category,
		"schema_version": doc.schema_version or 1,
		"definition": definition,
		"definition_json": json.dumps(definition, separators=(",", ":")),
	}


def _format_preview_html(subject, html_content):
	"""Render preview through Frappe's final raw-HTML email formatter.

	The visual compiler returns the source stored on Email Template. Actual sends go
	through Email Queue and Premailer, so builder preview should use the same final
	formatting path whenever the asset manifest is available.
	"""
	add_css = getattr(frappe.local, "bundled_assets", None) is not None
	return get_formatted_html(subject, html_content, raw_html=True, add_css=add_css)


def _manual_html_state(doc):
	mode = doc.get("custom_builder_mode") or "Raw HTML"
	current_html = doc.response_html if doc.use_html else doc.response
	has_content = bool((current_html or "").strip())
	stored_hash = doc.get("custom_builder_content_hash") or ""
	conflict = bool(mode == "Visual" and stored_hash and _content_hash(current_html) != stored_hash)
	return {
		"has_manual_html": bool(mode == "Raw HTML" and has_content),
		"html_conflict": conflict,
		"requires_overwrite_confirmation": bool((mode == "Raw HTML" and has_content) or conflict),
	}


@frappe.whitelist(methods=["POST"])
def create_visual_template(template_name, subject=None):
	_require_designer()
	frappe.has_permission("Email Template", "create", throw=True)
	template_name = str(template_name or "").strip()[:140]
	subject_source = validate_semantic_tokens(str(subject or template_name or "").strip()[:140])
	if not template_name:
		frappe.throw(_("Template name is required"))
	if not subject_source:
		frappe.throw(_("Subject is required"))
	if frappe.db.exists("Email Template", template_name):
		frappe.throw(_("Email Template {0} already exists").format(frappe.bold(template_name)))
	schema = validate_schema(None)
	compiled = compile_schema(schema, "", normalized=True)
	compiled_subject = _compiled_subject(subject_source)
	validate_template(compiled_subject)
	validate_template(compiled["html"])
	doc = frappe.get_doc({
		"doctype": "Email Template",
		"name": template_name,
		"subject": compiled_subject,
		"use_html": 1,
		"response_html": compiled["html"],
		"custom_builder_mode": "Visual",
		"custom_builder_schema": json.dumps(compiled["schema"], separators=(",", ":")),
		"custom_builder_schema_version": 1,
		"custom_builder_content_hash": _content_hash(compiled["html"]),
		"custom_builder_subject_source": subject_source,
	})
	doc.insert()
	return {"name": doc.name, "modified": doc.modified, "route": f"/builder?template={quote(doc.name, safe='')}"}


@frappe.whitelist(methods=["GET"])
def get_merge_fields(reference_doctype):
	_require_designer()
	if not reference_doctype or not frappe.has_permission(reference_doctype, "read"):
		frappe.throw(_("You do not have permission to inspect this DocType"), frappe.PermissionError)
	return reference_field_rows(reference_doctype)


@frappe.whitelist(methods=["GET"])
def get_link_merge_fields(reference_doctype, link_fieldname):
	"""Return one level of readable fields from a static Frappe Link.

	The root Link itself remains available as its record ID. Related fields are
	returned with a dotted path such as ``lead_owner.full_name``.
	"""
	_require_designer()
	if not reference_doctype or not frappe.has_permission(reference_doctype, "read"):
		frappe.throw(_("You do not have permission to inspect this DocType"), frappe.PermissionError)
	target_doctype = link_target_doctype(reference_doctype, str(link_fieldname or "").strip())
	if not target_doctype:
		frappe.throw(_("This Link field is unavailable or you cannot read its linked DocType"), frappe.PermissionError)
	return {
		"link_fieldname": str(link_fieldname or "").strip(),
		"target_doctype": target_doctype,
		"fields": reference_field_rows(target_doctype, prefix=str(link_fieldname or "").strip()),
	}


IMAGE_EXTENSIONS = (".apng", ".avif", ".gif", ".jpg", ".jpeg", ".png", ".webp")
IMAGE_FILE_TYPES = {"image", "png", "jpg", "jpeg", "gif", "webp", "avif", "apng"}


def _is_public_image_file(row):
	file_url = str(row.get("file_url") or "").strip()
	file_name = str(row.get("file_name") or "").strip()
	file_type = str(row.get("file_type") or "").strip().lower()
	if cint(row.get("is_private")) or not file_url or file_url.startswith("/private/") or "/private/files/" in file_url:
		return False
	return file_type in IMAGE_FILE_TYPES or file_url.lower().split("?", 1)[0].endswith(IMAGE_EXTENSIONS) or file_name.lower().endswith(IMAGE_EXTENSIONS)


def _image_file_payload(row, template_name):
	return {
		"name": row.get("name"),
		"file_name": row.get("file_name") or row.get("name"),
		"file_url": row.get("file_url"),
		"thumbnail_url": row.get("thumbnail_url") or row.get("file_url"),
		"file_size": cint(row.get("file_size") or 0),
		"file_type": row.get("file_type") or "",
		"attached_to_doctype": row.get("attached_to_doctype") or "",
		"attached_to_name": row.get("attached_to_name") or "",
		"is_attached_to_template": bool(row.get("attached_to_doctype") == "Email Template" and row.get("attached_to_name") == template_name),
	}


@frappe.whitelist(methods=["GET", "POST"])
def list_builder_images(template_name, scope="template", search="", start=0, page_length=24):
	_template(template_name, "read")
	frappe.has_permission("File", "read", throw=True)
	scope = str(scope or "template").strip().lower()
	search = str(search or "").strip()[:120]
	page_length = max(1, min(cint(page_length) or 24, 60))
	start = max(0, cint(start))
	filters = {"is_folder": 0, "is_private": 0}
	if scope != "public":
		filters.update({"attached_to_doctype": "Email Template", "attached_to_name": template_name})
	if search:
		filters["file_name"] = ["like", f"%{search}%"]

	fields = ["name", "file_name", "file_url", "thumbnail_url", "file_size", "file_type", "is_private", "attached_to_doctype", "attached_to_name"]
	rows = []
	seen_images = 0
	row_start = 0
	batch_size = min(240, max(80, page_length * 4))
	has_more = False
	while len(rows) < page_length + 1:
		batch = frappe.get_list(
			"File",
			filters=filters,
			fields=fields,
			order_by="modified desc",
			offset=row_start,
			limit=batch_size,
		)
		if not batch:
			break
		for row in batch:
			if not _is_public_image_file(row):
				continue
			if seen_images < start:
				seen_images += 1
				continue
			rows.append(_image_file_payload(row, template_name))
			seen_images += 1
			if len(rows) >= page_length + 1:
				has_more = True
				break
		if has_more or len(batch) < batch_size:
			break
		row_start += len(batch)

	return {
		"rows": rows[:page_length],
		"has_more": has_more,
		"next_start": start + min(len(rows), page_length),
		"start": start,
		"page_length": page_length,
	}


@frappe.whitelist(methods=["POST"])
def attach_builder_image(template_name, file_name):
	_template(template_name, "write", for_update=True)
	if not file_name:
		frappe.throw(_("Choose an image first"))
	file_doc = frappe.get_doc("File", file_name)
	file_doc.check_permission("read")
	row = file_doc.as_dict()
	if not _is_public_image_file(row):
		frappe.throw(_("Only public image files can be used in email templates"))
	if file_doc.attached_to_doctype == "Email Template" and file_doc.attached_to_name == template_name:
		return _image_file_payload(row, template_name)
	existing = frappe.db.get_value(
		"File",
		{
			"attached_to_doctype": "Email Template",
			"attached_to_name": template_name,
			"file_url": file_doc.file_url,
			"is_private": 0,
		},
		"name",
	)
	if existing:
		return _image_file_payload(frappe.get_doc("File", existing).as_dict(), template_name)
	attached = frappe.get_doc(
		{
			"doctype": "File",
			"attached_to_doctype": "Email Template",
			"attached_to_name": template_name,
			"folder": file_doc.folder or "Home/Attachments",
			"file_name": file_doc.file_name,
			"file_url": file_doc.file_url,
			"is_private": 0,
		}
	)
	attached.insert()
	return _image_file_payload(attached.as_dict(), template_name)


@frappe.whitelist(methods=["GET"])
def load_builder(template_name):
	doc = _template(template_name)
	state = _manual_html_state(doc)
	mode = doc.get("custom_builder_mode") or "Raw HTML"
	schema_status = "valid"
	schema_error = ""
	can_save = True
	try:
		schema = validate_schema(doc.get("custom_builder_schema"))
	except Exception as exc:
		if mode == "Visual":
			schema_status = "invalid"
			schema_error = str(exc)
			can_save = False
		schema = validate_schema(None)
	return {
		"name": doc.name,
		"subject": _subject_source(doc),
		"mode": mode,
		"schema": schema,
		"schema_status": schema_status,
		"schema_error": schema_error,
		"can_save": can_save,
		"schema_version": doc.get("custom_builder_schema_version") or 1,
		"content_hash": doc.get("custom_builder_content_hash") or "",
		"preheader": doc.get("custom_preheader_text") or "",
		"reference_doctype": doc.get("custom_reference_doctype") or "",
		"preview_document": doc.get("custom_preview_document") or "",
		"validate_dynamic_fields": bool(doc.get("custom_reference_doctype")),
		"modified": doc.modified,
		"timezone": _builder_timezone(),
		"html": doc.response_html if doc.use_html else doc.response,
		**state,
	}


def _revision(template, compiled, save_note=None):
	last = frappe.db.get_value("Email Builder Revision", {"template": template.name}, "revision_number", order_by="revision_number desc") or 0
	revision = frappe.get_doc(
		{
			"doctype": "Email Builder Revision",
			"template": template.name,
			"revision_number": int(last) + 1,
			"content_hash": _content_hash(compiled["html"]),
			"subject": _subject_source(template),
			"preheader": template.get("custom_preheader_text") or "",
			"schema_json": json.dumps(compiled["schema"], separators=(",", ":")),
			"compiled_html": compiled["html"],
			"html_bytes": len(compiled["html"].encode()),
			"save_note": str(save_note or "")[:500],
		}
	)
	revision.insert(ignore_permissions=True)
	names = frappe.get_all(
		"Email Builder Revision",
		filters={"template": template.name},
		pluck="name",
		order_by="revision_number desc",
		limit=0,
	)
	for name in names[20:]:
		try:
			old = frappe.get_doc("Email Builder Revision", name)
			old.flags.email_builder_retention = True
			old.delete(ignore_permissions=True)
		except Exception:
			frappe.log_error(title="Email Builder revision retention failed", message=frappe.get_traceback())
	return revision


def _revision_changed(template, compiled):
	last = frappe.get_all(
		"Email Builder Revision",
		filters={"template": template.name},
		fields=["content_hash", "subject", "preheader"],
		order_by="revision_number desc",
		limit=1,
	)
	if not last:
		return True
	return any(
		(
			last[0].content_hash != _content_hash(compiled["html"]),
			last[0].subject != _subject_source(template),
			last[0].preheader != (template.get("custom_preheader_text") or ""),
		)
	)


@frappe.whitelist(methods=["POST"])
def save_builder(template_name, expected_modified=None, schema=None, metadata=None, save_note=None, allow_overwrite_html=0, client_id=None):
	# Hold the template row while compiling and saving. This serializes visual-builder
	# mutations so two requests with the same version cannot both pass the version check.
	doc = _template(template_name, "write", for_update=True)
	_check_modified(doc, expected_modified)
	manual_state = _manual_html_state(doc)
	if manual_state["requires_overwrite_confirmation"] and not cint(allow_overwrite_html):
		frappe.throw(_("Confirm that the visual builder may replace the current manual HTML."))
	state = _compile_builder_request(schema, metadata, fallback_subject=_subject_source(doc))
	validated = state["schema"]
	compiled = state["compiled"]
	compiled_subject = state["compiled_subject"]
	subject_source = state["subject_source"]
	preheader = state["preheader"]
	reference_doctype = state["reference_doctype"]
	preview_document = state["preview_document"]
	validate_dynamic_fields = state["validate_dynamic_fields"]
	doc.subject = compiled_subject
	doc.custom_builder_subject_source = subject_source
	doc.custom_builder_mode = "Visual"
	doc.custom_builder_schema = json.dumps(compiled["schema"], separators=(",", ":"))
	doc.custom_builder_schema_version = 1
	doc.custom_builder_content_hash = _content_hash(compiled["html"])
	doc.custom_preheader_text = preheader
	doc.custom_reference_doctype = reference_doctype
	doc.custom_preview_document = preview_document
	doc.use_html = 1
	doc.response_html = compiled["html"]
	doc.save()
	revision = _revision(doc, compiled, save_note) if _revision_changed(doc, compiled) else None
	publish_builder_saved(doc, revision=revision, client_id=client_id)
	publish_builder_revision_created(doc.name, revision, client_id=client_id)
	return {
		"name": doc.name,
		"modified": doc.modified,
		"revision": revision.name if revision else None,
		"revision_number": revision.revision_number if revision else None,
		"content_hash": doc.custom_builder_content_hash,
		"bytes": compiled["bytes"],
		"warnings": compiled["warnings"],
		"issues": compiled["issues"],
		"schema": compiled["schema"],
		"metadata": {
			"subject": subject_source,
			"preheader": preheader,
			"reference_doctype": reference_doctype,
			"preview_document": preview_document,
			"validate_dynamic_fields": validate_dynamic_fields,
		},
	}


@frappe.whitelist(methods=["POST"])
def render_preview(schema, metadata=None, reference_doctype=None, reference_name=None):
	_require_designer()
	state = _render_builder_request(
		schema,
		metadata,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)
	formatted_html = _format_preview_html(state["subject"], state["html_content"])
	return {
		"subject": state["subject"],
		"html": formatted_html,
		"plain_text": state["plain_text"],
		"warnings": state["compiled"]["warnings"],
		"issues": state["compiled"]["issues"],
		"bytes": len(formatted_html.encode()),
	}


def _check_test_email_rate_limit():
	window = 600
	window_number = int(time.time()) // window
	key = frappe.cache.make_key(f"email-builder-test:{frappe.session.user}:{window_number}")
	if not frappe.cache.get(key):
		frappe.cache.setex(key, window, 0)
	if frappe.cache.incrby(key, 1) > 10:
		frappe.throw(_("You can send at most 10 test emails every 10 minutes."), frappe.RateLimitExceededError)


@frappe.whitelist(methods=["POST"])
def send_test_email(template_name, schema, metadata=None, recipient=None, reference_doctype=None, reference_name=None):
	template = _template(template_name, "email")
	recipient = str(recipient or "").strip()
	if not recipient:
		frappe.throw(_("A test recipient is required"))
	if any(character in recipient for character in (",", ";", "\n", "\r")):
		frappe.throw(_("Send a test to one email address at a time"))
	validate_email_address(recipient, throw=True)
	_check_test_email_rate_limit()
	state = _render_builder_request(
		schema,
		metadata,
		fallback_subject=_subject_source(template),
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)
	frappe.sendmail(
		recipients=[recipient],
		subject=state["subject"],
		content=state["html_content"],
		raw_html=True,
		delayed=True,
		reference_doctype="Email Template",
		reference_name=template.name,
	)
	return {"status": "queued", "recipient": recipient, "warnings": state["compiled"]["warnings"], "issues": state["compiled"]["issues"]}


@frappe.whitelist(methods=["GET"])
def list_components(start=0, page_length=20, category=None):
	_require_designer()
	frappe.has_permission("Email Builder Component", "read", throw=True)
	filters = {"enabled": 1}
	if category:
		filters["category"] = category
	return frappe.get_list(
		"Email Builder Component",
		filters=filters,
		fields=["name", "component_name", "component_type", "category", "schema_version", "modified"],
		offset=max(0, cint(start)),
		limit=max(1, min(cint(page_length) or 20, 50)),
		order_by="modified desc",
	)


@frappe.whitelist(methods=["GET", "POST"])
def load_component(component_name):
	_require_designer()
	frappe.has_permission("Email Builder Component", "read", throw=True)
	doc = frappe.get_doc("Email Builder Component", component_name)
	doc.check_permission("read")
	if not cint(doc.enabled):
		frappe.throw(_("This saved component is disabled."))
	return _normalized_component_payload(doc)


@frappe.whitelist(methods=["GET"])
def list_revisions(template_name, start=0, page_length=50):
	_template(template_name, "read")
	frappe.has_permission("Email Builder Revision", "read", throw=True)
	revisions = frappe.get_list(
		"Email Builder Revision",
		filters={"template": template_name},
		fields=["name", "revision_number", "subject", "preheader", "save_note", "creation", "content_hash", "html_bytes"],
		offset=max(0, cint(start)),
		limit=max(1, min(cint(page_length) or 50, 50)),
		order_by="revision_number desc",
	)
	for revision in revisions:
		revision["html_bytes"] = cint(revision.get("html_bytes") or 0)
		revision["content_hash"] = (revision.get("content_hash") or "")[:12]
		revision.update(_timezone_payload(revision.get("creation")))
	return revisions


@frappe.whitelist(methods=["POST"])
def save_component(component):
	_require_designer()
	component = _payload(component, max_bytes=MAX_COMPONENT_BYTES, label="builder component")
	validated = validate_component(component)
	name = component.get("name")
	if name:
		doc = frappe.get_doc("Email Builder Component", name)
		doc.check_permission("write")
	else:
		frappe.has_permission("Email Builder Component", "create", throw=True)
		doc = frappe.new_doc("Email Builder Component")
	doc.component_name = str(component.get("component_name") or "")[:140]
	if not doc.component_name:
		frappe.throw(_("Component name is required"))
	doc.component_type = validated["component_type"]
	doc.category = validated["category"]
	doc.enabled = cint(component.get("enabled", 1))
	doc.definition_json = json.dumps(validated, separators=(",", ":"))
	doc.save()
	return {"name": doc.name, "component_name": doc.component_name, "definition": validated}


@frappe.whitelist(methods=["POST"])
def render_revision_preview(template_name, revision_name):
	_template(template_name, "read")
	revision = frappe.get_doc("Email Builder Revision", revision_name)
	revision.check_permission("read")
	if revision.template != template_name:
		frappe.throw(_("The revision does not belong to this template"))
	schema, compiled, compiled_subject = _revision_compiled(revision)
	template = frappe.get_doc("Email Template", template_name)
	context = _reference_context(template.get("custom_reference_doctype"), template.get("custom_preview_document"))
	subject = frappe.render_template(compiled_subject, context)
	html_content = frappe.render_template(compiled["html"], context)
	formatted_html = _format_preview_html(subject, html_content)
	return {
		"revision_number": revision.revision_number,
		"subject": subject,
		"preheader": frappe.render_template(revision.preheader or "", context),
		"html": formatted_html,
		"plain_text": frappe.render_template(compiled["plain_text"], context),
		"warnings": compiled["warnings"],
		"issues": compiled["issues"],
		"bytes": len(formatted_html.encode()),
		**_timezone_payload(revision.creation),
		"schema": schema,
	}


@frappe.whitelist(methods=["POST"])
def restore_revision(template_name, revision_name, expected_modified=None, client_id=None):
	doc = _template(template_name, "write", for_update=True)
	_check_modified(doc, expected_modified)
	revision = frappe.get_doc("Email Builder Revision", revision_name)
	revision.check_permission("read")
	if revision.template != template_name:
		frappe.throw(_("The revision does not belong to this template"))
	schema, compiled, compiled_subject = _revision_compiled(revision)
	_validate_reference_usage(
		schema,
		revision.subject,
		revision.preheader,
		doc.get("custom_reference_doctype") or "",
		bool(doc.get("custom_reference_doctype")),
	)
	doc.custom_builder_mode = "Visual"
	doc.custom_builder_schema = json.dumps(schema, separators=(",", ":"))
	doc.custom_builder_schema_version = 1
	doc.custom_builder_content_hash = _content_hash(compiled["html"])
	doc.custom_preheader_text = revision.preheader
	doc.custom_builder_subject_source = revision.subject
	doc.subject = compiled_subject
	doc.use_html = 1
	doc.response_html = compiled["html"]
	doc.save()
	new_revision = _revision(doc, compiled, _("Restored from revision {0}").format(revision.revision_number))
	publish_builder_saved(doc, revision=new_revision, client_id=client_id)
	publish_builder_revision_created(doc.name, new_revision, client_id=client_id)
	return {"name": doc.name, "modified": doc.modified, "revision": new_revision.name, "revision_number": new_revision.revision_number}


@frappe.whitelist(methods=["POST"])
def switch_to_raw_html(template_name, expected_modified=None):
	doc = _template(template_name, "write", for_update=True)
	_check_modified(doc, expected_modified)
	doc.custom_builder_mode = "Raw HTML"
	doc.save()
	return {"name": doc.name, "modified": doc.modified, "mode": "Raw HTML"}
