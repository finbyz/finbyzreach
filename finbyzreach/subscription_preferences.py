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
	row = frappe.db.get_value("Subscription Topic", topic, ["name", "category", "disabled"], as_dict=True)
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


def _save(email, topic, status, source, *, token_hash=None, expires=None):
	email = normalize_email(email)
	source = str(source or "")[:140]
	_topic(topic, active=status != "Unsubscribed")
	name = preference_name(email, topic)
	doc = frappe.get_doc(PREFERENCE_DOCTYPE, name, for_update=True) if frappe.db.exists(PREFERENCE_DOCTYPE, name) else frappe.new_doc(PREFERENCE_DOCTYPE)
	if doc.is_new():
		doc.email = email
		doc.subscription_topic = topic
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
	}).insert(ignore_permissions=True)
	return doc


def unsubscribe(email, topic, source="Email unsubscribe link"):
	return _save(email, topic, "Unsubscribed", source)


def request_subscription(email, topic, source="Preference center"):
	email = normalize_email(email)
	_topic(topic)
	if is_subscribed(email, topic):
		return "Subscribed"
	existing = frappe.db.get_value(PREFERENCE_DOCTYPE, preference_name(email, topic), ["status", "requested_on"], as_dict=True)
	if existing and existing.status == "Pending" and existing.requested_on and now_datetime() - get_datetime(existing.requested_on) < timedelta(minutes=10):
		return "Pending"
	token = secrets.token_urlsafe(32)
	doc = _save(
		email, topic, "Pending", source,
		token_hash=hashlib.sha256(token.encode()).hexdigest(),
		expires=now_datetime() + timedelta(days=2),
	)
	url = get_url(f"/confirm_subscription?preference={doc.name}&token={token}")
	frappe.sendmail(
		recipients=[email],
		subject=_("Confirm your email subscription"),
		message=_("Please confirm your subscription to {0}: <a href='{1}'>Confirm subscription</a>").format(
			frappe.utils.escape_html(topic), frappe.utils.escape_html(url)
		),
	)
	return "Pending"


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=600)
def request_public_subscriptions(email, selected_topics):
	selected = frappe.parse_json(selected_topics) if isinstance(selected_topics, str) else selected_topics
	if not isinstance(selected, list) or not selected or len(selected) > 20 or not all(isinstance(topic, str) for topic in selected) or len(set(selected)) != len(selected):
		frappe.throw(_("Choose one or more subscription options"), frappe.ValidationError)
	email = normalize_email(email)
	for topic in selected:
		request_subscription(email, topic, "Public registration")
	return "Pending"


def _ensure_public_subscriber_lead(email):
	"""Make a confirmed public subscriber available to Lead-based campaigns."""
	if frappe.db.exists("Lead", {"email_id": email}):
		return
	frappe.get_doc({"doctype": "Lead", "email_id": email, "status": "Lead"}).insert(ignore_permissions=True)


def confirm(preference, token):
	doc = frappe.get_doc(PREFERENCE_DOCTYPE, preference, for_update=True)
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


def recipient_urls(recipient):
	params = {"campaign_recipient": recipient.name, "email": normalize_email(recipient.custom_normalized_email or recipient.custom_recipient_email)}
	signed = get_signed_params(params)
	return {
		"unsubscribe_url": get_url(f"/api/method/finbyzreach.email_marketing.unsubscribe_marketing?{signed}"),
		"email_preference_center_url": get_url(f"/manage_subscriptions?{signed}"),
	}


def topic_rows(email, language="en"):
	language = language if language in LANGUAGES else "en"
	state = statuses(email) if email else {}
	rows = []
	for topic in frappe.get_all("Subscription Topic", filters={"disabled": 0}, fields=["name", "description", "category"], order_by="category asc, name asc", limit_page_length=0):
		translation = frappe.db.get_value("Subscription Topic Translation", {"parent": topic.name, "language": language}, ["label", "description"], as_dict=True)
		rows.append({
			"name": topic.name,
			"label": translation.label if translation and translation.label else topic.name,
			"description": translation.description if translation and translation.description else topic.description,
			"category": topic.category or "Mailing Type",
			"status": state.get(topic.name, "Unknown"),
		})
	return rows


def save_selection(email, selected, visible, source="Preference center"):
	"""Only modify the active options shown to the user; preserve disabled ones."""
	if not all(isinstance(topic, str) for topic in selected + visible):
		frappe.throw(_("Invalid subscription selection"), frappe.ValidationError)
	selected, visible = set(selected), set(visible)
	active = set(frappe.get_all("Subscription Topic", filters={"disabled": 0}, pluck="name", limit_page_length=0))
	if visible != active or not selected <= visible:
		frappe.throw(_("Subscription options changed. Please reload the page."), frappe.ValidationError)
	before = statuses(email)
	result = {}
	for topic in active:
		if topic in selected:
			if before.get(topic) != "Subscribed":
				result[topic] = request_subscription(email, topic, source)
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
	return {"email": chosen, "emails": emails, "topics": topic_rows(chosen) if chosen else []}


@frappe.whitelist(methods=["POST"])
def set_person_preference(doctype, name, topic, subscribed, email=None):
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
		return request_subscription(person["email"], topic, "Desk: " + doctype + " " + name)
	unsubscribe(person["email"], topic, "Desk: " + doctype + " " + name)
	return "Unsubscribed"
