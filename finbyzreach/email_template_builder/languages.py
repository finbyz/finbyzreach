"""Language-aware email setup and independently editable language versions."""
import frappe
from frappe import _

LANGUAGES = ("de", "fr", "it", "en")


def validate_metadata(doc, method=None):
	language = doc.get("custom_language")
	if language and language not in LANGUAGES:
		frappe.throw(_("Choose German, French, Italian or English"))
	if doc.get("custom_email_type"):
		from finbyzreach.consent import email_policy
		if not email_policy(doc.custom_email_type).available:
			frappe.throw(_("Choose an active email type"))
	if doc.doctype == "Email Template Master" and doc.get("enabled") and language and doc.get("custom_email_type"):
		if frappe.db.exists(doc.doctype, {"name": ["!=", doc.name or ""], "enabled": 1,
			"custom_language": language, "custom_email_type": doc.custom_email_type}):
			frappe.throw(_("An enabled master already exists for this email type and language"))


@frappe.whitelist(methods=["GET"])
def suggested_master(email_type, language):
	frappe.has_permission("Email Template Master", "read", throw=True)
	if language not in LANGUAGES:
		frappe.throw(_("Unsupported email language"))
	rows = frappe.get_list("Email Template Master", filters={"enabled": 1, "custom_email_type": email_type,
		"custom_language": language}, fields=["name", "subject"], order_by="name asc", limit_page_length=1)
	return rows[0] if rows else None


@frappe.whitelist(methods=["POST"])
def configure_email(template_name, email_type, language, folder=None):
	if language not in LANGUAGES:
		frappe.throw(_("Choose an email language"))
	doc = frappe.get_doc("Email Template", template_name)
	doc.check_permission("write")
	if folder:
		frappe.get_doc("Email Folder", folder).check_permission("read")
	values = {"custom_email_type": email_type, "custom_language": language, "custom_folder": folder or None}
	if all(doc.get(key) == value for key, value in values.items()):
		return {"updated": False}
	doc.update(values)
	doc.save()
	return {"updated": True}


@frappe.whitelist(methods=["POST"])
def add_language_version(template_name, language, new_name, master_name=None):
	if language not in LANGUAGES:
		frappe.throw(_("Choose an email language"))
	frappe.has_permission("Email Template", "create", throw=True)
	source = frappe.get_doc("Email Template", template_name, for_update=True)
	source.check_permission("write")
	group = source.get("custom_version_group") or source.name
	frappe.db.get_value("Email Template", group, "name", for_update=True)
	if source.custom_language == language or frappe.db.exists("Email Template", {"custom_version_group": group, "custom_language": language}):
		frappe.throw(_("This email already has a version in that language"))
	if not source.get("custom_version_group"):
		source.db_set("custom_version_group", group, update_modified=False)
	if master_name:
		master = frappe.get_doc("Email Template Master", master_name)
		master.check_permission("read")
		if not master.enabled or master.custom_language != language or master.custom_email_type != source.custom_email_type:
			frappe.throw(_("Choose a master for the target language and email type"))
		from finbyzreach.email_template_builder.library import create_email_from_master
		result = create_email_from_master(master_name, new_name)
		doc = frappe.get_doc("Email Template", result["name"])
	else:
		new_name = str(new_name or "").strip()
		if not new_name or len(new_name) > 140:
			frappe.throw(_("Choose a name between 1 and 140 characters"))
		doc = frappe.copy_doc(source)
		doc.name = new_name
		doc.insert()
		from finbyzreach.email_template_builder.library import _copy_public_attachments
		_copy_public_attachments(source, doc)
	doc.update({"custom_language": language, "custom_email_type": source.custom_email_type,
		"custom_version_group": group, "custom_folder": source.get("custom_folder")})
	doc.save()
	return {"name": doc.name}


@frappe.whitelist(methods=["GET"])
def email_setup(template_name):
	doc = frappe.get_doc("Email Template", template_name)
	doc.check_permission("read")
	return {"language": doc.get("custom_language") or "", "folder": doc.get("custom_folder") or "", "email_type": doc.get("custom_email_type") or ""}


@frappe.whitelist(methods=["POST"])
def duplicate_email(template_name, new_name=None):
	"""EM-41: an independent copy of an email (its own name, no shared language group)."""
	frappe.has_permission("Email Template", "create", throw=True)
	source = frappe.get_doc("Email Template", template_name)
	source.check_permission("read")
	base = str(new_name or "").strip() or f"{source.name} (copy)"
	if len(base) > 140:
		frappe.throw(_("Choose a name of at most 140 characters"))
	name, number = base, 2
	while frappe.db.exists("Email Template", name):
		suffix = f" {number}"
		name, number = base[:140 - len(suffix)] + suffix, number + 1
	doc = frappe.copy_doc(source)
	doc.name = name
	doc.custom_version_group = None
	doc.insert()
	from finbyzreach.email_template_builder.library import _copy_public_attachments
	_copy_public_attachments(source, doc)
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def move_emails_to_folder(template_names, folder=None):
	"""EM-41: bulk "Move to folder" for the selected emails; an empty folder means "No folder"."""
	names = frappe.parse_json(template_names)
	if not isinstance(names, list) or not names or len(names) > 200:
		frappe.throw(_("Select between 1 and 200 emails"))
	if folder:
		frappe.get_doc("Email Folder", folder).check_permission("read")
	moved = 0
	for name in names:
		doc = frappe.get_doc("Email Template", name)
		doc.check_permission("write")
		if (doc.get("custom_folder") or None) != (folder or None):
			doc.db_set("custom_folder", folder or None)
			moved += 1
	return {"moved": moved}


@frappe.whitelist(methods=["POST"])
def email_usage(template_names):
	"""EM-40: status, where used and send time of the emails on screen (one batch per list page)."""
	names = frappe.parse_json(template_names)
	if not isinstance(names, list):
		frappe.throw(_("Invalid list of emails"))
	names = [str(name) for name in names[:100] if name]
	frappe.has_permission("Email Template", "read", throw=True)
	result = {name: {"status": "", "used_in": [], "send_time": ""} for name in names}
	if not names:
		return result
	if frappe.has_permission("Campaign", "read"):
		rows = frappe.get_all(
			"Campaign", filters={"custom_email_template": ["in", names]},
			fields=["name", "campaign_name", "custom_email_template", "custom_broadcast_status", "custom_start_on", "modified"],
			order_by="modified desc", limit_page_length=500,
		)
		for row in rows:
			entry = result[row.custom_email_template]
			entry["used_in"].append({"kind": "campaign", "name": row.name, "title": row.campaign_name or row.name})
			if not entry["status"]:
				entry["status"] = row.custom_broadcast_status or "Draft"
				entry["send_time"] = str(row.custom_start_on or "")
	if frappe.has_permission("Automation Workflow", "read") and frappe.db.exists("DocType", "Automation Workflow Version"):
		for name in names:
			versions = frappe.get_all(
				"Automation Workflow Version", filters={"graph_json": ["like", f"%{name}%"]},
				fields=["workflow"], limit_page_length=20,
			)
			for workflow in dict.fromkeys(row.workflow for row in versions):
				title = frappe.db.get_value("Automation Workflow", workflow, "title") or workflow
				result[name]["used_in"].append({"kind": "workflow", "name": workflow, "title": title})
			if versions and not result[name]["status"]:
				result[name]["status"] = "In workflow"
	return result
