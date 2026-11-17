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
