from __future__ import annotations

import re

EMAIL_TEMPLATE_DOCTYPE = "Email Template"
EMAIL_TEMPLATE_MASTER_DOCTYPE = "Email Template Master"
BUILDER_TARGET_DOCTYPES = frozenset(
	{EMAIL_TEMPLATE_DOCTYPE, EMAIL_TEMPLATE_MASTER_DOCTYPE}
)

SCHEMA_VERSION = 1
MAX_BLOCKS = 200
MAX_SCHEMA_BYTES = 1_000_000
MAX_COMPONENT_BYTES = 200_000
MAX_METADATA_BYTES = 50_000
MAX_CODE_BYTES = 50_000

LAYOUTS = {
	"1": [100],
	"1/2:1/2": [50, 50],
	"1/3:1/3:1/3": [33.333, 33.333, 33.334],
	"1/3:2/3": [33.333, 66.667],
	"2/3:1/3": [66.667, 33.333],
	"1/4:1/4:1/4:1/4": [25, 25, 25, 25],
	"1/4:3/4": [25, 75],
	"3/4:1/4": [75, 25],
}

BLOCK_TYPES = {"text", "image", "button", "divider", "spacer", "social", "preview_url", "code"}
COMPONENT_TYPES = {"Block", "Section"}
COMPONENT_CATEGORIES = {"Header", "Content", "CTA", "Footer", "Social", "Other"}
DEVICE_VALUES = {"both", "desktop", "mobile"}
CONDITION_OPERATORS = {"equals", "not_equals", "contains", "not_contains", "empty", "not_empty"}
BUTTON_ACTIONS = {"url", "email", "file", "telephone", "sms"}
ALIGNMENTS = {"left", "center", "right"}
VERTICAL_ALIGNMENTS = {"top", "middle", "bottom"}
MOBILE_STACKING = {"stack", "reverse", "none"}
FONT_WEIGHTS = {"normal", "bold", "400", "500", "600", "700"}
FONT_STYLES = {"normal", "italic"}
TEXT_DECORATIONS = {"none", "underline", "line-through"}
BORDER_STYLES = {"solid", "dotted", "dashed"}
SOCIAL_PLATFORMS = {"Facebook", "Instagram", "LinkedIn", "YouTube", "X", "TikTok", "WhatsApp", "Website"}

SAFE_URL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "sms:", "/", "#")
NODE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FIELDNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REFERENCE_FIELD_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")
FONT_FAMILY = re.compile(r"^[A-Za-z0-9 ,'\"-]{1,160}$")
CSS_LENGTH = re.compile(r"^(?:0|[0-9]{1,4}(?:\.[0-9]{1,2})?)(?:px|%|em|rem|pt)?$|^auto$", re.I)
CSS_COLOR = re.compile(
	r"^(?:#[0-9a-f]{3,8}|rgba?\(\s*[0-9]{1,3}\s*,\s*[0-9]{1,3}\s*,\s*[0-9]{1,3}(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\)|transparent|white|black)$",
	re.I,
)

DEFAULT_SETTINGS = {
	"content_width": 600,
	"body_background": "#f5f7fa",
	"content_background": "#ffffff",
	"font_family": "Arial, Helvetica, sans-serif",
	"font_size": "16px",
	"text_color": "#1f2937",
	"link_color": "#2563eb",
	"link_decoration": "underline",
	"button_background": "#2563eb",
	"button_text_color": "#ffffff",
	"button_radius": "4px",
	"section_padding": "0px",
}


def new_schema() -> dict:
	return {"version": SCHEMA_VERSION, "settings": dict(DEFAULT_SETTINGS), "sections": []}
