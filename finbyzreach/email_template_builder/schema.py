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


NAMED_COLORS = {
	"white": "#ffffff",
	"black": "#000000",
	"transparent": "transparent",
	"gray": "#6b7280",
	"grey": "#6b7280",
	"red": "#ef4444",
	"blue": "#3b82f6",
	"green": "#10b981",
	"yellow": "#f59e0b",
	"purple": "#8b5cf6",
	"indigo": "#6366f1",
	"pink": "#ec4899",
	"navy": "#1e3a8a",
	"teal": "#14b8a6",
	"orange": "#f97316",
	"cyan": "#06b6d4",
}


def _node_id(value):
	if not value:
		return frappe.generate_hash(length=10)
	val_str = re.sub(r"[^A-Za-z0-9_-]", "-", str(value).strip())
	if not val_str or not NODE_ID.fullmatch(val_str):
		return frappe.generate_hash(length=10)
	return val_str[:64]


def _ensure_unique_id(node_id, seen_ids, prefix="node"):
	clean_id = _node_id(node_id)
	if clean_id in seen_ids:
		clean_id = f"{prefix}-{frappe.generate_hash(length=8)}"
	seen_ids.add(clean_id)
	return clean_id


def _css(value, kind="length", default="0px"):
	raw = str(value if value not in (None, "") else default).strip()
	pattern = CSS_COLOR if kind == "color" else CSS_LENGTH
	if pattern.fullmatch(raw):
		return raw
	if kind == "color":
		lower = raw.lower()
		if lower in NAMED_COLORS:
			return NAMED_COLORS[lower]
		if re.fullmatch(r"[0-9a-f]{3,8}", lower):
			return f"#{lower}"
		return default if default != "0px" else "transparent"
	else:
		m = re.search(r"^[+-]?\d+(?:\.\d+)?(?:px|%|em|rem|pt)?", raw.lower())
		if m and CSS_LENGTH.fullmatch(m.group(0)):
			return m.group(0)
		m_num = re.search(r"^[+-]?\d+(?:\.\d+)?", raw)
		if m_num:
			return f"{m_num.group(0)}px"
		return default


def _zero_length(value):
	"""True when a CSS length resolves to nothing at all (0, 0px, 0%, ...)."""
	match = re.match(r"^0+(?:\.0+)?(?:px|%|em|rem|pt)?$", str(value or "").strip(), re.I)
	return bool(match)


def _font_family(value):
	value = str(value or DEFAULT_SETTINGS["font_family"]).strip()
	if not FONT_FAMILY.fullmatch(value):
		return DEFAULT_SETTINGS["font_family"]
	return value


def _url(value, allow_full_token=False):
	raw = validate_semantic_tokens(str(value or "").strip())
	if not raw:
		return ""
	if raw.startswith(SAFE_URL_SCHEMES) or (allow_full_token and is_semantic_token(raw)):
		return raw
	if raw.startswith("www.") or ("." in raw and not raw.startswith(("#", "/"))):
		return f"https://{raw}"
	return "#"


def _is_private_url(value):
	return urlparse(str(value or "")).path.startswith("/private")


def _visibility(value):
	if not value or not isinstance(value, dict):
		return {"device": "both", "match": "all", "conditions": []}
	device = value.get("device", "both")
	if device not in DEVICE_VALUES:
		device = "both"
	match = value.get("match", "all")
	if match not in {"all", "any"}:
		match = "all"
	conditions = value.get("conditions") or []
	if not isinstance(conditions, list):
		conditions = []
	conditions = conditions[:5]
	normalized = []
	for condition in conditions:
		if not isinstance(condition, dict):
			continue
		fieldname = str(condition.get("fieldname") or "").strip()
		operator = condition.get("operator")
		if not REFERENCE_FIELD_PATH.fullmatch(fieldname) or operator not in CONDITION_OPERATORS:
			continue
		normalized.append({"fieldname": fieldname, "operator": operator, "value": str(condition.get("value") or "")[:500]})
	return {"device": device, "match": match, "conditions": normalized}


def _spacing(style):
	style = style if isinstance(style, dict) else {}
	result = {}
	for side in ("top", "right", "bottom", "left"):
		val = style.get(side)
		if str(val).strip().lower() in ("auto", "none"):
			result[side] = "0px"
		else:
			result[side] = _css(val, default="0px")
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
			val = _css(style[key])
			if val == "auto" and key not in {"width", "height"}:
				val = "0px"
			# A block that asked for an unreadable size is better off inheriting
			# the document's, so drop the key instead of writing 0px into it.
			if key in ("font_size", "line_height") and _zero_length(val):
				continue
			result[key] = val
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
	if value in (None, ""):
		return default
	if isinstance(value, (int, float)):
		try:
			if math.isnan(value) or math.isinf(value):
				return default
			return max(minimum, min(maximum, int(round(value))))
		except Exception:
			return default
	val_str = str(value).strip().lower()
	if val_str in ("auto", "none", "inherit", "initial", "unset"):
		return default
	match = re.search(r"^[+-]?\d+(?:\.\d+)?", val_str)
	if match:
		try:
			return max(minimum, min(maximum, int(round(float(match.group(0))))))
		except Exception:
			return default
	return default


def _validate_block(block):
	if not isinstance(block, dict):
		block = {}
	type_ = block.get("type")
	if type_ not in BLOCK_TYPES:
		type_ = "text"
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
			val = content.get(key)
			if val not in (None, ""):
				val_str = str(val).strip().lower()
				if val_str in ("100%", "auto", "none", "inherit", "full"):
					continue
				parsed = _bounded_int(val, default=None, minimum=1, maximum=2000)
				if parsed is not None:
					out[key] = parsed
		out["preserve_aspect_ratio"] = bool(content.get("preserve_aspect_ratio", True))
	elif type_ == "button":
		out["text"] = validate_semantic_tokens(str(content.get("text") or "Button")[:500])
		action = content.get("action") or "url"
		if action not in BUTTON_ACTIONS:
			action = "url"
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
		if not isinstance(items, list):
			items = []
		items = items[:12]
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
		section = {}
	section_id = _ensure_unique_id(section.get("id"), seen_ids, prefix="sec")
	columns = section.get("columns") or []
	columns_len = len(columns) if isinstance(columns, list) else 1

	raw_layout = str(section.get("layout") or "1").strip()
	ALIAS_LAYOUTS = {
		"1": "1",
		"single": "1",
		"1-col": "1",
		"2": "1/2:1/2",
		"2-col": "1/2:1/2",
		"half": "1/2:1/2",
		"50:50": "1/2:1/2",
		"3": "1/3:1/3:1/3",
		"3-col": "1/3:1/3:1/3",
		"third": "1/3:1/3:1/3",
		"thirds": "1/3:1/3:1/3",
		"4": "1/4:1/4:1/4:1/4",
		"4-col": "1/4:1/4:1/4:1/4",
		"quarter": "1/4:1/4:1/4:1/4",
		"quarters": "1/4:1/4:1/4:1/4",
	}
	if raw_layout in LAYOUTS:
		layout = raw_layout
	elif raw_layout in ALIAS_LAYOUTS:
		layout = ALIAS_LAYOUTS[raw_layout]
	elif columns_len == 2:
		layout = "1/2:1/2"
	elif columns_len == 3:
		layout = "1/3:1/3:1/3"
	elif columns_len == 4:
		layout = "1/4:1/4:1/4:1/4"
	else:
		layout = "1"

	section["layout"] = layout
	if layout not in LAYOUTS:
		layout = "1"

	expected_cols = len(LAYOUTS[layout])
	if not isinstance(columns, list):
		columns = []
	if len(columns) < expected_cols:
		while len(columns) < expected_cols:
			columns.append({"id": frappe.generate_hash(length=10), "style": {}, "blocks": []})
	elif len(columns) > expected_cols:
		columns = columns[:expected_cols]

	column_widths = section.get("column_widths")
	if not isinstance(column_widths, list) or len(column_widths) != len(columns):
		column_widths = list(LAYOUTS[layout])
	try:
		column_widths = [float(width) for width in column_widths]
		if any(not math.isfinite(width) or width < 5 or width > 95 for width in column_widths) and len(column_widths) > 1:
			column_widths = list(LAYOUTS[layout])
		total_width = sum(column_widths)
		if not 95.0 <= total_width <= 105.0:
			column_widths = list(LAYOUTS[layout])
	except Exception:
		column_widths = list(LAYOUTS[layout])

	total_width = sum(column_widths) or 100
	column_widths = [round(width * 100 / total_width, 3) for width in column_widths]
	column_widths[-1] = round(column_widths[-1] + 100 - sum(column_widths), 3)
	normalized_columns = []
	for column in columns:
		if not isinstance(column, dict):
			continue
		column_id = _ensure_unique_id(column.get("id"), seen_ids, prefix="col")
		blocks = column.get("blocks") or []
		if not isinstance(blocks, list):
			blocks = []
		normalized_blocks = [_validate_block(block) for block in blocks if isinstance(block, dict)]
		for block in normalized_blocks:
			block["id"] = _ensure_unique_id(block.get("id"), seen_ids, prefix="blk")
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
	raw_version = schema.get("version")
	if raw_version is not None:
		try:
			version = int(float(str(raw_version).strip().lstrip("vV")))
		except (ValueError, TypeError):
			version = SCHEMA_VERSION
	else:
		version = SCHEMA_VERSION

	if version > 5:
		frappe.throw(_("Unsupported builder schema version"))
	raw_settings = schema.get("settings")
	if isinstance(raw_settings, str):
		try:
			raw_settings = json.loads(raw_settings)
		except Exception:
			raw_settings = None

	settings = dict(DEFAULT_SETTINGS)
	if isinstance(raw_settings, dict):
		settings.update(raw_settings)

	settings["content_width"] = _bounded_int(settings.get("content_width"), 600, 320, 900)
	# Fall back to the documented default for each setting, not to _css's generic
	# "0px"/transparent. An unparseable value is a mistake to correct, not a
	# design instruction: a transparent text_color hides every unstyled string,
	# and a 0px font_size hides every button label, because a button is the one
	# element with no inline font-size of its own to override it.
	for key in ("body_background", "content_background", "text_color", "link_color", "button_background", "button_text_color"):
		settings[key] = _css(settings.get(key), "color", DEFAULT_SETTINGS[key])
	for key in ("font_size", "button_radius", "section_padding"):
		fallback = DEFAULT_SETTINGS[key]
		val = _css(settings.get(key), default=fallback)
		if val == "auto":
			val = fallback
		settings[key] = val
	# Zero is a legitimate radius or padding, but never a legitimate body size.
	if _zero_length(settings["font_size"]):
		settings["font_size"] = DEFAULT_SETTINGS["font_size"]
	settings["font_family"] = _font_family(settings.get("font_family"))
	settings["link_decoration"] = settings.get("link_decoration") if settings.get("link_decoration") in {"none", "underline"} else "underline"

	raw_sections = schema.get("sections")
	if isinstance(raw_sections, str):
		try:
			raw_sections = json.loads(raw_sections)
		except Exception:
			raw_sections = []
	if isinstance(raw_sections, dict):
		if "columns" in raw_sections:
			raw_sections = [raw_sections]
		else:
			raw_sections = list(raw_sections.values())
	if not isinstance(raw_sections, list):
		raw_sections = []
	sections = raw_sections
	seen_ids = set()
	normalized = {
		"version": SCHEMA_VERSION,
		"settings": settings,
		"sections": [_validate_section(section, seen_ids) for section in sections if isinstance(section, dict)],
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
