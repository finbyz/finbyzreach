frappe.pages["import-opt-ins"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: __("Import Opt-ins"), single_column: true});
	wrapper.opt_in_importer = new OptInImporter(page);
};
frappe.pages["import-opt-ins"].on_page_show = function (wrapper) {
	wrapper.opt_in_importer?.applyRouteOptions();
	wrapper.opt_in_importer?.loadHistory();
};

class OptInImporter {
	constructor(page) {
		this.page = page;
		this.method = "finbyzreach.consent_import.";
		this.state = {file: null, fileName: null, name: null, result: null, running: null};
		this.$root = $(page.main).addClass("import-opt-ins");
		page.set_secondary_action(__("Subscriptions & consent"), () => frappe.set_route("subscriptions-consent"));
		page.add_inner_button(__("Download example file"), () => this.downloadExample());
		this.$root.html(`
			<div class="ci-card">
				<h4>${__("Record people who already opted in")}</h4>
				<p class="text-muted ci-intro">${__("Each person is saved as a confirmed subscription for their email address and topic. No confirmation email is sent. Use this only for people who gave consent elsewhere and for whom you keep proof.")}</p>
				<h5 class="ci-step">${__("1. Who")}</h5>
				<p class="text-muted ci-intro">${__("Select records by filter, attach a file, pick single records, or combine them.")}</p>
				<div class="ci-rules">
					<div><b>${__("Lead")}</b><span>${__("Consent goes to the Lead's email. Unsubscribed and Do Not Contact Leads are skipped.")}</span></div>
					<div><b>${__("Contact")}</b><span>${__("Consent goes to the Contact's primary email. Unsubscribed Contacts are skipped.")}</span></div>
					<div><b>${__("Customer")}</b><span>${__("Consent goes to the primary email of its primary contact, or of all its contacts. Customer campaigns send to these contacts. Disabled Customers are skipped.")}</span></div>
				</div>
				<div class="ci-filter-box">
					<h6 class="ci-sub">${__("Select by filter")}</h6>
					<div class="ci-filter-type"></div>
					<div class="ci-filter-area hidden"></div>
					<div class="ci-filter-count text-muted ci-small"></div>
				</div>
				<div class="ci-form">
					<div class="ci-file">
						<label class="control-label">${__("File (optional)")}</label>
						<div class="ci-file-row">
							<button type="button" class="btn btn-default btn-sm" data-choose>${__("Choose CSV or Excel file")}</button>
							<span class="ci-file-name text-muted">${__("No file chosen")}</span>
							<button type="button" class="btn btn-link btn-xs ci-clear-file hidden" data-clear-file>${__("Remove")}</button>
						</div>
						<p class="help-box small text-muted">${__("Columns: <b>Email</b>, <b>Topic</b> (one or more, separated by commas), <b>Opted in on</b> (YYYY-MM-DD or DD.MM.YYYY), <b>Source</b>, <b>Language</b> (de, en, fr, it). Instead of Email you can give <b>Record type</b> (Lead, Contact or Customer) and <b>Record</b> (its ID). Empty cells use the defaults below. CSV (comma or semicolon) or Excel .xlsx, up to 50,000 rows.")}
						<a href="#" data-example>${__("Download example file")}</a></p>
					</div>
				</div>
				<details class="ci-records-box">
					<summary>${__("Pick single records")} <span class="ci-picked text-muted"></span></summary>
					<div class="ci-records">
						<div class="ci-pick-lead"></div>
						<div class="ci-pick-contact"></div>
						<div class="ci-pick-customer"></div>
					</div>
				</details>
				<div class="ci-customer-contacts"></div>
				<h5 class="ci-step">${__("2. Consent details")}</h5>
				<div class="ci-form">
					<div class="ci-source"></div>
					<div class="ci-date"></div>
					<div class="ci-language"></div>
					<div class="ci-topics"></div>
				</div>
				<div class="ci-actions"><button type="button" class="btn btn-primary btn-sm" data-check disabled>${__("Check")}</button></div>
			</div>
			<div class="ci-result"></div>
			<div class="ci-card ci-history-card"><h4>${__("Recent opt-in imports")}</h4><div class="ci-history"></div></div>`);
		this.makeControls();
		this.$root.on("click", "[data-choose]", () => this.chooseFile());
		this.$root.on("click", "[data-clear-file]", () => this.setFile(null));
		this.$root.on("click", "[data-example]", (e) => { e.preventDefault(); this.downloadExample(); });
		this.$root.on("click", "[data-check]", () => this.check());
		this.$root.on("click", "[data-start]", () => this.start());
		this.$root.on("change", "[data-confirm]", (e) => this.$root.find("[data-start]").prop("disabled", !e.currentTarget.checked));
		this.$root.on("click", "[data-open-run]", (e) => this.watch($(e.currentTarget).attr("data-open-run")));
		frappe.realtime.on("consent_import_progress", (data) => {
			if (data?.name && data.name === this.state.running) this.refreshStatus(data);
		});
	}
	escape(value) { return frappe.utils.escape_html(String(value ?? "")); }
	number(value) { return format_number(value || 0, null, 0); }
	downloadExample() { window.open(`/api/method/${this.method}download_template`); }
	makeControls() {
		const changed = () => this.updateButtons();
		this.filterType = frappe.ui.form.make_control({parent: this.$root.find(".ci-filter-type"), render_input: true, df: {
			fieldtype: "Select", fieldname: "filter_doctype", label: __("Record type"), options: ["", "Lead", "Contact", "Customer"],
			description: __("Every record of this type that matches the filters below is included. Without filters, all records of the type are included."),
			change: () => this.setFilterType(this.filterType.get_value()),
		}});
		const picker = (doctype, label, description) => frappe.ui.form.make_control({
			parent: this.$root.find(`.ci-pick-${doctype.toLowerCase()}`), render_input: true, df: {
				fieldtype: "MultiSelectList", fieldname: doctype.toLowerCase(), label, description,
				get_data: (txt) => frappe.call({method: this.method + "search_records", type: "GET", args: {doctype, txt}})
					.then(({message}) => (message || []).map(row => ({value: row.value, label: this.escape(row.value), description: this.escape(row.description)}))),
				change: changed,
			}});
		this.pickers = {
			Lead: picker("Lead", __("Leads"), __("Search by ID, name, company or email. Only Leads with an email are listed.")),
			Contact: picker("Contact", __("Contacts"), __("Search by ID, name, company or email. Only Contacts with an email are listed.")),
			Customer: picker("Customer", __("Customers"), __("Search by ID, name or email.")),
		};
		this.customerContacts = frappe.ui.form.make_control({parent: this.$root.find(".ci-customer-contacts"), render_input: true, df: {
			fieldtype: "Select", fieldname: "customer_contacts", label: __("Customer contacts"), options: ["Primary contact", "All contacts"],
			default: "Primary contact", description: __("Which contacts of each selected Customer get the consent. Also used for Customer rows in the file."),
			change: changed,
		}});
		this.customerContacts.set_value("Primary contact");
		this.toggleCustomerContacts();
		this.source = frappe.ui.form.make_control({parent: this.$root.find(".ci-source"), render_input: true, df: {
			fieldtype: "Data", fieldname: "consent_source", label: __("Consent source"), reqd: 1,
			description: __("Where these people gave consent, for example \"Swissbau 2026 sign-up form\". Saved in the consent log. A Source column overrides it per row."),
			change: changed,
		}});
		this.date = frappe.ui.form.make_control({parent: this.$root.find(".ci-date"), render_input: true, df: {
			fieldtype: "Date", fieldname: "default_opted_in_on", label: __("Opted in on"),
			description: __("When they gave consent. Used for selected records and file rows without a date. Leave empty if unknown."),
			change: changed,
		}});
		this.language = frappe.ui.form.make_control({parent: this.$root.find(".ci-language"), render_input: true, df: {
			fieldtype: "Select", fieldname: "default_language", label: __("Language of consent text"), options: ["", "de", "en", "fr", "it"],
			description: __("Used when a row has no Language column."), change: changed,
		}});
		this.topics = frappe.ui.form.make_control({parent: this.$root.find(".ci-topics"), render_input: true, df: {
			fieldtype: "MultiCheck", fieldname: "default_topics", label: __("Topics"), columns: 3, options: [],
			description: __("Required for selected records. For file rows, used when the row has no Topic."),
		}});
		this.topics.$wrapper.on("change", "input", changed);
		frappe.call({method: this.method + "topics", type: "GET"}).then(({message}) => {
			this.topics.df.options = (message || []).map(row => ({label: `${row.name} (${__(row.category)})`, value: row.name}));
			this.topics.refresh();
		});
		this.applyRouteOptions();
	}
	applyRouteOptions() {
		// Set by the "Import opt-ins" action in the Lead, Contact and Customer lists.
		const options = frappe.opt_in_import_options;
		if (!options) return;
		frappe.opt_in_import_options = null;
		this.state.name = null;
		this.$root.find(".ci-result").empty();
		if (options.filter_doctype) {
			this.setFilterType(options.filter_doctype, options.filters || []);
		}
		let picked = false;
		for (const [doctype, key] of [["Lead", "leads"], ["Contact", "contacts"], ["Customer", "customers"]]) {
			const names = Array.isArray(options[key]) ? options[key] : [];
			this.pickers[doctype].set_value(names);
			picked = picked || names.length > 0;
		}
		this.$root.find(".ci-records-box").prop("open", picked);
		this.updateButtons();
	}
	async setFilterType(doctype, filters = []) {
		if (this.filterType.get_value() !== (doctype || "")) {
			this.filterType.value = doctype || "";
			this.filterType.$input?.val(doctype || "");
		}
		this.filterDoctype = doctype || null;
		const $area = this.$root.find(".ci-filter-area").empty().toggleClass("hidden", !doctype);
		this.filterGroup = null;
		this.$root.find(".ci-result").empty();
		this.toggleCustomerContacts();
		if (doctype) {
			// FilterGroup needs the DocType's fields, which a page does not load by itself.
			this.filterLoading = true;
			this.updateButtons();
			try {
				await frappe.model.with_doctype(doctype);
			} finally {
				this.filterLoading = false;
			}
			if (this.filterDoctype !== doctype) return;
			this.filterGroup = new frappe.ui.FilterGroup({parent: $area, doctype, on_change: () => this.filtersChanged()});
			const rows = (Array.isArray(filters) ? filters : []).filter(row => Array.isArray(row));
			if (rows.length) {
				await this.filterGroup.add_filters(rows.map(row => row.slice(0, 4)));
				this.filterGroup.toggle_empty_filters(!this.filterGroup.filters.length);
				const added = this.filterGroup.get_filters().map(row => `${row[0]}.${row[1]}`);
				const dropped = rows.filter(row => !added.includes(`${row[0]}.${row[1]}`));
				if (dropped.length) {
					frappe.msgprint({title: __("Some filters were not applied"), indicator: "orange", message:
						__("These list filters could not be used here, so more records may match than in the list. Check the filters and the count before you import:")
						+ `<ul>${dropped.map(row => `<li>${this.escape(row[1])} ${this.escape(row[2])} ${this.escape(row[3])}</li>`).join("")}</ul>`});
				}
			}
		}
		this.filtersChanged();
	}
	recordFilters() { return this.filterGroup ? this.filterGroup.get_filters() : []; }
	filtersChanged() {
		this.$root.find(".ci-result").empty();
		this.updateButtons();
		clearTimeout(this.countTimer);
		const $count = this.$root.find(".ci-filter-count");
		const doctype = this.filterDoctype;
		if (!doctype) return $count.empty();
		$count.text(__("Counting…"));
		this.countTimer = setTimeout(async () => {
			const filters = this.recordFilters();
			const {message: r} = await frappe.call({method: this.method + "count_records", type: "GET",
				args: {doctype, filters: JSON.stringify(filters)}});
			if (doctype !== this.filterDoctype || JSON.stringify(filters) !== JSON.stringify(this.recordFilters())) return;
			const label = {Lead: __("Leads"), Contact: __("Contacts"), Customer: __("Customers")}[doctype];
			let text = filters.length ? __("{0} {1} match.", [this.number(r.count), label])
				: __("No filter set, so all {0} {1} are included.", [this.number(r.count), label]);
			if (r.with_email != null) text += " " + __("{0} of them have an email.", [this.number(r.with_email)]);
			if (doctype === "Customer") text += " " + __("Their contacts get the consent, see Customer contacts below.");
			if (r.count > r.limit) text = __("{0} {1} match. At most {2} can be imported at once. Add a filter to narrow it down.", [this.number(r.count), label, this.number(r.limit)]);
			const warn = r.count > r.limit || !r.count || !filters.length;
			$count.toggleClass("ci-warning", warn).toggleClass("text-muted", !warn).text(text);
		}, 400);
	}
	toggleCustomerContacts() {
		const customers = this.filterDoctype === "Customer" || (this.pickers?.Customer.get_value() || []).length > 0;
		this.customerContacts?.$wrapper.toggleClass("ci-dim", !customers);
	}
	chooseFile() {
		new frappe.ui.FileUploader({
			allow_multiple: false,
			disable_file_browser: true,
			allow_web_link: false,
			allow_toggle_private: false,
			make_attachments_public: false,
			restrictions: {allowed_file_types: [".csv", ".xlsx"]},
			on_success: (file) => this.setFile(file),
		});
	}
	setFile(file) {
		this.state.file = file?.file_url || null;
		this.state.fileName = file?.file_name || null;
		this.$root.find(".ci-file-name").text(file?.file_name || __("No file chosen"));
		this.$root.find("[data-clear-file]").toggleClass("hidden", !file);
		this.$root.find(".ci-result").empty();
		this.updateButtons();
	}
	selected(doctype) { return this.pickers[doctype].get_value() || []; }
	updateButtons() {
		const counts = ["Lead", "Contact", "Customer"].map(doctype => this.selected(doctype).length);
		const picked = counts.reduce((a, b) => a + b, 0);
		this.$root.find(".ci-picked").text(picked ? `(${__("{0} selected", [this.number(picked)])})` : "");
		this.toggleCustomerContacts();
		const who = this.state.file || this.filterDoctype || picked;
		this.$root.find("[data-check]").prop("disabled", !(who && !this.filterLoading && (this.source.get_value() || "").trim()));
	}
	async check() {
		const $btn = this.$root.find("[data-check]").prop("disabled", true);
		this.$root.find(".ci-result").html(`<div class="ci-card text-muted">${__("Checking…")}</div>`);
		try {
			const {message} = await frappe.call({method: this.method + "check", type: "POST", args: {
				name: this.state.name, import_file: this.state.file, leads: JSON.stringify(this.selected("Lead")),
				contacts: JSON.stringify(this.selected("Contact")), customers: JSON.stringify(this.selected("Customer")),
				filter_doctype: this.filterDoctype || "", record_filters: JSON.stringify(this.recordFilters()),
				customer_contacts: this.customerContacts.get_value(),
				consent_source: this.source.get_value(), default_opted_in_on: this.date.get_value(),
				default_language: this.language.get_value(), default_topics: JSON.stringify(this.topics.get_checked_options() || []),
			}});
			this.state.name = message.name;
			this.state.result = message;
			this.renderCheck(message);
			this.loadHistory();
		} catch (e) {
			this.$root.find(".ci-result").empty();
		} finally {
			this.updateButtons();
		}
	}
	tile(label, value, kind = "") { return `<div class="ci-tile ${kind}"><div class="ci-tile-value">${this.number(value)}</div><div class="ci-tile-label">${label}</div></div>`; }
	renderCheck(r) {
		const e = value => this.escape(value);
		const topics = r.topics.length ? r.topics.map(t => `<span class="indicator-pill green">${e(t.topic)}: ${this.number(t.count)}</span>`).join(" ") : `<span class="text-muted">${__("Nothing to import")}</span>`;
		const reasons = r.reasons.length ? `<table class="table table-sm ci-table"><thead><tr><th>${__("Outcome")}</th><th>${__("Reason")}</th><th class="text-right">${__("Count")}</th></tr></thead><tbody>${
			r.reasons.map(row => `<tr><td>${this.pill(row.action)}</td><td>${e(row.reason)}</td><td class="text-right">${this.number(row.count)}</td></tr>`).join("")}</tbody></table>` : "";
		const problems = r.problems.length ? `<details class="ci-problems"><summary>${__("Rows that will not be imported")} (${__("first {0}", [this.number(r.problems.length)])})</summary>
			<table class="table table-sm ci-table"><thead><tr><th>${__("Row")}</th><th>${__("Record")}</th><th>${__("Email")}</th><th>${__("Topic")}</th><th>${__("Outcome")}</th><th>${__("Reason")}</th></tr></thead><tbody>${
			r.problems.map(row => `<tr><td>${e(row.row)}</td><td>${e(row.record)}</td><td>${e(row.email)}</td><td>${e(row.topic)}</td><td>${this.pill(row.action)}</td><td>${e(row.reason)}</td></tr>`).join("")}</tbody></table></details>` : "";
		const warning = r.no_person ? `<p class="ci-warning">${r.no_person === 1
			? __("1 address has no Lead or Contact yet. Its consent is saved, but campaigns reach it only after you add it as a Lead or Contact.")
			: __("{0} addresses have no Lead or Contact yet. Their consent is saved, but campaigns reach them only after you add them as Leads or Contacts.", [this.number(r.no_person)])}</p>` : "";
		this.$root.find(".ci-result").html(`
			<div class="ci-card">
				<div class="ci-heading"><h4>${__("Check result")}</h4><a href="${frappe.utils.get_form_link("Opt-in Import Log", r.name)}" class="text-muted">${e(r.name)}</a></div>
				<div class="ci-tiles">${this.tile(__("Records and file rows"), r.total_rows)}${this.tile(__("Subscriptions to add"), r.subscribe, "green")}${this.tile(__("Skipped"), r.skip, "orange")}${this.tile(__("Failed"), r.fail, "red")}</div>
				<p class="text-muted ci-small">${__("Each email address and topic counts as one subscription, so a Customer with several contacts or a row with several topics adds more than one.")}</p>
				<div class="ci-topic-list">${topics}</div>
				${warning}${reasons}${problems}
				${r.subscribe ? `<div class="ci-confirm">
					<label class="pc-check"><input type="checkbox" data-confirm> ${__("I confirm these people gave consent for these topics and that we keep proof of it.")}</label>
					<button type="button" class="btn btn-primary btn-sm" data-start disabled>${(r.subscribe === 1 ? __("Import 1 subscription") : __("Import {0} subscriptions", [this.number(r.subscribe)]))}</button>
				</div>` : ""}
			</div>`);
	}
	pill(action) {
		const colour = {Subscribe: "green", Skip: "orange", Fail: "red"}[action] || "gray";
		const label = {Subscribe: __("Subscribe"), Skip: __("Skip"), Fail: __("Fail")}[action] || action;
		return `<span class="indicator-pill ${colour}">${this.escape(label)}</span>`;
	}
	async start() {
		const name = this.state.name;
		await frappe.call({method: this.method + "start", type: "POST", args: {name, consent_confirmed: 1}});
		this.setFile(null);
		Object.values(this.pickers).forEach(control => control.set_value([]));
		await this.setFilterType(null);
		this.watch(name);
	}
	async watch(name) {
		this.polls = 0;
		this.state.running = name;
		this.state.name = null;
		await this.refreshStatus();
	}
	async refreshStatus(live) {
		const name = this.state.running;
		if (!name) return;
		const {message: s} = await frappe.call({method: this.method + "status", type: "GET", args: {name}});
		if (name !== this.state.running) return;
		const e = value => this.escape(value);
		const progress = live?.total != null ? live : (s.progress || {});
		const finished = ["Completed", "Failed"].includes(s.status);
		const percent = finished ? 100 : progress.total ? Math.min(99, Math.round(progress.done / progress.total * 100)) : 0;
		this.$root.find(".ci-result").html(`
			<div class="ci-card">
				<div class="ci-heading"><h4>${__("Import {0}", [e(s.name)])}: ${e(s.consent_source)}</h4><span class="indicator-pill ${{Completed: "green", Failed: "red", Running: "blue", Queued: "orange"}[s.status] || "gray"}">${__(s.status)}</span></div>
				<div class="progress ci-progress"><div class="progress-bar" style="width:${percent}%"></div></div>
				${!finished && progress.total ? `<p class="text-muted ci-small">${__("{0} of {1} subscriptions written", [this.number(progress.done), this.number(progress.total)])}</p>` : ""}
				<div class="ci-tiles">${this.tile(__("Records and file rows"), s.total_rows)}${this.tile(__("Subscriptions added"), s.subscribed, "green")}${this.tile(__("Skipped"), s.skipped, "orange")}${this.tile(__("Failed"), s.failed, "red")}</div>
				${s.result_file ? `<a class="btn btn-default btn-sm" href="${e(s.result_file)}" target="_blank" rel="noopener">${__("Download result file")}</a>` : ""}
				${s.status === "Failed" ? `<pre class="ci-error">${e(s.error)}</pre>` : ""}
				${finished ? "" : `<p class="text-muted ci-small">${__("The import runs in the background. You can leave this page.")}</p>`}
			</div>`);
		clearTimeout(this.timer);
		if (finished) {
			this.loadHistory();
		} else {
			this.polls = (this.polls || 0) + 1;
			this.timer = setTimeout(() => this.refreshStatus(), this.polls < 5 ? 1500 : 4000);
		}
	}
	async loadHistory() {
		const {message} = await frappe.call({method: this.method + "history", type: "GET"});
		const e = value => this.escape(value);
		const rows = message || [];
		this.$root.find(".ci-history").html(rows.length ? `<div class="ci-table"><table class="table table-sm"><thead><tr>
			<th>${__("Import")}</th><th>${__("Consent source")}</th><th>${__("Status")}</th><th class="text-right">${__("Rows")}</th><th class="text-right">${__("Subscribed")}</th><th class="text-right">${__("Skipped")}</th><th class="text-right">${__("Failed")}</th><th>${__("By")}</th><th></th></tr></thead><tbody>${
			rows.map(r => `<tr><td><a href="${frappe.utils.get_form_link("Opt-in Import Log", r.name)}">${e(r.name)}</a><div class="text-muted ci-small">${e(frappe.datetime.str_to_user(r.creation))}</div></td>
				<td>${e(r.consent_source)}</td><td>${e(__(r.status))}</td><td class="text-right">${this.number(r.total_rows)}</td><td class="text-right">${this.number(r.subscribed)}</td>
				<td class="text-right">${this.number(r.skipped)}</td><td class="text-right">${this.number(r.failed)}</td><td>${e(frappe.user.full_name(r.owner))}</td>
				<td class="text-right">${r.status === "Draft" ? "" : `<button type="button" class="btn btn-xs btn-default" data-open-run="${e(r.name)}">${__("Show")}</button>`}
				${r.result_file ? ` <a class="btn btn-xs btn-default" href="${e(r.result_file)}" target="_blank" rel="noopener">${__("Result")}</a>` : ""}</td></tr>`).join("")}</tbody></table></div>`
			: `<p class="text-muted">${__("No imports yet.")}</p>`);
	}
}
