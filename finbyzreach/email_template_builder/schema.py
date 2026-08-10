from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from urllib.parse import urlparse

import frappe
from frappe import _

from .constants import (
	ALIGNMENTS,
	BLOCK_TYPES,
	BORDER_STYLES,
	BUTTON_ACTIONS,
	COMPONENT_CATEGORIES,
	COMPONENT_TYPES,
	CONDITION_OPERATORS,
	CSS_COLOR,
	CSS_LENGTH,
	DEFAULT_SETTINGS,
	DEVICE_VALUES,
	FONT_FAMILY,
	FONT_STYLES,
	FONT_WEIGHTS,
	LAYOUTS,
	MOBILE_STACKING,
	MAX_BLOCKS,
	MAX_CODE_BYTES,
	MAX_COMPONENT_BYTES,
	MAX_SCHEMA_BYTES,
	NODE_ID,
	REFERENCE_FIELD_PATH,
	SAFE_URL_SCHEMES,
	SCHEMA_VERSION,
	SOCIAL_PLATFORMS,
	TEXT_DECORATIONS,
	VERTICAL_ALIGNMENTS,
)
from .sanitizer import sanitize_code_html, sanitize_rich_html
from .tokens import is_semantic_token, validate_semantic_tokens


def parse_json(value, label="builder schema", max_bytes=None) -> dict:
	if isinstance(value, dict):
		return deepcopy(value)
	if not value:
		return {"version": SCHEMA_VERSION, "settings": dict(DEFAULT_SETTINGS), "sections": []}
	if max_bytes is not None and len(str(value).encode()) > max_bytes:
		frappe.throw(_("{0} is too large").format(label.title()))
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError) as exc:
		frappe.throw(_("Invalid {0}: {1}").format(label, exc))
	if not isinstance(parsed, dict):
		frappe.throw(_("{0} must be an object").format(label))
	return parsed


def _node_id(value):
	value = str(value or frappe.generate_hash(length=10))
	if not NODE_ID.fullmatch(value):
		frappe.throw(_("Builder node IDs may contain only letters, numbers, underscores, and hyphens"))
	return value


def _css(value, kind="length", default="0px"):
	value = str(value or default).strip()
	pattern = CSS_COLOR if kind == "color" else CSS_LENGTH
	if not pattern.fullmatch(value):
		frappe.throw(_("Unsupported CSS value: {0}").format(value))
	return value


def _font_family(value):
	value = str(value or DEFAULT_SETTINGS["font_family"]).strip()
	if not FONT_FAMILY.fullmatch(value):
		frappe.throw(_("Unsupported email font family"))
	return value


def _url(value, allow_full_token=False):
	value = validate_semantic_tokens(str(value or "").strip())
	if value and not value.startswith(SAFE_URL_SCHEMES) and not (allow_full_token and is_semantic_token(value)):
		frappe.throw(_("Only HTTP(S), mail, phone, SMS, anchors, or relative URLs are allowed"))
	return value


def _is_private_url(value):
	return urlparse(str(value or "")).path.startswith("/private")


def _visibility(value):
	if not value:
		return {"device": "both", "match": "all", "conditions": []}
	if not isinstance(value, dict):
		frappe.throw(_("Visibility must be an object"))
	device = value.get("device", "both")
	if device not in DEVICE_VALUES:
		frappe.throw(_("Invalid visibility device"))
	match = value.get("match", "all")
	if match not in {"all", "any"}:
		frappe.throw(_("Visibility match must be all or any"))
	conditions = value.get("conditions") or []
	if not isinstance(conditions, list) or len(conditions) > 5:
		frappe.throw(_("An item can have at most five visibility conditions"))
	normalized = []
	for condition in conditions:
		if not isinstance(condition, dict):
			frappe.throw(_("Visibility conditions must be objects"))
		fieldname = str(condition.get("fieldname") or "").strip()
		operator = condition.get("operator")
		if not REFERENCE_FIELD_PATH.fullmatch(fieldname):
			frappe.throw(_("Invalid visibility field"))
		if operator not in CONDITION_OPERATORS:
			frappe.throw(_("Invalid visibility operator"))
		normalized.append({"fieldname": fieldname, "operator": operator, "value": str(condition.get("value") or "")[:500]})
	return {"device": device, "match": match, "conditions": normalized}


def _spacing(style):
	style = style if isinstance(style, dict) else {}
	result = {side: _css(style.get(side), default="0px") for side in ("top", "right", "bottom", "left")}
	if "auto" in result.values():
		frappe.throw(_("Spacing values cannot use auto"))
	return result


def _style(style):
	style = style if isinstance(style, dict) else {}
	result = {"background": _css(style.get("background"), "color", "transparent")}
	result["padding"] = _spacing(style.get("padding"))
	result["margin"] = _spacing(style.get("margin"))
	for key in ("color", "font_color", "button_background", "button_text_color", "border_color"):
		if style.get(key):
			result[key] = _css(style[key], "color")
	for key in ("font_size", "line_height", "width", "height", "border_width", "radius", "button_padding_x", "button_padding_y"):
		if style.get(key) not in (None, ""):
			result[key] = _css(style[key])
			if result[key] == "auto" and key not in {"width", "height"}:
				frappe.throw(_("The CSS value auto is not supported for {0}").format(key.replace("_", " ")))
	if style.get("align") is not None:
		result["align"] = style["align"] if style["align"] in ALIGNMENTS else "left"
	if style.get("font_family"):
		result["font_family"] = _font_family(style["font_family"])
	if style.get("font_weight") is not None:
		result["font_weight"] = style["font_weight"] if str(style["font_weight"]) in FONT_WEIGHTS else "normal"
	if style.get("font_style") is not None:
		result["font_style"] = style["font_style"] if style["font_style"] in FONT_STYLES else "normal"
	if style.get("text_decoration") is not None:
		result["text_decoration"] = style["text_decoration"] if style["text_decoration"] in TEXT_DECORATIONS else "none"
	if style.get("border_style") is not None:
		result["border_style"] = style["border_style"] if style["border_style"] in BORDER_STYLES else "solid"
	return result


def _bounded_int(value, default, minimum, maximum):
	try:
		value = int(value if value not in (None, "") else default)
	except (TypeError, ValueError):
		frappe.throw(_("A numeric builder value is invalid"))
	return max(minimum, min(maximum, value))


def _validate_block(block):
	if not isinstance(block, dict) or block.get("type") not in BLOCK_TYPES:
		frappe.throw(_("Unsupported email builder block"))
	type_ = block["type"]
	content = block.get("content") if isinstance(block.get("content"), dict) else {}
	normalized = {
		"id": _node_id(block.get("id")),
		"type": type_,
		"style": _style(block.get("style")),
		"visibility": _visibility(block.get("visibility")),
		"content": {},
	}
	out = normalized["content"]

	if type_ == "text":
		out["html"] = sanitize_rich_html(str(content.get("html") or "")[:100_000])
		out["tag"] = content.get("tag") if content.get("tag") in {"p", "h1", "h2", "h3"} else "p"
	elif type_ == "image":
		out["src"] = _url(content.get("src"))
		if _is_private_url(out["src"]):
			frappe.throw(_("Email images must use public files"))
		out["alt"] = validate_semantic_tokens(str(content.get("alt") or "")[:500])
		out["decorative"] = bool(content.get("decorative"))
		out["href"] = _url(content.get("href"), allow_full_token=True)
		for key in ("width", "height"):
			if content.get(key) not in (None, ""):
				out[key] = _bounded_int(content[key], 1, 1, 2000)
		out["preserve_aspect_ratio"] = bool(content.get("preserve_aspect_ratio", True))
	elif type_ == "button":
		out["text"] = validate_semantic_tokens(str(content.get("text") or "Button")[:500])
		action = content.get("action") or "url"
		if action not in BUTTON_ACTIONS:
			frappe.throw(_("Unsupported button action"))
		out["action"] = action
		href = str(content.get("href") or "").strip()
		if action == "email" and href and ("{{" in href or "@" in href) and not href.startswith("mailto:"):
			href = f"mailto:{href}"
		elif action == "telephone" and href and ("{{" in href or re.fullmatch(r"[+0-9(). -]{3,40}", href)) and not href.startswith("tel:"):
			href = f"tel:{href}"
		elif action == "sms" and href and ("{{" in href or re.fullmatch(r"[+0-9(). -]{3,40}", href)) and not href.startswith("sms:"):
			href = f"sms:{href}"
		out["href"] = _url(href, allow_full_token=True)
		if action == "file" and _is_private_url(out["href"]):
			frappe.throw(_("Email file buttons must use public files"))
		out["full_width"] = bool(content.get("full_width"))
	elif type_ == "divider":
		out["style"] = content.get("style") if content.get("style") in BORDER_STYLES else "solid"
		out["thickness"] = _bounded_int(content.get("thickness"), 1, 1, 20)
	elif type_ == "spacer":
		out["height"] = _bounded_int(content.get("height"), 24, 1, 300)
	elif type_ == "social":
		items = content.get("items") or []
		if not isinstance(items, list) or len(items) > 12:
			frappe.throw(_("Social links must be a list of at most twelve items"))
		out["items"] = []
		for item in items:
			if not isinstance(item, dict):
				continue
			platform = item.get("platform") if item.get("platform") in SOCIAL_PLATFORMS else "Website"
			label = str(item.get("label") or platform).strip()[:80]
			out["items"].append({"platform": platform, "href": _url(item.get("href"), allow_full_token=True), "label": label})
		out["display"] = content.get("display") if content.get("display") in {"icon", "text", "both"} else "icon"
		out["icon_shape"] = content.get("icon_shape") if content.get("icon_shape") in {"square", "rounded", "circle"} else "circle"
		out["icon_size"] = _bounded_int(content.get("icon_size"), 24, 12, 64)
		out["item_spacing"] = _bounded_int(content.get("item_spacing"), 8, 0, 40)
	elif type_ == "preview_url":
		out["text"] = validate_semantic_tokens(str(content.get("text") or "View this email in your browser")[:200])
	elif type_ == "code":
		code = str(content.get("html") or "")
		if len(code.encode()) > MAX_CODE_BYTES:
			frappe.throw(_("Restricted code block is too large"))
		out["html"] = sanitize_code_html(code)
	return normalized


def _validate_section(section, seen_ids):
	if not isinstance(section, dict):
		frappe.throw(_("Sections must be objects"))
	section_id = _node_id(section.get("id"))
	if section_id in seen_ids:
		frappe.throw(_("Duplicate builder node ID"))
	seen_ids.add(section_id)
	layout = section.get("layout") or "1"
	if layout not in LAYOUTS:
		frappe.throw(_("Unsupported column layout: {0}").format(layout))
	columns = section.get("columns") or []
	if not isinstance(columns, list) or len(columns) != len(LAYOUTS[layout]):
		frappe.throw(_("Layout {0} requires {1} columns").format(layout, len(LAYOUTS[layout])))
	column_widths = section.get("column_widths")
	if column_widths in (None, []):
		column_widths = list(LAYOUTS[layout])
	if not isinstance(column_widths, list) or len(column_widths) != len(columns):
		frappe.throw(_("Column widths must match the number of columns"))
	try:
		column_widths = [float(width) for width in column_widths]
	except (TypeError, ValueError):
		frappe.throw(_("Column widths must be numbers"))
	if any(not math.isfinite(width) for width in column_widths):
		frappe.throw(_("Column widths must be finite numbers"))
	if len(column_widths) > 1 and any(width < 5 or width > 95 for width in column_widths):
		frappe.throw(_("Each column width must be between 5% and 95%"))
	total_width = sum(column_widths)
	if not 99.5 <= total_width <= 100.5:
		frappe.throw(_("Column widths must total 100%"))
	column_widths = [round(width * 100 / total_width, 3) for width in column_widths]
	column_widths[-1] = round(column_widths[-1] + 100 - sum(column_widths), 3)
	normalized_columns = []
	for column in columns:
		if not isinstance(column, dict):
			frappe.throw(_("Columns must be objects"))
		column_id = _node_id(column.get("id"))
		if column_id in seen_ids:
			frappe.throw(_("Duplicate builder node ID"))
		seen_ids.add(column_id)
		blocks = column.get("blocks") or []
		if not isinstance(blocks, list):
			frappe.throw(_("Column blocks must be a list"))
		normalized_blocks = [_validate_block(block) for block in blocks]
		for block in normalized_blocks:
			if block["id"] in seen_ids:
				frappe.throw(_("Duplicate builder node ID"))
			seen_ids.add(block["id"])
		normalized_columns.append({"id": column_id, "style": _style(column.get("style")), "blocks": normalized_blocks})
	normalized = {
		"id": section_id,
		"layout": layout,
		"column_widths": column_widths,
		"vertical_align": section.get("vertical_align") if section.get("vertical_align") in VERTICAL_ALIGNMENTS else "top",
		"mobile_stack": section.get("mobile_stack") if section.get("mobile_stack") in MOBILE_STACKING else "stack",
		"visibility": _visibility(section.get("visibility")),
		"style": _style(section.get("style")),
		"columns": normalized_columns,
	}
	# Optional reference to the saved Email Builder Component this row came from.
	# Used purely by the UI to decide whether to offer per-row AI editing.
	saved_component = section.get("saved_component")
	if saved_component and isinstance(saved_component, str):
		normalized["saved_component"] = saved_component[:140]
	return normalized


def validate_schema(value) -> dict:
	schema = parse_json(value, max_bytes=MAX_SCHEMA_BYTES)
	if schema.get("version", SCHEMA_VERSION) != SCHEMA_VERSION:
		frappe.throw(_("Unsupported builder schema version"))
	settings = dict(DEFAULT_SETTINGS)
	if schema.get("settings") and not isinstance(schema["settings"], dict):
		frappe.throw(_("Builder settings must be an object"))
	settings.update(schema.get("settings") or {})
	settings["content_width"] = _bounded_int(settings.get("content_width"), 600, 320, 900)
	for key in ("body_background", "content_background", "text_color", "link_color", "button_background", "button_text_color"):
		settings[key] = _css(settings.get(key), "color")
	for key in ("font_size", "button_radius", "section_padding"):
		settings[key] = _css(settings.get(key))
		if settings[key] == "auto":
			frappe.throw(_("The CSS value auto is not supported for {0}").format(key.replace("_", " ")))
	settings["font_family"] = _font_family(settings.get("font_family"))
	settings["link_decoration"] = settings.get("link_decoration") if settings.get("link_decoration") in {"none", "underline"} else "underline"
	sections = schema.get("sections") or []
	if not isinstance(sections, list):
		frappe.throw(_("Builder sections must be a list"))
	seen_ids = set()
	normalized = {
		"version": SCHEMA_VERSION,
		"settings": settings,
		"sections": [_validate_section(section, seen_ids) for section in sections],
	}
	count = sum(len(column["blocks"]) for section in normalized["sections"] for column in section["columns"])
	if count > MAX_BLOCKS:
		frappe.throw(_("A template can contain at most {0} blocks").format(MAX_BLOCKS))
	if len(json.dumps(normalized, separators=(",", ":")).encode()) > MAX_SCHEMA_BYTES:
		frappe.throw(_("Builder schema is too large"))
	return normalized


def validate_component(value) -> dict:
	component = parse_json(value, "component", max_bytes=MAX_COMPONENT_BYTES)
	if component.get("component_type") not in COMPONENT_TYPES:
		frappe.throw(_("Invalid component type"))
	if component.get("category") not in COMPONENT_CATEGORIES:
		frappe.throw(_("Invalid component category"))
	definition = component.get("definition")
	if component["component_type"] == "Block":
		definition = _validate_block(definition)
	else:
		definition = _validate_section(definition, set())
	normalized = {
		"component_type": component["component_type"],
		"category": component["category"],
		"definition": definition,
	}
	if len(json.dumps(normalized, separators=(",", ":")).encode()) > MAX_COMPONENT_BYTES:
		frappe.throw(_("Component is too large"))
	return normalized
