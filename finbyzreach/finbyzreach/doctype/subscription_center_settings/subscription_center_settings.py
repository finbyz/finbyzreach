import re
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.model.document import Document


def parse_embed_origins(value):
	origins = []
	for line in (value or "").splitlines():
		origin = line.strip().rstrip("/")
		if not origin:
			continue
		parts = urlsplit(origin)
		try:
			port = parts.port
		except ValueError:
			port = None
		if (
			parts.scheme != "https"
			or not parts.hostname
			or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", parts.hostname)
			or (":" in parts.netloc and port is None)
			or parts.username
			or parts.password
			or parts.path
			or parts.query
			or parts.fragment
			or parts.netloc != parts.hostname + (f":{port}" if port else "")
		):
			frappe.throw(_("Allowed Embed Origins must contain HTTPS origins only, one per line"))
		if origin not in origins:
			origins.append(origin)
	return origins


class SubscriptionCenterSettings(Document):
	def validate(self):
		parse_embed_origins(self.allowed_embed_origins)
		languages = [row.language for row in self.translations or []]
		if len(languages) != len(set(languages)):
			frappe.throw(_("Add only one translation per language"))
