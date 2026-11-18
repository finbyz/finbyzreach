"""Keep sms:, whatsapp: and similar links intact when Frappe builds an email.

Frappe's expand_relative_urls() turns every href that does not start with http, mailto:, tel: or data:
into a link on this site, so an SMS button became https://<site>/sms:+4179... and opened a web page
(a 404) on the phone instead of the messages app. Upstream only skips mailto: and tel:, so the other
phone and chat schemes are protected here, around the original function.
"""
from __future__ import annotations

import re

import frappe.email.email_body as email_body
import frappe.utils as frappe_utils
import frappe.utils.data as frappe_data

SCHEMES = ("sms", "smsto", "mms", "whatsapp", "callto", "facetime", "viber", "skype", "geo", "webcal")
_PROTECT = re.compile(r"""(\bhref\s*=\s*['"]?)(%s):""" % "|".join(SCHEMES), re.IGNORECASE)
_RESTORE = re.compile(r"""(\bhref\s*=\s*['"]?)http-kept-(%s):""" % "|".join(SCHEMES), re.IGNORECASE)


def install():
	"""Wrap expand_relative_urls once for every place that uses it."""
	original = frappe_data.expand_relative_urls
	if getattr(original, "_keeps_chat_schemes", False):
		return

	def expand_relative_urls(html: str) -> str:
		# "http-kept-" starts with "http", which the original leaves alone.
		protected = _PROTECT.sub(lambda match: f"{match.group(1)}http-kept-{match.group(2)}:", html or "")
		return _RESTORE.sub(lambda match: f"{match.group(1)}{match.group(2)}:", original(protected))

	expand_relative_urls._keeps_chat_schemes = True
	expand_relative_urls.__doc__ = original.__doc__
	frappe_data.expand_relative_urls = expand_relative_urls
	frappe_utils.expand_relative_urls = expand_relative_urls
	email_body.expand_relative_urls = expand_relative_urls


install()
