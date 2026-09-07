from __future__ import annotations

import json
import re
from copy import deepcopy

import frappe
from frappe import _

from urllib.parse import quote

from frappe.utils.jinja import validate_template

from .api import (
	_compiled_subject,
	_content_hash,
	_format_preview_html,
	_render_builder_request,
	_require_designer,
	_subject_source,
	_template,
)
from .constants import BLOCK_TYPES, LAYOUTS, MAX_SCHEMA_BYTES, SCHEMA_VERSION
from .design_defaults import apply_design_defaults, repair_text
from .schema import parse_json, validate_schema
from .tokens import TOKEN_RE, validate_semantic_tokens

# The AI Agent used for rewriting is configured on the "Followup Settings" single,
# consistent with the other AI Content Engine agents (smart reply, timeline, ...).
SETTINGS_DOCTYPE = "Followup Settings"
ENABLE_FIELD = "custom_enable_email_builder_ai"
REWRITE_AGENT_FIELD = "custom_email_builder_rewrite_agent"
GENERATOR_AGENT_FIELD = "custom_email_builder_generator_agent"

MAX_PROMPT_CHARS = 2000


# ---------------------------------------------------------------------------
# Settings helpers (agent name is resolved dynamically from the settings doc)
# ---------------------------------------------------------------------------
def _settings():
	if frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return frappe.get_single(SETTINGS_DOCTYPE)
	return frappe._dict()


def _ai_enabled(settings=None):
	settings = settings or _settings()
	return bool(settings.get(ENABLE_FIELD))


def _rewrite_agent(settings=None):
	settings = settings or _settings()
	return (settings.get(REWRITE_AGENT_FIELD) or "").strip()


def _generator_agent(settings=None):
	settings = settings or _settings()
	return (
		settings.get(GENERATOR_AGENT_FIELD)
		or settings.get(REWRITE_AGENT_FIELD)
		or ""
	).strip()


def _sample_prompts():
	"""Suggestion chips shown in the AI dialog, maintained in the Email Builder AI Prompt doctype."""
	if not frappe.db.exists("DocType", "Email Builder AI Prompt"):
		return []
	rows = frappe.get_all(
		"Email Builder AI Prompt",
		filters={"enabled": 1, "prompt_type": "Sample"},
		fields=["title", "prompt"],
		order_by="modified asc",
		limit=24,
	)
	return [{"title": row.title, "prompt": (row.prompt or row.title)} for row in rows if row.title]


def _chat_doc_name(template_name, user=None):
	user = user or frappe.session.user
	return f"{template_name}-{user}"


def _get_saved_chat_history(template_name, user=None):
	if not template_name or not frappe.db.exists("DocType", "Email Builder AI Chat"):
		return []
	name = _chat_doc_name(template_name, user)
	if not frappe.db.exists("Email Builder AI Chat", name):
		return []
	try:
		raw = frappe.db.get_value("Email Builder AI Chat", name, "chat_history_json")
		if not raw:
			return []
		turns = json.loads(raw)
		return turns if isinstance(turns, list) else []
	except Exception:
		return []


def _sanitize_turns_for_storage(chat_turns):
	"""Strip heavy schemas and HTML strings from persistent chat turns.

	The full schema and run metadata are already safely stored in Email Builder AI Run.
	Keeping only the summary, proposal_id, and change notes reduces storage size by >90%.
	"""
	sanitized = []
	for turn in (chat_turns or []):
		t = dict(turn)
		if "proposal" in t and isinstance(t["proposal"], dict):
			p = t["proposal"]
			t["proposal"] = {
				"proposal_id": p.get("proposal_id"),
				"summary": p.get("summary") or "",
				"change_notes": p.get("change_notes") or [],
				"warnings": p.get("warnings") or [],
				"scope": p.get("scope") or "template",
				"target_kind": p.get("target_kind") or "template",
				"target_id": p.get("target_id") or "",
				"status": p.get("status") or t.get("status") or "pending",
				"thinking_steps": p.get("thinking_steps") or [],
			}
		sanitized.append(t)
	return sanitized


def _save_chat_history(template_name, chat_turns, user=None):
	if not template_name or not frappe.db.exists("DocType", "Email Builder AI Chat"):
		return
	user = user or frappe.session.user
	name = _chat_doc_name(template_name, user)
	clean_turns = _sanitize_turns_for_storage(chat_turns)
	json_text = json.dumps(clean_turns, separators=(",", ":"))
	if frappe.db.exists("Email Builder AI Chat", name):
		frappe.db.set_value("Email Builder AI Chat", name, "chat_history_json", json_text, update_modified=True)
	else:
		doc = frappe.get_doc({
			"doctype": "Email Builder AI Chat",
			"template": template_name,
			"user": user,
			"chat_history_json": json_text,
		})
		doc.insert(ignore_permissions=True)


@frappe.whitelist(methods=["GET"])
def get_builder_ai_settings(template_name=None):
	"""Lightweight capability probe the builder UI calls on load."""
	_require_designer()
	settings = _settings()
	template_agent = _rewrite_agent(settings)
	generator_agent = _generator_agent(settings)
	return {
		"enabled": bool(_ai_enabled(settings) and (template_agent or generator_agent)),
		"rewrite_configured": bool(template_agent),
		"generator_configured": bool(generator_agent),
		"sample_prompts": _sample_prompts(),
		"chat_history": _get_saved_chat_history(template_name) if template_name else [],
	}


@frappe.whitelist(methods=["POST"])
def save_ai_sample_prompt(title: str, prompt: str):
	"""Create a new AI Sample Prompt from user selection."""
	_require_designer()
	
	if not title or not prompt:
		frappe.throw(_("Title and prompt are required."))
		
	doc = frappe.new_doc("Email Builder AI Prompt")
	doc.title = title
	doc.prompt = prompt
	doc.prompt_type = "Sample"
	doc.enabled = 1
	doc.insert(ignore_permissions=True)
	
	return doc.name


# ---------------------------------------------------------------------------
# Agent output coercion
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(r"^```[a-zA-Z0-9]*\s*|\s*```$")


def _coerce_ai_payload(result) -> dict:
	"""Normalize an agent response into a dict, tolerating string/JSON/pydantic."""
	if result is None:
		frappe.throw(_("The AI agent returned an empty response. Please try again."))
	if hasattr(result, "model_dump"):
		result = result.model_dump()
	elif hasattr(result, "dict") and not isinstance(result, dict):
		try:
			result = result.dict()
		except Exception:
			pass
	if isinstance(result, dict):
		# Some agents wrap the payload under "output".
		if isinstance(result.get("output"), dict):
			return result["output"]
		elif isinstance(result.get("output"), str):
			# Sometimes agents return the stringified JSON inside "output"
			result = result["output"]
		else:
			return result

	text = result if isinstance(result, str) else str(result)
	text = _FENCE_RE.sub("", text.strip()).strip()
	try:
		parsed = json.loads(text)
	except (TypeError, ValueError):
		start, end = text.find("{"), text.rfind("}")
		if start == -1 or end <= start:
			frappe.throw(_("The AI agent did not return a usable design. Please try again."))
		try:
			parsed = json.loads(text[start : end + 1])
		except (TypeError, ValueError):
			frappe.throw(_("The AI agent returned malformed JSON. Please try again."))
	if not isinstance(parsed, dict):
		frappe.throw(_("The AI agent returned an unexpected response. Please try again."))
	return parsed


def _extract_schema(payload: dict) -> dict:
	"""Pull the builder schema out of the agent payload."""
	schema = payload.get("schema")
	if schema is None:
		# The agent may have returned the schema object at the top level.
		if {"sections", "settings", "version"} & set(payload.keys()):
			schema = payload
		else:
			frappe.throw(_("The AI response did not include an email design."))
	if isinstance(schema, str):
		schema = parse_json(schema, label="AI schema", max_bytes=MAX_SCHEMA_BYTES)
	if not isinstance(schema, dict):
		frappe.throw(_("The AI response email design was not an object."))
	schema["version"] = SCHEMA_VERSION

	raw_settings = schema.get("settings")
	if isinstance(raw_settings, str):
		try:
			schema["settings"] = json.loads(raw_settings)
		except Exception:
			schema["settings"] = {}
	elif not isinstance(raw_settings, dict):
		schema["settings"] = {}

	sections = schema.get("sections") or []
	if isinstance(sections, list):
		total_blocks = sum(
			len(col.get("blocks") or [])
			for sec in sections
			if isinstance(sec, dict)
			for col in (sec.get("columns") or [])
			if isinstance(col, dict)
		)
		if total_blocks == 0:
			frappe.throw(
				_("The AI generated a design with no content blocks. Please try again with more details in your prompt.")
			)

	return schema


def _string_list(value):
	if not value:
		return []
	if isinstance(value, str):
		value = [value]
	if not isinstance(value, (list, tuple)):
		return []
	return [str(item)[:500] for item in value if str(item or "").strip()][:20]


# ---------------------------------------------------------------------------
# Merge-token sanitization
#
# The visual token validator (tokens.validate_semantic_tokens) rejects anything
# that is not a simple `{{ field }}` / `{{ field|default(...) }}` token. Agents
# occasionally emit dotted paths, filters or `{% %}` blocks, which would hard-
# fail the whole proposal. We strip those before compiling so a rewrite never
# crashes on token syntax; valid tokens are preserved untouched.
# ---------------------------------------------------------------------------
_JINJA_BLOCK_RE = re.compile(r"{%.*?%}|{#.*?#}", re.S)
_LOOSE_TOKEN_RE = re.compile(r"{{.*?}}", re.S)
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _sanitize_token_text(text):
	"""Return (clean_text, removed_count) keeping only valid visual merge tokens."""
	if not isinstance(text, str) or not any(marker in text for marker in ("{{", "{%", "{#")):
		return text, 0
	removed = 0

	def _drop_block(_match):
		nonlocal removed
		removed += 1
		return ""

	text = _JINJA_BLOCK_RE.sub(_drop_block, text)

	def _keep_valid(match):
		nonlocal removed
		token = match.group(0)
		if TOKEN_RE.fullmatch(token):
			return token
		removed += 1
		return ""

	return _LOOSE_TOKEN_RE.sub(_keep_valid, text), removed


def _sanitize_schema_tokens(value):
	"""Recursively sanitize every string in the schema. Returns (value, removed_count)."""
	removed = 0
	if isinstance(value, dict):
		for key, item in value.items():
			value[key], count = _sanitize_schema_tokens(item)
			removed += count
	elif isinstance(value, list):
		for index, item in enumerate(value):
			value[index], count = _sanitize_schema_tokens(item)
			removed += count
	elif isinstance(value, str):
		return _sanitize_token_text(value)
	return value, removed


def _apply_defaults_with_warnings(schema):
	"""Run the deterministic repair pass and translate its result into warnings.

	Keeps the two AI entry points identical in behaviour and gives the user a
	plain account of what was corrected on their behalf, rather than silently
	rewriting their design.
	"""
	stats = apply_design_defaults(schema)
	warnings = []
	if stats["tokens_repaired"]:
		warnings.append(
			_("Repaired {0} merge field(s) the AI wrote with single braces. Verify they point at the right fields.").format(
				stats["tokens_repaired"]
			)
		)
	if stats["placeholders"]:
		warnings.append(
			_("The AI left placeholder text you should replace: {0}").format(", ".join(stats["placeholders"][:5]))
		)
	return stats, warnings


def _resolve_generated_images(schema, template_name="") -> list[str]:
	"""Scan schema for any image blocks containing generation directives or empty src with descriptions,
	and automatically generate the image via generate_email_image, saving it as a Frappe public File.
	If generation fails or cannot be completed, cleanly remove the broken image block so the email remains professional."""
	warnings = []
	try:
		from .image_gen import generate_email_image

		for section in (schema.get("sections") or []):
			if not isinstance(section, dict):
				continue
			for column in (section.get("columns") or []):
				if not isinstance(column, dict):
					continue
				blocks_to_keep = []
				for block in (column.get("blocks") or []):
					if not isinstance(block, dict) or block.get("type") != "image":
						blocks_to_keep.append(block)
						continue
					content = block.get("content") if isinstance(block.get("content"), dict) else {}
					src = str(content.get("src") or "").strip()
					alt = str(content.get("alt") or "").strip()
					src_lower = src.lower()

					needs_generation = False
					img_prompt = ""

					if src.startswith(("generate:", "prompt:", "ai:", "[image", "[generate")) or "generate_email_image" in src_lower:
						needs_generation = True
						img_prompt = re.sub(r"^(generate|prompt|ai|\[image|\[generate):\s*", "", src, flags=re.I).rstrip("]").strip()
						if not img_prompt or "generate_email_image" in img_prompt:
							img_prompt = alt or "professional business email visual banner"
					elif not src or any(p in src_lower for p in ("placeholder", "dummyimage", "example.com", "via.placeholder", "[generated", "image_url")):
						needs_generation = True
						img_prompt = alt or "professional business email visual banner"

					if needs_generation:
						real_url = generate_email_image(img_prompt, template_name=template_name)
						if real_url and real_url.startswith(("/", "http")):
							content["src"] = real_url
							blocks_to_keep.append(block)
						else:
							msg = _("Image generation was unavailable. The email was formatted cleanly without image blocks.")
							if msg not in warnings:
								warnings.append(msg)
					else:
						blocks_to_keep.append(block)
				column["blocks"] = blocks_to_keep
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Failed resolving generated images in proposal")
	return warnings


# ---------------------------------------------------------------------------
# Context builder for the agent
# ---------------------------------------------------------------------------
def _collect_images(schema):
	"""Public image URLs already used in the current design, for the agent to reuse."""
	urls = []

	def walk(node):
		if isinstance(node, dict):
			if node.get("type") == "image":
				content = node.get("content") if isinstance(node.get("content"), dict) else {}
				src = str(content.get("src") or "").strip()
				if src:
					urls.append(src)
			for item in node.values():
				walk(item)
		elif isinstance(node, list):
			for item in node:
				walk(item)

	walk(schema)
	seen, out = set(), []
	for url in urls:
		if url not in seen:
			seen.add(url)
			out.append(url)
	return out[:20]


def _collect_palette(schema):
	"""Colors already used in the current design, so the AI keeps the same vibe."""
	colors = []
	settings = schema.get("settings") if isinstance(schema, dict) else {}
	for key in ("body_background", "content_background", "text_color", "link_color", "button_background", "button_text_color"):
		value = (settings or {}).get(key)
		if value:
			colors.append(str(value))
	colors.extend(_HEX_COLOR_RE.findall(json.dumps(schema, separators=(",", ":"))))
	seen, out = set(), []
	for color in colors:
		color = color.strip()
		if color and color.lower() not in seen:
			seen.add(color.lower())
			out.append(color)
	return out[:16]


def _format_chat_history(chat_history):
	if not chat_history:
		return "(no prior chat history - this is the first turn)"
	if isinstance(chat_history, str):
		try:
			chat_history = json.loads(chat_history)
		except Exception:
			return str(chat_history)[:2000] if str(chat_history).strip() else "(no prior chat history)"
	if not isinstance(chat_history, list):
		return "(no prior chat history)"

	formatted = []
	for turn in chat_history[-10:]:
		if isinstance(turn, dict):
			role = str(turn.get("role") or "user").upper()
			text = str(turn.get("text") or turn.get("content") or "").strip()
			if text:
				formatted.append(f"{role}: {text}")
		elif isinstance(turn, str) and turn.strip():
			formatted.append(turn.strip())
	return "\n".join(formatted) if formatted else "(no prior chat history)"


def _brand_name():
	"""The sending organisation's name, for the agent to write into copy.

	Without this the agent has nothing to put in a headline that needs a sender,
	so it writes "[Your Company Name]" and ships it. The name is knowable, so
	give it to the agent rather than leaving a placeholder for a human to catch.
	"""
	try:
		company = frappe.defaults.get_global_default("company")
		if company:
			return str(company)
	except Exception:
		pass
	try:
		return str(frappe.db.get_single_value("Website Settings", "app_name") or "")
	except Exception:
		return ""


def _scope_instruction(schema, scope="template", section_id=None):
	"""Tell the agent which part of the document it is allowed to touch.

	``generate_ai_rewrite`` has always accepted a scope, but it never reached
	the prompt, so a row-scoped edit asked the agent to rewrite the entire
	template and then silently discarded everything outside the row.
	"""
	if scope != "section" or not section_id:
		return (
			"You are editing the whole template. Any section may change, but only "
			"where the request calls for it."
		)
	labels = []
	for section in (schema.get("sections") or []):
		if isinstance(section, dict) and section.get("id") == section_id:
			labels.append(section.get("layout") or "1")
	layout = labels[0] if labels else "unknown"
	return (
		f"You are editing ONE section only: id \"{section_id}\" (layout \"{layout}\"). "
		"Return the complete document, but every other section must come back "
		"byte-identical — same ids, same copy, same styling. Change nothing outside "
		f"section \"{section_id}\"."
	)


def _agent_context(doc, schema, metadata, prompt, chat_history=None, scope="template", section_id=None):
	settings = schema.get("settings") if isinstance(schema, dict) else {}
	images = _collect_images(schema)
	palette = _collect_palette(schema)
	return {
		"scope_instruction": _scope_instruction(schema, scope, section_id),
		"company_name": _brand_name(),
		"user_prompt": prompt,
		"current_schema": json.dumps(schema, separators=(",", ":")),
		"current_settings": json.dumps(settings or {}, separators=(",", ":")),
		"subject": str(metadata.get("subject") or _subject_source(doc) or ""),
		"preheader": str(metadata.get("preheader") or ""),
		"reference_doctype": str(metadata.get("reference_doctype") or ""),
		"block_types": ", ".join(sorted(BLOCK_TYPES)),
		"layouts": ", ".join(LAYOUTS.keys()),
		"available_images": (
			"Existing template images:\n" + "\n".join(images)
			if images
			else "(No existing images yet. You can use the `generate_email_image` tool or supply relevant visual images.)"
		),
		"current_palette": ", ".join(palette) if palette else "(reuse the existing design settings colors)",
		"chat_history": _format_chat_history(chat_history),
	}


try:
	from langchain_core.callbacks import BaseCallbackHandler
except Exception:
	try:
		from langchain.callbacks.base import BaseCallbackHandler
	except Exception:
		class BaseCallbackHandler:
			pass


class EmailBuilderThinkingCallback(BaseCallbackHandler):
	"""LangChain callback handler that emits real agent thinking & tool events via Socket.io."""
	def __init__(self, template_name, user):
		super().__init__()
		self.template_name = template_name
		self.user = user
		self.steps = []

	def _publish(self, event_type, label, detail=""):
		step = {"type": event_type, "label": label, "detail": detail}
		self.steps.append(step)
		try:
			frappe.publish_realtime(
				"email_builder_ai_step",
				{"template_name": self.template_name, "step": step},
				user=self.user,
			)
		except Exception:
			pass

	def on_llm_start(self, serialized, prompts, **kwargs):
		self._publish("thinking", _("Analyzing email template and thinking..."))

	def on_chat_model_start(self, serialized, messages, **kwargs):
		self._publish("thinking", _("Analyzing email template and thinking..."))

	def on_tool_start(self, serialized, input_str, **kwargs):
		tool_name = serialized.get("name", "tool") if isinstance(serialized, dict) else str(serialized)
		self._publish("tool_start", _("Executing tool: {0}").format(tool_name), str(input_str)[:200])

	def on_tool_end(self, output, **kwargs):
		self._publish("tool_end", _("Tool finished execution"))

	def on_agent_action(self, action, **kwargs):
		tool_name = getattr(action, "tool", "tool")
		self._publish("action", _("Calling tool: {0}").format(tool_name))

	def on_llm_end(self, response, **kwargs):
		self._publish("formatting", _("Structuring proposal and formatting email..."))


def _invoke_rewrite_agent(agent_name, prompt, context_kwargs=None, callback_handler=None):
	settings = _settings()
	main_agent = _rewrite_agent(settings)

	if not frappe.db.exists("AI Agent", agent_name):
		if main_agent and frappe.db.exists("AI Agent", main_agent):
			agent_name = main_agent
		else:
			frappe.throw(
				_("The configured Email Builder AI Agent {0} does not exist. Update Followup Settings.").format(agent_name)
			)
	ai_agent_doc = frappe.get_doc("AI Agent", agent_name)
	if not (ai_agent_doc.messages or []):
		frappe.throw(
			_("The AI Agent '{0}' has no prompt instructions configured. Configure prompt messages in AI Agent.").format(agent_name)
		)

	payload = {
		"user_prompt": prompt,
		"current_schema": "{}",
		"current_settings": "{}",
		"subject": "",
		"preheader": "",
		"reference_doctype": "",
		"block_types": ", ".join(sorted(BLOCK_TYPES)),
		"layouts": ", ".join(LAYOUTS.keys()),
		"available_images": "(none - do not add any new images)",
		"current_palette": "(reuse the existing design settings colors)",
		"chat_history": "(no prior chat history)",
		"scope_instruction": "You are editing the whole template.",
		"company_name": _brand_name(),
	}
	if context_kwargs:
		for k, v in context_kwargs.items():
			if v is not None:
				payload[k] = v

	if not payload.get("chat_history"):
		payload["chat_history"] = "(no prior chat history)"

	# Inspect AI Agent prompt messages and auto-fill any missing input key placeholders required by LangChain
	for msg in (ai_agent_doc.messages or []):
		content = getattr(msg, "content", "") or ""
		placeholders = re.findall(r"\{([a-zA-Z0-9_]+)\}", content)
		for key in placeholders:
			if key not in payload or payload[key] is None or payload[key] == "":
				payload[key] = "(no prior chat history)" if key == "chat_history" else ""

	# Pass LangChain callback handler if provided
	if callback_handler:
		payload["callbacks"] = [callback_handler]

	# Same public entry point used by ai_engine / custom_research / finbyzreach.
	try:
		return ai_agent_doc.agent_service.invoke(query=prompt, **payload)
	except Exception as exc:
		recovered = _recover_unparsed_completion(exc)
		if recovered is None:
			raise
		return recovered


def _recover_unparsed_completion(exc):
	"""Salvage the model's JSON when the structured-output parser rejected it.

	The agent runs through a ``PydanticOutputParser``, which is all-or-nothing:
	one field the generated model dislikes discards an otherwise complete,
	usable design. That strictness buys nothing here, because ``validate_schema``
	independently coerces every field to a safe value and ``design_defaults``
	repairs the rest — a rejected ``"tag": "ul"`` would have become ``"p"``
	anyway.

	So the rich output schema stays (it is what shapes ``format_instructions``
	and therefore what the model aims at) while a parse failure falls back to
	the raw completion instead of losing the generation.
	"""
	try:
		from langchain_core.exceptions import OutputParserException
	except Exception:
		return None
	if not isinstance(exc, OutputParserException):
		return None

	text = getattr(exc, "llm_output", None) or ""
	if not text:
		# Older LangChain builds fold the completion into the message only.
		match = re.search(r"from completion (.*)", str(exc), re.S)
		if not match:
			return None
		text = match.group(1)

	start, end = text.find("{"), text.rfind("}")
	if start == -1 or end <= start:
		return None
	try:
		json.loads(text[start : end + 1])
	except (TypeError, ValueError):
		return None
	frappe.logger("email_builder").info(
		"Recovered an Email Builder generation the structured parser rejected"
	)
	return text[start : end + 1]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _log_run(template, prompt, agent, before_schema, after_schema, summary, change_notes, warnings, issues, status, error=""):
	if not frappe.db.exists("DocType", "Email Builder AI Run"):
		return None
	try:
		run = frappe.get_doc(
			{
				"doctype": "Email Builder AI Run",
				"template": template,
				"agent": agent,
				"status": status,
				"prompt": (prompt or "")[:2000],
				"summary": (summary or "")[:1000],
				"change_notes": "\n".join(change_notes)[:2000],
				"warnings": "\n".join(warnings)[:2000],
				"before_schema_json": json.dumps(before_schema, separators=(",", ":")),
				"after_schema_json": json.dumps(after_schema, separators=(",", ":")) if after_schema is not None else "",
				"before_hash": _content_hash(json.dumps(before_schema, sort_keys=True)),
				"after_hash": _content_hash(json.dumps(after_schema, sort_keys=True)) if after_schema is not None else "",
				"issues_json": json.dumps(issues or [], separators=(",", ":")),
				"error": (error or "")[:2000],
				"user": frappe.session.user,
			}
		)
		run.insert(ignore_permissions=True)
		return run.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Email Builder AI Run log failed")
		return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def create_template_with_ai(prompt, template_name=None, subject=None, reference_doctype=None):
	"""Build a complete visual email template from scratch using AI without requiring
	the user to create an Email Template document first.

	Creates the Email Template record with visual mode, saves initial chat history,
	and returns the route to directly open the builder with the newly generated design.
	"""
	_require_designer()
	frappe.has_permission("Email Template", "create", throw=True)

	settings = _settings()
	prompt = str(prompt or "").strip()
	if not prompt:
		frappe.throw(_("Describe the email template you want to create."))
	if len(prompt) > MAX_PROMPT_CHARS:
		frappe.throw(_("Your instructions are too long. Keep them under {0} characters.").format(MAX_PROMPT_CHARS))

	agent_name = _generator_agent(settings)
	if not _ai_enabled(settings) or not agent_name:
		frappe.throw(_("AI generation is not enabled or configured in Followup Settings."))

	starter_schema = validate_schema(None)

	starter_context = {
		"user_prompt": prompt,
		"current_schema": json.dumps(starter_schema, separators=(",", ":")),
		"current_settings": json.dumps(starter_schema.get("settings", {}), separators=(",", ":")),
		"subject": str(subject or "").strip(),
		"preheader": "",
		"reference_doctype": str(reference_doctype or "").strip(),
		"block_types": ", ".join(sorted(BLOCK_TYPES)),
		"layouts": ", ".join(LAYOUTS.keys()),
		"available_images": "(Brand new template. Use the `generate_email_image` tool if visuals, hero banners, or photos are needed.)",
		"current_palette": "(Choose a modern, high-contrast, visually pleasing palette matching the requested email topic)",
		"chat_history": "(New template creation from scratch)",
		"company_name": _brand_name(),
	}

	callback_name = str(template_name or "New Template")
	callback_handler = EmailBuilderThinkingCallback(callback_name, frappe.session.user)

	try:
		raw = _invoke_rewrite_agent(agent_name, prompt, starter_context, callback_handler=callback_handler)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), f"Email Builder AI generation failed - {agent_name}")
		frappe.throw(_("The AI agent could not generate the template: {0}").format(str(exc)[:250]))

	payload = _coerce_ai_payload(raw)
	ai_schema = _extract_schema(payload)
	proposed_schema = ai_schema

	proposed_subject = str(payload.get("subject") or subject or "").strip()
	summary = str(payload.get("summary") or "")[:1000]
	change_notes = _string_list(payload.get("change_notes"))

	# Determine clean, unique template name
	final_template_name = str(template_name or "").strip()[:140]
	if not final_template_name:
		source_title = proposed_subject or prompt[:40]
		base_name = re.sub(r"[^a-zA-Z0-9\s\-]", "", source_title).strip()
		if not base_name:
			base_name = "AI Email Template"
		base_name = base_name[:50].strip()

		candidate = base_name
		counter = 1
		while frappe.db.exists("Email Template", candidate):
			counter += 1
			candidate = f"{base_name} {counter}"
		final_template_name = candidate
	else:
		if frappe.db.exists("Email Template", final_template_name):
			frappe.throw(_("Email Template {0} already exists").format(frappe.bold(final_template_name)))

	if not proposed_subject:
		proposed_subject = final_template_name

	img_warnings = _resolve_generated_images(proposed_schema, template_name=final_template_name)

	# Repair the conventions the agent reliably gets wrong (block alignment,
	# section padding, single-braced merge tokens, social platform names)
	# before anything is compiled or persisted.
	defaults_stats, defaults_warnings = _apply_defaults_with_warnings(proposed_schema)

	raw_warnings = _string_list(payload.get("warnings")) + img_warnings + defaults_warnings
	warnings = [w.strip() for w in raw_warnings if str(w or "").strip()]

	proposed_preheader = str(payload.get("preheader") or "")

	proposed_subject, _subject_fixes = repair_text(proposed_subject)
	proposed_preheader, _preheader_fixes = repair_text(proposed_preheader)

	proposed_schema, _schema_removed = _sanitize_schema_tokens(proposed_schema)
	proposed_subject, _subject_removed = _sanitize_token_text(proposed_subject)
	proposed_preheader, _preheader_removed = _sanitize_token_text(proposed_preheader)

	subject_source = validate_semantic_tokens(proposed_subject[:140])
	compiled_subject = _compiled_subject(subject_source)
	validate_template(compiled_subject)

	state = _render_builder_request(
		proposed_schema,
		{"subject": subject_source, "preheader": proposed_preheader, "validate_dynamic_fields": 0},
	)
	normalized_schema = state["schema"]
	compiled = state["compiled"]
	validate_template(compiled["html"])
	issues = compiled.get("issues") or []

	doc = frappe.get_doc({
		"doctype": "Email Template",
		"name": final_template_name,
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

	proposal_id = _log_run(
		final_template_name, prompt, agent_name, starter_schema, normalized_schema,
		summary, change_notes, warnings, issues, status="Success",
	)

	result_payload = {
		"proposal_id": proposal_id,
		"scope": "template",
		"target_kind": "template",
		"target_id": "",
		"summary": summary,
		"schema": normalized_schema,
		"metadata": {
			"subject": state["subject_source"],
			"preheader": state["preheader"],
		},
		"change_notes": change_notes,
		"warnings": warnings,
		"preview_html": _format_preview_html(state["subject"], state["html_content"]),
		"preview_subject": state["subject"],
		"issues": issues,
		"repairs": defaults_stats,
	}

	# Seed initial conversation in Email Builder AI Chat
	timestamp = int(frappe.utils.now_datetime().timestamp() * 1000)
	user_turn = {"id": f"u-{timestamp}", "role": "user", "text": prompt}
	assistant_turn = {
		"id": proposal_id or f"a-{timestamp}",
		"role": "assistant",
		"text": summary or _("Here is your newly generated email template:"),
		"proposal": result_payload,
		"status": "accepted",
	}
	_save_chat_history(final_template_name, [user_turn, assistant_turn])

	return {
		"name": doc.name,
		"route": f"/builder?template={quote(doc.name, safe='')}",
		"subject": compiled_subject,
		"summary": summary,
	}


@frappe.whitelist(methods=["POST"])
def generate_ai_rewrite(template_name, schema, metadata=None, prompt=None, chat_history=None, scope="template", section_id=None):
	"""Generate an AI rewrite proposal for the current builder document.

	Returns a validated, compiled proposal. Nothing is persisted to the
	Email Template - the builder applies it locally (undoable) and the user
	saves through the normal path.
	"""
	doc = _template(template_name)

	settings = _settings()
	prompt = str(prompt or "").strip()
	if not prompt:
		frappe.throw(_("Describe what you want the AI to change."))
	if len(prompt) > MAX_PROMPT_CHARS:
		frappe.throw(_("Your instructions are too long. Keep them under {0} characters.").format(MAX_PROMPT_CHARS))

	current_schema = parse_json(schema, label="builder schema", max_bytes=MAX_SCHEMA_BYTES)
	metadata = frappe.parse_json(metadata) if isinstance(metadata, str) else (metadata or {})
	if not isinstance(metadata, dict):
		metadata = {}

	agent_name = _rewrite_agent(settings)
	if not _ai_enabled(settings) or not agent_name:
		frappe.throw(_("AI rewriting is not enabled or configured in Followup Settings."))

	context = _agent_context(
		doc, current_schema, metadata, prompt, chat_history=chat_history,
		scope=scope, section_id=section_id,
	)

	callback_handler = EmailBuilderThinkingCallback(template_name, frappe.session.user)
	try:
		raw = _invoke_rewrite_agent(agent_name, prompt, context, callback_handler=callback_handler)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), f"Email Builder AI rewrite failed - {agent_name}")
		_log_run(
			template_name, prompt, agent_name, current_schema, None, "", [], [], [],
			status="Failed", error=str(exc),
		)
		# Persist error turn so the UI conversation thread remains intact
		try:
			error_msg = _("The AI agent could not complete the rewrite: {0}").format(str(exc)[:200])
			timestamp = int(frappe.utils.now_datetime().timestamp() * 1000)
			existing = _get_saved_chat_history(template_name)
			_save_chat_history(template_name, existing + [
				{"id": f"u-{timestamp}", "role": "user", "text": prompt},
				{"id": f"e-{timestamp}", "role": "assistant", "text": error_msg, "isError": True},
			])
		except Exception:
			pass
		frappe.throw(error_msg)

	try:
		payload = _coerce_ai_payload(raw)
		ai_schema = _extract_schema(payload)
	except frappe.ValidationError as exc:
		# The AI returned something unreadable (e.g. a refusal or malformed JSON).
		# Persist the error turn so the conversation thread is visible on next open.
		try:
			err_text = str(exc)
			timestamp = int(frappe.utils.now_datetime().timestamp() * 1000)
			existing = _get_saved_chat_history(template_name)
			_save_chat_history(template_name, existing + [
				{"id": f"u-{timestamp}", "role": "user", "text": prompt},
				{"id": f"e-{timestamp}", "role": "assistant", "text": err_text, "isError": True},
			])
		except Exception:
			pass
		raise

	proposed_schema = ai_schema
	img_warnings = _resolve_generated_images(proposed_schema, template_name=template_name)

	# Repair the conventions the agent reliably gets wrong (block alignment,
	# section padding, single-braced merge tokens, social platform names)
	# before anything is compiled or persisted.
	defaults_stats, defaults_warnings = _apply_defaults_with_warnings(proposed_schema)

	summary = str(payload.get("summary") or "")[:1000]
	change_notes = _string_list(payload.get("change_notes"))
	raw_warnings = _string_list(payload.get("warnings")) + img_warnings + defaults_warnings
	warnings = []
	for w in raw_warnings:
		w_clean = str(w or "").strip()
		if w_clean and w_clean not in warnings:
			warnings.append(w_clean)

	proposed_subject = str(payload.get("subject") or metadata.get("subject") or _subject_source(doc) or "")
	proposed_preheader = str(payload.get("preheader") or metadata.get("preheader") or "")
	proposed_subject, _subject_fixes = repair_text(proposed_subject)
	proposed_preheader, _preheader_fixes = repair_text(proposed_preheader)

	# Strip any unsupported Jinja the agent may have invented so a single bad
	# token cannot crash the whole proposal. Valid merge tokens are preserved.
	proposed_schema, removed_schema = _sanitize_schema_tokens(proposed_schema)
	proposed_subject, removed_subject = _sanitize_token_text(proposed_subject)
	proposed_preheader, removed_preheader = _sanitize_token_text(proposed_preheader)
	if removed_schema + removed_subject + removed_preheader:
		msg = _("Removed unsupported dynamic fields the AI introduced. Re-add merge fields from the inspector if needed.")
		if msg not in warnings:
			warnings.append(msg)

	# Validate + compile through the SAME path as preview/save. This normalizes /
	# rejects anything unsupported. We skip dynamic-field validation for the
	# proposal preview so an AI-introduced token cannot block the review; the
	# canonical save path re-validates strictly on Accept + Save.
	preview_metadata = {
		"subject": proposed_subject,
		"preheader": proposed_preheader,
		"validate_dynamic_fields": 0,
	}
	try:
		state = _render_builder_request(proposed_schema, preview_metadata)
	except Exception as exc:
		_log_run(
			template_name, prompt, agent_name, current_schema, proposed_schema,
			summary, change_notes, warnings, [], status="Rejected", error=str(exc),
		)
		# Persist error turn so the UI conversation thread remains intact
		try:
			error_msg = _("The AI produced a design the builder cannot use: {0}").format(str(exc))
			timestamp = int(frappe.utils.now_datetime().timestamp() * 1000)
			existing = _get_saved_chat_history(template_name)
			_save_chat_history(template_name, existing + [
				{"id": f"u-{timestamp}", "role": "user", "text": prompt},
				{"id": f"e-{timestamp}", "role": "assistant", "text": error_msg, "isError": True},
			])
		except Exception:
			pass
		frappe.throw(error_msg)

	normalized_schema = state["schema"]
	compiled = state["compiled"]
	preview_html = _format_preview_html(state["subject"], state["html_content"])
	issues = compiled.get("issues") or []

	# Render the "before" from the client's current (possibly unsaved) schema so
	# the UI can show a true before/after without extra round-trips.
	before_html, before_subject = "", ""
	try:
		before_state = _render_builder_request(
			current_schema,
			{
				"subject": metadata.get("subject") or _subject_source(doc),
				"preheader": metadata.get("preheader") or "",
				"validate_dynamic_fields": 0,
			},
		)
		before_html = _format_preview_html(before_state["subject"], before_state["html_content"])
		before_subject = before_state["subject"]
	except Exception:
		frappe.clear_last_message()

	proposal_id = _log_run(
		template_name, prompt, agent_name, current_schema, normalized_schema,
		summary, change_notes, warnings, issues, status="Success",
	)

	result_payload = {
		"proposal_id": proposal_id,
		"scope": "template",
		"target_kind": "template",
		"target_id": "",
		"summary": summary,
		"schema": normalized_schema,
		"metadata": {
			"subject": state["subject_source"],
			"preheader": state["preheader"],
		},
		"change_notes": change_notes,
		"warnings": warnings + [issue["message"] for issue in issues if issue.get("severity") == "warning"],
		"preview_html": preview_html,
		"preview_subject": state["subject"],
		"before_html": before_html,
		"before_subject": before_subject,
		"issues": issues,
		"repairs": defaults_stats,
		"thinking_steps": callback_handler.steps,
	}

	# Persist conversation turn to Email Builder AI Chat
	try:
		existing_turns = _get_saved_chat_history(template_name)
		timestamp = int(frappe.utils.now_datetime().timestamp() * 1000)
		user_turn = {"id": f"u-{timestamp}", "role": "user", "text": prompt}
		assistant_turn = {
			"id": proposal_id or f"a-{timestamp}",
			"role": "assistant",
			"text": summary or "Here is the proposal:",
			"proposal": result_payload,
			"status": "pending",
		}
		_save_chat_history(template_name, existing_turns + [user_turn, assistant_turn])
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Save Email Builder AI Chat history failed")

	return result_payload


@frappe.whitelist(methods=["POST"])
def accept_ai_proposal(proposal_id: str, template_name: str | None = None):
	"""Mark an AI proposal as accepted (audit only; no template mutation)."""
	_require_designer()
	accepted = False
	if proposal_id and frappe.db.exists("Email Builder AI Run", proposal_id):
		frappe.db.set_value(
			"Email Builder AI Run",
			proposal_id,
			{"accepted": 1, "accepted_on": frappe.utils.now_datetime()},
			update_modified=False,
		)
		accepted = True
	if template_name:
		try:
			turns = _get_saved_chat_history(template_name)
			updated = False
			for turn in turns:
				p = turn.get("proposal")
				if p and (turn.get("id") == proposal_id or (isinstance(p, dict) and p.get("proposal_id") == proposal_id)):
					turn["status"] = "accepted"
					updated = True
			if updated:
				_save_chat_history(template_name, turns)
				accepted = True
		except Exception:
			pass
	return {"ok": accepted}


@frappe.whitelist(methods=["POST"])
def clear_builder_ai_chat(template_name):
	"""Clear saved chat history for current template and user."""
	_require_designer()
	if not template_name or not frappe.db.exists("DocType", "Email Builder AI Chat"):
		return {"ok": True}
	name = _chat_doc_name(template_name)
	if frappe.db.exists("Email Builder AI Chat", name):
		frappe.db.delete("Email Builder AI Chat", name)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def get_ai_run_preview(proposal_id: str):
	"""Return the rendered before/after preview and schema for a historic AI run."""
	_require_designer()
	proposal_id = (proposal_id or "").strip()
	if not proposal_id or not frappe.db.exists("Email Builder AI Run", proposal_id):
		frappe.throw(_("AI proposal record not found."), frappe.DoesNotExistError)

	run = frappe.get_doc("Email Builder AI Run", proposal_id)
	doc = _template(run.template)

	before_schema = json.loads(run.before_schema_json) if run.before_schema_json else None
	after_schema = json.loads(run.after_schema_json) if run.after_schema_json else None

	before_html, before_subject = "", ""
	if before_schema:
		try:
			before_state = _render_builder_request(
				before_schema,
				{"subject": _subject_source(doc), "validate_dynamic_fields": 0},
			)
			before_html = _format_preview_html(before_state["subject"], before_state["html_content"])
			before_subject = before_state["subject"]
		except Exception:
			frappe.clear_last_message()

	preview_html, preview_subject = "", ""
	if after_schema:
		try:
			after_state = _render_builder_request(
				after_schema,
				{"subject": _subject_source(doc), "validate_dynamic_fields": 0},
			)
			preview_html = _format_preview_html(after_state["subject"], after_state["html_content"])
			preview_subject = after_state["subject"]
		except Exception:
			frappe.clear_last_message()

	change_notes = [n.strip() for n in (run.change_notes or "").split("\n") if n.strip()]
	warnings = [w.strip() for w in (run.warnings or "").split("\n") if w.strip()]

	return {
		"proposal_id": run.name,
		"scope": "template",
		"target_kind": "template",
		"target_id": "",
		"summary": run.summary or "",
		"schema": after_schema,
		"metadata": {
			"subject": preview_subject or before_subject or _subject_source(doc),
			"preheader": "",
		},
		"change_notes": change_notes,
		"warnings": warnings,
		"preview_html": preview_html,
		"preview_subject": preview_subject,
		"before_html": before_html,
		"before_subject": before_subject,
		"issues": json.loads(run.issues_json) if run.issues_json else [],
		"status": "accepted" if run.accepted else ("rejected" if run.status == "Rejected" else "pending"),
	}
