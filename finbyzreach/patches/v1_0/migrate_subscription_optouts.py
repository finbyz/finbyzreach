import frappe

from finbyzreach.subscription_preferences import statuses, unsubscribe


def execute():
	# ``bench migrate`` syncs DocTypes before post_model_sync patches. A direct
	# console invocation skips that phase, so install the audit DocType first.
	if not frappe.db.exists("DocType", "Email Subscription Event"):
		frappe.reload_doc("finbyzreach", "doctype", "email_subscription_event")
	for topic in frappe.get_all("Subscription Topic", fields=["name", "category"], limit_page_length=0):
		if not topic.category:
			frappe.db.set_value("Subscription Topic", topic.name, "category", "Mailing Type")
	for name, description in (
		("Marketing E-Mails", "Offers, promotions and events"),
		("Stammtisch Newsletter", "Solar technology news and updates"),
		("Pressemitteilungen", "Press releases and company news"),
	):
		if not frappe.db.exists("Subscription Topic", name):
			translations = {
				"Marketing E-Mails": [("de", "Marketing E-Mails", "Angebote, Aktionen und Veranstaltungen"), ("fr", "E-mails marketing", "Offres, promotions et événements"), ("it", "Email di marketing", "Offerte, promozioni ed eventi")],
				"Stammtisch Newsletter": [("de", "Stammtisch-Newsletter", "Neuigkeiten rund um Solartechnik"), ("fr", "Newsletter Stammtisch", "Actualités sur la technologie solaire"), ("it", "Newsletter Stammtisch", "Novità sulla tecnologia solare")],
				"Pressemitteilungen": [("de", "Pressemitteilungen", "Presse- und Unternehmensnachrichten"), ("fr", "Communiqués de presse", "Actualités de presse et de l'entreprise"), ("it", "Comunicati stampa", "Notizie stampa e aziendali")],
			}
			frappe.get_doc({"doctype": "Subscription Topic", "topic_name": name, "category": "Mailing Type", "description": description, "translations": [{"language": lang, "label": label, "description": detail} for lang, label, detail in translations[name]]}).insert(ignore_permissions=True)
	for name in ("BIPV", "Store", "News"):
		if frappe.db.exists("Subscription Topic", name):
			frappe.db.set_value("Subscription Topic", name, "category", "Topic")
		else:
			frappe.get_doc({"doctype": "Subscription Topic", "topic_name": name, "category": "Topic"}).insert(ignore_permissions=True)
	for row in frappe.get_all(
		"Unsubscribe Topic Multi Select",
		filters={"parenttype": "Lead", "parentfield": "custom_unsubscribe_topics"},
		fields=["parent", "subscription_topic"],
		limit_page_length=0,
	):
		email = frappe.db.get_value("Lead", row.parent, "email_id")
		if (
			email
			and frappe.db.exists("Subscription Topic", row.subscription_topic)
			and statuses(email).get(row.subscription_topic) != "Unsubscribed"
		):
			unsubscribe(email, row.subscription_topic, "Legacy Lead opt-out migration")
