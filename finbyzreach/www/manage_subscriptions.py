import frappe
from frappe.utils.verified_command import get_signed_params

from finbyzreach.subscription_preferences import LANGUAGES, signed_recipient, topic_rows


COPY = {
	"de": {"title": "E-Mail-Abonnements aktualisieren", "intro": "Wählen Sie die Mitteilungen aus, die Sie erhalten möchten.", "mailing": "E-Mail-Arten", "topics": "Themen", "current": "Aktuelles Thema", "save": "Aktualisieren", "register": "Abonnieren", "pending": "Neue Abonnements müssen per E-Mail bestätigt werden.", "language": "Sprache", "waiting": "Bestätigung ausstehend", "saving": "Speichern...", "error": "Die Einstellungen konnten nicht gespeichert werden."},
	"en": {"title": "Update your email subscriptions", "intro": "Choose the emails you would like to receive.", "mailing": "Email types", "topics": "Topics", "current": "Current topic", "save": "Update", "register": "Subscribe", "pending": "Please confirm new subscriptions using the email we send you.", "language": "Language", "waiting": "Confirmation pending", "saving": "Saving...", "error": "Your preferences could not be saved."},
	"fr": {"title": "Mettre à jour vos abonnements", "intro": "Choisissez les e-mails que vous souhaitez recevoir.", "mailing": "Types d'e-mails", "topics": "Sujets", "current": "Sujet actuel", "save": "Mettre à jour", "register": "S'abonner", "pending": "Confirmez les nouveaux abonnements par e-mail.", "language": "Langue", "waiting": "Confirmation en attente", "saving": "Enregistrement...", "error": "Vos préférences n'ont pas pu être enregistrées."},
	"it": {"title": "Aggiorna i tuoi abbonamenti email", "intro": "Scegli le email che desideri ricevere.", "mailing": "Tipi di email", "topics": "Argomenti", "current": "Argomento attuale", "save": "Aggiorna", "register": "Iscriviti", "pending": "Conferma i nuovi abbonamenti tramite email.", "language": "Lingua", "waiting": "Conferma in attesa", "saving": "Salvataggio...", "error": "Impossibile salvare le preferenze."},
}


def get_copy(language):
	copy = COPY[language].copy()
	row = frappe.db.get_value(
		"Subscription Center Translation",
		{"parent": "Subscription Center Settings", "language": language},
		["title", "intro", "mailing", "topics", "current", "save", "register", "pending", "waiting", "saving", "error"],
		as_dict=True,
	)
	if row:
		copy.update({key: value for key, value in row.items() if value})
	return copy


def get_context(context):
	context.no_cache = True
	try:
		raw = frappe.safe_decode(getattr(frappe.request, "query_string", b""))
		campaign_recipient = frappe.form_dict.get("campaign_recipient")
		recipient, email = signed_recipient(campaign_recipient, raw)
		lead = frappe.get_doc("Lead", recipient.recipient)
		preferred = (lead.get("custom_preferred_language") or lead.get("language") or "en").lower()[:2]
		language = frappe.form_dict.get("lang") or preferred
		language = language if language in LANGUAGES else "en"
		campaign = frappe.db.get_value("Campaign", recipient.campaign_name, ["custom_subscription_topic", "custom_content_topic"], as_dict=True)
		current_topic = (campaign.custom_content_topic or campaign.custom_subscription_topic) if campaign else None
		rows = topic_rows(email, language)
		for row in rows:
			row["is_current"] = row["name"] == current_topic
		context.email = email
		context.campaign_recipient = campaign_recipient
		context.topics = rows
		context.copy = get_copy(language)
		context.language = language
		context.language_urls = {
			lang: "/manage_subscriptions?" + get_signed_params({"campaign_recipient": campaign_recipient, "email": email, "lang": lang})
			for lang in LANGUAGES
		}
	except (frappe.PermissionError, frappe.DoesNotExistError, frappe.ValidationError, ValueError):
		context.error_message = "This preference link is invalid. Please use the link in your email."
	return context
