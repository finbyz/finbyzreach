import frappe
from frappe.utils.verified_command import get_signed_params

from finbyzreach.subscription_preferences import LANGUAGES, signed_recipient, topic_rows, signed_address, address_urls


COPY = {
	"de": {"title": "E-Mail-Abonnements aktualisieren", "intro": "Wählen Sie die Mitteilungen aus, die Sie erhalten möchten.", "mailing": "E-Mail-Arten", "topics": "Themen", "current": "Aktuelles Thema", "save": "Aktualisieren", "register": "Abonnieren", "pending": "Neue Abonnements müssen per E-Mail bestätigt werden.", "language": "Sprache", "waiting": "Bestätigung ausstehend", "saving": "Speichern...", "error": "Die Einstellungen konnten nicht gespeichert werden."},
	"en": {"title": "Update your email subscriptions", "intro": "Choose the emails you would like to receive.", "mailing": "Email types", "topics": "Topics", "current": "Current topic", "save": "Update", "register": "Subscribe", "pending": "Please confirm new subscriptions using the email we send you.", "language": "Language", "waiting": "Confirmation pending", "saving": "Saving...", "error": "Your preferences could not be saved."},
	"fr": {"title": "Mettre à jour vos abonnements", "intro": "Choisissez les e-mails que vous souhaitez recevoir.", "mailing": "Types d'e-mails", "topics": "Sujets", "current": "Sujet actuel", "save": "Mettre à jour", "register": "S'abonner", "pending": "Confirmez les nouveaux abonnements par e-mail.", "language": "Langue", "waiting": "Confirmation en attente", "saving": "Enregistrement...", "error": "Vos préférences n'ont pas pu être enregistrées."},
	"it": {"title": "Aggiorna i tuoi abbonamenti email", "intro": "Scegli le email che desideri ricevere.", "mailing": "Tipi di email", "topics": "Argomenti", "current": "Argomento attuale", "save": "Aggiorna", "register": "Iscriviti", "pending": "Conferma i nuovi abbonamenti tramite email.", "language": "Lingua", "waiting": "Conferma in attesa", "saving": "Salvataggio...", "error": "Impossibile salvare le preferenze."},
}


def get_copy(language):
	"""Messages for /subscribe and older callers, taken from the published page design."""
	from finbyzreach.preference_center import copy_for
	language = language if language in COPY else "de"
	copy = COPY[language].copy()
	texts = copy_for(language)
	copy.update({"title": texts["h"], "intro": texts["s"], "mailing": texts["mailing"], "topics": texts["top"],
		"save": texts["save"], "current": texts["current"], "pending": texts["pending"], "waiting": texts["waiting"],
		"saving": texts["saving"], "error": texts["error"], "language": texts["language"], "subscribed": texts["subscribed"]})
	return copy


def _design(context, language, draft=False):
	from finbyzreach.preference_center import draft_config, page_context, published_config
	context.update(page_context(draft_config() if draft else published_config(), language))


def _preview(context):
	"""Desk editor preview: the draft design with sample options; editors only, never saves."""
	if frappe.session.user == "Guest" or not frappe.has_permission("Subscription Center Settings", "write"):
		raise frappe.PermissionError
	language = frappe.form_dict.get("lang") or "de"
	language = language if language in LANGUAGES else "de"
	context.preview = True
	context.email = "name@example.com"
	context.language = language
	context.copy = get_copy(language)
	context.topics = topic_rows(None, language)
	for index, row in enumerate(context.topics):
		row["status"] = "Subscribed" if index % 2 == 0 else "Unknown"
	context.language_urls = {lang: f"/manage_subscriptions?pc_preview=1&lang={lang}" for lang in LANGUAGES}
	context.unsubscribe_all_url = "#"
	_design(context, language, draft=True)
	return context


def get_context(context):
	context.no_cache = True
	if frappe.form_dict.get("pc_preview"):
		return _preview(context)
	try:
		raw = frappe.safe_decode(getattr(frappe.request, "query_string", b""))
		if frappe.form_dict.get("consent_email"):
			email, email_type, values = signed_address(raw)
			language = values.get("lang", ["de"])[0]
			language = language if language in LANGUAGES else "de"
			context.email = email
			context.topics = topic_rows(email, language)
			context.copy = get_copy(language)
			context.language = language
			context.language_urls = {lang: address_urls(email, email_type, lang)["email_preference_center_url"] for lang in LANGUAGES}
			context.unsubscribe_all_url = address_urls(email, email_type, language)["unsubscribe_all_url"]
			_design(context, language)
			return context
		campaign_recipient = frappe.form_dict.get("campaign_recipient")
		recipient, email = signed_recipient(campaign_recipient, raw)
		party_doctype = recipient.get("email_campaign_for") or "Lead"
		if party_doctype not in ("Lead", "Contact", "Customer"):
			raise frappe.ValidationError
		party = frappe.get_doc(party_doctype, recipient.recipient)
		preferred_doc = party
		if party_doctype == "Customer" and recipient.get("custom_contact"):
			from finbyzreach.customer_campaign import contact_for_customer
			if not contact_for_customer(party.name, recipient.custom_contact):
				raise frappe.ValidationError
			preferred_doc = frappe.get_doc("Contact", recipient.custom_contact)
		preferred = (preferred_doc.get("custom_preferred_language") or preferred_doc.get("language")
			or party.get("custom_preferred_language") or party.get("language") or "de").lower()[:2]
		language = frappe.form_dict.get("lang") or preferred
		language = language if language in LANGUAGES else "en"
		campaign = frappe.db.get_value("Campaign", recipient.campaign_name, ["custom_subscription_topic", "custom_content_topic"], as_dict=True)
		current_topic = (campaign.custom_content_topic or campaign.custom_subscription_topic) if campaign else None
		rows = topic_rows(email, language)
		for row in rows:
			row["is_current"] = row["name"] == current_topic
		context.email = email
		context.campaign_recipient = campaign_recipient
		context.unsubscribe_all_url = address_urls(email, campaign.custom_subscription_topic if campaign else "", language)["unsubscribe_all_url"]
		context.topics = rows
		context.copy = get_copy(language)
		context.language = language
		context.language_urls = {
			lang: "/manage_subscriptions?" + get_signed_params({"campaign_recipient": campaign_recipient, "email": email, "lang": lang})
			for lang in LANGUAGES
		}
		_design(context, language)
	except (frappe.PermissionError, frappe.DoesNotExistError, frappe.ValidationError, ValueError):
		language = frappe.form_dict.get("lang") if frappe.form_dict.get("lang") in LANGUAGES else "de"
		_design(context, language)
		context.error_message = context.text["invalid"]
	return context
