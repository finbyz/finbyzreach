frappe.pages["subscriptions-consent"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: __("Subscriptions & consent"), single_column: true});
	wrapper.consent_center = new ConsentCenter(page);
};
frappe.pages["subscriptions-consent"].on_page_show = function (wrapper) { wrapper.consent_center?.load(); };

class ConsentCenter {
	constructor(page) {
		this.page = page;
		this.tab = "types";
		this.offset = 0;
		this.method = "finbyzreach.finbyzreach.page.subscriptions_consent.subscriptions_consent.";
		this.$root = $(page.main).addClass("consent-center");
		page.set_secondary_action(__("Refresh"), () => this.load());
		this.$root.on("click", "[data-tab]", (e) => { this.tab = $(e.currentTarget).attr("data-tab"); this.render(); });
		this.$root.on("click", "[data-edit]", (e) => this.edit($(e.currentTarget).attr("data-edit")));
		this.$root.on("click", "[data-toggle]", (e) => this.toggle($(e.currentTarget).attr("data-toggle")));
        this.$root.on("click", "[data-subscribers]", (e) => {
            const topic = $(e.currentTarget).attr("data-subscribers");
            frappe.prompt([
                {fieldname:"audience_doctype", fieldtype:"Select", options:"Contact\nLead\nCustomer", label:__("Record type"), reqd:1},
                {fieldname:"segment_name", fieldtype:"Data", label:__("Segment name"), default:topic + " subscribers", reqd:1},
                {fieldtype:"HTML", options:`<p class="text-muted">${__("Creates a live segment using each record's primary email address.")}</p>`}
            ], async values => {
                const {message} = await frappe.call({method:"finbyzreach.subscriber_segments.create_subscriber_segment", type:"POST", args:{topic, ...values}});
                frappe.set_route("Form", "Reach Segment", message.name);
            }, __("Show subscribers as segment"));
        });
		this.$root.on("click", "[data-new-topic]", () => this.edit(null, "Topic"));
		this.$root.on("click", "[data-preview]", () => this.preview());
		this.$root.on("click", "[data-log-page]", (e) => { this.offset = Math.max(0, this.offset + Number($(e.currentTarget).attr("data-log-page")) * 50); this.log(); });
	}
	async load() {
		const id = this.request = (this.request || 0) + 1;
		const r = await frappe.call({method: this.method + "overview", type: "GET"});
		if (id !== this.request) return;
		this.data = r.message;
		if (this.data.can_create) this.page.set_primary_action(__("New mailing type"), () => this.edit());
		else this.page.clear_primary_action();
		this.render();
	}
	escape(value) { return frappe.utils.escape_html(String(value ?? "")); }
	render() {
		if (!this.data) return;
		const tabs = [["types", __("Mailing types & topics")], ["preview", __("Preference center")], ["rules", __("Sending rules")], ["log", __("Consent log")]];
		this.$root.html(`<nav class="cc-tabs">${tabs.filter(([key]) => key !== "log" || this.data.can_log).filter(([key]) => key !== "preview" || this.data.can_preview).map(([key, label]) => `<button class="btn btn-default ${key === this.tab ? "active" : ""}" data-tab="${key}" ${key === this.tab ? 'aria-current="page"' : ''}>${label}</button>`).join("")}</nav><div class="cc-body"></div>`);
		if (this.tab === "types") this.types();
		if (this.tab === "preview" && this.data.can_preview) {
			this.$root.find(".cc-body").html(`<section class="cc-card"><h4>${__("Preview an email address")}</h4><p class="text-muted">${__("Consent belongs to the email address. This preview does not change subscriptions or send email.")}</p><div id="cc-email"></div><button class="btn btn-default" data-preview>${__("Preview")}</button></section><div id="cc-preview" aria-live="polite"></div>`);
			this.email = frappe.ui.form.make_control({parent: this.$root.find("#cc-email"), df: {fieldname: "email", fieldtype: "Data", options: "Email", label: __("Email"), reqd: 1}, render_input: true});
		}
		if (this.tab === "rules") this.$root.find(".cc-body").html(`<section class="cc-card"><h4>${__("Sending rules")}</h4><table class="table"><tbody>${[
			[__("Subscribed to the mailing type"), __("Receives marketing email")],
			[__("Not subscribed or unsubscribed"), __("Skipped when consent is required")],
			[__("DOI pending"), __("Skipped unless the mailing type explicitly permits pending delivery")],
			[__("Hard bounce or spam complaint"), __("Blocked for every email type")],
			[__("Excluded segment or duplicate address"), __("Excluded or sent once")],
			[__("Consent not required / Transactional"), __("Marketing opt-outs do not block delivery")],
			[__("Topics"), __("Preferences and filters only; never a second consent gate")]
		].map(([a,b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join("")}</tbody></table></section>`);
		if (this.tab === "log" && this.data.can_log) this.log();
	}
	types() {
		const e = value => this.escape(value);
		this.$root.find(".cc-body").html(["Mailing Type", "Topic", "System"].map(category => `<section class="cc-card"><div class="cc-heading"><h4>${category === "Mailing Type" ? __("Mailing types") : category === "Topic" ? __("Topics") : __("System email type")}</h4>${category === "Topic" && this.data.can_create ? `<button class="btn btn-default btn-sm" data-new-topic>${__("New topic")}</button>` : ""}</div><div class="cc-table"><table class="table"><thead><tr><th>${__("Name")}</th><th>${__("Consent")}</th><th>${__("Subscribed")}</th><th>${__("Pending")}</th><th>${__("Unsubscribed")}</th><th></th></tr></thead><tbody>${this.data.types.filter(row => row.category === category).map(row => {
			const name=e(row.name), count=this.data.counts?.[row.name] || {};
			return `<tr class="${row.disabled ? "text-muted" : ""}"><td><strong>${name}</strong>${row.disabled ? ` <span class="indicator-pill gray">${__("Disabled")}</span>` : ""}<p class="text-muted">${e(row.description)}</p></td><td>${row.consent_required ? __("Required") + (row.double_opt_in ? " · DOI" : "") : __("Not required")}${row.deliver_while_pending ? `<br><small>${__("Pending delivery allowed")}</small>` : ""}</td>${["Subscribed", "Pending", "Unsubscribed"].map(status => `<td>${this.data.counts === null || category === "System" ? "—" : Number(count[status] || 0)}</td>`).join("")}<td>${this.data.can_edit && category !== "System" ? `<button class="btn btn-default btn-xs" data-edit="${name}">${__("Edit & translate")}</button> <button class="btn btn-default btn-xs" data-toggle="${name}">${row.disabled ? __("Enable") : __("Disable")}</button>` : ""}${this.data.can_preview && category !== "System" ? ` <button class="btn btn-default btn-xs" data-subscribers="${name}">${__("Show as segment")}</button>` : ""}</td></tr>`;
		}).join("") || `<tr><td colspan="6" class="text-muted">${__("No options yet")}</td></tr>`}</tbody></table></div></section>`).join(""));
	}
	async edit(name, category = "Mailing Type") {
		if (name ? !this.data.can_edit : !this.data.can_create) return;
		const doc = name ? await frappe.db.get_doc("Subscription Topic", name) : {doctype: "Subscription Topic", category, consent_required: 1, double_opt_in: 1, translations: []};
		const fields = [
			{fieldname: "topic_name", label: __("Internal name"), fieldtype: "Data", reqd: 1, read_only: Boolean(name), default: doc.topic_name},
			{fieldname: "description", label: __("Description"), fieldtype: "Small Text", default: doc.description},
			...(doc.category === "Mailing Type" ? [
				{fieldname: "consent_required", label: __("Consent required"), fieldtype: "Check", default: doc.consent_required},
				{fieldname: "double_opt_in", label: __("Double opt-in (confirmation email)"), fieldtype: "Check", default: doc.double_opt_in},
				{fieldname: "deliver_while_pending", label: __("Deliver while DOI is pending"), fieldtype: "Check", default: doc.deliver_while_pending, depends_on: "eval:doc.consent_required && doc.double_opt_in"},
			] : []),
			...["de", "fr", "it", "en"].flatMap(language => {
				const row = (doc.translations || []).find(row => row.language === language) || {};
				return [{fieldtype: "Section Break", label: language.toUpperCase()}, {fieldname: "label_" + language, label: __("Label"), fieldtype: "Data", default: row.label}, {fieldname: "description_" + language, label: __("Description"), fieldtype: "Small Text", default: row.description}];
			}),
		];
		const dialog = new frappe.ui.Dialog({title: name ? __("Edit and translate") : __("New subscription option"), fields, primary_action_label: __("Save"), primary_action: async values => {
			const button = dialog.get_primary_btn().prop("disabled", true);
			try {
				Object.assign(doc, {topic_name: values.topic_name, description: values.description, consent_required: values.consent_required || 0, double_opt_in: values.double_opt_in || 0, deliver_while_pending: values.deliver_while_pending || 0});
				doc.translations = ["de", "fr", "it", "en"].filter(lang => values["label_" + lang] || values["description_" + lang]).map(language => ({doctype: "Subscription Topic Translation", language, label: values["label_" + language] || values.topic_name, description: values["description_" + language] || ""}));
				await frappe.call({method: name ? "frappe.client.save" : "frappe.client.insert", type: "POST", args: {doc}});
				dialog.hide(); await this.load();
			} finally { button.prop("disabled", false); }
		}});
		dialog.show();
	}
	async toggle(name) {
		if (!this.data.can_edit) return;
		const row = this.data.types.find(row => row.name === name);
		if (!row || row.category === "System") return;
		await frappe.db.set_value("Subscription Topic", name, "disabled", row.disabled ? 0 : 1);
		await this.load();
	}
	async preview() {
		const email = this.email?.get_value();
		if (!email) return;
		const id = this.previewRequest = (this.previewRequest || 0) + 1;
		const r = await frappe.call({method: this.method + "address_preview", type: "GET", args: {email}});
		if (id !== this.previewRequest || this.tab !== "preview") return;
		this.$root.find("#cc-preview").html(`<section class="cc-card"><h4>${__("What this address receives")}</h4>${(r.message || []).map(row => `<div class="cc-decision"><strong>${this.escape(row.name)}</strong><span>${this.escape(row.reason || __("Eligible to receive"))}</span></div>`).join("")}</section>`);
	}
	async log() {
		const offset = this.offset;
		const rows = await frappe.db.get_list("Email Subscription Event", {fields: ["event_time", "email", "subscription_topic", "status", "source", "consent_version"], order_by: "event_time desc, name desc", start: offset, limit: 51});
		if (this.tab !== "log" || this.offset !== offset) return;
		this.$root.find(".cc-body").html(`<section class="cc-card cc-table"><table class="table"><thead><tr>${[__("Date"), __("Email"), __("Mailing type / topic"), __("Action"), __("Source"), __("Text version")].map(label => `<th>${label}</th>`).join("")}</tr></thead><tbody>${rows.slice(0,50).map(row => `<tr>${[row.event_time, row.email, row.subscription_topic, row.status, row.source, row.consent_version].map(value => `<td>${this.escape(value)}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="6">${__("No consent events")}</td></tr>`}</tbody></table><div class="cc-pagination"><button class="btn btn-default btn-sm" data-log-page="-1" ${offset === 0 ? "disabled" : ""}>${__("Previous")}</button><span>${__("Page")} ${Math.floor(offset/50)+1}</span><button class="btn btn-default btn-sm" data-log-page="1" ${rows.length <= 50 ? "disabled" : ""}>${__("Next")}</button></div></section>`);
	}
}
