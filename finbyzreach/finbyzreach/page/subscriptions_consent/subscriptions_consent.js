frappe.pages["subscriptions-consent"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: __("Subscriptions & consent"), single_column: true});
	wrapper.consent_center = new ConsentCenter(page);
};
frappe.pages["subscriptions-consent"].on_page_show = function (wrapper) { wrapper.consent_center?.load(); };

const PC_METHOD = "finbyzreach.preference_center.";
const PC_LANGS = ["de", "fr", "it", "en"];
const PC_PAGES = {
	manage: {label: "Preference center", url: "/manage_subscriptions",
		sections: {intro: "Title and introduction", types: "Mailing types", topics: "Topics", buttons: "Save and unsubscribe", foot: "Footer text"},
		texts: {h: "Title", s: "Introduction", mailing: "Mailing types heading", top: "Topics heading", save: "Button text", all: "Unsubscribe-all link", foot: "Footer text"},
		messages: {language: "Language label", current: "Current topic badge", waiting: "Pending confirmation note", pending: "After subscribing (double opt-in)", saving: "While saving", error: "Save failed", subscribed: "Saved", invalid: "Invalid link"}},
	subscribe: {label: "Subscribe page", url: "/subscribe",
		sections: {intro: "Title and introduction", names: "First and last name", email: "Email field", types: "Mailing types", topics: "Topics", legal: "Privacy note", buttons: "Subscribe button", foot: "Footer text"},
		texts: {h: "Title", s: "Introduction", mailing: "Mailing types heading", top: "Topics heading", register: "Button text", legal: "Privacy note", foot: "Footer text"},
		messages: {first_name: "First name label", last_name: "Last name label", email: "Email label", language: "Language label", choose: "No option chosen", pending: "After subscribing (double opt-in)", subscribed: "After subscribing (no double opt-in)", error: "Sign-up failed"}},
	confirm: {label: "Confirmation page", url: "/confirm_subscription",
		sections: {intro: "Title and introduction", button: "Confirm button", foot: "Footer text"},
		texts: {h: "Title", s: "Introduction", button: "Button text", foot: "Footer text"},
		messages: {done: "After confirming", invalid: "Invalid or expired link"}},
};

class ConsentCenter {
	constructor(page) {
		this.page = page;
		this.tab = "types";
		this.offset = 0;
		this.logFilters = {};
		this.method = "finbyzreach.finbyzreach.page.subscriptions_consent.subscriptions_consent.";
		this.$root = $(page.main).addClass("consent-center");
		page.set_secondary_action(__("Refresh"), () => this.load());
		this.$root.on("click", "[data-tab]", (e) => { this.tab = $(e.currentTarget).attr("data-tab"); this.offset = 0; this.render(); });
		this.$root.on("click", "[data-edit]", (e) => this.edit($(e.currentTarget).attr("data-edit")));
		this.$root.on("click", "[data-enable-toggle]", (e) => this.toggle($(e.currentTarget).attr("data-enable-toggle")));
		this.$root.on("click", "[data-delete]", (e) => this.remove($(e.currentTarget).attr("data-delete")));
		this.$root.on("click", "[data-subscribers]", (e) => {
			const topic = $(e.currentTarget).attr("data-subscribers");
			frappe.prompt([
				{fieldname: "audience_doctype", fieldtype: "Select", options: "Contact\nLead\nCustomer", label: __("Record type"), reqd: 1},
				{fieldname: "segment_name", fieldtype: "Data", label: __("Segment name"), default: topic + " subscribers", reqd: 1},
				{fieldtype: "HTML", options: `<p class="text-muted">${__("Creates a live segment using each record's primary email address.")}</p>`}
			], async values => {
				const {message} = await frappe.call({method: "finbyzreach.subscriber_segments.create_subscriber_segment", type: "POST", args: {topic, ...values}});
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
		const tabs = [["types", __("Mailing types & topics")], ["preview", __("Preference center")], ["address", __("Address check")], ["rules", __("Sending rules")], ["log", __("Consent log")]]
			.filter(([key]) => key !== "log" || this.data.can_log)
			.filter(([key]) => key !== "preview" || this.data.can_design)
			.filter(([key]) => key !== "address" || this.data.can_preview);
		if (!tabs.some(([key]) => key === this.tab)) this.tab = tabs[0][0];
		this.$root.html(`<nav class="cc-tabs"><div class="pc-seg">${tabs.map(([key, label]) => `<button type="button" class="${key === this.tab ? "active" : ""}" data-tab="${key}" ${key === this.tab ? 'aria-current="page"' : ""}>${label}</button>`).join("")}</div></nav><div class="cc-body"></div>`);
		if (this.tab === "types") this.types();
		if (this.tab === "preview") this.preferenceCenter();
		if (this.tab === "address") this.addressCheck();
		if (this.tab === "rules") this.rules();
		if (this.tab === "log" && this.data.can_log) this.log();
	}
	types() {
		const e = value => this.escape(value);
		const labelsCell = row => {
			const labels = this.data.labels?.[row.name] || {};
			const translated = PC_LANGS.filter(l => labels[l] && labels[l] !== row.name);
			if (!translated.length) return `<span class="text-muted small">${__("Not translated")}</span>${this.data.can_edit && row.category !== "System" ? ` · <a class="small" data-edit="${e(row.name)}">${__("Translate")}</a>` : ""}`;
			return PC_LANGS.map(l => `<div class="cc-label-line"><span class="cc-lang">${l.toUpperCase()}</span>${labels[l] ? e(labels[l]) : `<span class="text-muted">—</span>`}</div>`).join("");
		};
		const consentPill = row => {
			if (row.category === "Topic") return `<span class="indicator-pill gray" title="${__("Topics are preferences and filters only; they never block an email")}">${__("Preference only")}</span>`;
			if (!row.consent_required) return `<span class="indicator-pill green">${__("Not required")}</span>`;
			return `<span class="indicator-pill orange">${__("Required")}${row.double_opt_in ? " · DOI" : ""}</span>${row.deliver_while_pending ? `<div class="small text-muted">${__("Delivered while DOI pending")}</div>` : ""}`;
		};
		const menu = row => {
			if (row.category === "System") return "";
			const name = e(row.name), items = [];
			if (this.data.can_edit) items.push(`<a class="dropdown-item" data-edit="${name}">${__("Edit and translate")}</a>`);
			if (this.data.can_preview) items.push(`<a class="dropdown-item" data-subscribers="${name}">${__("Show subscribers as segment")}</a>`);
			if (this.data.can_edit) items.push(`<a class="dropdown-item" data-enable-toggle="${name}">${row.disabled ? __("Enable") : __("Disable")}</a>`);
			if (this.data.can_delete) items.push(`<div class="dropdown-divider"></div><a class="dropdown-item text-danger" data-delete="${name}">${__("Delete")}</a>`);
			if (!items.length) return "";
			return `<div class="dropdown"><button class="btn btn-default btn-xs" data-bs-toggle="dropdown" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" aria-label="${__("Actions")}">⋯</button><div class="dropdown-menu dropdown-menu-right dropdown-menu-end">${items.join("")}</div></div>`;
		};
		const sections = [
			["Mailing Type", __("Mailing types"), __("Decide consent: an email of this type only goes to addresses subscribed to it.")],
			["Topic", __("Topics"), __("Optional interests shown in the preference center. They filter, but never block an email.")],
			["System", __("System email type"), __("Order and service information. Marketing opt-outs do not apply.")],
		];
		this.$root.find(".cc-body").html(sections.map(([category, title, help]) => {
			const rows = this.data.types.filter(row => row.category === category);
			return `<section class="cc-card">
				<div class="cc-heading"><div><h4>${title}</h4><p class="text-muted small cc-help">${help}</p></div>${category === "Topic" && this.data.can_create ? `<button class="btn btn-default btn-sm" data-new-topic>${__("New topic")}</button>` : ""}</div>
				<div class="cc-table cc-types-wrap"><table class="table cc-types"><colgroup><col class="cc-col-name"><col class="cc-col-labels"><col class="cc-col-consent"><col class="cc-col-num"><col class="cc-col-num"><col class="cc-col-num"><col class="cc-col-menu"></colgroup>
				<thead><tr><th>${__("Name")}</th><th>${__("Labels")}</th><th>${__("Consent")}</th><th class="text-right">${__("Subscribed")}</th><th class="text-right">${__("Pending")}</th><th class="text-right">${__("Unsubscribed")}</th><th></th></tr></thead>
				<tbody>${rows.map(row => {
					const count = this.data.counts?.[row.name] || {};
					const num = status => this.data.counts === null || category === "System" ? `<span class="text-muted">—</span>` : Number(count[status] || 0);
					return `<tr class="${row.disabled ? "cc-disabled" : ""}"><td><strong>${e(row.name)}</strong>${row.disabled ? ` <span class="indicator-pill gray">${__("Disabled")}</span>` : ""}${row.description ? `<p class="text-muted">${e(row.description)}</p>` : ""}</td>
						<td class="cc-labels">${labelsCell(row)}</td><td>${consentPill(row)}</td>
						<td class="text-right">${num("Subscribed")}</td><td class="text-right">${num("Pending")}</td><td class="text-right">${num("Unsubscribed")}</td><td class="text-right">${menu(row)}</td></tr>`;
				}).join("") || `<tr><td colspan="7" class="text-muted">${__("No options yet")}</td></tr>`}</tbody></table></div></section>`;
		}).join(""));
	}
	rules() {
		this.$root.find(".cc-body").html(`<section class="cc-card"><h4>${__("Three layers of protection")}</h4><div class="cc-layers">${[
			[__("Layer 1 · Segment"), __("Filter in the segment (optional)"), __("A segment can filter on the subscription status of a mailing type. Recommended, but not required: Layer 2 checks campaign recipients anyway.")],
			[__("Layer 2 · Send guard"), __("Check before sending (always on for campaigns)"), __("Campaign emails are checked when the audience is built and again when the mail server takes them: subscription to the mailing type, unsubscribes, hard bounce, spam complaint, duplicate address. Workflow emails get the same check only when the send step sets an email type. Steps without one check unsubscribes and Do Not Contact only.")],
			[__("Layer 3 · In the email"), __("Unsubscribe always possible"), __("Marketing emails get a locked footer with unsubscribe and preference center links, plus the one-click List-Unsubscribe header. Transactional emails have no footer.")]
		].map(([k, t, d]) => `<div class="cc-layer"><small class="text-muted">${k}</small><strong>${t}</strong><p class="text-muted">${d}</p></div>`).join("")}</div></section>
		<section class="cc-card"><h4>${__("Who receives an email")}</h4><table class="table"><tbody>${[
			[__("Subscribed to the mailing type"), __("Receives it")],
			[__("Not subscribed, or unsubscribed from the mailing type"), __("Skipped when the mailing type requires consent")],
			[__("DOI pending"), __("Skipped, unless the mailing type allows delivery while pending")],
			[__("Lead or Contact unsubscribed, Do Not Contact, or globally unsubscribed"), __("Skipped when the mailing type requires consent")],
			[__("Lead disabled"), __("Skipped in campaigns. In workflows, skipped when the email type requires consent or no type is set")],
			[__("Hard bounce or spam complaint"), __("Blocked for every email type, Transactional included. Not checked for workflow steps without an email type")],
			[__("Excluded by segment filters or an email group"), __("Not sent")],
			[__("Same address more than once in a campaign"), __("Sent once")],
			[__("Mailing type without consent, or Transactional"), __("Subscriptions and unsubscribes do not block delivery. Hard bounces and spam complaints still do")],
			[__("Topics"), __("Preferences and segment filters only, never a consent check")]
		].map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join("")}</tbody></table></section>`);
	}
	async remove(name) {
		const counts = this.data.counts?.[name] || {};
		const stored = Object.values(counts).reduce((a, b) => a + Number(b || 0), 0);
		const message = stored
			? __("{0} has {1} stored consent records. Deleting is blocked while consent data exists; disable it instead to hide it everywhere and keep the data.", [this.escape(name), stored])
			: __("Delete {0}? This cannot be undone.", [this.escape(name)]);
		if (stored) return frappe.msgprint(message);
		frappe.confirm(message, async () => {
			await frappe.call({method: "frappe.client.delete", type: "POST", args: {doctype: "Subscription Topic", name}});
			frappe.show_alert({message: __("Deleted"), indicator: "green"});
			this.load();
		});
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
			...PC_LANGS.flatMap(language => {
				const row = (doc.translations || []).find(row => row.language === language) || {};
				return [{fieldtype: "Section Break", label: language.toUpperCase()}, {fieldname: "label_" + language, label: __("Label"), fieldtype: "Data", default: row.label}, {fieldname: "description_" + language, label: __("Description"), fieldtype: "Small Text", default: row.description}];
			}),
		];
		const dialog = new frappe.ui.Dialog({title: name ? __("Edit and translate") : __("New subscription option"), fields, primary_action_label: __("Save"), primary_action: async values => {
			const button = dialog.get_primary_btn().prop("disabled", true);
			try {
				Object.assign(doc, {topic_name: values.topic_name, description: values.description, consent_required: values.consent_required || 0, double_opt_in: values.double_opt_in || 0, deliver_while_pending: values.deliver_while_pending || 0});
				doc.translations = PC_LANGS.filter(lang => values["label_" + lang] || values["description_" + lang]).map(language => ({doctype: "Subscription Topic Translation", language, label: values["label_" + language] || values.topic_name, description: values["description_" + language] || ""}));
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

	/* ---------------- Preference center: page editor (CS-05, CS-06) ---------------- */
	async preferenceCenter() {
		const $body = this.$root.find(".cc-body");
		$body.html(`<div class="pc-editor"></div>`);
		if (!this.data.can_design) return;
		const {message} = await frappe.call({method: PC_METHOD + "get_editor_state", type: "GET"});
		if (this.tab !== "preview") return;
		this.pc = message;
		this.config = message.config;
		this.pcLang = this.pcLang || "de";
		this.pcPage = this.pcPage || "manage";
		this.selected = null;
		this.renderEditor();
	}
	/* ---------------- Address check: what one email address receives ---------------- */
	addressCheck() {
		this.$root.find(".cc-body").html(`<section class="cc-card cc-address"><h4>${__("What an email address receives")}</h4><p class="text-muted">${__("Consent belongs to the email address. This check does not change subscriptions or send email.")}</p><div class="cc-address-row"><div id="cc-email"></div><button class="btn btn-primary btn-sm" data-preview>${__("Check")}</button></div><div id="cc-preview" aria-live="polite"></div></section>`);
		this.email = frappe.ui.form.make_control({parent: this.$root.find("#cc-email"), df: {fieldname: "email", fieldtype: "Data", options: "Email", placeholder: "name@example.com"}, render_input: true});
		this.email.$input.on("keydown", e => { if (e.key === "Enter") this.preview(); });
	}
	panelOpen(key, fallback) {
		this.panels = this.panels || {};
		return (key in this.panels ? this.panels[key] : fallback) ? "open" : "";
	}
	pageCfg() {
		// The preference center keeps its keys at the top level; other pages under their own key.
		return this.pcPage === "manage" ? this.config : this.config[this.pcPage];
	}
	renderEditor() {
		const e = v => this.escape(v);
		const s = this.pc;
		this.$root.find(".pc-editor").html(`<section class="cc-card">
			<div class="pc-toolbar">
				<div class="pc-seg" role="tablist" aria-label="${__("Page")}">${Object.entries(PC_PAGES).map(([k, p]) => `<button class="${k === this.pcPage ? "active" : ""}" data-pc-page="${k}" role="tab" aria-selected="${k === this.pcPage}">${__(p.label)}</button>`).join("")}</div>
				<div class="pc-toolbar-right"><button class="btn btn-default btn-sm" data-pc-reset title="${__("Back to the Megasol defaults")}">${__("Reset to defaults")}</button><button class="btn btn-default btn-sm" data-pc-discard title="${__("Back to the last published version")}">${__("Discard changes")}</button><button class="btn btn-primary btn-sm" data-pc-publish>${__("Publish")}</button></div>
			</div>
			<div class="pc-subbar">
				<div class="pc-seg pc-seg-sm" role="group" aria-label="${__("Editing language")}">${PC_LANGS.map(l => `<button class="${l === this.pcLang ? "active" : ""}" data-pc-lang="${l}">${l.toUpperCase()}</button>`).join("")}</div>
				<span class="pc-status"></span><span class="text-muted small pc-save-state"></span>
				<span class="text-muted small pc-hint">${__("Click a text in the preview to edit it and its style.")}</span>
			</div>
			<div class="pc-layout">
				<div class="pc-frame-wrap"><iframe class="pc-frame" title="${__(PC_PAGES[this.pcPage].label)}: ${__("preview")}"></iframe></div>
				<div class="pc-side"></div>
			</div></section>`);
		this.renderSide();
		this.bindEditor();
		this.reloadFrame();
	}
	renderSide() {
		const e = v => this.escape(v);
		const s = this.pc;
		const spec = PC_PAGES[this.pcPage];
		const required = (s.pages?.[this.pcPage]?.required) || [];
		this.$root.find(".pc-status").html(s.unpublished_changes ? `<span class="indicator-pill orange">${__("Unpublished changes")}</span>` : `<span class="indicator-pill green">${__("Published")}</span>`);
		this.$root.find(".pc-side").html(`
					<div class="pc-panel pc-style-panel"></div>
					<details class="pc-panel" data-pc-panel="theme" ${this.panelOpen("theme", true)}><summary>${__("Theme and logo")} <span class="text-muted small">· ${__("all pages")}</span></summary>
						<div class="pc-row">${Object.keys(s.presets).map(p => `<button class="btn btn-default btn-xs" data-pc-preset="${p}">${__(p.charAt(0).toUpperCase() + p.slice(1))}</button>`).join("")}</div>
						<div class="pc-grid">
							<label>${__("Font")}<select class="form-control input-sm" data-pc-theme="font">${s.fonts.map(f => `<option ${this.config.theme.font === f ? "selected" : ""}>${f}</option>`).join("")}</select></label>
							<label>${__("Page width")}<select class="form-control input-sm" data-pc-theme="width">${s.widths.map(w => `<option value="${w}" ${this.config.theme.width === w ? "selected" : ""}>${w} px</option>`).join("")}</select></label>
							${[["primary", __("Primary")], ["button", __("Button")], ["background", __("Page background")], ["card", __("Card")], ["text", __("Text")]].map(([k, l]) => `<label>${l}<span class="pc-colour-field"><input type="color" class="pc-colour" data-pc-theme="${k}" value="${e(this.config.theme[k])}"><code>${e(this.config.theme[k])}</code></span></label>`).join("")}
							<label>${__("Button radius")}<select class="form-control input-sm" data-pc-theme="radius">${[0, 4, 6, 10, 20].map(r => `<option value="${r}" ${this.config.theme.radius === r ? "selected" : ""}>${r} px</option>`).join("")}</select></label>
						</div>
						<div class="pc-row"><button class="btn btn-default btn-xs" data-pc-logo>${this.config.theme.logo ? __("Replace logo") : __("Upload logo")}</button>${this.config.theme.logo ? `<button class="btn btn-default btn-xs" data-pc-logo-remove>${__("Remove logo")}</button>` : ""}</div>
						<p class="text-muted small">${__("Theme, logo and these options apply to all three pages.")}</p>
						<label class="pc-check"><input type="checkbox" data-pc-flag="show_descriptions" ${this.config.show_descriptions ? "checked" : ""}> ${__("Show descriptions")}</label>
						<label class="pc-check"><input type="checkbox" data-pc-flag="show_topics" ${this.config.show_topics ? "checked" : ""}> ${__("Show topics")}</label>
					</details>
					<details class="pc-panel" data-pc-panel="sections" ${this.panelOpen("sections", true)}><summary>${__("Sections")} <span class="text-muted small">· ${__(spec.label)}</span></summary><ul class="pc-sections">${this.pageCfg().order.map((k, i) => `<li class="${this.pageCfg().hidden.includes(k) ? "text-muted" : ""}"><span>${e(spec.sections[k] ? __(spec.sections[k]) : __("Text block") + ": " + (this.pageCfg().texts[this.pcLang][k] || "").slice(0, 24))}</span>
						<span><button class="btn btn-default btn-xs" data-pc-move="${i}|-1" aria-label="${__("Move up")}">↑</button><button class="btn btn-default btn-xs" data-pc-move="${i}|1" aria-label="${__("Move down")}">↓</button>${required.includes(k) ? `<span class="text-muted small" title="${__("This page needs it")}">${__("Required")}</span>` : `<button class="btn btn-default btn-xs" data-pc-hide="${k}">${this.pageCfg().hidden.includes(k) ? __("Show") : __("Hide")}</button>`}${spec.sections[k] ? "" : `<button class="btn btn-default btn-xs text-danger" data-pc-remove="${k}">${__("Remove")}</button>`}</span></li>`).join("")}</ul>
						<button class="btn btn-default btn-xs" data-pc-add-text>${__("Add text block")}</button></details>
					<details class="pc-panel" data-pc-panel="messages" ${this.panelOpen("messages", false)}><summary>${__("Messages")} <span class="text-muted small">· ${this.pcLang.toUpperCase()}</span></summary>${Object.entries(spec.messages).map(([k, l]) => `<label class="pc-msg">${__(l)}<input class="form-control input-sm" data-pc-message="${k}" value="${e(this.pageCfg().texts[this.pcLang][k] || "")}"></label>`).join("")}
						<p class="text-muted small">${__("Mailing type labels and descriptions are edited under Mailing types & topics. Texts are saved per language; styles and theme apply to all languages.")}</p></details>`);
		this.renderStylePanel();
	}
	renderStylePanel() {
		const $panel = this.$root.find(".pc-style-panel");
		const key = this.selected;
		if (!key) { $panel.html(`<h5>${__("Text style")}</h5><p class="text-muted small">${__("Click a text in the page to set its type (H1–P), size, weight, colour and alignment.")}</p>`); return; }
		const st = this.pageCfg().styles[key] || {};
		const colours = [["primary", this.config.theme.primary], ["text", this.config.theme.text], ["muted", "#5d6875"], ["white", "#ffffff"], ["#d98d0c", "#d98d0c"], ["#268c5c", "#268c5c"]];
		$panel.html(`<h5>${__("Text style")}: ${this.escape(__(PC_PAGES[this.pcPage].texts[key] || "Text block"))}</h5>
			<div class="btn-group pc-row" role="group">${["H1", "H2", "H3", "P"].map(t => `<button class="btn btn-default btn-xs ${st.tag === t ? "active" : ""}" data-pc-style="tag|${t}">${t}</button>`).join("")}</div>
			<div class="pc-grid"><label>${__("Size")}<select class="form-control input-sm" data-pc-style-size>${[11, 12, 13, 14, 16, 18, 20, 24, 28, 32].map(v => `<option value="${v}" ${st.size === v ? "selected" : ""}>${v} px</option>`).join("")}</select></label>
			<label>${__("Weight")}<select class="form-control input-sm" data-pc-style-bold><option value="0" ${!st.bold ? "selected" : ""}>${__("Regular")}</option><option value="1" ${st.bold ? "selected" : ""}>${__("Bold")}</option></select></label></div>
			<div class="pc-row">${colours.map(([v, c]) => `<button class="pc-swatch ${st.color === v ? "active" : ""}" style="background:${c}" data-pc-style="color|${v}" title="${v}" aria-label="${__("Colour")} ${v}"></button>`).join("")}</div>
			<div class="btn-group pc-row" role="group">${["left", "center", "right"].map(a => `<button class="btn btn-default btn-xs ${st.align === a ? "active" : ""}" data-pc-style="align|${a}">${__(a.charAt(0).toUpperCase() + a.slice(1))}</button>`).join("")}</div>
			<button class="btn btn-default btn-xs" data-pc-style="reset|1">${__("Reset style")}</button>`);
	}
	bindEditor() {
		const $ed = this.$root.find(".pc-editor");
		$ed.off(".pc");
		$ed[0]?.addEventListener("toggle", ev => { const key = ev.target.dataset?.pcPanel; if (key) (this.panels = this.panels || {})[key] = ev.target.open; }, true);
		$ed.on("click.pc", "[data-pc-page]", e => { this.pcPage = $(e.currentTarget).attr("data-pc-page"); this.selected = null; this.renderEditor(); });
		$ed.on("click.pc", "[data-pc-lang]", e => { this.pcLang = $(e.currentTarget).attr("data-pc-lang"); this.renderEditor(); });
		$ed.on("click.pc", "[data-pc-preset]", e => { Object.assign(this.config.theme, this.pc.presets[$(e.currentTarget).attr("data-pc-preset")]); this.changed(true, true); });
		$ed.on("change.pc", "[data-pc-theme]", e => { const k = $(e.currentTarget).attr("data-pc-theme"); const v = e.currentTarget.value; this.config.theme[k] = ["width", "radius"].includes(k) ? Number(v) : v; this.changed(true, true); });
		$ed.on("change.pc", "[data-pc-flag]", e => { this.config[$(e.currentTarget).attr("data-pc-flag")] = e.currentTarget.checked ? 1 : 0; this.changed(true); });
		$ed.on("change.pc", "[data-pc-message]", e => { this.pageCfg().texts[this.pcLang][$(e.currentTarget).attr("data-pc-message")] = e.currentTarget.value; this.changed(false); });
		$ed.on("click.pc", "[data-pc-move]", e => { const [i, d] = $(e.currentTarget).attr("data-pc-move").split("|").map(Number); const o = this.pageCfg().order; const j = i + d; if (j < 0 || j >= o.length) return; [o[i], o[j]] = [o[j], o[i]]; this.changed(true, true); });
		$ed.on("click.pc", "[data-pc-hide]", e => { const k = $(e.currentTarget).attr("data-pc-hide"); const h = this.pageCfg().hidden; this.pageCfg().hidden = h.includes(k) ? h.filter(x => x !== k) : [...h, k]; this.changed(true, true); });
		$ed.on("click.pc", "[data-pc-add-text]", () => {
			const used = new Set(this.pageCfg().custom);
			let n = 1; while (used.has("c" + n)) n++;
			const key = "c" + n;
			this.pageCfg().custom.push(key);
			PC_LANGS.forEach(l => { this.pageCfg().texts[l][key] = {de: "Neuer Textblock – zum Bearbeiten klicken.", fr: "Nouveau bloc de texte – cliquez pour modifier.", it: "Nuovo blocco di testo – clicca per modificare.", en: "New text block – click to edit."}[l]; });
			this.pageCfg().order.splice(1, 0, key);
			this.changed(true, true);
		});
		$ed.on("click.pc", "[data-pc-remove]", e => { const k = $(e.currentTarget).attr("data-pc-remove"); this.pageCfg().custom = this.pageCfg().custom.filter(x => x !== k); this.pageCfg().order = this.pageCfg().order.filter(x => x !== k); this.pageCfg().hidden = this.pageCfg().hidden.filter(x => x !== k); if (this.selected === k) this.selected = null; this.changed(true, true); });
		$ed.on("click.pc", "[data-pc-style]", e => {
			const [p, v] = $(e.currentTarget).attr("data-pc-style").split("|");
			if (!this.selected) return;
			if (p === "reset") delete this.pageCfg().styles[this.selected];
			else {
				const st = this.pageCfg().styles[this.selected] = this.pageCfg().styles[this.selected] || {};
				st[p] = v;
				if (p === "tag") { st.size = {H1: 26, H2: 20, H3: 16, P: 14}[v]; st.bold = v !== "P"; }
			}
			this.changed(true, false, true);
		});
		$ed.on("change.pc", "[data-pc-style-size]", e => { if (!this.selected) return; (this.pageCfg().styles[this.selected] = this.pageCfg().styles[this.selected] || {}).size = Number(e.currentTarget.value); this.changed(true, false, true); });
		$ed.on("change.pc", "[data-pc-style-bold]", e => { if (!this.selected) return; (this.pageCfg().styles[this.selected] = this.pageCfg().styles[this.selected] || {}).bold = e.currentTarget.value === "1"; this.changed(true, false, true); });
		$ed.on("click.pc", "[data-pc-logo]", () => new frappe.ui.FileUploader({
			restrictions: {allowed_file_types: ["image/*"]}, make_attachments_public: true, allow_multiple: false,
			on_success: file => { if (!String(file.file_url || "").startsWith("/files/")) return frappe.msgprint(__("Please upload a public image.")); this.config.theme.logo = file.file_url; this.changed(true, true); }
		}));
		$ed.on("click.pc", "[data-pc-logo-remove]", () => { this.config.theme.logo = ""; this.changed(true, true); });
		$ed.on("click.pc", "[data-pc-publish]", () => frappe.confirm(__("Publish the preference center, subscribe page and confirmation page? Visitors see the new version immediately."), async () => {
			await this.flush();
			await frappe.call({method: PC_METHOD + "publish", type: "POST", freeze: true});
			frappe.show_alert({message: __("Preference center published"), indicator: "green"});
			this.pc.unpublished_changes = false;
			this.renderSide();
		}));
		$ed.on("click.pc", "[data-pc-reset]", () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Reset to defaults"),
				fields: [
					{fieldname: "scope", fieldtype: "Select", label: __("What to reset"), reqd: 1, default: "all",
						options: [
							{value: "all", label: __("Everything: all three pages and the theme")},
							{value: this.pcPage, label: __("Only {0}: texts, styles and sections", [__(PC_PAGES[this.pcPage].label)])},
							{value: "theme", label: __("Only theme and logo (colours, font, width, logo)")},
						]},
					{fieldtype: "HTML", options: `<p class="text-muted small">${__("Colours, font and logo belong to the theme, which all three pages share, so a page reset keeps them. Mailing types are not affected. The reset is saved as a draft: visitors keep seeing the published version until you publish.")}</p>`},
				],
				primary_action_label: __("Reset"),
				primary_action: async values => {
					dialog.hide();
					clearTimeout(this.saveTimer);
					// An auto-save still on the wire would land after the reset and bring the old design back.
					await this.saving?.catch(() => {});
					const before = JSON.stringify(this.config);
					const {message} = await frappe.call({method: PC_METHOD + "reset_draft", type: "POST", args: {page: values.scope}, freeze: true});
					this.config = message; this.selected = null; this.pc.unpublished_changes = true;
					this.renderEditor();
					if (JSON.stringify(message) === before) {
						frappe.msgprint(values.scope === "theme" || values.scope === "all" ? __("Nothing to reset: the design already uses the defaults.")
							: __("Nothing to reset on this page. Your changes are probably in the theme (colours, font, logo): choose “Everything” or “Only theme and logo”."));
					} else {
						frappe.show_alert({message: __("Reset to defaults. Click Publish to make it visible on the websites."), indicator: "blue"});
					}
				},
			});
			dialog.show();
		});
		$ed.on("click.pc", "[data-pc-discard]", () => frappe.confirm(__("Discard all unpublished changes?"), async () => {
			clearTimeout(this.saveTimer);
			await this.saving?.catch(() => {});
			const {message} = await frappe.call({method: PC_METHOD + "discard_draft", type: "POST"});
			this.config = message; this.pc.unpublished_changes = false; this.selected = null; this.renderEditor();
		}));
	}
	changed(save = true, rerenderSide = false, stylePanel = false) {
		this.pc.unpublished_changes = true;
		if (rerenderSide) this.renderSide();
		else if (stylePanel) this.renderStylePanel();
		this.$root.find(".pc-status").html(`<span class="indicator-pill orange">${__("Unpublished changes")}</span>`);
		// The preview reloads only after the draft is saved, so it always shows the saved version.
		if (save) this.scheduleSave(true);
	}
	scheduleSave(reloadFrame = true) {
		clearTimeout(this.saveTimer);
		this.$root.find(".pc-save-state").text(__("Saving…"));
		this.saveTimer = setTimeout(async () => {
			await this.flush();
			if (reloadFrame) this.reloadFrame();
		}, 500);
	}
	async flush() {
		clearTimeout(this.saveTimer);
		// Keep the local copy: replacing it with the response would drop keystrokes typed
		// while the request was in flight. The server still validates what it stores.
		this.saving = frappe.call({method: PC_METHOD + "save_draft", type: "POST", args: {config: JSON.stringify(this.config)}});
		try { await this.saving; } finally { this.saving = null; }
		this.$root.find(".pc-save-state").text(__("All changes saved"));
	}
	reloadFrame() {
		const frame = this.$root.find(".pc-frame")[0];
		if (!frame) return;
		frame.onload = () => this.wireFrame(frame);
		const page = PC_PAGES[this.pcPage];
		// The confirmation page needs no real token in preview; editors only (server-checked).
		frame.src = `${page.url}?pc_preview=1&lang=${this.pcLang}&_=${Date.now()}`;
	}
	wireFrame(frame) {
		// Same-origin preview: texts are edited in place, the form never submits.
		const doc = frame.contentDocument;
		if (!doc) return;
		frame.style.height = Math.max(520, doc.documentElement.scrollHeight + 20) + "px";
		doc.addEventListener("submit", e => e.preventDefault(), true);
		doc.querySelectorAll("a").forEach(a => a.addEventListener("click", e => e.preventDefault()));
		doc.querySelectorAll("[data-pc-text]").forEach(el => {
			el.setAttribute("contenteditable", "true");
			el.setAttribute("spellcheck", "true");
			if (el.dataset.pcText === this.selected) el.classList.add("pc-selected");
			el.addEventListener("click", e => {
				e.preventDefault(); e.stopPropagation();
				doc.querySelectorAll(".pc-selected").forEach(x => x.classList.remove("pc-selected"));
				el.classList.add("pc-selected");
				this.selected = el.dataset.pcText;
				this.renderStylePanel();
			});
			el.addEventListener("keydown", e => { if (e.key === "Enter") e.preventDefault(); });
			el.addEventListener("input", () => {
				this.pageCfg().texts[this.pcLang][el.dataset.pcText] = el.innerText.trim();
				this.pc.unpublished_changes = true;
				this.scheduleSave(false);
			});
		});
		doc.querySelectorAll("input[type=checkbox]").forEach(cb => cb.addEventListener("click", e => e.preventDefault()));
	}
	async preview() {
		const email = this.email?.get_value();
		if (!email) return;
		const id = this.previewRequest = (this.previewRequest || 0) + 1;
		const r = await frappe.call({method: this.method + "address_preview", type: "GET", args: {email}});
		if (id !== this.previewRequest || this.tab !== "address") return;
		this.$root.find("#cc-preview").html((r.message || []).map(row => `<div class="cc-decision"><strong>${this.escape(row.name)}</strong><span>${this.escape(row.status)} · ${this.escape(row.reason || __("Eligible to receive"))}</span></div>`).join(""));
	}

	/* ---------------- Consent log (CS-10) ---------------- */
	async log() {
		const offset = this.offset, f = this.logFilters;
		const {message} = await frappe.call({method: this.method + "consent_log", type: "GET", args: {...f, start: offset}});
		if (this.tab !== "log" || this.offset !== offset) return;
		const e = v => this.escape(v);
		const topics = this.data.types.filter(t => t.category !== "System").map(t => t.name);
		const person = p => p ? `<a href="/app/${frappe.router.slug(p.doctype)}/${encodeURIComponent(p.name)}">${e(p.label)}</a> <span class="text-muted small">${__(p.doctype)}</span>` : `<span class="text-muted">—</span>`;
		this.$root.find(".cc-body").html(`<section class="cc-card cc-table">
			<div class="cc-filters">
				<input class="form-control input-sm" data-log-filter="search" placeholder="${__("Search email address")}" value="${e(f.search || "")}">
				<select class="form-control input-sm" data-log-filter="status"><option value="">${__("Action: all")}</option>${["Subscribed", "Pending", "Unsubscribed"].map(s => `<option value="${s}" ${f.status === s ? "selected" : ""}>${__(s)}</option>`).join("")}</select>
				<select class="form-control input-sm" data-log-filter="topic"><option value="">${__("Mailing type / topic: all")}</option>${topics.map(t => `<option value="${e(t)}" ${f.topic === t ? "selected" : ""}>${e(t)}</option>`).join("")}</select>
				<select class="form-control input-sm" data-log-filter="source"><option value="">${__("Source: all")}</option>${(message.sources || []).map(s => `<option value="${e(s)}" ${f.source === s ? "selected" : ""}>${e(s)}</option>`).join("")}</select>
				${message.can_export ? `<button class="btn btn-default btn-sm" data-log-export>${__("Export CSV")}</button>` : ""}
			</div>
			<table class="table"><thead><tr>${[__("Date and time"), __("Contact / lead"), __("Email"), __("Mailing type / topic"), __("Action"), __("Source"), __("Text version")].map(label => `<th>${label}</th>`).join("")}</tr></thead>
			<tbody>${message.rows.map(row => `<tr><td>${e(frappe.datetime.str_to_user(row.event_time))}</td><td>${person(row.person)}</td><td>${e(row.email)}</td><td>${e(row.subscription_topic)}</td><td>${e(__(row.status))}</td><td>${e(row.source)}</td><td>${e(row.consent_version)}</td></tr>`).join("") || `<tr><td colspan="7">${__("No consent events")}</td></tr>`}</tbody></table>
			<div class="cc-pagination"><button class="btn btn-default btn-sm" data-log-page="-1" ${offset === 0 ? "disabled" : ""}>${__("Previous")}</button><span>${__("Page")} ${Math.floor(offset / 50) + 1}</span><button class="btn btn-default btn-sm" data-log-page="1" ${message.has_more ? "" : "disabled"}>${__("Next")}</button></div></section>`);
		const $body = this.$root.find(".cc-body");
		$body.find("[data-log-filter]").on("change", ev => { this.logFilters[$(ev.currentTarget).attr("data-log-filter")] = ev.currentTarget.value || undefined; this.offset = 0; this.log(); });
		$body.find("[data-log-filter=search]").on("keydown", ev => { if (ev.key === "Enter") $(ev.currentTarget).trigger("change"); });
		$body.find("[data-log-export]").on("click", () => {
			const params = new URLSearchParams(Object.entries(this.logFilters).filter(([, v]) => v));
			window.open(`/api/method/${this.method}export_consent_log?${params.toString()}`);
		});
	}
}
