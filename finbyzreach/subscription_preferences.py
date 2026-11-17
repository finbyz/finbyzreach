"""Email-address-scoped, purpose-specific marketing consent."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import get_datetime, get_url, now_datetime, validate_email_address
from frappe.utils.verified_command import _sign_message, get_signed_params

PREFERENCE_DOCTYPE = "Email Subscription Preference"
LANGUAGES = ("de", "en", "fr", "it")


def normalize_email(email):
	email = str(email or "").strip().lower()
	validate_email_address(email, throw=True)
	return email


def preference_name(email, topic):
	return hashlib.sha256(f"{normalize_email(email)}\0{topic}".encode()).hexdigest()


def _topic(topic, active=True):
	fields = ["name", "category", "disabled", "description", "modified"]
	if frappe.db.has_column("Subscription Topic", "consent_required"):
		fields += ["consent_required", "double_opt_in", "deliver_while_pending"]
	row = frappe.db.get_value("Subscription Topic", topic, fields, as_dict=True)
	if row and "double_opt_in" not in row:
		row.update(consent_required=1, double_opt_in=1, deliver_while_pending=0)
	if not row or (active and row.disabled):
		frappe.throw(_("Subscription option is unavailable"))
	return row


def statuses(email):
	return {
		row.subscription_topic: row.status
		for row in frappe.get_all(
			PREFERENCE_DOCTYPE,
			filters={"email": normalize_email(email)},
			fields=["subscription_topic", "status"],
			limit_page_length=0,
		)
	}


def is_subscribed(email, topic):
	return statuses(email).get(topic) == "Subscribed"


def _save(email, topic, status, source, *, token_hash=None, expires=None, language=None):
	email = normalize_email(email)
	source = str(source or "")[:140]
	option = _topic(topic, active=status != "Unsubscribed")
	name = preference_name(email, topic)
	doc = frappe.get_doc(PREFERENCE_DOCTYPE, name, for_update=True) if frappe.db.exists(PREFERENCE_DOCTYPE, name) else frappe.new_doc(PREFERENCE_DOCTYPE)
	if doc.is_new():
		doc.email = email
		doc.subscription_topic = topic
	if status == "Pending" or (status == "Subscribed" and doc.status != "Pending"):
		doc.consent_version = str(option.get("modified") or "")
		doc.consent_text = option.get("description") or ""
		if language in LANGUAGES:
			translated = frappe.db.get_value("Subscription Topic Translation", {"parent": topic, "language": language}, ["label", "description"], as_dict=True)
			if translated:
				doc.consent_text = "\n".join(value for value in [translated.label, translated.description] if value)
	doc.status = status
	doc.consent_source = source
	now = now_datetime()
	if status == "Pending":
		doc.requested_on = now
		doc.confirmation_hash = token_hash
		doc.confirmation_expires_on = expires
	elif status == "Subscribed":
		doc.confirmed_on = now
		doc.confirmation_hash = None
		doc.confirmation_expires_on = None
	else:
		doc.unsubscribed_on = now
		doc.confirmation_hash = None
		doc.confirmation_expires_on = None
	doc.status = status
	doc.consent_source = source
	doc.save(ignore_permissions=True)
	frappe.get_doc({
		"doctype": "Email Subscription Event",
		"email": email,
		"subscription_topic": topic,
		"status": status,
		"source": source,
		"event_time": now,
		"consent_version": getattr(doc, "consent_version", None),
		"consent_text": getattr(doc, "consent_text", None),
	}).insert(ignore_permissions=True)
	return doc


DOI_COPY = {
	"de": {"subject": "Bitte bestätigen Sie Ihr Abonnement", "body": "Bitte bestätigen Sie Ihr Abonnement für «{0}».", "button": "Abonnement bestätigen",
		"ignore": "Wenn Sie sich nicht angemeldet haben, können Sie diese E-Mail ignorieren."},
	"fr": {"subject": "Veuillez confirmer votre abonnement", "body": "Veuillez confirmer votre abonnement à « {0} ».", "button": "Confirmer l'abonnement",
		"ignore": "Si vous ne vous êtes pas inscrit, vous pouvez ignorer cet e-mail."},
	"it": {"subject": "Conferma la tua iscrizione", "body": "Conferma la tua iscrizione a «{0}».", "button": "Conferma iscrizione",
		"ignore": "Se non ti sei iscritto, puoi ignorare questa email."},
	"en": {"subject": "Please confirm your subscription", "body": "Please confirm your subscription to “{0}”.", "button": "Confirm subscription",
		"ignore": "If you did not sign up, you can ignore this email."},
}


def topic_label(topic, language):
	label = frappe.db.get_value("Subscription Topic Translation", {"parent": topic, "language": language}, "label") if language else None
	return label or topic


def doi_message(topic, url, language):
	"""Double opt-in email in the subscriber's language (falls back to German)."""
	from html import escape
	language = language if language in LANGUAGES else "de"
	text = DOI_COPY[language]
	label = escape(topic_label(topic, language))
	return text["subject"], (
		f'<p>{text["body"].format(label)}</p>'
		f'<p><a href="{escape(url, quote=True)}" style="display:inline-block;padding:10px 18px;background:#0f2f4f;color:#ffffff;'
		f'text-decoration:none;border-radius:6px">{escape(text["button"])}</a></p>'
		f'<p style="color:#5d6875;font-size:12px">{escape(text["ignore"])}</p>'
	)


NAME_CACHE = "finbyzreach:pending_subscriber_name:"


def remember_name(email, first_name=None, last_name=None):
	"""Names typed on /subscribe wait in cache until the double opt-in is confirmed."""
	first_name, last_name = str(first_name or "").strip()[:140], str(last_name or "").strip()[:140]
	if first_name or last_name:
		frappe.cache.set_value(NAME_CACHE + email, {"first_name": first_name, "last_name": last_name}, expires_in_sec=3 * 86400)


def unsubscribe(email, topic, source="Email unsubscribe link"):
	if _topic(topic, active=False).category == "System":
		return None
	return _save(email, topic, "Unsubscribed", source)


def request_subscription(email, topic, source="Preference center", language=None):
	email = normalize_email(email)
	if language is not None and language not in LANGUAGES:
		frappe.throw(_("Unsupported subscription language"))
	consent_metadata = {"language": language} if language else {}
	option = _topic(topic)
	if option.category == "System":
		frappe.throw(_("System email types are not subscription preferences"))
	if is_subscribed(email, topic):
		return "Subscribed"
	if option.category == "Topic" or not frappe.utils.cint(option.double_opt_in):
		_save(email, topic, "Subscribed", source, **consent_metadata)
		if source == "Public registration":
			_ensure_public_subscriber_lead(email)
		return "Subscribed"

	existing = frappe.db.get_value(PREFERENCE_DOCTYPE, preference_name(email, topic), ["status", "requested_on"], as_dict=True)
	if existing and existing.status == "Pending" and existing.requested_on and now_datetime() - get_datetime(existing.requested_on) < timedelta(minutes=10):
		return "Pending"
	from finbyzreach.consent import suppressed_addresses, policy_ready
	if suppressed_addresses([email]):
		frappe.throw(_("A confirmation email cannot be sent to this address"))
	token = secrets.token_urlsafe(32)
	doc = _save(
		email, topic, "Pending", source,
		token_hash=hashlib.sha256(token.encode()).hexdigest(),
		expires=now_datetime() + timedelta(days=2),
		**consent_metadata,
	)
	url = get_url(f"/confirm_subscription?preference={doc.name}&token={token}&lang={language if language in LANGUAGES else 'de'}")
	subject, message = doi_message(topic, url, language)
	queue_options = {}
	if policy_ready():
		queue_options = {"add_unsubscribe_link": 0,
			"unsubscribe_method": "/api/method/finbyzreach.subscription_preferences.unsubscribe_address",
			"unsubscribe_params": {"email_type": "Transactional"}}
	queue = frappe.sendmail(
		**queue_options,
		delayed=True,
		recipients=[email],
		subject=subject,
		message=message,
	)
	if queue and isinstance(getattr(queue, "name", None), str):
		frappe.enqueue_doc("Email Queue", queue.name, "send", queue="short", enqueue_after_commit=True)
	return "Pending"


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=600)
def request_public_subscriptions(email, selected_topics, language=None, first_name=None, last_name=None):
	selected = frappe.parse_json(selected_topics) if isinstance(selected_topics, str) else selected_topics
	if not isinstance(selected, list) or not selected or len(selected) > 20 or not all(isinstance(topic, str) for topic in selected) or len(set(selected)) != len(selected):
		frappe.throw(_("Choose one or more subscription options"), frappe.ValidationError)
	email = normalize_email(email)
	remember_name(email, first_name, last_name)
	results = [request_subscription(email, topic, "Public registration", **({"language": language} if language else {})) for topic in selected]
	return "Pending" if "Pending" in results else "Subscribed"


def _ensure_public_subscriber_lead(email):
	"""Make a confirmed public subscriber available to Lead-based campaigns."""
	if frappe.db.exists("Lead", {"email_id": email}):
		return
	names = frappe.cache.get_value(NAME_CACHE + email) or {}
	lead = {"doctype": "Lead", "email_id": email, "status": "Lead"}
	lead.update({key: value for key, value in names.items() if key in ("first_name", "last_name") and value})
	frappe.get_doc(lead).insert(ignore_permissions=True)
	frappe.cache.delete_value(NAME_CACHE + email)


def confirm(preference, token):
	doc = frappe.get_doc(PREFERENCE_DOCTYPE, preference, for_update=True)
	if doc.status == "Subscribed" and doc.confirmed_on:
		# Opening the link again (or a second tab) after confirming is not an error.
		return doc.email
	if doc.status != "Pending" or not doc.confirmation_hash or not doc.confirmation_expires_on:
		frappe.throw(_("This confirmation link is no longer valid"), frappe.PermissionError)
	if now_datetime() > get_datetime(doc.confirmation_expires_on) or not hmac.compare_digest(
		doc.confirmation_hash, hashlib.sha256(str(token).encode()).hexdigest()
	):
		frappe.throw(_("This confirmation link is invalid or expired"), frappe.PermissionError)
	_save(doc.email, doc.subscription_topic, "Subscribed", "Double opt-in confirmation")
	if doc.consent_source == "Public registration":
		_ensure_public_subscriber_lead(doc.email)
	return doc.email


@frappe.whitelist(allow_guest=True, methods=["POST"])
def confirm_subscription(preference, token):
	return confirm(preference, token)


def signed_recipient(campaign_recipient, signed_query_string):
	"""Bind a public request to the email actually used for this campaign row."""
	from urllib.parse import parse_qs

	try:
		params, signature = str(signed_query_string or "").rsplit("&_signature=", 1)
	except ValueError:
		frappe.throw(_("Invalid preference link"), frappe.PermissionError)
	if not hmac.compare_digest(signature, _sign_message(params)):
		frappe.throw(_("Invalid preference link"), frappe.PermissionError)
	parsed = parse_qs(params)
	if parsed.get("campaign_recipient", [None])[0] != campaign_recipient:
		frappe.throw(_("Invalid preference link"), frappe.PermissionError)
	if not frappe.db.exists("Email Campaign", campaign_recipient):
		frappe.throw(_("Campaign recipient not found"), frappe.DoesNotExistError)
	recipient = frappe.get_doc("Email Campaign", campaign_recipient)
	email = normalize_email(recipient.custom_normalized_email or recipient.custom_recipient_email)
	if parsed.get("email") and normalize_email(parsed["email"][0]) != email:
		frappe.throw(_("Invalid preference link"), frappe.PermissionError)
	return recipient, email


def email_language(campaign_name):
	"""Language of the email that was sent, taken from its template (CS-05)."""
	template = frappe.db.get_value("Campaign", campaign_name, "custom_email_template") if campaign_name else None
	if template and frappe.db.has_column("Email Template", "custom_language"):
		language = str(frappe.db.get_value("Email Template", template, "custom_language") or "").lower()[:2]
		if language in LANGUAGES:
			return language
	return None


def recipient_urls(recipient):
	params = {"campaign_recipient": recipient.name, "email": normalize_email(recipient.custom_normalized_email or recipient.custom_recipient_email)}
	language = email_language(recipient.get("campaign_name"))
	if language:
		params["lang"] = language
	signed = get_signed_params(params)
	return {
		"unsubscribe_url": get_url(f"/api/method/finbyzreach.email_marketing.unsubscribe_marketing?{signed}"),
		"email_preference_center_url": get_url(f"/manage_subscriptions?{signed}"),
	}


def topic_rows(email, language="en"):
	language = language if language in LANGUAGES else "en"
	state = statuses(email) if email else {}
	rows = []
	doi_field = ["double_opt_in"] if frappe.db.has_column("Subscription Topic", "double_opt_in") else []
	for topic in frappe.get_all("Subscription Topic", filters={"disabled": 0, "category": ["in", ["Mailing Type", "Topic"]]}, fields=["name", "description", "category", *doi_field], order_by="category asc, name asc", limit_page_length=0):
		translation = frappe.db.get_value("Subscription Topic Translation", {"parent": topic.name, "language": language}, ["label", "description"], as_dict=True)
		rows.append({
			"name": topic.name,
			"label": translation.label if translation and translation.label else topic.name,
			"description": translation.description if translation and translation.description else topic.description,
			"category": topic.category or "Mailing Type",
			"status": state.get(topic.name, "Unknown"),
			# Subscribing to these sends a confirmation email, so Desk asks for its language first.
			"double_opt_in": int((topic.category or "Mailing Type") == "Mailing Type" and frappe.utils.cint(topic.get("double_opt_in"))),
		})
	return rows


def save_selection(email, selected, visible, source="Preference center", language=None):
	"""Only modify the active options shown to the user; preserve disabled ones."""
	if not all(isinstance(topic, str) for topic in selected + visible):
		frappe.throw(_("Invalid subscription selection"), frappe.ValidationError)
	selected, visible = set(selected), set(visible)
	active = set(frappe.get_all("Subscription Topic", filters={"disabled": 0, "category": ["in", ["Mailing Type", "Topic"]]}, pluck="name", limit_page_length=0))
	if visible != active or not selected <= visible:
		frappe.throw(_("Subscription options changed. Please reload the page."), frappe.ValidationError)
	before = statuses(email)
	result = {}
	for topic in active:
		if topic in selected:
			if before.get(topic) != "Subscribed":
				result[topic] = request_subscription(email, topic, source, **({"language": language} if language else {}))
		else:
			if before.get(topic) in ("Subscribed", "Pending"):
				unsubscribe(email, topic, source)
				result[topic] = "Unsubscribed"
	return result


@frappe.whitelist()
def get_person_preferences(doctype, name, email=None):
	if doctype not in ("Lead", "Contact"):
		frappe.throw(_("Unsupported record"), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	emails = [doc.email_id] if doctype == "Lead" else [row.email_id for row in doc.get("email_ids") or []]
	emails = list(dict.fromkeys(normalize_email(value) for value in emails if value))
	chosen = normalize_email(email) if email else (emails[0] if emails else None)
	if chosen and chosen not in emails:
		frappe.throw(_("Email is not on this record"), frappe.PermissionError)
	return {"email": chosen, "emails": emails, "topics": topic_rows(chosen) if chosen else [], "language": record_language(doc)}


def record_language(doc):
	"""The person's language for consent emails: preferred, then record language, fallback German."""
	value = str(doc.get("custom_preferred_language") or doc.get("language") or "").strip().lower()[:2]
	return value if value in LANGUAGES else "de"


@frappe.whitelist(methods=["POST"])
def set_person_preference(doctype, name, topic, subscribed, email=None, language=None):
	if doctype not in ("Lead", "Contact"):
		frappe.throw(_("Unsupported record"), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")
	if not (set(frappe.get_roles()) & {"Marketing Manager", "System Manager"}):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	person = get_person_preferences(doctype, name, email)
	if not person["email"]:
		frappe.throw(_("This record has no email address"))
	if frappe.utils.cint(subscribed):
		# The confirmation email goes out in the language chosen in Desk, else the person's own.
		language = str(language or "").strip().lower() or person.get("language") or "de"
		return request_subscription(person["email"], topic, "Desk: " + doctype + " " + name, language=language)
	unsubscribe(person["email"], topic, "Desk: " + doctype + " " + name)
	return "Unsubscribed"


def address_urls(email, email_type, language="de"):
	params = {"consent_email": normalize_email(email), "email_type": email_type, "lang": language if language in LANGUAGES else "de"}
	signed = get_signed_params(params)
	return {
		"unsubscribe_url": get_url(f"/api/method/finbyzreach.subscription_preferences.unsubscribe_address?{signed}"),
		"email_preference_center_url": get_url(f"/manage_subscriptions?{signed}"),
		"unsubscribe_all_url": get_url("/api/method/finbyzreach.subscription_preferences.unsubscribe_address?" + get_signed_params({**params, "scope": "all"})),
	}


def signed_address(signed_query_string):
	from urllib.parse import parse_qs
	try:
		params, signature = str(signed_query_string or "").rsplit("&_signature=", 1)
	except ValueError:
		frappe.throw(_("Invalid preference link"), frappe.PermissionError)
	if not hmac.compare_digest(signature, _sign_message(params)):
		frappe.throw(_("Invalid preference link"), frappe.PermissionError)
	values = parse_qs(params)
	if any(len(values.get(key, [])) != 1 for key in ("consent_email", "email_type")):
		frappe.throw(_("Invalid preference link"), frappe.PermissionError)
	return normalize_email(values["consent_email"][0]), values["email_type"][0], values


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def unsubscribe_address(**kwargs):
	raw = frappe.safe_decode(getattr(frappe.request, "query_string", b""))
	email, email_type, values = signed_address(raw)
	types = frappe.get_all("Subscription Topic", filters={"category": "Mailing Type"}, pluck="name", limit_page_length=0) if values.get("scope") == ["all"] else [email_type]
	for topic in types:
		if _topic(topic, active=False).category != "System":
			unsubscribe(email, topic)
	if frappe.request.method == "GET":
		frappe.db.commit()
		frappe.respond_as_web_page(_("Unsubscribed"), _("Your email preferences have been updated."), indicator_color="green")
	return "success"


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=600)
def update_address_preferences(selected_topics, visible_topics, signed_query_string, **kwargs):
	email, _, values = signed_address(signed_query_string)
	selected = frappe.parse_json(selected_topics) if isinstance(selected_topics, str) else selected_topics
	visible = frappe.parse_json(visible_topics) if isinstance(visible_topics, str) else visible_topics
	if not isinstance(selected, list) or not isinstance(visible, list):
		frappe.throw(_("Invalid subscription selection"), frappe.ValidationError)
	save_selection(email, selected, visible, language=values.get("lang", ["de"])[0])
	return "success"
