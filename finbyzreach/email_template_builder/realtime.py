from __future__ import annotations

from typing import Any

import frappe


def _publish_to_template(template_name: str, event: str, message: dict[str, Any]) -> None:
	if not template_name:
		return
	frappe.publish_realtime(
		event,
		message=message,
		doctype="Email Template",
		docname=template_name,
		after_commit=True,
	)


def publish_builder_saved(template, *, revision=None, client_id: str | None = None) -> None:
	_publish_to_template(
		template.name,
		"email_builder_saved",
		{
			"template_name": template.name,
			"modified": str(template.modified),
			"content_hash": template.get("custom_builder_content_hash") or "",
			"revision": revision.name if revision else None,
			"revision_number": revision.revision_number if revision else None,
			"actor": frappe.session.user,
			"client_id": str(client_id or "")[:80],
		},
	)


def publish_builder_revision_created(template_name: str, revision, *, client_id: str | None = None) -> None:
	if not revision:
		return
	_publish_to_template(
		template_name,
		"email_builder_revision_created",
		{
			"template_name": template_name,
			"revision": revision.name,
			"revision_number": revision.revision_number,
			"actor": frappe.session.user,
			"client_id": str(client_id or "")[:80],
		},
	)


def publish_builder_assets_changed(template_name: str, *, file_name: str | None = None) -> None:
	_publish_to_template(
		template_name,
		"email_builder_assets_changed",
		{
			"template_name": template_name,
			"file_name": file_name,
			"actor": frappe.session.user,
		},
	)


def on_file_after_insert(doc, method=None) -> None:
	if doc.attached_to_doctype == "Email Template" and doc.attached_to_name and not doc.is_private:
		publish_builder_assets_changed(doc.attached_to_name, file_name=doc.name)
