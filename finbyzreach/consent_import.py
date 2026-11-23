"""Bulk import of consent that people already gave elsewhere (CSV or Excel).

Each row records a confirmed subscription per email address and topic through the
same path as a double opt-in confirmation (subscription_preferences._save), so the
consent log, consent text and segment updates stay identical. Large files run in a
background job that commits every CHUNK rows.
"""

import csv
import io
import re
from datetime import date, datetime

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, validate_email_address

from finbyzreach.subscription_preferences import LANGUAGES, PREFERENCE_DOCTYPE, preference_name

DOCTYPE = "Opt-in Import Log"
ROLES = ("Marketing Manager", "System Manager")
MAX_ROWS = 50000
CHUNK = 500
PREVIEW_LIMIT = 200
RECORD_TYPES = ("Lead", "Contact", "Customer")

SUBSCRIBE, SKIP, FAIL = "Subscribe", "Skip", "Fail"

# Normalised header -> internal column. Covers English and German exports.
COLUMNS = {
	"email": "email", "e_mail": "email", "email_id": "email", "email_address": "email", "e_mail_adresse": "email", "mail": "email",
	"topic": "topic", "topics": "topic", "mailing_type": "topic", "mailing_types": "topic", "email_type": "topic",
	"subscription_topic": "topic", "subscription": "topic", "subscriptions": "topic", "thema": "topic", "themen": "topic",
	"opted_in_on": "opted_in_on", "opt_in_date": "opted_in_on", "opt_in_on": "opted_in_on", "consent_date": "opted_in_on",
	"confirmed_on": "opted_in_on", "date": "opted_in_on", "datum": "opted_in_on", "einwilligung_am": "opted_in_on",
	"source": "source", "consent_source": "source", "proof": "source", "quelle": "source",
	"language": "language", "lang": "language", "sprache": "language",
	"record_type": "record_type", "doctype": "record_type", "record": "record", "record_id": "record", "id": "record",
}
LANGUAGE_NAMES = {"german": "de", "deutsch": "de", "english": "en", "englisch": "en", "french": "fr", "français": "fr",
	"francais": "fr", "französisch": "fr", "italian": "it", "italiano": "it", "italienisch": "it"}
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
	"%d.%m.%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d/%m/%Y", "%d/%m/%Y %H:%M")


def _require_role():
	if not set(frappe.get_roles()) & set(ROLES):
		frappe.throw(_("Only a Marketing Manager can import consent"), frappe.PermissionError)


# ---------------------------------------------------------------- reading the file

def _header_key(value):
	return re.sub(r"[^a-z0-9äöüéèàç]+", "_", str(value or "").strip().lower()).strip("_")


def _decode(content):
	if isinstance(content, str):
		return content.lstrip("﻿")
	for encoding in ("utf-8-sig", "cp1252", "latin-1"):
		try:
			return content.decode(encoding)
		except UnicodeDecodeError:
			continue


def _csv_rows(text):
	first = text.split("\n", 1)[0]
	delimiter = max((",", ";", "\t"), key=first.count)
	return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def read_table(content, filename=""):
	"""Rows as lists, from CSV (comma, semicolon or tab) or the first sheet of an .xlsx file."""
	if str(filename).lower().endswith(".xlsx") or (isinstance(content, bytes) and content[:2] == b"PK"):
		from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file
		return read_xlsx_file_from_attached_file(fcontent=content if isinstance(content, bytes) else content.encode(), read_only=True)
	return _csv_rows(_decode(content))


def parse_table(rows):
	"""Return (columns, records). Each record keeps its file row number and original values."""
	rows = [row for row in rows or [] if any(str(cell if cell is not None else "").strip() for cell in row)]
	if not rows:
		frappe.throw(_("The file is empty"))
	headers = [_header_key(cell) for cell in rows[0]]
	columns = {}
	for index, key in enumerate(headers):
		column = COLUMNS.get(key)
		if column and column not in columns:
			columns[column] = index
	if "email" not in columns and "record" not in columns:
		frappe.throw(_("The file needs an Email column (or Record type and Record columns). Found: {0}").format(
			", ".join(str(cell) for cell in rows[0])))
	if len(rows) - 1 > MAX_ROWS:
		frappe.throw(_("The file has {0} rows. Import at most {1} rows per file.").format(len(rows) - 1, MAX_ROWS))
	records = []
	for number, row in enumerate(rows[1:], start=2):
		value = {key: row[index] if index < len(row) else None for key, index in columns.items()}
		value["row"] = number
		value["original"] = ["" if cell is None else cell for cell in row]
		records.append(value)
	return {"header": ["" if cell is None else cell for cell in rows[0]], "columns": sorted(columns)}, records


# ---------------------------------------------------------------- planning

def _text(value):
	if value is None:
		return ""
	if isinstance(value, float) and value.is_integer():
		value = int(value)
	return str(value).strip()


def _parse_date(value):
	if value in (None, ""):
		return None
	if isinstance(value, datetime):
		return value
	if isinstance(value, date):
		return datetime(value.year, value.month, value.day)
	text = _text(value)
	for fmt in DATE_FORMATS:
		try:
			return datetime.strptime(text, fmt)
		except ValueError:
			continue
	raise ValueError(text)


def _language(value, default):
	text = _text(value).lower()
	if not text:
		return default
	text = LANGUAGE_NAMES.get(text, text[:2] if len(text) <= 5 else text)
	if text not in LANGUAGES:
		raise ValueError(value)
	return text


def _topic_lookup():
	"""Topic names and their translated labels, matched without case."""
	topics = {row.name: row for row in frappe.get_all("Subscription Topic", fields=["name", "category", "disabled"], limit_page_length=0)}
	lookup = {name.lower(): name for name in topics}
	for row in frappe.get_all("Subscription Topic Translation", filters={"parenttype": "Subscription Topic"},
			fields=["parent", "label"], limit_page_length=0):
		if row.label and row.parent in topics:
			lookup.setdefault(row.label.strip().lower(), row.parent)
	return topics, lookup


def _split_topics(value):
	return [part.strip() for part in re.split(r"[,;|\n]", _text(value)) if part.strip()]


def _chunks(values, size=CHUNK):
	values = list(values)
	for offset in range(0, len(values), size):
		yield values[offset:offset + size]


PRIMARY_CONTACT, ALL_CONTACTS = "Primary contact", "All contacts"


def _record_type(record):
	return _text(record.get("record_type")).title() or "Lead"


def _target(email, label, blocked=None):
	return frappe._dict(email=_text(email).lower(), label=label, blocked=blocked)


def _record_targets(records, customer_contacts=PRIMARY_CONTACT):
	"""Email addresses behind each (record type, record) row, by the rules campaigns use.

	Lead: its email. Contact: its primary email. Customer: the primary email of its primary
	contact, or of every linked contact. Each target carries the opt-out that would stop a
	campaign (blocked). get_list is used, so a record the user may not read counts as not found.
	"""
	from finbyzreach.email_marketing import _reference_unsubscribed_pairs

	wanted = {}
	for record in records:
		if not _text(record.get("email")) and _text(record.get("record")):
			wanted.setdefault(_record_type(record), set()).add(_text(record.get("record")))
	targets = {}

	lead_names = wanted.get("Lead", set())
	opted_out = _reference_unsubscribed_pairs(lead_names, "Lead") if lead_names else set()
	for part in _chunks(lead_names):
		for row in frappe.get_list("Lead", filters={"name": ["in", part]}, fields=["name", "email_id", "unsubscribed", "status"], limit_page_length=0):
			email = _text(row.email_id).lower()
			blocked = (_("Lead is unsubscribed or set to Do Not Contact") if cint(row.unsubscribed) or row.status == "Do Not Contact"
				else _("Unsubscribed from this Lead's emails") if (row.name, email) in opted_out else None)
			targets[("Lead", row.name)] = [_target(email, f"Lead {row.name}", blocked)] if email else []

	customers = {}
	for part in _chunks(wanted.get("Customer", set())):
		customers.update({row.name: row for row in frappe.get_list("Customer", filters={"name": ["in", part]},
			fields=["name", "disabled", "customer_primary_contact"], limit_page_length=0)})
	linked = {}
	for part in _chunks(customers):
		for row in frappe.get_all("Dynamic Link", filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": ["in", part]},
				fields=["parent", "link_name"], limit_page_length=0):
			linked.setdefault(row.link_name, set()).add(row.parent)
	chosen = {}
	for name, customer in customers.items():
		contacts = linked.get(name, set())
		if customer_contacts == ALL_CONTACTS:
			chosen[name] = sorted(contacts)
		else:
			chosen[name] = [customer.customer_primary_contact] if customer.customer_primary_contact in contacts else []

	contact_names = set(wanted.get("Contact", set())) | {contact for names in chosen.values() for contact in names}
	contacts = {}
	for part in _chunks(contact_names):
		contacts.update({row.name: row for row in frappe.get_list("Contact", filters={"name": ["in", part]},
			fields=["name", "email_id", "unsubscribed"], limit_page_length=0)})
	contact_out = _reference_unsubscribed_pairs(contacts, "Contact") if contacts else set()
	customer_out = _reference_unsubscribed_pairs(customers, "Customer") if customers else set()

	def contact_block(contact, email):
		if cint(contact.unsubscribed):
			return _("Contact is unsubscribed")
		if (contact.name, email) in contact_out:
			return _("Unsubscribed from this Contact's emails")

	for name in wanted.get("Contact", set()):
		contact = contacts.get(name)
		if contact:
			email = _text(contact.email_id).lower()
			targets[("Contact", name)] = [_target(email, f"Contact {name}", contact_block(contact, email))] if email else []

	for name, customer in customers.items():
		if cint(customer.disabled):
			targets[("Customer", name)] = [_target("", f"Customer {name}", _("Customer is disabled"))]
			continue
		rows = []
		for contact_name in chosen[name]:
			contact = contacts.get(contact_name)
			email = _text(contact and contact.email_id).lower()
			if not email:
				continue
			blocked = contact_block(contact, email) or (_("Unsubscribed from this Customer's emails") if (name, email) in customer_out else None)
			rows.append(_target(email, f"Customer {name} / Contact {contact_name}", blocked))
		targets[("Customer", name)] = rows
	return targets


def selected_records(doctype, names):
	"""Records picked on the page as import rows: email, topic and date come from the run defaults."""
	return [{"row": _("Selected"), "record_type": doctype, "record": name} for name in dict.fromkeys(names) if name]


def lead_records(names):
	return selected_records("Lead", names)


def _existing_preferences(emails):
	state = {}
	for part in _chunks(emails):
		for row in frappe.get_all(PREFERENCE_DOCTYPE, filters={"email": ["in", part]},
				fields=["email", "subscription_topic", "status", "unsubscribed_on"], limit_page_length=0):
			state[(row.email, row.subscription_topic)] = row
	return state


def _known_people(emails):
	known = set()
	for part in _chunks(emails):
		known.update(email.lower() for email in frappe.get_all("Lead", filters={"email_id": ["in", part]}, pluck="email_id", limit_page_length=0) if email)
		known.update(email.lower() for email in frappe.get_all("Contact Email", filters={"email_id": ["in", part]}, pluck="email_id", limit_page_length=0) if email)
	return known


def plan(records, *, consent_source, default_topics=(), default_language=None, default_opted_in_on=None,
		customer_contacts=PRIMARY_CONTACT):
	"""Decide every (row, topic) pair without writing anything.

	Returns a list of dicts: row, email, topic, action (Subscribe/Skip/Fail), reason,
	opted_in_on, language, source, note.
	"""
	from finbyzreach.consent import suppressed_addresses

	topics, lookup = _topic_lookup()
	default_topics = [topic for topic in default_topics or [] if topic]
	record_targets = _record_targets(records, customer_contacts)
	now = now_datetime()
	default_opted_in_on = _parse_date(default_opted_in_on) if default_opted_in_on else None
	items = []

	def add(record, target, topic, action, reason="", **extra):
		items.append(dict(row=record["row"], record=target.label, email=target.email, topic=topic, action=action, reason=reason, **extra))

	for record in records:
		email = _text(record.get("email")).lower()
		if email or not _text(record.get("record")):
			targets = [_target(email, "")]
		else:
			record_type, name = _record_type(record), _text(record.get("record"))
			if record_type not in RECORD_TYPES:
				add(record, _target("", ""), "", FAIL, _("Record type must be Lead, Contact or Customer"))
				continue
			targets = record_targets.get((record_type, name))
			if targets is None:
				add(record, _target("", f"{record_type} {name}"), "", FAIL, _("{0} {1} not found").format(record_type, name))
				continue
			if not targets:
				reason = (_("Customer {0} has no primary contact with an email. Choose All contacts to use its other contacts") if record_type == "Customer" and customer_contacts != ALL_CONTACTS
					else _("Customer {0} has no contact with an email") if record_type == "Customer" else _("{0} has no email").format(f"{record_type} {name}"))
				add(record, _target("", f"{record_type} {name}"), "", FAIL, reason.format(name))
				continue
		for target in targets:
			if target.blocked:
				add(record, target, "", SKIP, target.blocked)
				continue
			if not target.email or not validate_email_address(target.email, throw=False):
				add(record, target, "", FAIL, _("Missing or invalid email"))
				continue
			try:
				opted_in_on = _parse_date(record.get("opted_in_on")) or default_opted_in_on
			except ValueError:
				add(record, target, "", FAIL, _("Unreadable opt-in date. Use YYYY-MM-DD or DD.MM.YYYY"))
				continue
			if opted_in_on and opted_in_on > now:
				add(record, target, "", FAIL, _("Opt-in date is in the future"))
				continue
			try:
				language = _language(record.get("language"), default_language)
			except ValueError:
				add(record, target, "", FAIL, _("Unknown language. Use de, en, fr or it"))
				continue
			names = _split_topics(record.get("topic")) or default_topics
			if not names:
				add(record, target, "", FAIL, _("No topic in the row and no default topic chosen"))
				continue
			source = (_text(record.get("source")) or consent_source)
			for raw in names:
				topic = lookup.get(raw.lower())
				option = topics.get(topic)
				if not option:
					add(record, target, raw, FAIL, _("Unknown topic {0}").format(raw))
				elif option.category == "System":
					add(record, target, topic, FAIL, _("{0} is a system email type and needs no consent").format(topic))
				elif option.disabled:
					add(record, target, topic, FAIL, _("Topic {0} is disabled").format(topic))
				else:
					add(record, target, topic, SUBSCRIBE, opted_in_on=opted_in_on, language=language, source=source)

	wanted = [item for item in items if item["action"] == SUBSCRIBE]
	emails = sorted({item["email"] for item in wanted})
	from finbyzreach.email_marketing import _globally_unsubscribed_emails
	state = _existing_preferences(emails)
	blocks = suppressed_addresses(emails)
	global_out = _globally_unsubscribed_emails(emails)
	known = _known_people(emails)
	seen = {}
	for item in wanted:
		key = (item["email"], item["topic"])
		current = state.get(key)
		if key in seen:
			item.update(action=SKIP, reason=_("Same email and topic as {0}").format(seen[key]))
			continue
		seen[key] = _("row {0}").format(item["row"]) if isinstance(item["row"], int) else (item["record"] or item["row"])
		if item["email"] in global_out:
			item.update(action=SKIP, reason=_("Globally unsubscribed"))
		elif item["email"] in blocks:
			item.update(action=SKIP, reason=_("Address blocked: {0}").format(_(blocks[item["email"]])))
		elif current and current.status == "Subscribed":
			item.update(action=SKIP, reason=_("Already subscribed"))
		elif current and current.status == "Unsubscribed" and not (
			item["opted_in_on"] and current.unsubscribed_on and item["opted_in_on"] > current.unsubscribed_on
		):
			item.update(action=SKIP, reason=_("Unsubscribed on {0}. Only an opt-in dated after that can be imported").format(
				frappe.utils.format_date(current.unsubscribed_on) if current.unsubscribed_on else _("an earlier date")))
		elif item["email"] not in known:
			item["note"] = _("No Lead or Contact has this email yet, so campaigns will not reach it until one is created")
	return items


def summary(items, total_rows):
	counts = {SUBSCRIBE: 0, SKIP: 0, FAIL: 0}
	reasons, topics = {}, {}
	for item in items:
		counts[item["action"]] += 1
		if item["action"] == SUBSCRIBE:
			topics[item["topic"]] = topics.get(item["topic"], 0) + 1
		else:
			key = _("Same email and topic as an earlier row") if item["reason"].startswith(_("Same email")) else item["reason"]
			reasons[(item["action"], key)] = reasons.get((item["action"], key), 0) + 1
	return {
		"total_rows": total_rows,
		"subscribe": counts[SUBSCRIBE], "skip": counts[SKIP], "fail": counts[FAIL],
		"no_person": sum(1 for item in items if item.get("note")),
		"topics": [{"topic": topic, "count": count} for topic, count in sorted(topics.items())],
		"reasons": [{"action": action, "reason": reason, "count": count}
			for (action, reason), count in sorted(reasons.items(), key=lambda pair: -pair[1])],
		"problems": [{key: item.get(key) for key in ("row", "record", "email", "topic", "action", "reason")}
			for item in items if item["action"] != SUBSCRIBE][:PREVIEW_LIMIT],
	}


# ---------------------------------------------------------------- run document

def _file_content(file_url):
	file = frappe.get_doc("File", {"file_url": file_url})
	if not frappe.has_permission("File", "read", file):
		frappe.throw(_("You cannot read this file"), frappe.PermissionError)
	return file.get_content(), file.file_name


SELECTIONS = (("Lead", "leads"), ("Contact", "contacts"), ("Customer", "customers"))


def _names(value):
	if isinstance(value, str) and value.strip().startswith("["):
		value = frappe.parse_json(value)
	if isinstance(value, str):
		value = value.splitlines()
	return list(dict.fromkeys(_text(name) for name in value or [] if _text(name)))


def _load(doc):
	"""File rows (if a file is attached), then the selected Leads, Contacts and Customers, and their plan."""
	records = []
	if doc.import_file:
		content, filename = _file_content(doc.import_file)
		records = parse_table(read_table(content, filename))[1]
	for doctype, field in SELECTIONS:
		records += selected_records(doctype, _names(doc.get(field)))
	if len(records) > MAX_ROWS:
		frappe.throw(_("{0} rows in total. Import at most {1} per run.").format(len(records), MAX_ROWS))
	items = plan(records, consent_source=doc.consent_source, default_topics=_split_topics(doc.default_topics),
		default_language=doc.default_language or None, default_opted_in_on=doc.default_opted_in_on,
		customer_contacts=doc.customer_contacts or PRIMARY_CONTACT)
	return records, items


def _validate_settings(doc):
	if not _text(doc.consent_source):
		frappe.throw(_("Describe where the consent came from"))
	selected = any(_names(doc.get(field)) for _doctype, field in SELECTIONS)
	if not doc.import_file and not selected:
		frappe.throw(_("Attach a file or select at least one Lead, Contact or Customer"))
	if selected and not _split_topics(doc.default_topics):
		frappe.throw(_("Choose the topics the selected records opted in to"))
	if doc.default_opted_in_on and frappe.utils.getdate(doc.default_opted_in_on) > frappe.utils.getdate():
		frappe.throw(_("The default opt-in date cannot be in the future"))


def _topic_list(value):
	if isinstance(value, str) and value.strip().startswith("["):
		value = frappe.parse_json(value)
	if isinstance(value, (list, tuple)):
		return [_text(topic) for topic in value if _text(topic)]
	return _split_topics(value)


@frappe.whitelist(methods=["POST"])
def check(consent_source, import_file=None, leads=None, contacts=None, customers=None, customer_contacts=None,
		default_topics=None, default_language=None, default_opted_in_on=None, name=None):
	"""Save the run as Draft and return what an import would do. Writes no consent."""
	_require_role()
	values = {"import_file": import_file or None, "leads": "\n".join(_names(leads)),
		"contacts": "\n".join(_names(contacts)), "customers": "\n".join(_names(customers)),
		"customer_contacts": ALL_CONTACTS if customer_contacts == ALL_CONTACTS else PRIMARY_CONTACT,
		"consent_source": _text(consent_source)[:140], "default_topics": "\n".join(_topic_list(default_topics)),
		"default_language": default_language if default_language in LANGUAGES else "",
		"default_opted_in_on": default_opted_in_on or None}
	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.check_permission("write")
		if doc.status != "Draft":
			frappe.throw(_("This import has already started"))
		doc.update(values)
	else:
		doc = frappe.get_doc({"doctype": DOCTYPE, **values})
	_validate_settings(doc)
	records, items = _load(doc)
	doc.total_rows = len(records)
	if doc.is_new():
		doc.insert()
	else:
		doc.save()
	return {"name": doc.name, **summary(items, len(records))}


@frappe.whitelist(methods=["POST"])
def start(name, consent_confirmed=0):
	_require_role()
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("write")
	if doc.status != "Draft":
		frappe.throw(_("This import has already started"))
	if not cint(consent_confirmed):
		frappe.throw(_("Confirm that these people gave consent and that you keep proof of it"))
	_validate_settings(doc)
	doc.db_set({"status": "Queued", "consent_confirmed": 1, "error": None})
	frappe.enqueue("finbyzreach.consent_import.run", name=doc.name, queue="long", timeout=3 * 3600,
		job_id=f"opt-in-import:{doc.name}", deduplicate=True, enqueue_after_commit=True)
	return doc.status


def _progress(doc, done, total, counts):
	doc.db_set({"subscribed": counts[SUBSCRIBE], "skipped": counts[SKIP], "failed": counts[FAIL]}, update_modified=False)
	frappe.cache.set_value(f"consent_import_progress:{doc.name}", {"done": done, "total": total}, expires_in_sec=6 * 3600)
	frappe.publish_realtime("consent_import_progress", {"name": doc.name, "done": done, "total": total, **{k.lower(): v for k, v in counts.items()}},
		user=doc.owner, after_commit=True)


def _commit():
	if not frappe.flags.in_test:
		frappe.db.commit()


def run(name):
	"""Background job: re-plan against current data, then write each Subscribe pair."""
	from finbyzreach.subscription_preferences import _save

	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status != "Queued":
		return
	doc.db_set({"status": "Running", "started_on": now_datetime()})
	_commit()
	try:
		records, items = _load(doc)
		counts = {SUBSCRIBE: 0, SKIP: 0, FAIL: 0}
		for item in items:
			if item["action"] != SUBSCRIBE:
				counts[item["action"]] += 1
		todo = [item for item in items if item["action"] == SUBSCRIBE]
		total = len(todo)
		_progress(doc, 0, total, counts)
		_commit()
		for done, item in enumerate(todo, start=1):
			stamp = item["opted_in_on"].strftime("%Y-%m-%d") if item["opted_in_on"] else None
			source = f"Import {doc.name}" + (f" ({stamp})" if stamp else "") + f": {item['source']}"
			frappe.db.savepoint("consent_import_row")
			try:
				_save(item["email"], item["topic"], "Subscribed", source[:140], language=item["language"])
				if item["opted_in_on"]:
					frappe.db.set_value(PREFERENCE_DOCTYPE, preference_name(item["email"], item["topic"]),
						"confirmed_on", item["opted_in_on"], update_modified=False)
				counts[SUBSCRIBE] += 1
			except Exception as error:
				frappe.db.rollback(save_point="consent_import_row")
				item.update(action=FAIL, reason=str(error)[:300] or error.__class__.__name__)
				counts[FAIL] += 1
			if done % CHUNK == 0:
				_progress(doc, done, total, counts)
				_commit()
		_attach_result(doc, items)
		doc.db_set({"status": "Completed", "finished_on": now_datetime(), "total_rows": len(records)})
		_progress(doc, total, total, counts)
		_commit()
	except Exception:
		frappe.db.rollback()
		doc.db_set({"status": "Failed", "finished_on": now_datetime(), "error": frappe.get_traceback()})
		frappe.publish_realtime("consent_import_progress", {"name": doc.name, "failed_run": 1}, user=doc.owner, after_commit=True)
		_commit()
		if frappe.flags.in_test:
			raise


def _attach_result(doc, items):
	"""One line per row and topic with its outcome, so nothing in the import is unexplained."""
	out = io.StringIO()
	writer = csv.writer(out)
	writer.writerow(["Row", "Record", "Email", "Topic", "Opted in on", "Outcome", "Reason", "Note"])
	labels = {SUBSCRIBE: "Subscribed", SKIP: "Skipped", FAIL: "Failed"}
	for item in items:
		date = item.get("opted_in_on")
		writer.writerow([item["row"], item.get("record", ""), item["email"], item["topic"], date.strftime("%Y-%m-%d") if date else "",
			labels[item["action"]], item["reason"], item.get("note", "")])
	file = frappe.get_doc({"doctype": "File", "file_name": f"{doc.name}-result.csv", "is_private": 1, "attached_to_doctype": DOCTYPE,
		"attached_to_name": doc.name, "attached_to_field": "result_file", "content": out.getvalue().encode("utf-8-sig")})
	file.insert(ignore_permissions=True)
	doc.db_set("result_file", file.file_url)


@frappe.whitelist(methods=["GET"])
def status(name):
	_require_role()
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	result = {key: doc.get(key) for key in ("name", "status", "total_rows", "subscribed", "skipped", "failed",
		"started_on", "finished_on", "result_file", "consent_source", "error")}
	result["progress"] = frappe.cache.get_value(f"consent_import_progress:{doc.name}") or {}
	return result


@frappe.whitelist(methods=["GET"])
def history():
	_require_role()
	return frappe.get_list(DOCTYPE, fields=["name", "status", "consent_source", "total_rows", "subscribed", "skipped", "failed",
		"creation", "owner", "result_file"], order_by="creation desc", limit_page_length=20)


SEARCH = {
	"Lead": (["name", "lead_name", "company_name", "email_id"], {"email_id": ["is", "set"]}),
	"Contact": (["name", "full_name", "company_name", "email_id"], {"email_id": ["is", "set"]}),
	"Customer": (["name", "customer_name", "email_id"], {"disabled": 0}),
}


@frappe.whitelist(methods=["GET"])
def search_records(doctype, txt=""):
	"""Records for the page's pickers, by ID, name, company or email. Leads and Contacts need an email."""
	_require_role()
	if doctype not in SEARCH:
		frappe.throw(_("Unsupported record type"))
	fields, filters = SEARCH[doctype]
	like = f"%{_text(txt)[:100]}%"
	rows = frappe.get_list(doctype, filters=filters, or_filters={field: ["like", like] for field in fields},
		fields=fields, order_by="modified desc", limit_page_length=20)
	return [{"value": row.name, "description": " · ".join(str(row[field]) for field in fields[1:] if row.get(field))} for row in rows]


@frappe.whitelist(methods=["GET"])
def search_leads(txt=""):
	return search_records("Lead", txt)


@frappe.whitelist(methods=["GET"])
def topics():
	_require_role()
	return frappe.get_all("Subscription Topic", filters={"disabled": 0, "category": ["in", ["Mailing Type", "Topic"]]},
		fields=["name", "category"], order_by="category asc, name asc", limit_page_length=0)


def template():
	"""Example file using this site's own active mailing types, so it imports as it is."""
	names = frappe.get_all("Subscription Topic", filters={"disabled": 0, "category": "Mailing Type"}, pluck="name",
		order_by="name asc", limit_page_length=2) or ["Newsletter"]
	first_topic, second = names[0], names[-1]
	both = f"{first_topic}, {second}" if second != first_topic else first_topic

	def first(doctype, filters):
		names = frappe.get_list(doctype, filters=filters, pluck="name", order_by="creation desc", limit_page_length=1)
		return names[0] if names else None

	lead = first("Lead", {"email_id": ["is", "set"]}) or "CRM-LEAD-2026-00001"
	contact = first("Contact", {"email_id": ["is", "set"]}) or "Anna Muster"
	customer = first("Customer", {"disabled": 0, "customer_primary_contact": ["is", "set"], "email_id": ["is", "set"]}) or "Muster AG"
	out = io.StringIO()
	writer = csv.writer(out)
	writer.writerow(["Email", "Record type", "Record", "Topic", "Opted in on", "Source", "Language"])
	writer.writerow(["anna.muster@example.com", "", "", first_topic, "2025-03-14", "Swissbau 2025 sign-up form", "de"])
	writer.writerow(["luca.rossi@example.com", "", "", both, "02.09.2025", "Website contact form", "it"])
	writer.writerow(["marie.dupont@example.com", "", "", second, "", "", "fr"])
	writer.writerow(["", "Lead", lead, first_topic, "2025-06-30", "Signed order form", "en"])
	writer.writerow(["", "Contact", contact, first_topic, "2025-07-15", "Phone call", "de"])
	writer.writerow(["", "Customer", customer, second, "2025-08-01", "Customer portal sign-up", "de"])
	return out.getvalue()


@frappe.whitelist(methods=["GET"])
def download_template():
	_require_role()
	frappe.response["filename"] = "opt-in-import-example.csv"
	frappe.response["filecontent"] = template().encode("utf-8-sig")
	frappe.response["type"] = "download"
