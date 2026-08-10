from __future__ import annotations

import ast
import html
import json
import re

import frappe
from frappe import _
from jinja2 import pass_context

from .reference_fields import resolve_linked_value

TOKEN_RE = re.compile(
	r"""{{\s*(?P<field>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*
	(?:\|\s*default\(\s*(?P<fallback>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*(?:,\s*true)?\s*\))?
	\s*}}""",
	re.VERBOSE,
)


def _fallback(match: re.Match) -> str:
	value = match.group("fallback")
	if not value:
		return ""
	try:
		return ast.literal_eval(value)
	except (SyntaxError, ValueError):
		frappe.throw(_("Invalid merge-field fallback"))


def _raise_token_validation(code: str, message: str) -> None:
	frappe.local.response["builder_validation"] = {"code": code}
	frappe.throw(_(message))


def validate_semantic_tokens(value) -> str:
	"""Allow only simple field tokens with an optional literal fallback in visual mode."""
	value = str(value or "")
	if re.search(r"{{\s*}}", value):
		_raise_token_validation(
			"empty_dynamic_field",
			"Empty dynamic field tokens like {{ }} are not allowed. Choose a field or remove the braces.",
		)
	if any(marker in value for marker in ("{%", "%}", "{#", "#}")):
		_raise_token_validation(
			"unsupported_jinja",
			"Visual templates support merge fields only. Use {{ field_name }} here, or switch this template to Raw HTML for custom Jinja blocks.",
		)
	remainder = TOKEN_RE.sub("", value)
	if any(marker in remainder for marker in ("{{", "}}")):
		_raise_token_validation(
			"invalid_dynamic_field_syntax",
			'Invalid dynamic field syntax. Use {{ field_name }} or {{ field_name|default("Fallback", true) }}.',
		)
	return value


def token_fields(value) -> set[str]:
	"""Return the field names used by valid visual-builder merge tokens."""
	value = validate_semantic_tokens(value)
	return {match.group("field") for match in TOKEN_RE.finditer(value)}


def is_semantic_token(value) -> bool:
	"""Return whether the complete value is one supported visual-builder token."""
	return bool(TOKEN_RE.fullmatch(validate_semantic_tokens(value)))


def field_expression(fieldname: str, fallback: str = "") -> str:
	key = json.dumps(str(fieldname), ensure_ascii=False)
	default = json.dumps(str(fallback or ""), ensure_ascii=False)
	return f"ebv({key},{default})"


def compile_tokens(value, output_filter="e") -> str:
	value = validate_semantic_tokens(value)

	def replace(match: re.Match) -> str:
		expression = field_expression(match.group("field"), _fallback(match))
		return f"{{{{ {expression} | {output_filter} }}}}"

	return TOKEN_RE.sub(replace, value)


def compile_attribute(value) -> str:
	"""Escape literal attribute text while retaining compiled Jinja token expressions."""
	value = validate_semantic_tokens(value)
	parts = []
	position = 0
	for match in TOKEN_RE.finditer(value):
		parts.append(html.escape(value[position : match.start()], quote=True))
		expression = field_expression(match.group("field"), _fallback(match))
		parts.append(f"{{{{ {expression} | e }}}}")
		position = match.end()
	parts.append(html.escape(value[position:], quote=True))
	return "".join(parts)


def compile_url(value) -> str:
	"""URL-encode only dynamic path fragments; the literal scheme is validated in schema.py."""
	value = validate_semantic_tokens(value)
	full_token = TOKEN_RE.fullmatch(value)
	if full_token:
		expression = field_expression(full_token.group("field"), _fallback(full_token))
		return f"{{{{ {expression} | email_builder_safe_url | e }}}}"
	parts = []
	position = 0
	for match in TOKEN_RE.finditer(value):
		parts.append(html.escape(value[position : match.start()], quote=True))
		expression = field_expression(match.group("field"), _fallback(match))
		parts.append(f"{{{{ {expression} | urlencode | e }}}}")
		position = match.end()
	parts.append(html.escape(value[position:], quote=True))
	return "".join(parts)


@pass_context
def ebv(context, fieldname, fallback=""):
	"""Read one permitted merge value from either core Email Template context shape."""
	missing = object()
	source = context.get("doc", missing)
	source_doctype = getattr(source, "doctype", None) if source is not missing else None
	# ``frappe._dict`` returns ``None`` for unknown attributes, so ``hasattr``
	# reports that ``as_dict`` exists even though it is not callable. Preview
	# contexts intentionally use ``frappe._dict``; only call a real converter.
	as_dict = getattr(source, "as_dict", None) if source is not missing else None
	if callable(as_dict):
		source = as_dict()
	if isinstance(source, dict):
		source_doctype = source_doctype or source.get("doctype")
		if "." in str(fieldname or "") and source_doctype:
			value, valid_path = resolve_linked_value(str(source_doctype), str(fieldname), source)
			if not valid_path:
				value = missing
		else:
			value = source.get(fieldname, missing)
	else:
		value = missing
	if value is missing:
		value = context.get(fieldname, missing)
	return fallback if value is missing or not value else value


def ebt(value) -> str:
	"""Compact generated-Jinja alias for subject-safe text."""
	return email_builder_text(value)


def email_builder_safe_url(value) -> str:
	value = str(value or "").strip()
	if value.startswith(("http://", "https://", "mailto:", "tel:", "sms:", "/", "#")):
		return value
	return "#"


def email_builder_text(value) -> str:
	return re.sub(r"[\r\n]+", " ", str(value or "")).strip()
