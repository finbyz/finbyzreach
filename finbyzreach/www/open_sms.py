"""Landing page for the SMS button in an email.

Gmail and Outlook do not open sms: links, so the email button points to this https page. On a phone it
opens the messages app with the number and text; on a computer it shows the number to text.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import frappe
from frappe import _

no_cache = 1
PHONE = re.compile(r"^\+?[0-9(). -]{3,40}$")
LINK_IN_TEXT = re.compile(r"https?://|www\.", re.IGNORECASE)


def sms_targets(number: str, body: str) -> dict:
	"""The number to show and the sms: link for Android and iPhone. Empty when the number is not valid."""
	number = str(number or "").strip()
	body = str(body or "").strip()[:300]
	if not PHONE.fullmatch(number):
		return {"valid": False}
	if LINK_IN_TEXT.search(body):
		# A prefilled text must not carry a link: this page could otherwise be used to send people scam texts.
		body = ""
	digits = re.sub(r"[^0-9+]", "", number)
	suffix = quote(body, safe="")
	return {
		"valid": True,
		"number": number,
		"body": body,
		"android": f"sms:{digits}" + (f"?body={suffix}" if body else ""),
		"ios": f"sms:{digits}" + (f"&body={suffix}" if body else ""),
	}


def get_context(context):
	context.no_cache = 1
	context.no_breadcrumbs = 1
	context.show_sidebar = False
	context.title = _("Send a text message")
	context.update(sms_targets(frappe.form_dict.get("to"), frappe.form_dict.get("body")))
