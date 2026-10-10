"""Response policy for the public subscription form when embedded externally."""

import frappe

from finbyzreach.finbyzreach.doctype.subscription_center_settings.subscription_center_settings import (
	parse_embed_origins,
)


def set_subscription_embed_policy(response, request):
	if request.path != "/subscribe" or request.args.get("embed") != "1":
		return

	origins = parse_embed_origins(
		frappe.db.get_single_value("Subscription Center Settings", "allowed_embed_origins")
	)
	if not origins:
		return

	policy = response.headers.get("Content-Security-Policy", "")
	if "frame-ancestors" in policy.lower():
		return
	frame_policy = "frame-ancestors 'self' " + " ".join(origins)
	response.headers["Content-Security-Policy"] = (
		policy.rstrip("; ") + "; " + frame_policy if policy else frame_policy
	)
