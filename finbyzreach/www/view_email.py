from __future__ import annotations

import hmac
import hashlib
import json

import frappe
from frappe import _

from finbyzreach.email_template_builder.services import (
	get_campaign_snapshot,
	render_campaign_snapshot,
)

no_cache = 1


def _sign_message(message: str) -> str:
	"""HMAC-SHA-512 signature matching manage_subscriptions.py / email_marketing.py."""
	from frappe.utils.password import get_encryption_key
	secret = frappe.local.conf.get("secret") or get_encryption_key()
	return hmac.new(secret.encode(), message.encode(), digestmod=hashlib.sha512).hexdigest()


def _is_valid_signature() -> bool:
	"""Return True when the request carries a valid HMAC _signature param."""
	query_string = frappe.safe_decode(getattr(frappe.request, "query_string", b""))
	separator = "&_signature="
	if query_string and separator in query_string:
		params, signature_part = query_string.split(separator, 1)
		given_signature = signature_part.split("&", 1)[0]
		computed = _sign_message(params)
		return hmac.compare_digest(given_signature, computed)
	return False


def get_context(context):
	"""Frappe www page context for /view_email.

	Validates the HMAC-signed URL, re-renders the campaign/template snapshot with
	the recipient/lead context, and passes the HTML to the template.

	"email_preview_url" is intentionally NOT re-injected here to avoid a
	self-referencing "View in browser" link inside the browser view page.
	"""
	context.no_cache = 1

	# validate signature
	if not _is_valid_signature():
		context.error_message = _("This link is invalid or has expired.")
		return context

	subject = ""
	html = ""
	mode = "Visual"
	doc_context = None

	sender_name = ""
	sender_email = ""
	preheader = ""
	recipient_email = ""

	campaign_recipient_id = frappe.form_dict.get("campaign_recipient")
	campaign_id = frappe.form_dict.get("campaign")
	template_id = frappe.form_dict.get("template")

	if campaign_recipient_id:
		# Production Campaign Recipient
		if not frappe.db.exists("Email Campaign", campaign_recipient_id):
			context.error_message = _("This link is invalid or the campaign does not exist.")
			return context

		recipient = frappe.get_doc("Email Campaign", campaign_recipient_id)
		if not frappe.db.exists("Campaign", recipient.campaign_name):
			context.error_message = _("The campaign for this email could not be found.")
			return context

		campaign = frappe.get_doc("Campaign", recipient.campaign_name)
		if not (campaign.custom_snapshot_subject and campaign.custom_snapshot_html):
			context.error_message = _("The email content for this campaign is no longer available.")
			return context

		subject = campaign.custom_snapshot_subject
		html = campaign.custom_snapshot_html
		mode = campaign.custom_template_mode or "Standard"
		preheader = campaign.get("custom_preheader_text") or ""
		sender_name = campaign.get("custom_sender_name") or ""
		if campaign.get("custom_email_account"):
			sender_email = frappe.db.get_value("Email Account", campaign.custom_email_account, "email_id") or ""

		if frappe.db.exists("Lead", recipient.recipient):
			doc_context = frappe.get_doc("Lead", recipient.recipient)
			recipient_email = doc_context.get("email_id") or ""

	elif campaign_id:
		# Campaign Test / Preview
		if not frappe.db.exists("Campaign", campaign_id):
			context.error_message = _("The campaign for this email could not be found.")
			return context

		campaign = frappe.get_doc("Campaign", campaign_id)
		sender_name = campaign.get("custom_sender_name") or ""
		if campaign.get("custom_email_account"):
			sender_email = frappe.db.get_value("Email Account", campaign.custom_email_account, "email_id") or ""

		if campaign.custom_broadcast_status != "Draft" and campaign.custom_snapshot_subject and campaign.custom_snapshot_html:
			subject = campaign.custom_snapshot_subject
			html = campaign.custom_snapshot_html
			mode = campaign.custom_template_mode or "Standard"
			preheader = campaign.get("custom_preheader_text") or ""
		else:
			if not campaign.custom_email_template:
				context.error_message = _("The campaign email template could not be found.")
				return context
			snapshot = get_campaign_snapshot(
				campaign.custom_email_template,
				campaign.custom_subject_override,
				check_permission=False,
			)
			subject = snapshot.subject
			html = snapshot.html
			mode = snapshot.mode
			preheader = snapshot.get("preheader") or ""

		lead_name = frappe.form_dict.get("lead")
		if lead_name and frappe.db.exists("Lead", lead_name):
			doc_context = frappe.get_doc("Lead", lead_name)
			recipient_email = doc_context.get("email_id") or ""

	elif template_id:
		# Builder / Template Test
		if not frappe.db.exists("Email Template", template_id):
			context.error_message = _("The email template could not be found.")
			return context

		snapshot = get_campaign_snapshot(
			template_id,
			frappe.form_dict.get("subject_override"),
			check_permission=False,
		)
		subject = snapshot.subject
		html = snapshot.html
		mode = snapshot.mode
		preheader = snapshot.get("preheader") or ""

		lead_name = frappe.form_dict.get("lead")
		ref_doctype = frappe.form_dict.get("reference_doctype")
		ref_name = frappe.form_dict.get("reference_name")

		if lead_name and frappe.db.exists("Lead", lead_name):
			doc_context = frappe.get_doc("Lead", lead_name)
			recipient_email = doc_context.get("email_id") or ""
		elif ref_doctype and ref_name and frappe.db.exists(ref_doctype, ref_name):
			doc_context = frappe.get_doc(ref_doctype, ref_name)
			recipient_email = doc_context.get("email_id") or ""
	else:
		context.error_message = _("No email reference provided.")
		return context

	# render snapshot without email_preview_url to avoid circular self-reference
	try:
		rendered = render_campaign_snapshot(subject, html, doc_context)
		if preheader:
			try:
				preheader = render_campaign_snapshot(preheader, preheader, doc_context).subject
			except Exception:
				pass
	except Exception:
		frappe.log_error(frappe.get_traceback(), "view_email render error")
		context.error_message = _("The email content could not be rendered.")
		return context

	context.email_subject = rendered.subject
	context.email_html = rendered.html
	context.email_html_json = json.dumps(rendered.html or "")
	context.is_visual_mode = (mode == "Visual")
	context.title = rendered.subject
	context.preheader = preheader or ""
	context.sender_name = sender_name or "Megasol"
	context.sender_email = sender_email or ""
	context.recipient_email = recipient_email or ""
	context.avatar_label = ((sender_name or "Megasol")[:2]).upper()
	return context
