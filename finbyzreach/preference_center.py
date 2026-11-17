"""Preference center page design (CS-05, CS-06): texts per language, styles, theme, sections.

Marketing edits a draft in the desk page and publishes it; the public page
/manage_subscriptions renders only the published version. Everything stored here is
validated to plain values, because the public page renders it to anonymous visitors.
"""
from __future__ import annotations

import copy
import json
import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

SETTINGS = "Subscription Center Settings"
LANGUAGES = ("de", "fr", "it", "en")
SECTIONS = ("intro", "types", "topics", "buttons", "foot")
FONTS = {
	"Inter": '"Inter", Arial, sans-serif',
	"Arial": "Arial, Helvetica, sans-serif",
	"Georgia": "Georgia, serif",
	"Roboto": '"Roboto", Arial, sans-serif',
}
WIDTHS = (480, 560, 640, 720)
TAGS = ("H1", "H2", "H3", "P")
ALIGN = ("left", "center", "right")
NAMED_COLOURS = ("primary", "text", "muted", "white")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_CUSTOM_BLOCKS = 10

# Editable in place on the page. Message texts (saving, error, ...) are edited in a list.
PAGE_TEXTS = ("h", "s", "mailing", "top", "save", "all", "foot")
MESSAGE_TEXTS = ("language", "current", "waiting", "pending", "saving", "error", "subscribed", "invalid")

DEFAULT_TEXTS = {
	"de": {"h": "E-Mail-Abonnements aktualisieren", "s": "Wählen Sie die Mitteilungen aus, die Sie von Megasol erhalten möchten.",
		"mailing": "E-Mail-Arten", "top": "Themen", "save": "Einstellungen speichern", "all": "Von allen Marketing-E-Mails abmelden",
		"foot": "Megasol Energie AG", "language": "Sprache", "current": "Aktuelles Thema", "waiting": "Bestätigung ausstehend",
		"pending": "Neue Abonnements müssen per E-Mail bestätigt werden.", "saving": "Speichern...",
		"error": "Die Einstellungen konnten nicht gespeichert werden.", "subscribed": "Ihre Abonnements wurden aktualisiert.",
		"invalid": "Dieser Link ist ungültig. Bitte verwenden Sie den Link in Ihrer E-Mail."},
	"fr": {"h": "Mettre à jour vos abonnements", "s": "Choisissez les e-mails que vous souhaitez recevoir de Megasol.",
		"mailing": "Types d'e-mails", "top": "Thèmes", "save": "Enregistrer", "all": "Se désabonner de tous les e-mails marketing",
		"foot": "Megasol Energie SA", "language": "Langue", "current": "Thème actuel", "waiting": "Confirmation en attente",
		"pending": "Confirmez les nouveaux abonnements par e-mail.", "saving": "Enregistrement...",
		"error": "Vos préférences n'ont pas pu être enregistrées.", "subscribed": "Vos abonnements ont été mis à jour.",
		"invalid": "Ce lien n'est pas valide. Veuillez utiliser le lien de votre e-mail."},
	"it": {"h": "Aggiorna i tuoi abbonamenti email", "s": "Scegli quali email desideri ricevere da Megasol.",
		"mailing": "Tipi di email", "top": "Temi", "save": "Salva", "all": "Annulla l'iscrizione a tutte le email di marketing",
		"foot": "Megasol Energie SA", "language": "Lingua", "current": "Tema attuale", "waiting": "Conferma in attesa",
		"pending": "Conferma i nuovi abbonamenti tramite email.", "saving": "Salvataggio...",
		"error": "Impossibile salvare le preferenze.", "subscribed": "I tuoi abbonamenti sono stati aggiornati.",
		"invalid": "Questo link non è valido. Usa il link contenuto nella tua email."},
	"en": {"h": "Update your email subscriptions", "s": "Choose the emails you would like to receive from Megasol.",
		"mailing": "Email types", "top": "Topics", "save": "Save preferences", "all": "Unsubscribe from all marketing emails",
		"foot": "Megasol Energie AG", "language": "Language", "current": "Current topic", "waiting": "Confirmation pending",
		"pending": "Please confirm new subscriptions using the email we send you.", "saving": "Saving...",
		"error": "Your preferences could not be saved.", "subscribed": "Your subscriptions have been updated.",
		"invalid": "This preference link is invalid. Please use the link in your email."},
}
DEFAULT_STYLES = {
	"h": {"tag": "H1", "size": 24, "color": "primary", "bold": True, "align": "left"},
	"s": {"tag": "P", "size": 14, "color": "muted", "bold": False, "align": "left"},
	"mailing": {"tag": "H3", "size": 13, "color": "text", "bold": True, "align": "left"},
	"top": {"tag": "H3", "size": 13, "color": "text", "bold": True, "align": "left"},
	"save": {"tag": "P", "size": 14, "color": "white", "bold": True, "align": "left"},
	"all": {"tag": "P", "size": 13, "color": "primary", "bold": False, "align": "left"},
	"foot": {"tag": "P", "size": 12, "color": "muted", "bold": False, "align": "left"},
}
CUSTOM_STYLE = {"tag": "P", "size": 14, "color": "text", "bold": False, "align": "left"}
PRESETS = {
	"navy": {"primary": "#0f2f4f", "button": "#0f2f4f", "background": "#f4f6f8", "card": "#ffffff", "text": "#1f2933"},
	"solar": {"primary": "#0f2f4f", "button": "#d98d0c", "background": "#fdf6ea", "card": "#ffffff", "text": "#1f2933"},
	"neutral": {"primary": "#171717", "button": "#171717", "background": "#f3f3f3", "card": "#ffffff", "text": "#171717"},
}


SUBSCRIBE_TEXTS = {
	"de": {"h": "Newsletter und E-Mails abonnieren", "s": "Wählen Sie, welche E-Mails Sie von Megasol erhalten möchten.",
		"mailing": "E-Mail-Arten", "top": "Themen", "register": "Abonnieren",
		"legal": "Mit dem Abonnieren akzeptieren Sie unsere Datenschutzerklärung. Sie können sich jederzeit abmelden.", "foot": "Megasol Energie AG",
		"first_name": "Vorname", "last_name": "Nachname", "email": "E-Mail", "language": "Sprache",
		"choose": "Bitte wählen Sie mindestens eine Option.", "pending": "Fast geschafft: Bitte bestätigen Sie Ihr Abonnement über den Link in der E-Mail, die wir Ihnen gesendet haben.",
		"subscribed": "Vielen Dank, Ihr Abonnement ist aktiv.", "error": "Ihre Anmeldung konnte nicht gespeichert werden. Bitte versuchen Sie es erneut."},
	"fr": {"h": "S'abonner aux e-mails", "s": "Choisissez les e-mails que vous souhaitez recevoir de Megasol.",
		"mailing": "Types d'e-mails", "top": "Thèmes", "register": "S'abonner",
		"legal": "En vous abonnant, vous acceptez notre politique de confidentialité. Vous pouvez vous désabonner à tout moment.", "foot": "Megasol Energie SA",
		"first_name": "Prénom", "last_name": "Nom", "email": "E-mail", "language": "Langue",
		"choose": "Veuillez choisir au moins une option.", "pending": "Presque terminé : veuillez confirmer votre abonnement via le lien de l'e-mail que nous vous avons envoyé.",
		"subscribed": "Merci, votre abonnement est actif.", "error": "Votre inscription n'a pas pu être enregistrée. Veuillez réessayer."},
	"it": {"h": "Iscriviti alle email", "s": "Scegli quali email desideri ricevere da Megasol.",
		"mailing": "Tipi di email", "top": "Temi", "register": "Iscriviti",
		"legal": "Iscrivendoti accetti la nostra informativa sulla privacy. Puoi annullare l'iscrizione in qualsiasi momento.", "foot": "Megasol Energie SA",
		"first_name": "Nome", "last_name": "Cognome", "email": "E-mail", "language": "Lingua",
		"choose": "Scegli almeno un'opzione.", "pending": "Quasi fatto: conferma la tua iscrizione tramite il link nell'email che ti abbiamo inviato.",
		"subscribed": "Grazie, la tua iscrizione è attiva.", "error": "Non è stato possibile salvare l'iscrizione. Riprova."},
	"en": {"h": "Subscribe to our emails", "s": "Choose the emails you would like to receive from Megasol.",
		"mailing": "Email types", "top": "Topics", "register": "Subscribe",
		"legal": "By subscribing you accept our privacy policy. You can unsubscribe at any time.", "foot": "Megasol Energie AG",
		"first_name": "First name", "last_name": "Last name", "email": "Email", "language": "Language",
		"choose": "Please choose at least one option.", "pending": "Almost done: please confirm your subscription using the link in the email we sent you.",
		"subscribed": "Thank you, your subscription is active.", "error": "Your sign-up could not be saved. Please try again."},
}
CONFIRM_TEXTS = {
	"de": {"h": "Abonnement bestätigen", "s": "Bitte bestätigen Sie, dass Sie diese E-Mails erhalten möchten.", "button": "Abonnement bestätigen",
		"foot": "Megasol Energie AG", "done": "Vielen Dank. Ihr Abonnement ist bestätigt.", "invalid": "Dieser Bestätigungslink ist ungültig oder abgelaufen."},
	"fr": {"h": "Confirmer l'abonnement", "s": "Veuillez confirmer que vous souhaitez recevoir ces e-mails.", "button": "Confirmer l'abonnement",
		"foot": "Megasol Energie SA", "done": "Merci. Votre abonnement est confirmé.", "invalid": "Ce lien de confirmation n'est pas valide ou a expiré."},
	"it": {"h": "Conferma l'iscrizione", "s": "Conferma di voler ricevere queste email.", "button": "Conferma iscrizione",
		"foot": "Megasol Energie SA", "done": "Grazie. La tua iscrizione è confermata.", "invalid": "Questo link di conferma non è valido o è scaduto."},
	"en": {"h": "Confirm your subscription", "s": "Please confirm that you want to receive these emails.", "button": "Confirm subscription",
		"foot": "Megasol Energie AG", "done": "Thank you. Your subscription is confirmed.", "invalid": "This confirmation link is invalid or has expired."},
}
BUTTON_STYLE = {"tag": "P", "size": 14, "color": "white", "bold": True, "align": "left"}
SMALL_STYLE = {"tag": "P", "size": 12, "color": "muted", "bold": False, "align": "left"}

# One spec per editable page. The preference center keeps its keys at the top level
# of the design (backwards compatible); the other pages live under their own key.
PAGES = {
	"manage": {"sections": SECTIONS, "page_texts": PAGE_TEXTS, "message_texts": MESSAGE_TEXTS,
		"texts": DEFAULT_TEXTS, "styles": DEFAULT_STYLES},
	"subscribe": {"sections": ("intro", "names", "email", "types", "topics", "legal", "buttons", "foot"),
		"page_texts": ("h", "s", "mailing", "top", "register", "legal", "foot"),
		"message_texts": ("first_name", "last_name", "email", "language", "choose", "pending", "subscribed", "error"),
		"texts": SUBSCRIBE_TEXTS, "required": ("email", "buttons"),
		"styles": {"h": DEFAULT_STYLES["h"], "s": DEFAULT_STYLES["s"], "mailing": DEFAULT_STYLES["mailing"],
			"top": DEFAULT_STYLES["top"], "register": BUTTON_STYLE, "legal": SMALL_STYLE, "foot": SMALL_STYLE}},
	"confirm": {"sections": ("intro", "button", "foot"), "page_texts": ("h", "s", "button", "foot"),
		"message_texts": ("done", "invalid"), "texts": CONFIRM_TEXTS, "required": ("button",),
		"styles": {"h": DEFAULT_STYLES["h"], "s": DEFAULT_STYLES["s"], "button": BUTTON_STYLE, "foot": SMALL_STYLE}},
}


def _default_page(page):
	spec = PAGES[page]
	return {"order": list(spec["sections"]), "hidden": [], "custom": [],
		"texts": copy.deepcopy(spec["texts"]), "styles": copy.deepcopy(spec["styles"])}


def default_config():
	return {
		"theme": {**PRESETS["solar"], "font": "Inter", "width": 560, "radius": 6, "logo": ""},
		"show_descriptions": 1,
		"show_topics": 1,
		"order": list(SECTIONS),
		"hidden": [],
		"custom": [],  # ids of extra text blocks, e.g. ["c1"]
		"texts": copy.deepcopy(DEFAULT_TEXTS),
		"styles": copy.deepcopy(DEFAULT_STYLES),
		"subscribe": _default_page("subscribe"),
		"confirm": _default_page("confirm"),
	}


def _legacy_texts():
	"""Older sites kept page texts in the Subscription Center Translation table."""
	mapping = {"title": "h", "intro": "s", "mailing": "mailing", "topics": "top", "save": "save", "current": "current",
		"pending": "pending", "waiting": "waiting", "saving": "saving", "error": "error"}
	result = {}
	try:
		rows = frappe.get_all("Subscription Center Translation", filters={"parent": SETTINGS},
			fields=["language", *mapping], limit_page_length=0)
	except Exception:
		return result
	for row in rows if isinstance(rows, list) else []:
		if row.language in LANGUAGES:
			result[row.language] = {mapping[key]: row[key] for key in mapping if row.get(key)}
	return result


def _plain(value, limit=2000):
	return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or ""))[:limit]


def _clean_page(base, raw, spec):
	"""Order, hidden sections, extra text blocks, texts and styles of one page (in place)."""
	sections, page_texts, message_texts = tuple(spec["sections"]), tuple(spec["page_texts"]), tuple(spec["message_texts"])
	custom = [c for c in (raw.get("custom") or []) if isinstance(c, str) and re.fullmatch(r"c\d{1,3}", c)]
	base["custom"] = list(dict.fromkeys(custom))[:MAX_CUSTOM_BLOCKS]
	allowed_sections = set(sections) | set(base["custom"])
	order = [key for key in (raw.get("order") or []) if key in allowed_sections]
	base["order"] = list(dict.fromkeys(order + [key for key in sections + tuple(base["custom"]) if key not in order]))
	# Sections a page cannot work without (e.g. the email field) can never be hidden.
	base["hidden"] = [key for key in dict.fromkeys(raw.get("hidden") or []) if key in allowed_sections
		and key not in spec.get("required", ())]
	text_keys = page_texts + message_texts + tuple(base["custom"])
	texts = raw.get("texts") if isinstance(raw.get("texts"), dict) else {}
	for lang in LANGUAGES:
		given = texts.get(lang) if isinstance(texts.get(lang), dict) else {}
		for key in text_keys:
			if key in given:
				base["texts"][lang][key] = _plain(given[key])
			elif key in base["custom"]:
				base["texts"][lang].setdefault(key, "")
	styles = raw.get("styles") if isinstance(raw.get("styles"), dict) else {}
	for key in page_texts + tuple(base["custom"]):
		given = styles.get(key) if isinstance(styles.get(key), dict) else {}
		style = dict(spec["styles"].get(key, CUSTOM_STYLE))
		if given.get("tag") in TAGS:
			style["tag"] = given["tag"]
		if "size" in given:
			style["size"] = max(10, min(cint(given["size"]), 40))
		colour = given.get("color")
		if colour in NAMED_COLOURS or (isinstance(colour, str) and HEX.match(colour)):
			style["color"] = colour
		if "bold" in given:
			style["bold"] = bool(given["bold"])
		if given.get("align") in ALIGN:
			style["align"] = given["align"]
		base["styles"][key] = style
	return base


def clean_config(value):
	"""Accept only known keys and safe values; unknown input falls back to the defaults."""
	raw = frappe.parse_json(value) if isinstance(value, str) else (value or {})
	if not isinstance(raw, dict):
		frappe.throw(_("Invalid preference center design"))
	base = default_config()
	theme = raw.get("theme") if isinstance(raw.get("theme"), dict) else {}
	for key in ("primary", "button", "background", "card", "text"):
		if isinstance(theme.get(key), str) and HEX.match(theme[key]):
			base["theme"][key] = theme[key]
	if theme.get("font") in FONTS:
		base["theme"]["font"] = theme["font"]
	if cint(theme.get("width")) in WIDTHS:
		base["theme"]["width"] = cint(theme["width"])
	base["theme"]["radius"] = max(0, min(cint(theme.get("radius", 6)), 24))
	logo = str(theme.get("logo") or "")
	# Only public files of this site; never arbitrary external URLs.
	base["theme"]["logo"] = logo if re.match(r"^/files/[^\s\"'<>]+$", logo) else ""
	base["show_descriptions"] = 1 if raw.get("show_descriptions", 1) else 0
	base["show_topics"] = 1 if raw.get("show_topics", 1) else 0
	_clean_page(base, raw, PAGES["manage"])
	for page in ("subscribe", "confirm"):
		_clean_page(base[page], raw.get(page) if isinstance(raw.get(page), dict) else {}, PAGES[page])
	return base


def _load(stored):
	"""A broken stored design must never break the public page: fall back to defaults."""
	if not isinstance(stored, str) or not stored.strip():
		return None
	try:
		return clean_config(stored)
	except Exception:
		frappe.clear_last_message()
		frappe.log_error(title="Invalid preference center design")
		return None


def published_config():
	config = _load(frappe.db.get_single_value(SETTINGS, "published_config_json"))
	if config:
		return config
	config = default_config()
	for lang, values in _legacy_texts().items():
		config["texts"][lang].update(values)
	return config


def draft_config():
	return _load(frappe.db.get_single_value(SETTINGS, "draft_config_json")) or published_config()


def _require_editor():
	frappe.has_permission(SETTINGS, "write", throw=True)


@frappe.whitelist(methods=["GET"])
def get_editor_state():
	_require_editor()
	draft = frappe.db.get_single_value(SETTINGS, "draft_config_json")
	published = frappe.db.get_single_value(SETTINGS, "published_config_json")
	return {
		"config": draft_config(),
		"unpublished_changes": bool(draft) and clean_config(draft) != (clean_config(published) if published else published_config()),
		"published_on": frappe.db.get_single_value(SETTINGS, "published_on"),
		"fonts": list(FONTS), "widths": list(WIDTHS), "presets": PRESETS, "languages": list(LANGUAGES),
		"sections": list(SECTIONS), "page_texts": list(PAGE_TEXTS), "message_texts": list(MESSAGE_TEXTS),
		"pages": {name: {"sections": list(spec["sections"]), "page_texts": list(spec["page_texts"]),
			"message_texts": list(spec["message_texts"]), "required": list(spec.get("required", ()))} for name, spec in PAGES.items()},
	}


@frappe.whitelist(methods=["POST"])
def save_draft(config):
	_require_editor()
	clean = clean_config(config)
	frappe.db.set_single_value(SETTINGS, "draft_config_json", json.dumps(clean, ensure_ascii=False))
	return clean


@frappe.whitelist(methods=["POST"])
def publish(config=None):
	_require_editor()
	clean = clean_config(config) if config else draft_config()
	data = json.dumps(clean, ensure_ascii=False)
	frappe.db.set_single_value(SETTINGS, {"draft_config_json": data, "published_config_json": data, "published_on": now_datetime()})
	return {"published_on": frappe.db.get_single_value(SETTINGS, "published_on")}


@frappe.whitelist(methods=["POST"])
def reset_draft(page=None):
	"""Reset the draft to the built-in defaults: one page, the shared theme, or everything.

	Like any edit this only changes the draft; visitors see it after Publish.
	"""
	_require_editor()
	defaults = default_config()
	if page in (None, "", "all"):
		config = defaults
	elif page == "theme":
		# Shared by all pages: colours, font, width, button radius, logo and display options.
		config = draft_config()
		for key in ("theme", "show_descriptions", "show_topics"):
			config[key] = defaults[key]
	elif page == "manage":
		config = draft_config()
		for key in ("order", "hidden", "custom", "texts", "styles"):
			config[key] = defaults[key]
	elif page in PAGES:
		config = draft_config()
		config[page] = defaults[page]
	else:
		frappe.throw(_("Unknown page"))
	return save_draft(json.dumps(config, ensure_ascii=False))


@frappe.whitelist(methods=["POST"])
def discard_draft():
	_require_editor()
	frappe.db.set_single_value(SETTINGS, "draft_config_json", None)
	return published_config()


def resolve_colour(colour, theme):
	return {"primary": theme["primary"], "text": theme["text"], "muted": "#5d6875", "white": "#ffffff"}.get(colour, colour)


def page_context(config, language, page="manage"):
	"""Values the template needs, with every style already resolved to CSS."""
	language = language if language in LANGUAGES else "de"
	shared = config
	config = config if page == "manage" else {**config[page], "show_descriptions": shared["show_descriptions"], "show_topics": shared["show_topics"]}
	theme = dict(shared["theme"])
	theme["font_css"] = FONTS[theme["font"]]
	css = {}
	for key, style in config["styles"].items():
		css[key] = "font-size:{}px;font-weight:{};color:{};text-align:{}".format(
			style["size"], 700 if style["bold"] else 400, resolve_colour(style["color"], theme), style["align"])
	return {
		"pc": config, "pc_theme": theme, "pc_css": css, "text": config["texts"][language],
		"tags": {key: style["tag"].lower() if style["tag"] != "P" else "p" for key, style in config["styles"].items()},
		"sections": [key for key in config["order"] if key not in config["hidden"]],
	}


def copy_for(language):
	"""Messages for the public pages (subscribe, confirm) from the published design."""
	language = language if language in LANGUAGES else "de"
	return published_config()["texts"][language]


def require_preview():
	"""Editor-only preview of the draft design; guests and readers get a 403."""
	if frappe.session.user == "Guest" or not frappe.has_permission(SETTINGS, "write"):
		raise frappe.PermissionError


def apply_design(context, page, language, preview=False):
	if preview:
		require_preview()
	context.update(page_context(draft_config() if preview else published_config(), language, page))
	context.preview = preview
