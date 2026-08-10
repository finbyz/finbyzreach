from __future__ import annotations

import re

import frappe
import nh3
from frappe import _

from .tokens import validate_semantic_tokens

RICH_TAGS = {"p", "div", "br", "ul", "ol", "li", "strong", "b", "em", "i", "u", "s", "a", "span", "font", "h1", "h2", "h3"}
CODE_TAGS = RICH_TAGS | {"div", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "img", "pre", "code", "blockquote"}
ALLOWED_CSS = {
	"background-color", "border", "border-bottom", "border-color", "border-left", "border-radius", "border-right",
	"border-top", "color", "display", "font-family", "font-size", "font-style", "font-weight", "height", "letter-spacing",
	"line-height", "margin", "margin-bottom", "margin-left", "margin-right", "margin-top", "max-width", "padding",
	"padding-bottom", "padding-left", "padding-right", "padding-top", "text-align", "text-decoration", "vertical-align", "width",
}
ATTRIBUTES = {
	"*": {"style", "title"},
	"a": {"href", "target", "title"},
	"font": {"color", "face", "size"},
	"img": {"src", "alt", "width", "height", "title", "style", "border"},
	"table": {"width", "height", "align", "cellpadding", "cellspacing", "border", "role", "style"},
	"td": {"width", "height", "align", "valign", "colspan", "rowspan", "bgcolor", "style"},
	"th": {"width", "height", "align", "valign", "colspan", "rowspan", "bgcolor", "style"},
}
FORBIDDEN_CODE = re.compile(
	r"<\s*/?\s*(?:script|style|iframe|frame|frameset|form|input|button|textarea|select|option|object|embed|video|audio|link|meta|base)\b"
	r"|\bon[a-z]+\s*=|(?:href|src)\s*=\s*[\"']?\s*(?:javascript|vbscript|data)\s*:"
	r"|url\s*\(\s*[\"']?\s*(?:javascript|vbscript|data)\s*:",
	re.IGNORECASE,
)
DYNAMIC_SCHEME = re.compile(r"(?:href|src)\s*=\s*[\"']\s*{{", re.IGNORECASE)
EMPTY_RICH_BLOCK = re.compile(r"<(p|div)>\s*(?:<br\s*/?>)?\s*</\1>", re.IGNORECASE)
RICH_PARAGRAPH_WITHOUT_STYLE = re.compile(r"<p(?![^>]*\bstyle\s*=)([^>]*)>", re.IGNORECASE)


def _clean(value, tags):
	value = validate_semantic_tokens(value)
	if DYNAMIC_SCHEME.search(value):
		frappe.throw(_("A dynamic URL must keep a literal HTTP(S), mail, phone, SMS, anchor, or relative prefix"))
	return nh3.clean(
		value,
		tags=tags,
		clean_content_tags={"script", "style", "iframe", "object", "embed", "form"},
		attributes=ATTRIBUTES,
		strip_comments=True,
		filter_style_properties=ALLOWED_CSS,
		url_schemes={"http", "https", "mailto", "tel", "sms"},
		url_relative="pass_through",
	)


def sanitize_rich_html(value) -> str:
	cleaned = _clean(str(value or ""), RICH_TAGS)
	# Browsers create empty <p><br></p> / <div><br></div> nodes at the
	# beginning or end of a contenteditable field. They add email-client
	# margins but do not represent content; use the dedicated Spacer block for
	# intentional vertical space. Styled or in-between blank nodes are kept.
	cleaned = EMPTY_RICH_BLOCK.sub("", cleaned)
	# Paragraph margins are browser defaults, not a design decision. Make the
	# compact default explicit and email-safe; an author supplied inline style
	# remains untouched.
	cleaned = RICH_PARAGRAPH_WITHOUT_STYLE.sub(r'<p\1 style="margin:0">', cleaned)
	return cleaned


def sanitize_code_html(value) -> str:
	value = str(value or "")
	if FORBIDDEN_CODE.search(value):
		frappe.throw(_("Restricted HTML contains a forbidden tag, event handler, or URL scheme"))
	cleaned = _clean(value, CODE_TAGS)
	if FORBIDDEN_CODE.search(cleaned):
		frappe.throw(_("Restricted HTML contains unsafe content"))
	return cleaned
