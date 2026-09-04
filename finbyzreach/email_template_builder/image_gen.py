from __future__ import annotations

import frappe
from frappe import _


def generate_email_image(prompt: str, template_name: str | None = None) -> str:
	"""Unified helper that invokes the LangChain tool function directly."""
	try:
		from finbyzai.ai.ai_tools.generate_email_image import generate_email_image_tool

		res = generate_email_image_tool.invoke(prompt)
		res_str = str(res or "").strip()
		if res_str.startswith("IMAGE_GENERATION_FAILED:") or not res_str.startswith(("/", "http")):
			return ""
		return res_str
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), f"generate_email_image failed for prompt: {prompt}")
		return ""
