from __future__ import annotations

"""Deterministic repair and design-default pass for AI-proposed schemas.

The agent writes a builder schema from a natural-language brief. Even a strong
model gets three classes of thing wrong, consistently, because they are
conventions of *this* schema rather than of email design:

1. It puts ``align`` inside ``content`` (where the validator drops it) instead
   of ``block.style.align`` -- so every image and button falls back to the
   compiler's ``left`` default.
2. It omits ``style.padding`` entirely, or emits it as a CSS shorthand string
   which ``_spacing`` cannot read -- so every edge is flush.
3. It writes merge tokens as ``{ doc.field }`` -- single-braced and ``doc.``
   prefixed -- which is neither what ``TOKEN_RE`` matches nor what ``ebv``
   resolves, so every personalised value and link ships broken.

Prompt wording reduces all three but never eliminates them, and a prompt
regression silently reintroduces them. This module fixes them after the fact,
so the floor on output quality is set by code rather than by the model.

Everything here is conservative: a default is applied only where the agent
expressed no preference. Any value the agent (or a human) actually set is left
untouched.
"""

import re

from .constants import ALIGNMENTS, SOCIAL_PLATFORMS

# ---------------------------------------------------------------------------
# Merge-token repair
# ---------------------------------------------------------------------------
# ``{ field }`` or ``{ doc.field }`` -- a single-braced token. Written by agents
# that were shown ``{{ ... }}`` examples through a LangChain f-string template,
# which collapses ``{{`` to ``{`` before the model ever sees it.
_SINGLE_BRACE_TOKEN = re.compile(r"(?<!\{)\{\s*(?:doc\.)?([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*\}(?!\})")

# ``{{ doc.field }}`` -- correctly braced but wrongly prefixed. ``ebv`` reads
# ``doc.field`` as a *link path* and tries to resolve a link field literally
# named ``doc``, which always misses.
_DOC_PREFIXED_TOKEN = re.compile(r"\{\{\s*doc\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*(\|[^}]*)?\}\}")

# A URL that is nothing but a scheme followed by one token, e.g.
# ``https://{{ dashboard_link }}``. The field holds a whole URL, so the literal
# scheme prefix would double up.
_SCHEME_PLUS_TOKEN = re.compile(r"^(?:https?://|mailto:|tel:|sms:)\{\{\s*([^}|]+?)\s*(\|[^}]*)?\}\}$")

# Unfilled copy the agent left behind: "[Your Company Name]", "[Product]", ...
_BRACKET_PLACEHOLDER = re.compile(r"\[(?:[A-Z][A-Za-z]*(?:\s+[A-Za-z]+){0,4})\]")

_LOREM = re.compile(r"\blorem ipsum\b", re.I)


def _repair_token_text(text):
	"""Return (repaired_text, fixed_count) for one string."""
	if not isinstance(text, str) or "{" not in text:
		return text, 0
	fixed = 0

	def _single(match):
		nonlocal fixed
		fixed += 1
		return "{{ %s }}" % match.group(1)

	text = _SINGLE_BRACE_TOKEN.sub(_single, text)

	def _prefixed(match):
		nonlocal fixed
		fixed += 1
		filters = (match.group(2) or "").strip()
		return "{{ %s %s}}" % (match.group(1), filters + " " if filters else "")

	text = _DOC_PREFIXED_TOKEN.sub(_prefixed, text)
	return text, fixed


def _repair_url(value):
	"""Repair a URL field, collapsing ``scheme://{{ token }}`` to ``{{ token }}``."""
	repaired, fixed = _repair_token_text(value)
	if isinstance(repaired, str):
		collapsed = _SCHEME_PLUS_TOKEN.match(repaired.strip())
		if collapsed:
			filters = (collapsed.group(2) or "").strip()
			repaired = "{{ %s %s}}" % (collapsed.group(1), filters + " " if filters else "")
			fixed += 1
	return repaired, fixed


# ---------------------------------------------------------------------------
# Social platform repair
# ---------------------------------------------------------------------------
# ``_validate_block`` tests platform membership exactly and case-sensitively,
# so "facebook" or "Twitter" silently degrade to the generic "Website" globe.
_PLATFORM_ALIASES = {
	"twitter": "X", "x.com": "X", "tweet": "X",
	"fb": "Facebook", "facebook": "Facebook", "meta": "Facebook",
	"ig": "Instagram", "insta": "Instagram", "instagram": "Instagram",
	"linked in": "LinkedIn", "linkedin": "LinkedIn", "li": "LinkedIn",
	"yt": "YouTube", "youtube": "YouTube",
	"tiktok": "TikTok", "tik tok": "TikTok",
	"whatsapp": "WhatsApp", "wa": "WhatsApp",
	"web": "Website", "site": "Website", "homepage": "Website", "website": "Website",
}

_PLATFORM_BY_LOWER = {p.lower(): p for p in SOCIAL_PLATFORMS}

# Recovers the platform from a merge-token field name such as
# ``{{ facebook_link }}`` -- the common shape once tokens are repaired.
_PLATFORM_HINTS = (
	("facebook", "Facebook"), ("instagram", "Instagram"), ("linkedin", "LinkedIn"),
	("youtube", "YouTube"), ("tiktok", "TikTok"), ("whatsapp", "WhatsApp"),
	("twitter", "X"), ("x_link", "X"),
)


def _resolve_platform(raw_platform, href, label):
	"""Best-effort recovery of the intended social platform."""
	candidate = str(raw_platform or "").strip()
	exact = _PLATFORM_BY_LOWER.get(candidate.lower())
	if exact and exact != "Website":
		return exact
	aliased = _PLATFORM_ALIASES.get(candidate.lower())
	if aliased and aliased != "Website":
		return aliased
	# Fall back to whatever the href or label reveals -- covers the case where
	# the validator already collapsed the platform to "Website".
	haystack = f"{href} {label}".lower()
	for needle, platform in _PLATFORM_HINTS:
		if needle in haystack:
			return platform
	return exact or aliased or "Website"


# ---------------------------------------------------------------------------
# Spacing and alignment
# ---------------------------------------------------------------------------
ZERO = {"top": "0px", "right": "0px", "bottom": "0px", "left": "0px"}

# Section insets. Without these the 600px content table runs text to its very
# edge, which is the single most visible "this looks unfinished" tell.
SECTION_PADDING = {"top": "24px", "right": "24px", "bottom": "24px", "left": "24px"}

# Breathing room around a CTA so it does not collide with the copy above it.
BUTTON_PADDING = {"top": "8px", "right": "0px", "bottom": "8px", "left": "0px"}

# Blocks whose alignment the compiler defaults to ``left`` but which read as
# centered in almost every real email design.
_CENTERED_BY_DEFAULT = {"image", "button"}

_TEXT_ALIGN_IN_HTML = re.compile(r"text-align\s*:\s*(left|center|right)", re.I)


def _is_unset(spacing):
	"""True when every side is zero/absent -- i.e. the agent expressed nothing."""
	if not isinstance(spacing, dict) or not spacing:
		return True
	return all(str(v).strip() in ("", "0", "0px", "None") for v in spacing.values())


def _column_text_alignment(column):
	"""Infer a column's intended alignment from the inline CSS of its text blocks.

	The agent reliably expresses alignment for text (it can write
	``text-align`` straight into the HTML) and just as reliably fails to for
	images and buttons. Reading the former lets a mixed column stay coherent
	instead of centering a block the author meant to keep left.
	"""
	votes = {}
	for block in column.get("blocks") or []:
		if not isinstance(block, dict) or block.get("type") != "text":
			continue
		html = ((block.get("content") or {}).get("html")) or ""
		for match in _TEXT_ALIGN_IN_HTML.finditer(html):
			value = match.group(1).lower()
			votes[value] = votes.get(value, 0) + 1
	if not votes:
		return None
	return max(votes.items(), key=lambda item: item[1])[0]


def _apply_block_defaults(block, inherited_align, notes):
	style = block.setdefault("style", {})
	type_ = block.get("type")

	if type_ in _CENTERED_BY_DEFAULT and not style.get("align"):
		style["align"] = inherited_align or "center"
		notes.append(f"{type_}:align={style['align']}")

	if type_ == "button" and _is_unset(style.get("padding")):
		style["padding"] = dict(BUTTON_PADDING)
		notes.append("button:padding")

	# An align the agent did set but spelled wrongly would be dropped by the
	# validator; normalise it here instead of losing it.
	if style.get("align") and style["align"] not in ALIGNMENTS:
		style["align"] = inherited_align or "center"


def apply_design_defaults(schema):
	"""Repair and fill an AI-proposed schema in place.

	Returns a dict of counters describing what was changed, suitable for
	surfacing to the user and for logging on the Email Builder AI Run.
	"""
	stats = {"tokens_repaired": 0, "alignments_set": 0, "sections_padded": 0,
	         "buttons_padded": 0, "social_fixed": 0, "placeholders": []}
	if not isinstance(schema, dict):
		return stats

	notes = []

	for section in schema.get("sections") or []:
		if not isinstance(section, dict):
			continue
		section_style = section.setdefault("style", {})
		if _is_unset(section_style.get("padding")):
			section_style["padding"] = dict(SECTION_PADDING)
			stats["sections_padded"] += 1

		for column in section.get("columns") or []:
			if not isinstance(column, dict):
				continue
			inherited = _column_text_alignment(column)
			for block in column.get("blocks") or []:
				if not isinstance(block, dict):
					continue
				before = len(notes)
				_apply_block_defaults(block, inherited, notes)
				for note in notes[before:]:
					if note.endswith(":padding"):
						stats["buttons_padded"] += 1
					else:
						stats["alignments_set"] += 1

				content = block.get("content")
				if not isinstance(content, dict):
					continue
				if block.get("type") == "social":
					for item in content.get("items") or []:
						if not isinstance(item, dict):
							continue
						resolved = _resolve_platform(item.get("platform"), item.get("href"), item.get("label"))
						if resolved != item.get("platform"):
							old_label = str(item.get("label") or "").strip()
							item["platform"] = resolved
							# "Website" is the label the validator stamps on a
							# collapsed platform; replace it, keep a real one.
							if not old_label or old_label in _PLATFORM_BY_LOWER.values():
								item["label"] = resolved
							stats["social_fixed"] += 1

	# Token repair runs over every string in the document, including the URL
	# fields, so nothing that ships can carry a broken merge field.
	stats["tokens_repaired"] += _repair_tree(schema)
	stats["placeholders"] = _collect_placeholders(schema)
	return stats


_URL_KEYS = {"href", "src"}

# An ``<a href>`` written inside rich text, as opposed to a block's own href
# field. ``sanitize_rich_html`` rejects a bare ``{{ token }}`` here (see
# ``DYNAMIC_SCHEME``): inline anchors are not run through
# ``email_builder_safe_url``, so the literal scheme is what keeps a merge field
# from resolving to ``javascript:``. A block-level href has no such rule
# because ``_url(..., allow_full_token=True)`` accepts a whole token there.
_INLINE_ANCHOR_HREF = re.compile(r'(<a\b[^>]*?\bhref\s*=\s*")([^"]*)(")', re.I)

_SAFE_INLINE_PREFIXES = ("http://", "https://", "mailto:", "tel:", "sms:", "/", "#")


def _fix_inline_anchor_hrefs(html):
	"""Give any inline anchor whose href is a bare token a literal scheme.

	Repairing ``{ doc.blog_link }`` to ``{{ blog_link }}`` inside rich text would
	otherwise turn a link that was merely broken into one that fails validation
	and takes the whole generation down with it.
	"""
	if not isinstance(html, str) or "<a" not in html.lower():
		return html, 0
	fixed = 0

	def replace(match):
		nonlocal fixed
		href = match.group(2).strip()
		if href.startswith("{{") and not href.startswith(_SAFE_INLINE_PREFIXES):
			fixed += 1
			return f"{match.group(1)}https://{href}{match.group(3)}"
		return match.group(0)

	return _INLINE_ANCHOR_HREF.sub(replace, html), fixed


def _repair_tree(node):
	"""Recursively repair merge tokens across the whole schema."""
	fixed = 0
	if isinstance(node, dict):
		for key, value in node.items():
			if isinstance(value, str):
				repaired, count = _repair_url(value) if key in _URL_KEYS else _repair_token_text(value)
				if key == "html":
					repaired, anchor_count = _fix_inline_anchor_hrefs(repaired)
					count += anchor_count
				node[key] = repaired
				fixed += count
			else:
				fixed += _repair_tree(value)
	elif isinstance(node, list):
		for index, item in enumerate(node):
			if isinstance(item, str):
				node[index], count = _repair_token_text(item)
				fixed += count
			else:
				fixed += _repair_tree(item)
	return fixed


def _collect_placeholders(node, found=None):
	"""Collect unfilled copy like ``[Your Company Name]`` so it can be flagged.

	These are not repaired -- the real value is not knowable here -- but
	shipping them silently is worse than telling the user they are there.
	"""
	if found is None:
		found = set()
	if isinstance(node, dict):
		for value in node.values():
			_collect_placeholders(value, found)
	elif isinstance(node, list):
		for item in node:
			_collect_placeholders(item, found)
	elif isinstance(node, str):
		for match in _BRACKET_PLACEHOLDER.finditer(node):
			found.add(match.group(0))
		if _LOREM.search(node):
			found.add("Lorem ipsum")
	return sorted(found)


def repair_text(value):
	"""Public helper for standalone strings such as the subject and preheader."""
	repaired, count = _repair_token_text(value)
	return repaired, count
