"""Shared email-address consent policy for campaigns and workflow sends."""
from email.utils import getaddresses

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

TRANSACTIONAL = "Transactional"
UNSUBSCRIBE_MISSING = "The email has no unsubscribe link. Add an Unsubscribe link block to the email, or use the Transactional email type."


def email_has_unsubscribe(html):
	"""True when a template's source places the recipient's unsubscribe link (EM-11).

	The builder's Unsubscribe and Compliance blocks, and hand-written HTML, all use
	{{ unsubscribe_url }}; a template without it cannot give the recipient an opt-out.
	"""
	return "unsubscribe_url" in str(html or "")


POLICY_FIELDS = ["name", "category", "disabled", "consent_required", "double_opt_in", "deliver_while_pending"]


def policy_ready():
	return frappe.db.has_column("Subscription Topic", "consent_required") and frappe.db.table_exists("Email Delivery Suppression")


def email_policy(email_type):
	fields = POLICY_FIELDS if policy_ready() else ["name", "category", "disabled"]
	row = frappe.db.get_value("Subscription Topic", email_type, fields, as_dict=True) if email_type else None
	if row and "consent_required" not in row:
		row.update(consent_required=1, double_opt_in=1, deliver_while_pending=0)
	if not row or row.disabled or row.category not in ("Mailing Type", "System"):
		return frappe._dict(available=False, consent_required=True)
	if row.category == "System" and row.name != TRANSACTIONAL:
		return frappe._dict(available=False, consent_required=True)
	row.available = True
	return row


def suppressed_addresses(emails):
	values = sorted({str(email or "").strip().lower() for email in emails if email})
	result = {}
	if not frappe.db.table_exists("Email Delivery Suppression"):
		return result
	for offset in range(0, len(values), 500):
		for row in frappe.get_all("Email Delivery Suppression", filters={"email": ["in", values[offset:offset + 500]]}, fields=["email", "reason"], limit_page_length=0):
			result[row.email] = row.reason
	return result


def consent_exclusion(email, email_type, *, policy=None, status=None, status_loaded=False, suppressions=None):
	"""Return one reason or None. Batch callers pass loaded policy/status/blocks."""
	email = str(email or "").strip().lower()
	if not email or not frappe.utils.validate_email_address(email, throw=False):
		return _("Missing or invalid email")
	policy = policy if policy is not None else email_policy(email_type)
	if not policy.available:
		return _("Email type unavailable or disabled")
	blocks = suppressions if suppressions is not None else suppressed_addresses([email])
	if email in blocks:
		return _(blocks[email])
	if not cint(policy.consent_required):
		return None
	if not status_loaded:
		status = frappe.db.get_value("Email Subscription Preference", {"email": email, "subscription_topic": email_type}, "status")
	if status == "Subscribed" or (status == "Pending" and cint(policy.deliver_while_pending)):
		return None
	return _("No confirmed subscription to {0}").format(email_type)


def capture_delivery_failure(doc, method=None):
	if not frappe.db.table_exists("Email Delivery Suppression") or doc.get("sent_or_received") != "Sent":
		return
	reason = {"Bounced": "Hard bounce", "Marked As Spam": "Spam complaint"}.get(doc.get("delivery_status"))
	if not reason:
		return
	for _, address in getaddresses([str(doc.get("recipients") or "")]):
		email = address.strip().lower()
		if not frappe.utils.validate_email_address(email, throw=False):
			continue
		name = frappe.db.get_value("Email Delivery Suppression", {"email": email}, "name")
		if not name:
			frappe.get_doc(dict(doctype="Email Delivery Suppression", email=email, reason=reason, communication=doc.name, recorded_on=now_datetime())).insert(ignore_permissions=True, ignore_if_duplicate=True)


FOOTER_LABELS = {
	"de": ("Abmelden", "E-Mail-Einstellungen"),
	"fr": ("Se désabonner", "Préférences e-mail"),
	"it": ("Annulla iscrizione", "Preferenze email"),
	"en": ("Unsubscribe", "Email preferences"),
}


def delivery_footer(html, urls, language=None):
	"""Append a server-owned footer after rendering, outside editable builder content."""
	from html import escape
	from finbyzreach.email_marketing import _insert_email_footer
	labels = FOOTER_LABELS.get(language) or (_("Unsubscribe"), _("Email preference center"))
	links = f'<a href="{escape(urls["unsubscribe_url"], quote=True)}">{escape(labels[0])}</a> · <a href="{escape(urls["email_preference_center_url"], quote=True)}">{escape(labels[1])}</a>'
	return _insert_email_footer(html, '<div class="email-preferences" style="padding:20px;text-align:center;font-size:12px">' + links + '</div>')


def add_list_headers(queue, unsubscribe_url):
	# QueueBuilder.email_headers prefixes every supplied key with X-. Standard
	# List-Unsubscribe headers must be inserted in the stored MIME header block.
	from email.parser import Parser
	message = str(queue.message or "")
	headers = Parser().parsestr(message, headersonly=True)
	prefix = ""
	if not headers.get("List-Unsubscribe"):
		prefix += f"List-Unsubscribe: <{unsubscribe_url}>\r\n"
	if not headers.get("List-Unsubscribe-Post"):
		prefix += "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
	if prefix:
		queue.db_set("message", prefix + message, update_modified=False)


class ConsentQueueMixin:
	"""Recheck our single-recipient messages at SMTP handoff, including retries."""
	def send(self, *args, **kwargs):
		from finbyzreach.email_marketing import UNSUBSCRIBE_METHOD, _current_recipient_exclusion, mark_campaign_metrics_dirty
		method = str(self.unsubscribe_method or "")
		owned = (f"/api/method/{UNSUBSCRIBE_METHOD}", "/api/method/finbyzreach.subscription_preferences.unsubscribe_address")
		pending = [row for row in self.recipients if row.status != "Sent"]
		if method not in owned or not pending:
			return super().send(*args, **kwargs)
		params = frappe.parse_json(self.unsubscribe_params or "{}")
		if not isinstance(params, dict):
			frappe.throw(_("Invalid consent context for queued email"))
		reason = None
		campaign_recipient = None
		if method == f"/api/method/{UNSUBSCRIBE_METHOD}" and params.get("campaign_recipient"):
			campaign_recipient = frappe.get_doc("Email Campaign", params["campaign_recipient"])
			campaign = frappe.get_doc("Campaign", campaign_recipient.campaign_name)
			if len(pending) != 1 or pending[0].recipient.strip().lower() != str(campaign_recipient.custom_recipient_email or "").strip().lower():
				reason = _("Queued recipient does not match its consent context")
			else:
				reason = _current_recipient_exclusion(campaign_recipient, campaign)
		elif method == "/api/method/finbyzreach.subscription_preferences.unsubscribe_address":
			from finbyzreach.email_marketing import test_recipient_exclusion
			if not str(params.get("email_type") or "").strip():
				# Every email needs exactly one email type; without it consent cannot be checked (rule 4.1).
				reason = _("No email type set: choose a mailing type or Transactional")
			for row in self.recipients:
				if not reason and row.status != "Sent":
					reason = test_recipient_exclusion(row.recipient, params.get("email_type"))
					if reason:
						break
		elif method == f"/api/method/{UNSUBSCRIBE_METHOD}":
			reason = _("Missing consent context for queued email")
		if reason:
			self.db_set({"status": "Error", "error": "Suppressed: " + str(reason)}, update_modified=False)
			if campaign_recipient:
				frappe.db.set_value("Email Campaign", campaign_recipient.name, {"status": "Completed", "custom_delivery_status": "Skipped", "custom_excluded_reason": reason}, update_modified=False)
				mark_campaign_metrics_dirty(campaign_recipient.campaign_name)
			return
		return super().send(*args, **kwargs)
