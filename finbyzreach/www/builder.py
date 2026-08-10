from urllib.parse import urlencode

import frappe

no_cache = 1


def get_context():
	if frappe.session.user == "Guest":
		_redirect(f"/login?{urlencode({'redirect-to': frappe.local.request.full_path or '/builder'})}")
	if not {"Email Designer", "System Manager"}.intersection(frappe.get_roles()):
		frappe.throw("The Email Designer role is required", frappe.PermissionError)

	csrf_token = frappe.sessions.get_csrf_token()
	# Manually commit the CSRF token here
	frappe.db.commit()  # nosemgrep
	favicon = (
			frappe.get_cached_value(
				"Website Settings",
				"Website Settings",
				"favicon",
			)
			or "/assets/frappe/images/frappe-favicon.svg"
		)
	context = frappe._dict()
	context.boot = frappe._dict(csrf_token=csrf_token, favicon=favicon)
	context.boot_json = frappe.as_json(
		{
			"csrf_token": csrf_token,
			"site_name": frappe.local.site,
			"user": frappe.session.user,
			"favicon": favicon,
		}
	)
	return context


def _redirect(location):
	frappe.local.flags.redirect_location = location
	raise frappe.Redirect
