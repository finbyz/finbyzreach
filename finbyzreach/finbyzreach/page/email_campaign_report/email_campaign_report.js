frappe.pages["email-campaign-report"].on_page_load = function (wrapper) {
	wrapper.campaign_report = new EmailCampaignReport(wrapper);
};

frappe.pages["email-campaign-report"].on_page_show = function (wrapper) {
	wrapper.campaign_report?.applyRoute();
};

class EmailCampaignReport {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Email Campaign Report"), single_column: true });
		this.page.main.addClass("email-campaign-report-page");
		this.method = "finbyzreach.finbyzreach.page.email_campaign_report.email_campaign_report.";
		this.metric = "opened";
		this.days = 30;
		this.pageNumber = 1;
		this.requestId = 0;
		this.view = "single";
		this.compareItems = [];
		this.comparisonOptions = [];
		this.optionsRequestId = 0;
		this.metrics = [
			["sent", __("Sent")], ["delivered", __("Delivered")], ["opened", __("Opened")],
			["clicked", __("Clicked")], ["unsubscribed", __("Unsubscribed")],
			["hard_bounce", __("Hard bounce")], ["soft_bounce", __("Soft bounce")],
			["spam", __("Marked as spam")], ["replied", __("Replied")], ["failed", __("Failed")],
		];
		this.page.set_primary_action(__("Refresh"), () => this.view === "single" ? this.load() : this.loadCohort(), "refresh");
		this.render();
		this.makeControls();
		this.bind();
		this.applyRoute();
	}

	render() {
		this.page.main.html(`
			<div class="ecr-shell">
				<p class="ecr-intro">${__("Email broadcast results by campaign or email template")}</p>
				<nav class="ecr-view-tabs" aria-label="${__("Report view")}">
					<button type="button" data-view="single" class="active">${__("Single report")}</button>
					<button type="button" data-view="compare">${__("Compare")}</button>
					<button type="button" data-view="overall">${__("Overall")}</button>
				</nav>
				<div class="ecr-single">
				<section class="ecr-card ecr-filters">
					<div class="ecr-filter" data-field="scope"></div>
					<div class="ecr-filter" data-field="campaign"></div>
					<div class="ecr-filter" data-field="template"></div>
					<div class="ecr-filter" data-field="days"></div>
					<button class="btn btn-primary btn-sm ecr-apply" type="button">${__("Show report")}</button>
					<div class="ecr-custom-range">
						<div class="ecr-filter" data-field="from_date"></div>
						<div class="ecr-filter" data-field="to_date"></div>
						<small>${__("Choose up to 366 days.")}</small>
					</div>
				</section>
				<div class="ecr-state" role="status"></div>
				<p class="ecr-summary-note">${__("Totals and percentages cover all sends. The date range applies to the timeline only.")}</p>
				<section class="ecr-single-acceptance"></section>
				<section class="ecr-metrics"></section>
				<section class="ecr-card ecr-chart-card">
					<div class="ecr-section-head"><div><h3>${__("Activity timeline")}</h3><p>${__("Daily first actions during the selected period")}</p></div><span class="ecr-chart-period"></span></div>
					<div id="ecr-trend"></div>
					<div class="ecr-peaks"></div>
					<p class="ecr-note ecr-timeline-note"></p>
				</section>
				<section class="ecr-card ecr-details">
					<div class="ecr-section-head"><div><h3>${__("Details")}</h3><p>${__("People behind each recorded action")}</p></div><span class="ecr-detail-total"></span></div>
					<nav class="ecr-tabs" aria-label="${__("Campaign actions")}"></nav>
					<div class="ecr-table-wrap"><table class="ecr-table"><thead><tr><th>${__("Full Name")}</th><th>${__("Email")}</th><th>${__("Campaign")}</th><th>${__("Status")}</th><th>${__("Action Time")}</th></tr></thead><tbody></tbody></table></div>
					<div class="ecr-pagination"><span class="ecr-page-label"></span><div><button class="btn btn-default btn-sm ecr-prev">${__("Previous")}</button><button class="btn btn-default btn-sm ecr-next">${__("Next")}</button></div></div>
				</section>
				</div>
				<div class="ecr-cohort" hidden>
					<section class="ecr-card ecr-cohort-filters">
						<div class="ecr-compare-selection">
							<label class="ecr-filter"><span class="control-label">${__("Compare by")}</span><select class="form-control ecr-compare-scope"><option value="campaign">${__("Campaign")}</option><option value="template">${__("Email Template")}</option></select></label>
							<div class="ecr-filter"><label class="control-label ecr-compare-input-label" for="ecr-compare-input">${__("Campaign")}</label><div class="ecr-picker"><input id="ecr-compare-input" class="form-control ecr-compare-input" type="text" autocomplete="off" placeholder="${__("Search campaigns")}"><div class="ecr-suggestions" hidden></div></div></div>
							<div class="ecr-compare-chips"></div>
						</div>
						<div class="ecr-period-row"><label class="ecr-filter"><span class="control-label">${__("Send period")}</span><select class="form-control ecr-cohort-period"><option value="previous_month">${__("Previous calendar month")}</option><option value="7">${__("Last 7 days")}</option><option value="30">${__("Last 30 days")}</option><option value="90">${__("Last 90 days")}</option><option value="custom">${__("Custom")}</option></select></label><button class="btn btn-primary btn-sm ecr-cohort-apply" type="button">${__("Show report")}</button></div>
						<div class="ecr-cohort-custom-range">
							<label class="ecr-filter"><span class="control-label">${__("From Date")}</span><input class="form-control ecr-cohort-from" type="date"></label>
							<label class="ecr-filter"><span class="control-label">${__("To Date")}</span><input class="form-control ecr-cohort-to" type="date"></label>
							<small>${__("Choose up to 366 days.")}</small>
						</div>
					</section>
					<div class="ecr-cohort-state" role="status"></div>
					<p class="ecr-summary-note ecr-cohort-note"></p>
					<div class="ecr-overall-result" hidden>
						<section class="ecr-cohort-metrics"></section>
						<section class="ecr-card ecr-chart-card"><div class="ecr-section-head"><div><h3>${__("Send activity")}</h3><p>${__("Completed attempts by send date")}</p></div><span class="ecr-cohort-range"></span></div><div id="ecr-overall-trend"></div></section>
					</div>
					<div class="ecr-compare-result" hidden>
						<section class="ecr-card ecr-chart-card ecr-compare-chart-card"><div class="ecr-section-head"><div><h3>${__("Performance comparison")}</h3><p>${__("Rates for emails sent in the selected period")}</p></div><span class="ecr-cohort-range"></span></div><div id="ecr-compare-chart"></div></section>
						<section class="ecr-card ecr-compare-table-wrap"><div class="ecr-section-head"><div><h3>${__("Comparison details")}</h3><p>${__("Recorded outcomes and engagement")}</p></div></div><div class="ecr-table-wrap"><table class="ecr-table ecr-compare-table"><thead></thead><tbody></tbody></table></div></section>
					</div>
				</div>
			</div>`);
		this.page.main.find(".ecr-tabs").html(this.metrics.map(([key, label]) =>
			`<button type="button" data-metric="${key}" class="ecr-tab">${this.esc(label)}</button>`).join(""));
	}

	makeControls() {
		const make = (field, df) => {
			const control = frappe.ui.form.make_control({ parent: this.page.main.find(`[data-field="${field}"]`), df, render_input: true });
			control.refresh();
			return control;
		};
		this.scope = make("scope", { fieldtype: "Select", fieldname: "scope", label: __("View by"), options: [__("Campaign"), __("Email Template")], default: __("Campaign"), change: () => this.scope && this.toggleScope() });
		this.campaign = make("campaign", { fieldtype: "Link", fieldname: "campaign", label: __("Campaign"), options: "Campaign" });
		this.template = make("template", { fieldtype: "Link", fieldname: "template", label: __("Email Template"), options: "Email Template" });
		this.period = make("days", { fieldtype: "Select", fieldname: "days", label: __("Timeline in days"), options: ["7", "30", "90", __("Custom")], default: "30", change: () => this.period && this.togglePeriod() });
		this.fromDate = make("from_date", { fieldtype: "Date", fieldname: "from_date", label: __("From Date"), default: frappe.datetime.add_days(frappe.datetime.get_today(), -29) });
		this.toDate = make("to_date", { fieldtype: "Date", fieldname: "to_date", label: __("To Date"), default: frappe.datetime.get_today() });
		this.toggleScope();
		this.togglePeriod();
		this.resetComparison();
		this.toggleCohortPeriod();
	}

	toggleScope() {
		const byTemplate = this.scope.get_value() === __("Email Template");
		this.page.main.find('[data-field="campaign"]').toggle(!byTemplate);
		this.page.main.find('[data-field="template"]').toggle(byTemplate);
	}

	togglePeriod() {
		this.page.main.find(".ecr-custom-range").toggleClass("is-visible", this.period.get_value() === __("Custom"));
	}

	resetComparison() {
		this.requestId += 1;
		this.compareItems = [];
		const byTemplate = this.page.main.find(".ecr-compare-scope").val() === "template";
		this.page.main.find(".ecr-compare-input-label").text(byTemplate ? __("Email Template") : __("Campaign"));
		this.page.main.find(".ecr-compare-input").val("").attr("placeholder", byTemplate ? __("Search email templates") : __("Search campaigns"));
		this.page.main.find(".ecr-suggestions").prop("hidden", true).empty();
		this.page.main.find(".ecr-compare-result").prop("hidden", true);
		this.renderCompareItems();
		if (this.view === "compare") {
			this.page.main.find(".ecr-cohort-state").text(__("Choose two to five campaigns or email templates."));
			this.loadComparisonOptions();
		}
	}

	toggleCohortPeriod() {
		this.page.main.find(".ecr-cohort-custom-range").toggleClass("is-visible", this.page.main.find(".ecr-cohort-period").val() === "custom");
	}

	async loadComparisonOptions() {
		const scope = this.page.main.find(".ecr-compare-scope").val();
		const requestId = ++this.optionsRequestId;
		this.comparisonOptions = [];
		try {
			const result = await frappe.call({ method: this.method + "get_comparison_options", args: { scope } });
			if (requestId !== this.optionsRequestId || scope !== this.page.main.find(".ecr-compare-scope").val()) return;
			this.comparisonOptions = result.message || [];
			if (this.page.main.find(".ecr-compare-input").is(":focus")) this.renderSuggestions();
		} catch (error) {
			if (requestId === this.optionsRequestId) this.page.main.find(".ecr-cohort-state").text(__("Campaign suggestions could not load. Try refreshing the page."));
		}
	}

	renderSuggestions() {
		const query = this.page.main.find(".ecr-compare-input").val().trim().toLocaleLowerCase();
		const matches = this.comparisonOptions.filter((name) =>
			!this.compareItems.includes(name) && name.toLocaleLowerCase().includes(query)).slice(0, 8);
		const menu = this.page.main.find(".ecr-suggestions");
		menu.html(matches.length ? matches.map((name) =>
			`<button type="button" class="ecr-suggestion" data-compare-choice="${this.esc(name)}">${this.esc(name)}</button>`).join("") : `<span class="ecr-suggestion-empty">${query ? __("No matching items") : __("No items available")}</span>`);
		menu.prop("hidden", false);
	}

	setView(view) {
		if (!["single", "compare", "overall"].includes(view)) return;
		this.view = view;
		this.requestId += 1;
		this.page.main.find("[data-view]").removeClass("active").filter(`[data-view="${view}"]`).addClass("active");
		this.page.main.find(".ecr-single").prop("hidden", view !== "single");
		this.page.main.find(".ecr-cohort").prop("hidden", view === "single");
		this.page.main.find(".ecr-compare-selection").prop("hidden", view !== "compare");
		this.page.main.find(".ecr-overall-result, .ecr-compare-result").prop("hidden", true);
		this.page.main.find(".ecr-cohort-note").text("");
		this.renderCompareItems();
		if (view === "overall") this.loadCohort();
		if (view === "compare") {
			this.page.main.find(".ecr-cohort-state").text(__("Choose two to five campaigns or email templates."));
			this.loadComparisonOptions();
		}
	}

	renderCompareItems() {
		this.page.main.find(".ecr-compare-chips").html(this.compareItems.map((name, index) =>
			`<span class="ecr-compare-chip">${this.esc(name)} <button type="button" data-remove-compare="${index}" aria-label="${this.esc(__("Remove {0}", [name]))}">×</button></span>`).join(""));
		this.page.main.find(".ecr-compare-input").prop("disabled", this.compareItems.length >= 5);
		this.page.main.find(".ecr-cohort-apply").prop("disabled", this.view === "compare" && this.compareItems.length < 2);
	}

	addCompareItem(selectedName) {
		const input = this.page.main.find(".ecr-compare-input");
		const typed = String(selectedName || input.val()).trim();
		const name = this.comparisonOptions.find((option) => option.toLocaleLowerCase() === typed.toLocaleLowerCase());
		if (!name) {
			this.page.main.find(".ecr-cohort-state").text(__("Choose a campaign or template from the suggestions."));
			return;
		}
		if (this.compareItems.includes(name) || this.compareItems.length >= 5) {
			this.page.main.find(".ecr-cohort-state").text(__("Choose a new item; comparison allows up to five."));
			return;
		}
		this.compareItems.push(name);
		this.requestId += 1;
		input.val("");
		this.page.main.find(".ecr-suggestions").prop("hidden", true);
		this.page.main.find(".ecr-compare-result").prop("hidden", true);
		this.renderCompareItems();
		this.page.main.find(".ecr-cohort-state").text(this.compareItems.length < 2 ? __("Add one more item to compare.") : __("Ready to compare {0} items.", [this.compareItems.length]));
	}

	cohortSelection() {
		const period = this.page.main.find(".ecr-cohort-period").val();
		return period === "custom"
			? { period, from_date: this.page.main.find(".ecr-cohort-from").val(), to_date: this.page.main.find(".ecr-cohort-to").val() }
			: { period };
	}

	bind() {
		this.page.main.on("click", "[data-view]", (event) => this.setView(event.currentTarget.dataset.view));
		this.page.main.on("change", ".ecr-compare-scope", () => this.resetComparison());
		this.page.main.on("focus input", ".ecr-compare-input", () => this.renderSuggestions());
		this.page.main.on("blur", ".ecr-compare-input", () => {
			setTimeout(() => this.page.main.find(".ecr-suggestions").prop("hidden", true), 150);
		});
		this.page.main.on("click", "[data-compare-choice]", (event) => this.addCompareItem(event.currentTarget.dataset.compareChoice));
		this.page.main.on("change", ".ecr-cohort-period", () => {
			this.toggleCohortPeriod();
			this.page.main.find(".ecr-overall-result, .ecr-compare-result").prop("hidden", true);
			this.page.main.find(".ecr-cohort-state").text(__("Show the report to apply the new period."));
		});
		this.page.main.on("keydown", ".ecr-compare-input", (event) => {
			if (event.key === "Enter") { event.preventDefault(); this.addCompareItem(); }
			if (event.key === "Escape") this.page.main.find(".ecr-suggestions").prop("hidden", true);
		});
		this.page.main.on("click", ".ecr-cohort-apply", () => this.loadCohort());
		this.page.main.on("click", "[data-remove-compare]", (event) => {
			this.requestId += 1;
			this.compareItems.splice(Number(event.currentTarget.dataset.removeCompare), 1);
			this.page.main.find(".ecr-compare-result").prop("hidden", true);
			this.renderCompareItems();
			this.page.main.find(".ecr-cohort-state").text(this.compareItems.length < 2 ? __("Choose at least two items to compare.") : __("Ready to compare {0} items.", [this.compareItems.length]));
		});
		this.page.main.on("click", ".ecr-apply", () => this.load());
		this.page.main.on("click", "[data-metric]", (event) => {
			this.metric = event.currentTarget.dataset.metric;
			this.pageNumber = 1;
			this.highlightMetric();
			this.loadDetails();
		});
		this.page.main.on("click", ".ecr-prev", () => { this.pageNumber -= 1; this.loadDetails(); });
		this.page.main.on("click", ".ecr-next", () => { this.pageNumber += 1; this.loadDetails(); });
	}

	async applyRoute() {
		const params = new URLSearchParams(window.location.search);
		const campaign = params.get("campaign") || frappe.route_options?.campaign;
		const template = params.get("template") || frappe.route_options?.template;
		if (frappe.route_options) {
			delete frappe.route_options.campaign;
			delete frappe.route_options.template;
		}
		if (campaign && campaign !== this.campaign.get_value()) {
			this.setView("single");
			await this.scope.set_value(__("Campaign"));
			await this.campaign.set_value(campaign);
			this.toggleScope();
			this.load();
		} else if (template && template !== this.template.get_value()) {
			this.setView("single");
			await this.scope.set_value(__("Email Template"));
			await this.template.set_value(template);
			this.toggleScope();
			this.load();
		}
	}

	async loadCohort() {
		if (this.view === "single") return;
		const range = this.cohortSelection();
		const state = this.page.main.find(".ecr-cohort-state");
		if (range.period === "custom" && (!range.from_date || !range.to_date || range.from_date > range.to_date || Date.parse(range.to_date) - Date.parse(range.from_date) > 365 * 86400000)) {
			state.text(__("Choose a valid date range of up to 366 days."));
			return;
		}
		if (this.view === "compare" && this.compareItems.length < 2) {
			state.text(__("Select at least two items to compare."));
			return;
		}
		const requestId = ++this.requestId;
		const view = this.view;
		this.page.main.find(".ecr-overall-result, .ecr-compare-result").prop("hidden", true);
		state.text(__("Loading report…"));
		try {
			const comparison = view === "compare";
			const method = comparison ? "get_comparison" : "get_overview";
			const args = comparison ? { ...range, scope: this.page.main.find(".ecr-compare-scope").val(), values: JSON.stringify(this.compareItems) } : range;
			const result = await frappe.call({ method: this.method + method, args });
			if (requestId !== this.requestId || view !== this.view) return;
			const data = result.message || {};
			this.page.main.find(".ecr-cohort-note").text(data.note || "");
			this.page.main.find(".ecr-cohort-range").text(data.range?.label || "");
			if (comparison) {
				this.renderComparison(data);
				this.page.main.find(".ecr-compare-result").prop("hidden", false);
				state.text(__("Comparing {0} items", [(data.items || []).length]));
			} else {
				this.renderOverall(data);
				this.page.main.find(".ecr-overall-result").prop("hidden", false);
				state.text(__("Showing {0} campaign(s)", [data.campaign_count || 0]));
			}
		} catch (error) {
			if (requestId === this.requestId) state.text(__("Could not load this report."));
		}
	}

	renderOverall(data) {
		const counts = data.summary || {};
		const cards = [
			[__("Mail-server acceptance rate"), this.rate(counts.acceptance_rate), `${this.number(counts.accepted)} / ${this.number(counts.completed)} ${__("completed attempts")}`],
			[__("Inbox delivery"), __("Unavailable"), __("Inbox delivery receipts are not available.")],
			[__("Sent"), this.number(counts.sent), __("Current sent status")],
			[__("Failed"), this.number(counts.failed), __("Completed attempts")],
			[__("Opened"), this.number(counts.opened), this.rate(counts.open_rate)],
			[__("Clicked"), this.number(counts.clicked), this.rate(counts.click_rate)],
			[__("Replied"), this.number(counts.replied), this.rate(counts.reply_rate)],
			[__("Hard bounce"), this.number(counts.hard_bounce), __("Recorded feedback")],
			[__("Soft bounce"), this.number(counts.soft_bounce), __("Recorded feedback")],
			[__("Marked as spam"), this.number(counts.spam), __("Recorded feedback")],
		];
		this.page.main.find(".ecr-cohort-metrics").html(cards.map(([label, value, note]) =>
			`<div class="ecr-card ecr-metric"><span>${this.esc(label)}</span><strong>${this.esc(value)}</strong><small>${this.esc(note)}</small></div>`).join(""));
		const rows = data.trend || [];
		this.page.main.find("#ecr-overall-trend").empty();
		if (!rows.some((row) => Number(row.eligible || 0))) {
			this.page.main.find("#ecr-overall-trend").html(`<div class="ecr-chart-empty">${__("No completed send attempts in this period.")}</div>`);
			return;
		}
		const acrossYears = rows[0]?.date.slice(0, 4) !== rows[rows.length - 1]?.date.slice(0, 4);
		new frappe.Chart("#ecr-overall-trend", {
			data: { labels: rows.map((row) => acrossYears ? row.date : row.date.slice(5)), datasets: [
				{ name: __("Accepted"), values: rows.map((row) => Number(row.sent || 0) + Number(row.hard_bounce || 0) + Number(row.soft_bounce || 0) + Number(row.spam || 0)) },
				{ name: __("Failed"), values: rows.map((row) => Number(row.failed || 0)) },
			] },
			type: "line", height: 250, colors: ["#1d7f67", "#d14343"], axisOptions: { xIsSeries: true }, lineOptions: { hideDots: 1, spline: 0 }, animate: 0,
		});
	}

	renderComparison(data) {
		const items = data.items || [];
		const headers = [data.scope === "template" ? __("Email Template") : __("Campaign"), __("Attempts"), __("Accepted"), __("Opened"), __("Clicked"), __("Replied"), __("Unsubscribed"), __("Bounces"), __("Spam"), __("Failed")];
		const countRate = (count, rate) => `<strong>${this.number(count)}</strong><small>${this.esc(this.rate(rate))}</small>`;
		this.page.main.find(".ecr-compare-table thead").html(`<tr>${headers.map((label) => `<th>${this.esc(label)}</th>`).join("")}</tr>`);
		this.page.main.find(".ecr-compare-table tbody").html(items.map((item) => {
			const summary = item.summary || {};
			const bounces = Number(summary.hard_bounce || 0) + Number(summary.soft_bounce || 0);
			return `<tr><th>${this.esc(item.name)}${data.scope === "template" ? `<small>${this.number(item.campaign_count)} ${__("campaigns")}</small>` : ""}</th><td>${this.number(summary.completed)}</td><td>${countRate(summary.accepted, summary.acceptance_rate)}</td><td>${countRate(summary.opened, summary.open_rate)}</td><td>${countRate(summary.clicked, summary.click_rate)}</td><td>${countRate(summary.replied, summary.reply_rate)}</td><td>${this.number(summary.unsubscribed)}</td><td>${this.number(bounces)}</td><td>${this.number(summary.spam)}</td><td>${this.number(summary.failed)}</td></tr>`;
		}).join(""));
		this.page.main.find("#ecr-compare-chart").empty();
		const hasAttempts = items.some((item) => Number(item.summary?.completed));
		this.page.main.find(".ecr-compare-chart-card").toggleClass("is-empty", !hasAttempts);
		if (!hasAttempts) {
			this.page.main.find("#ecr-compare-chart").html(`<div class="ecr-chart-empty">${__("No sends in this period. Try Last 90 days or a custom range.")}</div>`);
			return;
		}
		new frappe.Chart("#ecr-compare-chart", {
			data: { labels: items.map((item) => item.name), datasets: [
				["acceptance_rate", __("Acceptance")], ["open_rate", __("Open")], ["click_rate", __("Click")], ["reply_rate", __("Reply")],
			].map(([key, name]) => ({ name, values: items.map((item) => Number(item.summary?.[key] || 0)) })) },
			type: "bar", height: 290, colors: ["#171717", "#1d7f67", "#2563eb", "#7c3aed"], axisOptions: { xIsSeries: true }, animate: 0,
		});
	}

	rate(value) { return value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`; }

	selection() {
		const scope = this.scope.get_value() === __("Email Template") ? "template" : "campaign";
		return { scope, value: scope === "campaign" ? this.campaign.get_value() : this.template.get_value() };
	}

	async load() {
		const selection = this.selection();
		if (!selection.value) {
			this.page.main.find(".ecr-state").text(__("Select a campaign or email template to view results."));
			return;
		}
		const requestId = ++this.requestId;
		const custom = this.period.get_value() === __("Custom");
		const range = custom
			? { from_date: this.fromDate.get_value(), to_date: this.toDate.get_value() }
			: { days: Number(this.period.get_value()) || 30 };
		if (custom && (!range.from_date || !range.to_date || range.from_date > range.to_date)) {
			this.page.main.find(".ecr-state").text(__("Select a valid From Date and To Date."));
			return;
		}
		if (custom && Date.parse(range.to_date) - Date.parse(range.from_date) > 365 * 86400000) {
			this.page.main.find(".ecr-state").text(__("Select no more than 366 days for the timeline."));
			return;
		}
		this.pageNumber = 1;
		this.page.main.find(".ecr-state").text(__("Loading report…"));
		try {
			const result = await frappe.call({ method: this.method + "get_report", args: { ...selection, ...range } });
			if (requestId !== this.requestId) return;
			this.report = result.message || {};
			this.days = this.report.days || 30;
			this.page.main.find(".ecr-state").text(__("Showing {0} campaign(s)", [this.report.campaign_count || 0]));
			this.renderMetrics();
			this.renderTrend();
			this.highlightMetric();
			await this.loadDetails();
		} catch (error) {
			if (requestId === this.requestId) this.page.main.find(".ecr-state").text(__("Could not load this report."));
		}
	}

	renderMetrics() {
		const counts = this.report.summary || {};
		const eligible = Number(counts.eligible || 0);
		const sent = Number(counts.sent || 0);
		const accepted = sent + Number(counts.hard_bounce || 0) + Number(counts.soft_bounce || 0) + Number(counts.spam || 0);
		const completed = accepted + Number(counts.failed || 0);
		const notes = this.report.notes || {};
		this.page.main.find(".ecr-single-acceptance").html(`<div class="ecr-card ecr-metric"><span>${__("Mail-server acceptance rate")}</span><strong>${this.esc(this.rate(completed ? 100 * accepted / completed : null))}</strong><small>${this.number(accepted)} / ${this.number(completed)} ${__("completed attempts")}</small></div>`);
		this.page.main.find(".ecr-metrics").html(this.metrics.map(([key, label]) => {
			const count = counts[key];
			const available = count !== null && count !== undefined;
			const engagement = ["opened", "clicked", "unsubscribed", "replied"].includes(key);
			const outcome = ["hard_bounce", "soft_bounce", "spam", "failed"].includes(key);
			const denominator = engagement ? accepted : (outcome ? completed : eligible);
			const percent = available && denominator ? `${(100 * Number(count) / denominator).toFixed(1)}%` : (available ? "0%" : "—");
			const note = notes[key] || (engagement ? __("Percent of accepted sends") : (outcome ? __("Percent of completed delivery attempts") : __("Percent of eligible recipients")));
			return `<button type="button" class="ecr-card ecr-metric ${available ? "" : "ecr-unavailable"}" data-metric="${key}" title="${this.esc(note)}">
				<span>${this.esc(label)}</span><strong>${available ? this.number(count) : "—"}</strong><small>${available ? percent : __("Unavailable")}</small>
			</button>`;
		}).join(""));
	}

	renderTrend() {
		const rows = this.report.trend || [];
		const keys = ["sent", "opened", "clicked", "unsubscribed", "replied", "failed", "hard_bounce", "soft_bounce", "spam"];
		const colors = ["#171717", "#1d7f67", "#2563eb", "#d97706", "#7c3aed", "#d14343", "#9b4f31", "#e0a34f", "#b45381"];
		const activeSeries = keys.map((key, index) => ({ key, color: colors[index] }))
			.filter(({ key }) => rows.some((row) => Number(row[key] || 0) > 0));
		this.page.main.find("#ecr-trend").empty();
		this.page.main.find(".ecr-chart-period").text(this.report.range?.label || __("Last {0} days", [this.days]));
		this.page.main.find(".ecr-timeline-note").text(this.report.notes?.timeline || "");
		this.page.main.find(".ecr-peaks").html(["opened", "clicked", "replied", "unsubscribed"].map((key) => {
			const peak = rows.reduce((best, row) => Number(row[key] || 0) > Number(best?.[key] || 0) ? row : best, null);
			if (!peak || !peak[key]) return "";
			const label = this.metrics.find((entry) => entry[0] === key)[1];
			return `<span><strong>${this.esc(label)}</strong> ${this.esc(peak.date)} · ${this.number(peak[key])}</span>`;
		}).join(""));
		if (!activeSeries.length) {
			this.page.main.find("#ecr-trend").html(`<div class="ecr-chart-empty">${__("No recorded activity in this period.")}</div>`);
			return;
		}
		const acrossYears = rows[0]?.date.slice(0, 4) !== rows[rows.length - 1]?.date.slice(0, 4);
		new frappe.Chart("#ecr-trend", {
			data: { labels: rows.map((row) => acrossYears ? row.date : row.date.slice(5)), datasets: activeSeries.map(({ key }) => ({ name: this.metrics.find((entry) => entry[0] === key)[1], values: rows.map((row) => Number(row[key] || 0)) })) },
			type: "line", height: 250, colors: activeSeries.map(({ color }) => color), axisOptions: { xIsSeries: true },
			lineOptions: { hideDots: 1, spline: 0 }, animate: 0,
		});
	}

	highlightMetric() {
		this.page.main.find("[data-metric]").removeClass("active");
		this.page.main.find(`[data-metric="${this.metric}"]`).addClass("active");
	}

	async loadDetails() {
		if (!this.report) return;
		const metric = this.metric;
		const page = this.pageNumber;
		const requestId = this.requestId;
		const selection = this.selection();
		const body = this.page.main.find(".ecr-table tbody");
		body.html(`<tr><td colspan="5">${__("Loading…")}</td></tr>`);
		try {
			const result = await frappe.call({ method: this.method + "get_details", args: { ...selection, metric, page } });
			if (requestId !== this.requestId || metric !== this.metric || page !== this.pageNumber) return;
			const data = result.message || { rows: [], total: 0, page_size: 25 };
			const rows = data.rows || [];
			const label = this.metrics.find((entry) => entry[0] === metric)[1];
			body.html(rows.length ? rows.map((row) => {
				const link = frappe.utils.get_form_link("Lead", row.lead);
				return `<tr><td><a href="${this.esc(link)}">${this.esc(row.full_name)}</a></td><td>${this.esc(row.email)}</td><td>${this.esc(row.campaign_name)}</td><td>${this.esc(label)}</td><td>${this.esc(row.action_time ? frappe.datetime.str_to_user(row.action_time) : "—")}</td></tr>`;
			}).join("") : `<tr><td colspan="5" class="ecr-empty">${this.esc(this.report.notes?.[metric] || __("No recorded recipients for this action."))}</td></tr>`);
			this.page.main.find(".ecr-detail-total").text(__("{0} results", [this.number(data.total)]));
			const first = data.total ? (page - 1) * data.page_size + 1 : 0;
			const last = Math.min(page * data.page_size, data.total);
			this.page.main.find(".ecr-page-label").text(__("Showing {0}–{1} of {2}", [first, last, data.total]));
			this.page.main.find(".ecr-prev").prop("disabled", page <= 1);
			this.page.main.find(".ecr-next").prop("disabled", last >= data.total);
		} catch (error) {
			body.html(`<tr><td colspan="5" class="ecr-empty">${__("Could not load recipients.")}</td></tr>`);
		}
	}

	number(value) { return new Intl.NumberFormat().format(Number(value || 0)); }
	esc(value) { return frappe.utils.escape_html(String(value ?? "")); }
}
