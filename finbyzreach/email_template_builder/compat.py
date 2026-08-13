from __future__ import annotations

import inspect

import frappe
from frappe.email.email_body import get_formatted_html
from frappe.utils import get_url, scrub_urls


def _accepts_parameter(callable_, parameter: str) -> bool:
	try:
		return parameter in inspect.signature(callable_).parameters
	except (TypeError, ValueError):
		return False


def format_email_html(subject, message, *, raw_html=False, add_css=True, unsubscribe_link=None):
	"""Format email HTML on both Frappe 15 and 16.

	Frappe 16 added ``raw_html`` and ``add_css`` to ``get_formatted_html``.
	Visual-builder output is already a complete HTML document, so the v15 fallback
	must inline that document directly instead of nesting it in Frappe's standard
	email wrapper.
	"""
	if _accepts_parameter(get_formatted_html, "raw_html"):
		return get_formatted_html(
			subject,
			message,
			unsubscribe_link=unsubscribe_link,
			raw_html=raw_html,
			add_css=add_css,
		)

	if not raw_html:
		return get_formatted_html(subject, message, unsubscribe_link=unsubscribe_link)

	params = {
		"site_url": get_url(),
		"title": subject,
		"print_html": None,
		"subject": subject,
	}
	html = scrub_urls(frappe.render_template(message, params))
	if unsubscribe_link:
		html = html.replace("<!--unsubscribe link here-->", unsubscribe_link.html)

	# Frappe 15 cannot disable hook-provided email CSS. The visual builder owns
	# its complete document, so use Premailer directly when add_css is false.
	if not add_css:
		from premailer import Premailer

		return Premailer(
			html=html,
			external_styles=None,
			strip_important=False,
			allow_loading_external_files=True,
		).transform()

	from frappe.email.email_body import inline_style_in_html

	return inline_style_in_html(html)


def sendmail(*, raw_html=False, add_css=True, **kwargs):
	"""Queue mail using Frappe 16's raw-HTML path or an equivalent v15 builder."""
	if _accepts_parameter(frappe.sendmail, "raw_html"):
		return frappe.sendmail(raw_html=raw_html, add_css=add_css, **kwargs)

	if not raw_html:
		return frappe.sendmail(**kwargs)

	return _send_raw_html_v15(add_css=add_css, **kwargs)


def _send_raw_html_v15(*, add_css=True, **kwargs):
	from frappe.email.doctype.email_queue.email_queue import QueueBuilder

	class RawHTMLQueueBuilder(QueueBuilder):
		def email_html_content(self):
			return format_email_html(
				self.subject,
				self._message,
				raw_html=True,
				add_css=add_css,
				unsubscribe_link=self.unsubscribe_message(),
			)

	message = kwargs.pop("content", None) or kwargs.pop("message", "No Message")
	delayed = kwargs.pop("delayed", True)
	now = kwargs.pop("now", None)
	if not delayed:
		now = True

	# These aliases and options are handled by frappe.sendmail before it creates
	# QueueBuilder. Apply the same normalization for the v15 raw-HTML fallback.
	kwargs["reference_doctype"] = kwargs.pop("doctype", None) or kwargs.get("reference_doctype")
	kwargs["reference_name"] = kwargs.pop("name", None) or kwargs.get("reference_name")
	kwargs.pop("retry", None)
	kwargs.pop("as_markdown", None)
	kwargs.pop("template", None)
	kwargs.pop("args", None)

	accepted = inspect.signature(QueueBuilder).parameters
	builder_kwargs = {key: value for key, value in kwargs.items() if key in accepted}
	builder = RawHTMLQueueBuilder(message=message, **builder_kwargs)
	return builder.process(send_now=bool(now))
