from __future__ import annotations

"""Move Email Builder agent prompts between source files and the AI Agent doctype.

The prompts are database rows, which makes them undiffable, unreviewable and
unrecoverable. These helpers treat the files in this directory as the source of
truth and the database as a deployment target.

The escaping this module performs is the point of the whole design. Prompts are
rendered through LangChain's ``ChatPromptTemplate``, which uses f-string syntax:
a literal brace must be doubled or it is read as a variable. Getting that wrong
once already shipped every generated email with broken merge fields, because
``{{ first_name }}`` written in a prompt reaches the model as ``{ first_name }``.

So prompt files are written in plain syntax and escaped mechanically here:

    every { and } in the file  ->  doubled, so it survives as a literal
    <<variable_name>>          ->  {variable_name}, an actual template variable
    <<INCLUDE:name>>           ->  inlined from prompts/_name.md before escaping

You never write an escape by hand, so you cannot get it wrong.
"""

import json
import os
from datetime import datetime

import frappe

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(HERE, "backup")

# Kept in step with _agent_context() / _invoke_rewrite_agent() in ai.py. A
# variable used in a prompt but missing here is a typo, not a feature: the
# runtime would silently fill it with an empty string.
KNOWN_VARIABLES = {
	"user_prompt", "current_schema", "current_settings", "subject", "preheader",
	"reference_doctype", "block_types", "layouts", "available_images",
	"current_palette", "chat_history", "scope_instruction", "query",
	"format_instructions",
}


def _read(relative_path):
	with open(os.path.join(HERE, relative_path), encoding="utf-8") as handle:
		return handle.read()


def _resolve_includes(text, depth=0):
	"""Inline ``<<INCLUDE:name>>`` from ``prompts/_name.md``."""
	if depth > 5:
		frappe.throw("Include depth exceeded in Email Builder prompt files")
	import re

	def replace(match):
		return _resolve_includes(_read(f"prompts/_{match.group(1)}.md"), depth + 1)

	return re.sub(r"<<INCLUDE:([A-Za-z0-9_]+)>>", replace, text)


def render(relative_path):
	"""Return the LangChain-ready prompt body for one source file."""
	import re

	text = _resolve_includes(_read(relative_path))

	unknown = {name for name in re.findall(r"<<([A-Za-z0-9_]+)>>", text)} - KNOWN_VARIABLES
	if unknown:
		frappe.throw(
			f"{relative_path} uses unknown prompt variable(s): {', '.join(sorted(unknown))}. "
			f"Add them to _agent_context() in ai.py and to KNOWN_VARIABLES, or fix the typo."
		)

	# Escape every brace, then re-open only the real variables.
	text = text.replace("{", "{{").replace("}", "}}")
	text = re.sub(r"<<([A-Za-z0-9_]+)>>", r"{\1}", text)
	return text


def _capture():
	"""Write the current DB state to backup/ and return the path."""
	os.makedirs(BACKUP_DIR, exist_ok=True)
	config = json.loads(_read("agents.json"))
	captured = {}
	for name in config:
		if not frappe.db.exists("AI Agent", name):
			continue
		doc = frappe.get_doc("AI Agent", name)
		captured[name] = {
			"llm_provider": doc.llm_provider, "llm": doc.llm,
			"agent_type": doc.agent_type, "temperature": doc.temperature,
			"max_tokens": doc.max_tokens, "output_schema": doc.output_schema,
			"messages": [
				{"idx": m.idx, "type": m.type, "content_type": m.content_type, "content": m.content}
				for m in doc.messages
			],
		}
	path = os.path.join(BACKUP_DIR, f"ai-agents-{datetime.now():%Y%m%d-%H%M%S}.json")
	with open(path, "w", encoding="utf-8") as handle:
		json.dump({"captured": datetime.now().isoformat(), "agents": captured},
		          handle, indent=2, ensure_ascii=False)
	return path


def push(dry_run=False):
	"""Write the source files to the AI Agent doctype.

	Always captures the current state to backup/ first, so a bad push is
	recoverable with restore().
	"""
	config = json.loads(_read("agents.json"))
	backup_path = None if dry_run else _capture()
	report = []

	for name, spec in config.items():
		if not frappe.db.exists("AI Agent", name):
			report.append(f"SKIP   {name} (no such AI Agent)")
			continue

		doc = frappe.get_doc("AI Agent", name)
		changes = []

		for field in ("llm_provider", "llm", "agent_type", "temperature", "max_tokens"):
			if field in spec and doc.get(field) != spec[field]:
				changes.append(f"{field}: {doc.get(field)} -> {spec[field]}")
				if not dry_run:
					doc.set(field, spec[field])

		if spec.get("output_schema"):
			schema_text = json.dumps(json.loads(_read(spec["output_schema"])), indent=2)
			if (doc.output_schema or "").strip() != schema_text.strip():
				old_len = len(doc.output_schema or "")
				changes.append(f"output_schema: {old_len} -> {len(schema_text)} bytes")
				if not dry_run:
					doc.output_schema = schema_text

		rendered = [
			{"type": m["type"], "content_type": m.get("content_type", "text"), "content": render(m["file"])}
			for m in spec.get("messages", [])
		]
		current = [
			{"type": m.type, "content_type": m.content_type, "content": m.content}
			for m in doc.messages
		]
		if rendered != current:
			sizes = " ".join(
				f"{m['type']}:{len(m['content'])}" for m in rendered
			)
			changes.append(f"messages: {len(current)} -> {len(rendered)} ({sizes} chars)")
			if not dry_run:
				doc.messages = []
				for message in rendered:
					doc.append("messages", message)

		if not changes:
			report.append(f"OK     {name} (already current)")
			continue
		if not dry_run:
			doc.save(ignore_permissions=True)
		report.append(("WOULD  " if dry_run else "PUSHED ") + name)
		report.extend(f"         {line}" for line in changes)

	if backup_path:
		report.append(f"\nbacked up to {os.path.relpath(backup_path, HERE)}")
	if not dry_run:
		frappe.db.commit()
	output = "\n".join(report)
	print(output)
	return output


def pull():
	"""Capture the live database state into backup/ without changing anything."""
	path = _capture()
	print(f"captured live agent state to {path}")
	return path


def restore(path):
	"""Restore agents from a backup/ capture."""
	if not os.path.isabs(path):
		path = os.path.join(HERE, path)
	with open(path, encoding="utf-8") as handle:
		payload = json.load(handle)

	restored = []
	for name, spec in (payload.get("agents") or {}).items():
		if not frappe.db.exists("AI Agent", name):
			continue
		doc = frappe.get_doc("AI Agent", name)
		for field in ("llm_provider", "llm", "agent_type", "temperature", "max_tokens", "output_schema"):
			if field in spec:
				doc.set(field, spec[field])
		doc.messages = []
		for message in sorted(spec.get("messages") or [], key=lambda m: m.get("idx", 0)):
			doc.append("messages", {
				"type": message["type"],
				"content_type": message.get("content_type", "text"),
				"content": message["content"],
			})
		doc.save(ignore_permissions=True)
		restored.append(name)
	frappe.db.commit()
	print(f"restored {len(restored)} agent(s) from {os.path.basename(path)}: {', '.join(restored)}")
	return restored
