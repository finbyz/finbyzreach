from __future__ import annotations

import hmac
import hashlib
import json
from urllib.parse import parse_qsl

import frappe
from frappe import _

from finbyzreach.email_template_builder.services import (
	get_campaign_snapshot,
	render_campaign_snapshot,
)
from finbyzreach.email_template_builder.targets import normalize_template_doctype

no_cache = 1


def _sign_message(message: str) -> str:
	"""HMAC-SHA-512 signature matching manage_subscriptions.py / email_marketing.py."""
	from frappe.utils.password import get_encryption_key
	secret = frappe.local.conf.get("secret") or get_encryption_key()
	return hmac.new(secret.encode(), message.encode(), digestmod=hashlib.sha512).hexdigest()


def _verified_params():
	"""Return only parameters covered by the URL signature."""
	query_string = frappe.safe_decode(getattr(frappe.request, "query_string", b""))
	separator = "&_signature="
	if not query_string or query_string.count(separator) != 1:
		return None
	params, given_signature = query_string.split(separator, 1)
	if not params or "&" in given_signature or not hmac.compare_digest(given_signature, _sign_message(params)):
		return None
	try:
		pairs = parse_qsl(params, keep_blank_values=True, strict_parsing=True)
	except ValueError:
		return None
	verified = {}
	for key, value in pairs:
		if key in verified or key == "_signature":
			return None
		verified[key] = value
	return verified


def get_context(context):
	"""Frappe www page context for /view_email.

	Validates the HMAC-signed URL, re-renders the campaign/template snapshot with
	the recipient/lead context, and passes the HTML to the template.

	"email_preview_url" is intentionally NOT re-injected here to avoid a
	self-referencing "View in browser" link inside the browser view page.
	"""
	context.no_cache = 1

	# validate signature
	params = _verified_params()
	if params is None:
		context.error_message = _("This link is invalid or has expired.")
		return context

	subject = ""
	html = ""
	mode = "Visual"
	doc_context = None
	extra_context = {}

	sender_name = ""
	sender_email = ""
	preheader = ""
	recipient_email = ""

	campaign_recipient_id = params.get("campaign_recipient")
	campaign_id = params.get("campaign")
	template_id = params.get("template")

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

		audience_doctype = recipient.email_campaign_for or "Lead"
		if frappe.db.exists(audience_doctype, recipient.recipient):
			party = frappe.get_doc(audience_doctype, recipient.recipient)
			contact = None
			if audience_doctype == "Customer" and recipient.get("custom_contact"):
				from finbyzreach.customer_campaign import contact_for_customer
				if not contact_for_customer(party.name, recipient.custom_contact) or not frappe.db.exists("Contact", recipient.custom_contact):
					context.error_message = _("Contact is not linked to Customer")
					return context
				contact = frappe.get_doc("Contact", recipient.custom_contact)
			doc_context = contact if campaign.get("custom_personalization_doctype") == "Contact" else party
			extra_context = {"customer": party if audience_doctype == "Customer" else None, "contact": contact}
			recipient_email = recipient.custom_recipient_email or ""

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

		lead_name = params.get("lead")
		ref_doctype = params.get("reference_doctype")
		ref_name = params.get("reference_name")
		if lead_name and frappe.db.exists("Lead", lead_name):
			doc_context = frappe.get_doc("Lead", lead_name)
			recipient_email = doc_context.get("email_id") or ""
		elif ref_doctype in ("Customer", "Contact") and ref_name and frappe.db.exists(ref_doctype, ref_name):
			if (campaign.get("custom_audience_doctype") or "Lead") == "Customer":
				customer_name = params.get("customer")
				if not customer_name or not frappe.db.exists("Customer", customer_name):
					context.error_message = _("Invalid Customer preview reference")
					return context
				from finbyzreach.customer_campaign import contact_for_customer, customer_contacts
				customer = frappe.get_doc("Customer", customer_name)
				contact_name = params.get("contact") or (ref_name if ref_doctype == "Contact" else None)
				if ref_doctype == "Customer" and not contact_name:
					contact_name = next(iter(customer_contacts(customer, campaign.get("custom_contact_mode") or "Primary Contact")), None)
				if ((ref_doctype == "Customer" and customer_name != ref_name)
					or (ref_doctype == "Contact" and ref_name != contact_name)
					or not contact_for_customer(customer_name, contact_name)
					or not frappe.db.exists("Contact", contact_name)):
					context.error_message = _("Contact is not linked to Customer")
					return context
				contact = frappe.get_doc("Contact", contact_name)
				doc_context = contact if ref_doctype == "Contact" else customer
				extra_context = {"customer": customer, "contact": contact}
			else:
				doc_context = frappe.get_doc(ref_doctype, ref_name)
			recipient_email = doc_context.get("email_id") or ""

	elif template_id:
		# Builder / Template Test
		template_doctype = normalize_template_doctype(params.get("template_doctype"))
		if not frappe.db.exists(template_doctype, template_id):
			context.error_message = _("The email template could not be found.")
			return context

		snapshot = get_campaign_snapshot(
			template_id,
			params.get("subject_override"),
			check_permission=False,
			template_doctype=template_doctype,
		)
		subject = snapshot.subject
		html = snapshot.html
		mode = snapshot.mode
		preheader = snapshot.get("preheader") or ""

		lead_name = params.get("lead")
		ref_doctype = params.get("reference_doctype")
		ref_name = params.get("reference_name")

		if lead_name and frappe.db.exists("Lead", lead_name):
			doc_context = frappe.get_doc("Lead", lead_name)
			recipient_email = doc_context.get("email_id") or ""
		elif ref_doctype in ("Customer", "Contact") and ref_name and frappe.db.exists(ref_doctype, ref_name):
			customer_name = params.get("customer")
			contact_name = params.get("contact")
			if (not customer_name or not contact_name
				or not frappe.db.exists("Customer", customer_name)
				or not frappe.db.exists("Contact", contact_name)):
				context.error_message = _("Invalid Customer preview reference")
				return context
			from finbyzreach.customer_campaign import contact_for_customer
			if ((ref_doctype == "Customer" and ref_name != customer_name)
				or (ref_doctype == "Contact" and ref_name != contact_name)
				or not contact_for_customer(customer_name, contact_name)):
				context.error_message = _("Contact is not linked to Customer")
				return context
			customer = frappe.get_doc("Customer", customer_name)
			contact = frappe.get_doc("Contact", contact_name)
			doc_context = contact if ref_doctype == "Contact" else customer
			extra_context = {"customer": customer, "contact": contact}
			recipient_email = contact.get("email_id") or ""
	else:
		context.error_message = _("No email reference provided.")
		return context

	# render snapshot without email_preview_url to avoid circular self-reference
	try:
		rendered = render_campaign_snapshot(subject, html, doc_context, extra_context=extra_context)
		if preheader:
			try:
				preheader = render_campaign_snapshot(preheader, preheader, doc_context, extra_context=extra_context).subject
			except Exception:
				pass
	except Exception:
		frappe.log_error(frappe.get_traceback(), "view_email render error")
		context.error_message = _("The email content could not be rendered.")
		return context

	context.email_subject = rendered.subject
	context.email_html = rendered.html
	context.email_html_json = json.dumps(rendered.html or "").replace("<", "\\u003c")
	context.is_visual_mode = (mode == "Visual")
	context.title = rendered.subject
	context.preheader = preheader or ""
	context.sender_name = sender_name or "Megasol"
	context.sender_email = sender_email or ""
	context.recipient_email = recipient_email or ""
	context.avatar_label = ((sender_name or "Megasol")[:2]).upper()
	return context
