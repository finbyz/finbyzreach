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
		this.metrics = [
			["sent", __("Sent")], ["delivered", __("Delivered")], ["opened", __("Opened")],
			["clicked", __("Clicked")], ["unsubscribed", __("Unsubscribed")],
			["hard_bounce", __("Hard bounce")], ["soft_bounce", __("Soft bounce")],
			["spam", __("Marked as spam")], ["replied", __("Replied")], ["failed", __("Failed")],
		];
		this.page.set_primary_action(__("Refresh"), () => this.load(), "refresh");
		this.render();
		this.makeControls();
		this.bind();
		this.applyRoute();
	}

	render() {
		this.page.main.html(`
			<div class="ecr-shell">
				<p class="ecr-intro">${__("Email broadcast results by campaign or email template")}</p>
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
		this.period = make("days", { fieldtype: "Select", fieldname: "days", label: __("Timeline"), options: ["7", "30", "90", __("Custom")], default: "30", change: () => this.period && this.togglePeriod() });
		this.fromDate = make("from_date", { fieldtype: "Date", fieldname: "from_date", label: __("From Date"), default: frappe.datetime.add_days(frappe.datetime.get_today(), -29) });
		this.toDate = make("to_date", { fieldtype: "Date", fieldname: "to_date", label: __("To Date"), default: frappe.datetime.get_today() });
		this.toggleScope();
		this.togglePeriod();
	}

	toggleScope() {
		const byTemplate = this.scope.get_value() === __("Email Template");
		this.page.main.find('[data-field="campaign"]').toggle(!byTemplate);
		this.page.main.find('[data-field="template"]').toggle(byTemplate);
	}

	togglePeriod() {
		this.page.main.find(".ecr-custom-range").toggleClass("is-visible", this.period.get_value() === __("Custom"));
	}

	bind() {
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
			await this.scope.set_value(__("Campaign"));
			await this.campaign.set_value(campaign);
			this.toggleScope();
			this.load();
		} else if (template && template !== this.template.get_value()) {
			await this.scope.set_value(__("Email Template"));
			await this.template.set_value(template);
			this.toggleScope();
			this.load();
		}
	}

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
