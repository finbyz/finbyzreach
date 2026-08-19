frappe.pages["email-campaign-studio"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Email Campaign Studio"),
		single_column: true,
	});
	wrapper.email_campaign_studio = new EmailCampaignStudio(page, wrapper);
};

frappe.pages["email-campaign-studio"].on_page_show = function (wrapper) {
	if (wrapper.email_campaign_studio) {
		wrapper.email_campaign_studio.handleRouteChange();
	}
	// Desk keeps the previous route's scroll position. A cached studio could therefore
	// reopen halfway through the audience card, underneath the sticky page header.
	requestAnimationFrame(() => {
		window.scrollTo(0, 0);
		if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
		$(wrapper).closest(".main-section").scrollTop(0);
		$(wrapper).find(".ecs-side, .ecs-samples").scrollTop(0);
	});
};

class EmailCampaignStudio {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.method = "finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio.";
		this.preview = null;
		this.previewRequest = 0;
		this.healthPreviewRequest = 0;
		this.previewQueuedKey = null;
		this.previewInFlight = null;
		this.previewInFlightKey = null;
		this.audienceChangeFrame = null;
		this.previewFailed = false;
		this.templateStateRequest = 0;
		this.busy = false;
		this.reviewPending = false;
		this.deliveryPlanValid = true;
		this.bootstrapLoaded = false;
		this.bootstrapRequest = 0;
		this.bootstrapApplyQueue = Promise.resolve();
		this.routeKey = null;
		this.routeLoading = false;
		this.sourceCampaign = null;
		this.emailGroupOptions = [];
		this.presetFilters = null;
		this.applyingAudiencePreset = false;
		this.applyingSegmentSelection = false;
		this.applyingBootstrap = false;
		this.activeStaticSegment = false;
		this.editable = true;
		this.render();
		this.makeForms();
		this.makeActions();
		this.makeLeadFilters();
		this.loadBootstrap(this.getRouteState());
	}

	getRouteState() {
		const params = new URLSearchParams(window.location.search || "");
		const legacyCampaign = params.get("campaign") || "";
		const value = params.get("studio_campaign") || params.get("campaign_name") || params.get("docname") || legacyCampaign;
		const session = params.get("studio_session") || params.get("new") || "direct";
		if (legacyCampaign && !params.get("studio_campaign")) {
			params.delete("campaign");
			params.set("studio_campaign", legacyCampaign);
			window.history.replaceState(window.history.state, "", window.location.pathname + "?" + params.toString());
		}
		["studio_campaign", "campaign", "campaign_name", "docname", "studio_session", "new"].forEach((key) => {
			if (frappe.route_options) delete frappe.route_options[key];
		});
		if (frappe.route_options && !Object.keys(frappe.route_options).length) {
			frappe.route_options = {};
		}
		if (!value) return { campaign: "", key: "new:" + session };
		let campaign;
		try {
			campaign = String(JSON.parse(value));
		} catch (error) {
			campaign = value;
		}
		return { campaign: campaign, key: "campaign:" + campaign + ":" + session };
	}

	handleRouteChange() {
		const route = this.getRouteState();
		if (route.key !== this.routeKey || (!this.bootstrapLoaded && !this.routeLoading)) {
			this.loadBootstrap(route);
		}
	}

	render() {
		this.$root = $(this.wrapper).find(".page-content");
		this.$root.addClass("email-campaign-studio").html([
			"<style>",
			".email-campaign-studio{background:linear-gradient(180deg,#f7f9fc 0%,var(--bg-light-gray,#f7f8fa) 42%);padding:14px 0 64px;min-height:calc(100vh - 110px);overflow-x:hidden}.email-campaign-studio *{box-sizing:border-box}",
			".ecs-shell{width:min(1440px,100%);max-width:100%;margin:0 auto;padding:0 18px;container-type:inline-size}",
			".ecs-hero{position:relative;isolation:isolate;overflow:hidden;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 24px;border-radius:16px;padding:15px 22px 12px;margin-bottom:16px;color:#fff;background:radial-gradient(circle at 90% 10%,rgba(56,189,248,.42),transparent 30%),linear-gradient(125deg,#172554 0%,#1d4ed8 58%,#0284c7 100%);box-shadow:0 11px 28px rgba(30,64,175,.16)}",
			".ecs-hero:after{content:'';position:absolute;z-index:-1;width:250px;height:250px;border:52px solid rgba(255,255,255,.07);border-radius:50%;right:-86px;top:-150px}.ecs-hero-copy{position:relative;z-index:1}.ecs-eyebrow{display:inline-flex;align-items:center;margin-bottom:7px;color:#bfdbfe;font-size:10px;font-weight:750;text-transform:uppercase;letter-spacing:.11em}",
			".ecs-hero h2{font-size:20px;line-height:1.18;margin:0 0 4px;font-weight:760;color:#fff;letter-spacing:-.02em}.ecs-hero p{margin:0;max-width:760px;color:rgba(255,255,255,.8);font-size:11.5px;line-height:1.4}.ecs-hero-trust{position:relative;z-index:1;display:flex;align-items:center;justify-content:flex-end;align-content:center;gap:7px 14px;min-width:0;flex-wrap:wrap}.ecs-hero-trust span{display:flex;align-items:center;gap:7px;color:rgba(255,255,255,.88);font-size:10px;font-weight:600;white-space:nowrap}.ecs-hero-trust i{width:7px;height:7px;border-radius:50%;background:#86efac;box-shadow:0 0 0 4px rgba(134,239,172,.12)}",
			".ecs-flow{position:relative;z-index:1;grid-column:1/-1;display:flex;gap:6px;flex-wrap:wrap;margin-top:0;padding-top:9px;border-top:1px solid rgba(255,255,255,.14)}.ecs-flow button{appearance:none;display:inline-flex;align-items:center;gap:6px;border:1px solid transparent;border-radius:999px;padding:4px 9px 4px 5px;background:rgba(255,255,255,.1);color:rgba(255,255,255,.84);font-size:10px;font-weight:650;cursor:pointer;transition:.18s ease}.ecs-flow button:hover{border-color:rgba(255,255,255,.3);background:rgba(255,255,255,.17);color:#fff}.ecs-flow button span{display:inline;padding:0;background:transparent}.ecs-flow b{display:grid;place-items:center;width:18px;height:18px;border-radius:50%;background:rgba(255,255,255,.94);color:#1d4ed8;font-size:9.5px}.ecs-flow button.complete{border-color:rgba(134,239,172,.34);background:rgba(16,185,129,.28);color:#fff;box-shadow:inset 0 0 0 1px rgba(134,239,172,.08)}.ecs-flow button.complete b{background:#bbf7d0;color:#166534}.ecs-flow button.current{border-color:rgba(255,255,255,.42);background:rgba(255,255,255,.16);color:#fff}",
			".ecs-grid{position:relative;isolation:isolate;display:grid;grid-template-columns:minmax(0,1fr) clamp(340px,26cqw,392px);gap:16px;align-items:start}.ecs-grid,.ecs-main,.ecs-side,.ecs-card{min-width:0}",
			".ecs-main{display:grid;gap:16px;container-type:inline-size}.ecs-side{z-index:8;display:flex;flex-direction:column;gap:14px;position:sticky;top:72px;width:100%;min-width:0;max-width:100%;height:calc(100vh - 88px);min-height:0;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;scrollbar-gutter:stable;padding:2px 6px 16px 2px}.ecs-side .ecs-card{flex-shrink:0;overflow:hidden}.ecs-side::-webkit-scrollbar{width:6px}.ecs-side::-webkit-scrollbar-thumb{border-radius:999px;background:rgba(148,163,184,.48)}.ecs-side::-webkit-scrollbar-track{background:transparent}",
			".ecs-card{position:relative;background:var(--card-bg,#fff);border:1px solid rgba(203,213,225,.72);border-radius:15px;box-shadow:0 5px 18px rgba(15,23,42,.055);overflow:visible;transition:border-color .18s ease,box-shadow .18s ease}.ecs-card[data-step]{scroll-margin-top:76px}.ecs-form-card:hover{border-color:rgba(148,163,184,.85);box-shadow:0 8px 24px rgba(15,23,42,.07)}",
			".ecs-card:focus-within{z-index:2}.email-campaign-studio .awesomplete>ul{z-index:1200!important;max-height:280px;overflow-y:auto}",
			".ecs-state-banner{display:none;align-items:flex-start;gap:10px;margin:-4px 0 16px;padding:11px 14px;border:1px solid #bfdbfe;border-radius:11px;background:#eff6ff;color:#1e3a5f;font-size:11.5px;line-height:1.45}.ecs-state-banner.visible{display:flex}.ecs-state-banner strong{white-space:nowrap;color:#1d4ed8}.ecs-readonly [data-audience-preset],.ecs-readonly #ecs-filter-builder,.ecs-readonly #ecs-exclude-filter-builder,.ecs-readonly .ecs-day-pill,.ecs-readonly .ecs-toggle-card{pointer-events:none;opacity:.72}",
			".ecs-capacity-note{display:flex;align-items:flex-start;gap:9px;margin:2px 7px 8px;padding:10px 11px;border:1px solid #dbeafe;border-radius:9px;background:#f8fbff;color:#36516f;font-size:10.5px;line-height:1.4}.ecs-capacity-note:before{content:'i';display:grid;place-items:center;flex:0 0 17px;width:17px;height:17px;border-radius:50%;background:#dbeafe;color:#1d4ed8;font-size:10px;font-weight:800}.ecs-capacity-note strong{color:#1e40af}.ecs-capacity-note.warn{border-color:#fed7aa;background:#fff7ed;color:#9a3412}.ecs-capacity-note.warn:before{content:'!';background:#ffedd5;color:#c2410c}.ecs-capacity-note.warn strong{color:#c2410c}.ecs-capacity-note.danger{border-color:#fecaca;background:#fff7f7;color:#991b1b}.ecs-capacity-note.danger:before{content:'!';background:#fee2e2;color:#b91c1c}.ecs-capacity-note.danger strong{color:#991b1b}",
			".ecs-email-preview{display:grid;gap:12px}.ecs-email-preview-meta{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 12px;padding:11px 13px;border:1px solid var(--border-color,#d7dce2);border-radius:10px;background:var(--subtle-fg,#f8fafc);font-size:11px}.ecs-email-preview-meta span{color:var(--text-muted)}.ecs-email-preview-meta strong{min-width:0;overflow-wrap:anywhere}.ecs-email-preview-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px}.ecs-email-preview-toolbar small{color:var(--text-muted)}.ecs-email-preview-toolbar .btn.active{border-color:#2563eb;background:#eff6ff;color:#1d4ed8}.ecs-email-preview-stage{display:flex;justify-content:center;min-height:620px;padding:14px;border:1px solid var(--border-color,#d7dce2);border-radius:11px;background:#e9eef5;overflow:auto}.ecs-email-preview-frame{width:100%;max-width:100%;height:620px;border:0;border-radius:7px;background:#fff;box-shadow:0 5px 18px rgba(15,23,42,.13);transition:width .18s ease}.ecs-email-preview-frame.mobile{width:390px}",
			".ecs-card-head{display:flex;align-items:center;gap:12px;padding:15px 18px 13px;border-bottom:1px solid var(--border-color,#edf0f2);background:linear-gradient(90deg,rgba(248,250,252,.76),transparent);border-radius:15px 15px 0 0}",
			".ecs-step{width:30px;height:30px;flex:0 0 30px;display:grid;place-items:center;border-radius:10px;background:#e8f0ff;color:#1d4ed8;font-size:12px;font-weight:780;box-shadow:inset 0 0 0 1px rgba(37,99,235,.06)}",
			".ecs-card[data-step='2'] .ecs-step{background:#f3e8ff;color:#7e22ce}.ecs-card[data-step='3'] .ecs-step{background:#e0f2fe;color:#0369a1}.ecs-card[data-step='4'] .ecs-step{background:#ffedd5;color:#c2410c}.ecs-card[data-step='5'] .ecs-step{background:#dcfce7;color:#15803d}.ecs-card[data-step].complete{border-color:rgba(34,197,94,.5)}.ecs-card[data-step].complete .ecs-card-head{background:linear-gradient(90deg,rgba(240,253,244,.9),transparent)}.ecs-card[data-step].complete .ecs-step{background:#dcfce7;color:#15803d;box-shadow:inset 0 0 0 1px rgba(34,197,94,.16)}.ecs-card[data-step].current{border-color:rgba(96,165,250,.72)}.ecs-card-head h3{font-size:14px;margin:0 0 3px;font-weight:730;letter-spacing:-.005em}.ecs-card-head p{font-size:11px;line-height:1.35;color:var(--text-muted,#6b7280);margin:0}.ecs-card-body{padding:16px 18px 18px}",
			".ecs-card .form-section{padding:0!important;border:0!important}.ecs-card .section-body{margin:0!important}.ecs-card .form-column{padding-left:7px;padding-right:7px}.ecs-form-card .form-section+.form-section{margin-top:13px!important;padding-top:14px!important;border-top:1px solid var(--border-color,#edf0f2)!important}.ecs-form-card .section-head{margin:0 7px 10px!important;padding:0!important;color:var(--text-color);font-size:11px!important;font-weight:720!important;text-transform:uppercase;letter-spacing:.045em}",
			".ecs-card .frappe-control{margin-bottom:11px}.ecs-form-card .control-label{margin-bottom:5px;font-size:11px;font-weight:650;color:var(--text-color)}.ecs-form-card .form-control,.ecs-form-card .input-with-feedback:not([type='checkbox']){min-height:36px;border:1px solid transparent;border-radius:8px;background:var(--control-bg,#f4f5f6);box-shadow:none;transition:border-color .15s,box-shadow .15s,background .15s}.ecs-form-card .form-control:focus,.ecs-form-card .input-with-feedback:not([type='checkbox']):focus{border-color:#60a5fa;background:var(--card-bg,#fff);box-shadow:0 0 0 3px rgba(37,99,235,.1)}.ecs-form-card .link-field .link-btn{top:3px;right:3px;height:30px;border-left:1px solid var(--border-color);border-radius:0 7px 7px 0;background:var(--card-bg,#fff);box-shadow:-3px 0 8px rgba(15,23,42,.04)}.ecs-form-card .link-field .link-btn a{width:28px;justify-content:center}.ecs-form-card .help-box{margin-top:4px;font-size:10.5px;line-height:1.35}.ecs-audience-card .ecs-card-body{padding:0}.ecs-audience-intro{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:15px 18px;background:linear-gradient(90deg,rgba(37,99,235,.07),rgba(14,165,233,.025));border-bottom:1px solid var(--border-color,#e5e7eb)}",
			".ecs-presets{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ecs-presets-label{font-size:11px;color:var(--text-muted);font-weight:700;text-transform:uppercase;letter-spacing:.045em;margin-right:2px}.ecs-preset-card{display:flex;align-items:center;gap:8px!important;border:1px solid var(--border-color,#d7dce2)!important;border-radius:9px!important;padding:7px 11px!important;background:var(--card-bg,#fff)!important;color:var(--text-color)!important;box-shadow:0 1px 2px rgba(15,23,42,.03)}.ecs-preset-card:hover{border-color:#93b4f8!important;background:#f8fbff!important}.ecs-preset-card.active{border-color:#2563eb!important;background:#eff6ff!important;color:#1749b8!important;box-shadow:0 0 0 2px rgba(37,99,235,.08)}.ecs-preset-mark{display:grid;place-items:center;width:20px;height:20px;border-radius:6px;background:#e8f0ff;color:#1d4ed8;font-size:11px;font-weight:800}.ecs-preset-clear{border:0!important;background:transparent!important;color:var(--text-muted)!important;padding:7px 5px!important}.ecs-preset-clear:hover{color:var(--text-color)!important;text-decoration:underline}",
			".ecs-safety-note{display:flex;align-items:center;gap:7px;max-width:310px;color:#36516f;font-size:11px;line-height:1.35}.ecs-safety-icon{display:grid;place-items:center;flex:0 0 24px;width:24px;height:24px;border-radius:50%;background:#dbeafe;color:#1d4ed8;font-weight:800}",
			".ecs-audience-columns{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr);gap:0}.ecs-target-panel{min-width:0;padding:18px}.ecs-target-panel+.ecs-target-panel{border-left:1px solid var(--border-color,#e5e7eb);background:rgba(248,250,252,.52)}.ecs-target-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}.ecs-target-title{display:flex;gap:10px;align-items:flex-start}.ecs-target-icon{display:grid;place-items:center;flex:0 0 30px;width:30px;height:30px;border-radius:9px;font-size:16px;font-weight:700}.ecs-include-panel .ecs-target-icon{background:#dcfce7;color:#15803d}.ecs-exclude-panel .ecs-target-icon{background:#ffedd5;color:#c2410c}.ecs-target-head h4{font-size:13px;font-weight:720;margin:1px 0 2px}.ecs-target-head p{font-size:11px;color:var(--text-muted);margin:0;line-height:1.35}.ecs-count-pill,.ecs-optional-pill{display:inline-flex;align-items:center;white-space:nowrap;border-radius:999px;padding:4px 8px;font-size:10px;font-weight:700}.ecs-count-pill{background:#e8f0ff;color:#1d4ed8}.ecs-optional-pill{background:var(--subtle-fg,#eef1f5);color:var(--text-muted)}",
			"#ecs-filter-builder .filter-area,#ecs-exclude-filter-builder .filter-area{border:1px solid var(--border-color,#d7dce2);border-radius:11px;padding:10px;background:var(--card-bg,#fff);box-shadow:inset 0 1px 0 rgba(15,23,42,.02)}#ecs-filter-builder .empty-filters,#ecs-exclude-filter-builder .empty-filters{padding:14px 8px;font-size:11.5px}#ecs-filter-builder .divider,#ecs-exclude-filter-builder .divider{margin:5px 0 7px;border-color:var(--border-color)}#ecs-filter-builder .filter-action-buttons,#ecs-exclude-filter-builder .filter-action-buttons{display:flex;justify-content:space-between;align-items:center}#ecs-filter-builder .add-filter,#ecs-exclude-filter-builder .add-filter{color:#1d4ed8!important;font-weight:650}#ecs-filter-builder .clear-filters,#ecs-exclude-filter-builder .clear-filters{background:transparent;border-color:transparent;color:var(--text-muted)}",
			".ecs-blacklist-divider{display:flex;align-items:center;gap:9px;margin:14px 0 8px;color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.045em}.ecs-blacklist-divider:before,.ecs-blacklist-divider:after{content:'';height:1px;background:var(--border-color);flex:1}.ecs-exclude-panel .frappe-control:last-child{margin-bottom:0}.ecs-exclude-panel [data-fieldname='exclude_email_groups'] .control-label{font-size:11.5px;font-weight:650}.ecs-exclude-panel [data-fieldname='exclude_email_groups'] .multiselect-list>.form-control{display:flex;align-items:center;min-height:40px;padding:7px 11px;border:1px solid var(--border-color,#d7dce2)!important;background:var(--card-bg,#fff);cursor:pointer}.ecs-exclude-panel [data-fieldname='exclude_email_groups'] .status-text{display:block;width:100%;min-width:0;color:var(--text-color,#1f2937);font-size:11.5px;line-height:1.35}.ecs-exclude-panel [data-fieldname='exclude_email_groups'] .status-text .text-extra-muted{color:var(--text-muted,#6b7280)!important}.ecs-exclude-panel [data-fieldname='exclude_email_groups'] .dropdown-menu{width:100%;min-width:240px;max-height:280px;overflow-y:auto}",
			".ecs-target-badges{display:flex;align-items:center;gap:5px}.ecs-audience-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:13px 18px;border-top:1px solid var(--border-color,#e5e7eb);background:var(--card-bg,#fff);border-radius:0 0 13px 13px}.ecs-audience-state{display:flex;align-items:center;gap:10px;font-size:11.5px;color:var(--text-muted)}.ecs-audience-state-dot{width:9px;height:9px;border-radius:50%;background:#94a3b8;box-shadow:0 0 0 4px rgba(148,163,184,.13)}.ecs-audience-state-dot.ready{background:#22c55e;box-shadow:0 0 0 4px rgba(34,197,94,.13)}.ecs-audience-state-dot.warn{background:#f59e0b;box-shadow:0 0 0 4px rgba(245,158,11,.13)}.ecs-audience-actions{display:flex;gap:8px;justify-content:flex-end}.ecs-audience-actions .btn{min-width:142px}",
			".ecs-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.ecs-metric{min-width:0;overflow:hidden;padding:12px 5px;border:1px solid rgba(226,232,240,.8);border-radius:11px;background:linear-gradient(180deg,var(--card-bg,#fff),var(--subtle-fg,#f7f8fa));text-align:center}.ecs-metric strong{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;font-size:22px;line-height:1.1;letter-spacing:-.025em}.ecs-metric span{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em}",
			".ecs-metric.eligible strong{color:#16803a}.ecs-metric.excluded strong{color:#c2410c}.ecs-preview-empty{padding:24px 10px;text-align:center;color:var(--text-muted);font-size:12px}",
			".ecs-reasons{margin-top:12px;display:grid;gap:6px}.ecs-reason{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;padding:6px 8px;border-radius:7px;background:var(--subtle-fg,#f7f8fa)}",
			".ecs-preview-card{flex:0 0 auto;display:flex;flex-direction:column}.ecs-preview-card .ecs-card-head{flex:0 0 auto;padding:14px}.ecs-preview-card .ecs-card-body{display:flex;flex-direction:column;gap:10px;padding:14px;overflow:visible}.ecs-preview-card .ecs-step{background:#dcfce7;color:#15803d}.ecs-preview-card .ecs-metrics,.ecs-preview-card .ecs-reasons{flex:0 0 auto}.ecs-health-action{padding:0 14px 14px}.ecs-health-action .btn{width:100%;min-height:34px;border-radius:8px!important;font-weight:650}.ecs-health-dialog{display:grid;gap:16px;padding:2px 0 6px}.ecs-health-dialog .ecs-metrics{gap:10px}.ecs-health-dialog .ecs-metric{padding:16px 8px}.ecs-health-section{min-width:0;border:1px solid var(--border-color,#d7dce2);border-radius:11px;overflow:hidden;background:var(--card-bg,#fff)}.ecs-health-section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 13px;background:var(--subtle-fg,#f7f8fa);border-bottom:1px solid var(--border-color,#e5e7eb)}.ecs-health-section-head h4{margin:0;font-size:12px;font-weight:720}.ecs-health-section-head span{color:var(--text-muted);font-size:10.5px}.ecs-health-list{max-height:260px;overflow-y:auto;padding:0 13px}.ecs-health-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(150px,42%);align-items:center;gap:14px;min-width:0;padding:10px 0;color:var(--text-color)!important;text-decoration:none!important}.ecs-health-row+.ecs-health-row{border-top:1px solid var(--border-color,#e5e7eb)}.ecs-health-row span,.ecs-health-row strong,.ecs-health-row small{min-width:0}.ecs-health-row strong,.ecs-health-row small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ecs-health-row small{color:var(--text-muted);text-align:right}.ecs-health-empty{padding:14px;color:var(--text-muted);font-size:11px}.ecs-topic-optouts{flex:0 0 auto;min-width:0;margin-top:0;border:1px solid #fed7aa;border-radius:10px;background:#fffaf5;overflow:hidden}.ecs-topic-optouts summary{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0;padding:9px 10px;color:#9a3412;font-size:10.5px;font-weight:700;cursor:pointer;list-style:none}.ecs-topic-optouts summary span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ecs-topic-optouts summary::-webkit-details-marker{display:none}.ecs-topic-optouts summary:after{content:'›';flex:0 0 auto;font-size:16px;line-height:1;transition:transform .15s}.ecs-topic-optouts[open] summary:after{transform:rotate(90deg)}.ecs-topic-optouts summary strong{flex:0 0 auto;margin-left:auto;padding:2px 6px;border-radius:999px;background:#ffedd5;color:#c2410c;font-size:9.5px}.ecs-optout-list{padding:0 10px 7px;border-top:1px solid #fed7aa}.ecs-optout-context{padding:7px 0 4px;color:#9a6a50;font-size:9.5px}.ecs-optout-row{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;padding:7px 0;color:var(--text-color)!important;text-decoration:none!important}.ecs-optout-row+.ecs-optout-row{border-top:1px solid rgba(254,215,170,.7)}.ecs-optout-row span{min-width:0;overflow:hidden}.ecs-optout-row strong,.ecs-optout-row small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ecs-optout-row strong{font-size:10.5px}.ecs-optout-row small{margin-top:1px;color:var(--text-muted);font-size:9.5px}.ecs-optout-open{flex:0 0 auto;color:#c2410c;font-size:12px}.ecs-optout-more{padding:7px 0 2px;color:#9a6a50;font-size:9.5px;font-weight:650}",
			".ecs-health-pagination{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 13px;border-top:1px solid var(--border-color,#e5e7eb);background:var(--subtle-fg,#f8fafc)}.ecs-health-pagination>span{color:var(--text-muted);font-size:10.5px}.ecs-health-pagination>div{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}.ecs-page-size{display:flex;align-items:center;gap:6px;margin:0 4px 0 0;color:var(--text-muted);font-size:10.5px;font-weight:500}.ecs-page-size select{width:66px;min-height:30px;padding:4px 22px 4px 8px;border-radius:7px}.ecs-health-pagination strong{min-width:82px;text-align:center;font-size:10.5px}.ecs-health-pagination .btn{border-radius:7px!important}",
			".ecs-health-toolbar{position:sticky;top:0;z-index:4;display:flex;align-items:center;gap:10px;padding:10px 0 12px;background:var(--modal-bg,var(--card-bg,#fff));border-bottom:1px solid var(--border-color,#e5e7eb)}.ecs-health-search-wrap{position:relative;flex:1 1 320px;min-width:180px}.ecs-health-search-wrap .form-control{height:36px;padding-right:36px;border-radius:8px}.ecs-health-search-clear{position:absolute;right:5px;top:50%;transform:translateY(-50%);display:none;width:26px;height:26px;padding:0!important;border:0!important;border-radius:6px!important;background:transparent!important;color:var(--text-muted)!important;font-size:17px;line-height:26px}.ecs-health-search-wrap.has-value .ecs-health-search-clear{display:block}.ecs-health-toolbar .ecs-page-size{flex:0 0 auto;margin:0}.ecs-health-results{position:relative;min-height:120px;padding-top:14px}.ecs-health-results.ecs-loading{pointer-events:none;opacity:.68}.ecs-health-filter-note{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;padding:9px 11px;border:1px solid #dbeafe;border-radius:9px;background:#f8fbff;color:#36516f;font-size:10.5px}.ecs-health-filter-note strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#1d4ed8}.ecs-health-dialog .ecs-health-section+.ecs-health-section{margin-top:12px}@media(max-width:580px){.ecs-health-toolbar{align-items:stretch;flex-direction:column}.ecs-health-toolbar .ecs-page-size{justify-content:space-between}.ecs-health-toolbar .ecs-page-size select{width:86px}}",
			".ecs-summary-card{flex:0 0 auto;display:flex;min-height:0}.ecs-summary{flex:1 1 auto;display:flex;flex-direction:column;min-width:0;min-height:0;padding:16px}.ecs-summary-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.ecs-summary-title span{order:2;flex:0 0 auto;padding:4px 7px;border-radius:999px;background:#ecfdf5;color:#15803d;font-size:9px;font-weight:750;text-transform:uppercase;letter-spacing:.045em}.ecs-summary h3{min-width:0;font-size:14px;margin:0}.ecs-summary-row{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;min-width:0;padding:8px 0;font-size:11.5px;border-bottom:1px solid var(--border-color)}.ecs-summary-row:last-child{border:0}.ecs-summary-row span{flex:0 0 auto;color:var(--text-muted)}.ecs-summary-row strong{min-width:0;max-width:64%;overflow-wrap:anywhere;white-space:normal;line-height:1.35;text-align:right}",
			".ecs-launch-note{position:relative;font-size:10.5px;color:#36516f;line-height:1.45;padding:11px 11px 11px 33px;border:1px solid #dbeafe;border-radius:10px;background:#f0f7ff;margin-top:12px}.ecs-launch-note:before{content:'i';position:absolute;left:11px;top:11px;display:grid;place-items:center;width:15px;height:15px;border-radius:50%;background:#dbeafe;color:#1d4ed8;font-size:9px;font-weight:800}.ecs-side-actions{display:grid;grid-template-columns:1fr;gap:8px;margin-top:13px}.ecs-side-actions .btn{width:100%;min-height:34px;border-radius:8px!important;font-weight:650;white-space:normal;line-height:1.2}.ecs-side-actions #ecs-launch-btn{min-height:38px;background:#1d4ed8!important;border-color:#1d4ed8!important}",
			".ecs-days-wrap{margin:0 7px 4px;padding:15px;border:1px solid rgba(203,213,225,.72);border-radius:13px;background:linear-gradient(180deg,var(--card-bg,#fff),rgba(248,250,252,.55))}.ecs-days-header{display:flex;align-items:center;gap:11px;margin-bottom:14px}.ecs-days-icon{display:grid;place-items:center;flex:0 0 38px;width:38px;height:38px;border-radius:11px;background:#eff6ff;color:#2563eb;box-shadow:inset 0 0 0 1px rgba(37,99,235,.08)}.ecs-days-icon svg{width:20px;height:20px;stroke:currentColor}.ecs-days-copy{min-width:0}.ecs-days-copy h4{margin:0 0 2px;font-size:13px;font-weight:740;color:var(--text-color)}.ecs-days-copy p{margin:0;color:var(--text-muted);font-size:10.5px;line-height:1.35}.ecs-days-count{margin-left:auto;padding:4px 8px;border-radius:999px;background:#eff6ff;color:#1d4ed8;font-size:9.5px;font-weight:750;white-space:nowrap}.ecs-day-picker{display:grid;grid-template-columns:repeat(7,minmax(76px,1fr));gap:8px}.ecs-day-pill{position:relative;appearance:none;display:grid;align-content:center;justify-items:center;gap:3px;min-height:78px;border:1px solid var(--border-color,#d7dce2);border-radius:11px;padding:13px 7px 10px;background:var(--card-bg,#fff);color:var(--text-muted);cursor:pointer;box-shadow:0 1px 2px rgba(15,23,42,.025);transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease,background .16s ease,color .16s ease}.ecs-day-pill:hover{transform:translateY(-1px);border-color:#93c5fd;color:#1d4ed8;box-shadow:0 5px 12px rgba(37,99,235,.08)}.ecs-day-pill:focus-visible{outline:0;border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.13)}.ecs-day-pill strong{font-size:12px;font-weight:780;line-height:1;text-transform:uppercase;letter-spacing:.055em}.ecs-day-pill small{font-size:9.5px;color:inherit;opacity:.76}.ecs-day-check{position:absolute;display:grid;place-items:center;right:8px;top:8px;width:17px;height:17px;border:1.5px solid #cbd5e1;border-radius:50%;background:var(--card-bg,#fff);color:transparent;font-size:10px;font-weight:850;line-height:1;transition:.16s ease}.ecs-day-pill.active{border-color:#60a5fa;background:linear-gradient(145deg,#eff6ff,#f8fbff);color:#1d4ed8;box-shadow:0 0 0 2px rgba(37,99,235,.07),0 5px 12px rgba(37,99,235,.06)}.ecs-day-pill.active .ecs-day-check{border-color:#2563eb;background:#2563eb;color:#fff;box-shadow:0 2px 5px rgba(37,99,235,.25)}.ecs-days-note{display:flex;align-items:center;gap:8px;margin-top:13px;padding-top:11px;border-top:1px solid var(--border-color,#e5e7eb);color:var(--text-muted);font-size:10.5px;line-height:1.35}.ecs-days-note i{display:grid;place-items:center;flex:0 0 18px;width:18px;height:18px;border-radius:50%;background:#eff6ff;color:#2563eb;font-size:10px;font-style:normal;font-weight:800}.ecs-days-note.warn{color:#b45309}.ecs-days-note.warn i{background:#fff7ed;color:#c2410c}.ecs-window-note{margin:0 7px 11px;padding:9px 11px;border-radius:9px;background:var(--subtle-fg,#f7f8fa);color:var(--text-muted);font-size:10.5px}.ecs-tracking-note{display:flex;align-items:center;gap:13px;margin:0 7px 2px;padding:11px 13px;border:1px solid #dbeafe;border-radius:10px;background:linear-gradient(90deg,#eff6ff,rgba(239,246,255,.35));font-size:10.5px}.ecs-tracking-note strong{flex:0 0 auto;color:#1d4ed8}.ecs-tracking-note span{color:#52647a;line-height:1.4}.ecs-toggle-stack{display:grid;gap:9px;padding:0 7px}.ecs-toggle-card{appearance:none;display:flex;align-items:center;gap:11px;width:100%;border:1px solid var(--border-color,#d7dce2);border-radius:11px;padding:10px 11px;background:var(--subtle-fg,#f8fafc);color:var(--text-color);text-align:left;cursor:pointer;transition:.16s ease}.ecs-toggle-card:hover{border-color:#93c5fd;background:#f8fbff}.ecs-toggle-icon{display:grid;place-items:center;flex:0 0 30px;width:30px;height:30px;border-radius:9px;background:var(--card-bg,#fff);color:#64748b;font-size:14px;font-style:normal;font-weight:760}.ecs-toggle-copy{display:grid;gap:2px;min-width:0}.ecs-toggle-copy strong{font-size:11.5px;font-weight:700}.ecs-toggle-copy small{color:var(--text-muted);font-size:9.5px;line-height:1.35}.ecs-switch{position:relative;flex:0 0 34px;width:34px;height:19px;margin-left:auto;border-radius:999px;background:#cbd5e1;box-shadow:inset 0 0 0 1px rgba(15,23,42,.05);transition:.16s}.ecs-switch i{position:absolute;left:3px;top:3px;width:13px;height:13px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(15,23,42,.25);transition:.16s}.ecs-toggle-card.active{border-color:#93c5fd;background:#eff6ff}.ecs-toggle-card.active .ecs-toggle-icon{background:#dbeafe;color:#1d4ed8}.ecs-toggle-card.active .ecs-switch{background:#2563eb}.ecs-toggle-card.active .ecs-switch i{transform:translateX(15px)}",
			".ecs-loading{opacity:.58;pointer-events:none}.ecs-status-dot{width:8px;height:8px;border-radius:50%;background:#94a3b8;display:inline-block;margin-right:6px}.ecs-status-dot.ready{background:#22c55e}.ecs-status-dot.warn{background:#f59e0b}",
			".email-campaign-studio.ecs-route-loading{position:relative;min-height:520px}.email-campaign-studio.ecs-route-loading .ecs-grid{visibility:hidden}.email-campaign-studio.ecs-route-loading:after{content:attr(data-loading-label);position:absolute;z-index:30;top:150px;left:50%;transform:translateX(-50%);padding:11px 16px;border:1px solid #dbeafe;border-radius:10px;background:var(--card-bg,#fff);color:#1e40af;font-size:12px;font-weight:650;box-shadow:0 8px 24px rgba(15,23,42,.08)}",
			"@container(max-width:860px){.ecs-audience-columns{grid-template-columns:1fr}.ecs-target-panel+.ecs-target-panel{border-left:0;border-top:1px solid var(--border-color)}.ecs-day-picker{grid-template-columns:repeat(4,minmax(90px,1fr))}}",
			"@media(max-width:1280px){.ecs-audience-intro{align-items:flex-start;flex-direction:column}.ecs-safety-note{max-width:none}.ecs-hero-trust{display:none}}",
			"@container(max-width:980px){.ecs-grid{grid-template-columns:1fr}.ecs-side{position:static;grid-row:1;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);height:auto;min-height:0;overflow:visible;padding:0}.ecs-main{grid-row:2}.ecs-preview-card,.ecs-summary-card{align-self:start;min-height:0}.ecs-summary{min-height:0}.ecs-launch-note{margin-top:12px}.ecs-audience-columns{grid-template-columns:1fr}.ecs-target-panel+.ecs-target-panel{border-left:0;border-top:1px solid var(--border-color)}}",
			"@media(max-width:980px){.ecs-hero{grid-template-columns:1fr;padding:18px}.ecs-shell{padding:0 12px}}",
			"@media(max-width:700px){.ecs-side{grid-template-columns:1fr}.ecs-preview-card{max-height:520px}.ecs-day-picker{grid-template-columns:repeat(4,minmax(70px,1fr))}.ecs-days-wrap{padding:13px}.ecs-target-head,.ecs-summary-title{align-items:flex-start;flex-direction:column}.ecs-target-badges{flex-wrap:wrap}}",
			"@media(max-width:580px){.ecs-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.ecs-metric{padding:10px 4px}.ecs-metric strong{font-size:18px}.ecs-flow{overflow-x:auto;flex-wrap:nowrap;padding-bottom:2px}.ecs-flow button{flex:0 0 auto}.ecs-flow button span{display:none}.ecs-card-body,.ecs-card-head{padding-left:12px;padding-right:12px}.ecs-audience-intro,.ecs-target-panel,.ecs-audience-footer{padding-left:12px;padding-right:12px}.ecs-audience-footer{align-items:stretch;flex-direction:column}.ecs-audience-actions{justify-content:stretch}.ecs-audience-actions .btn{width:100%;min-width:0}.ecs-presets{width:100%}.ecs-preset-card{flex:1 1 100%;justify-content:center}.ecs-preset-clear{width:100%;text-align:center}.ecs-day-picker{grid-template-columns:repeat(2,minmax(0,1fr))}.ecs-days-header{align-items:flex-start;flex-wrap:wrap}.ecs-days-count{margin-left:49px;margin-top:-8px}.ecs-tracking-note{align-items:flex-start;flex-direction:column;gap:5px}.ecs-side-actions{grid-template-columns:1fr}.ecs-side-actions .btn:first-child{grid-column:auto}.ecs-health-row{grid-template-columns:1fr;gap:3px}.ecs-health-row small{text-align:left}.ecs-health-pagination{align-items:stretch;flex-direction:column}.ecs-health-pagination>div{justify-content:space-between}}",
			"</style>",
			"<div class='ecs-shell'>",
			"<section class='ecs-hero'><div class='ecs-hero-copy'><span class='ecs-eyebrow'>" + __("Campaign workspace") + "</span><h2>" + __("Build, target and launch in one place") + "</h2><p>" + __("Create a compliant campaign, verify its real audience and control delivery without leaving this page.") + "</p></div><div class='ecs-hero-trust'><span><i></i>" + __("Live audience checks") + "</span><span><i></i>" + __("Flexible batch delivery") + "</span><span><i></i>" + __("Automatic UTM tracking") + "</span></div>",
			"<nav class='ecs-flow' aria-label='" + __("Campaign steps") + "'><button type='button' data-scroll-step='1'><b>1</b><span>" + __("Audience") + "</span></button><button type='button' data-scroll-step='2'><b>2</b><span>" + __("Content") + "</span></button><button type='button' data-scroll-step='3'><b>3</b><span>" + __("Sender") + "</span></button><button type='button' data-scroll-step='4'><b>4</b><span>" + __("Delivery") + "</span></button><button type='button' data-scroll-step='5'><b>5</b><span>" + __("Tracking") + "</span></button></nav></section>",
			"<div class='ecs-state-banner' id='ecs-state-banner'></div>",
			"<div class='ecs-grid'><main class='ecs-main'>",
			this.card("1", __("Build your audience"), __("Choose who should receive this email, then remove anyone who should not."), "<section class='ecs-target-panel' style='margin-bottom: 20px; border-radius: 8px; border: 1px solid var(--border-color); background: rgba(248,250,252,.52);'><div class='ecs-target-head' style='margin-bottom: 8px;'><div class='ecs-target-title'><span class='ecs-target-icon' style='background: #e0e7ff; color: #4338ca;'>★</span><div><h4>" + __("Audience Segment") + "</h4><p>" + __("Load an existing saved segment") + "</p></div></div></div><div id='ecs-segment-form'></div></section><div class='ecs-audience-intro'><div class='ecs-presets'><span class='ecs-presets-label'>" + __("Quick start") + "</span><button class='btn btn-sm ecs-preset-card' data-audience-preset='active-email'><span class='ecs-preset-mark'>✓</span><span>" + __("Active leads with email") + "</span></button><button class='btn btn-sm ecs-preset-card' data-audience-preset='all-email'><span class='ecs-preset-mark'>@</span><span>" + __("All leads with email") + "</span></button><button class='btn btn-sm ecs-preset-clear' data-audience-preset='clear'>" + __("Reset") + "</button></div><div class='ecs-safety-note'><span class='ecs-safety-icon'>i</span><span>" + __("Rules inside a group use AND. Add another group to include Leads matching either group.") + "</span></div></div><div class='ecs-audience-columns'><section class='ecs-target-panel ecs-include-panel'><div class='ecs-target-head'><div class='ecs-target-title'><span class='ecs-target-icon'>+</span><div><h4>" + __("Include Leads") + "</h4><p>" + __("Who should receive this campaign?") + "</p></div></div><div style='display: flex; gap: 8px; align-items: center;'><span class='ecs-count-pill' id='ecs-filter-count'>0 " + __("filters") + "</span><button class='btn btn-default btn-sm' id='ecs-save-segment-btn'>" + __("Save as Segment") + "</button></div></div><div id='ecs-filter-builder'><div id='ecs-filter-groups'></div><button type='button' class='btn btn-default btn-sm' id='ecs-add-or-group'>" + __("Add OR group") + "</button></div></section><section class='ecs-target-panel ecs-exclude-panel'><div class='ecs-target-head'><div class='ecs-target-title'><span class='ecs-target-icon'>−</span><div><h4>" + __("Exclude and suppress") + "</h4><p>" + __("Remove matching Leads.") + "</p></div></div><div class='ecs-target-badges'><span class='ecs-count-pill' id='ecs-exclude-filter-count'>0 " + __("rules") + "</span><span class='ecs-optional-pill'>" + __("Optional") + "</span></div></div><div id='ecs-exclude-filter-builder'><div id='ecs-exclude-filter-groups'></div><button type='button' class='btn btn-default btn-sm' id='ecs-add-exclude-or-group'>" + __("Add OR group") + "</button></div></section></div><div class='ecs-audience-footer'><div class='ecs-audience-state'><span class='ecs-audience-state-dot' id='ecs-audience-state-dot'></span><span id='ecs-audience-state-text'>" + __("Choose a preset or add at least one include filter.") + "</span></div><div class='ecs-audience-actions'><button class='btn btn-primary btn-sm' id='ecs-preview-btn' disabled>" + __("Preview Audience") + "</button></div></div>"),
			this.card("2", __("Campaign and email"), __("Name the campaign and select a standard or visual-builder Email Template."), "<div id='ecs-content-form'></div>"),
			this.card("3", __("Sender identity"), __("Choose the outgoing account recipients should see."), "<div id='ecs-sender-form'></div>"),
			this.card("4", __("Delivery plan"), __("Set the send time, batch size, cadence, weekdays and optional sending hours."), "<div id='ecs-schedule-form'></div>"),
			this.card("5", __("Tracking"), __("UTM tags are added automatically; opens and signed clicks feed campaign metrics."), "<div id='ecs-tracking-form'></div>"),
			"</main><aside class='ecs-side'>",
			"<section class='ecs-card ecs-preview-card'><div class='ecs-card-head'><div class='ecs-step'>✓</div><div><h3>" + __("Audience health") + "</h3><p><span class='ecs-status-dot' id='ecs-preview-dot'></span><span id='ecs-preview-status'>" + __("Waiting for filters") + "</span></p></div></div><div class='ecs-card-body' id='ecs-preview-panel'><div class='ecs-preview-empty'>" + __("Add Lead filters or select a segment, then preview the campaign audience.") + "</div></div><div class='ecs-health-action'><button class='btn btn-default btn-sm' id='ecs-health-btn' disabled>" + __("View Full Audience Health") + "</button></div></section>",
			"<section class='ecs-card ecs-summary-card'><div class='ecs-summary'><div class='ecs-summary-title'><span>" + __("Ready check") + "</span><h3>" + __("Launch summary") + "</h3></div><div id='ecs-summary-rows'></div><div class='ecs-launch-note'>" + __("Scheduling freezes recipients, recipient email addresses, Email Template content and the batch plan. Personalization uses the Lead data current when each email is queued.") + "</div><div class='ecs-side-actions'><button class='btn btn-primary btn-sm' id='ecs-launch-btn'>" + __("Review & Schedule") + "</button><button class='btn btn-default btn-sm' id='ecs-email-preview-btn'>" + __("Preview Email") + "</button><button class='btn btn-default btn-sm' id='ecs-test-btn'>" + __("Send Test") + "</button><button class='btn btn-default btn-sm' id='ecs-draft-btn'>" + __("Save Draft") + "</button></div></div></section>",
			"</aside></div></div>",
		].join(""));
	}

	card(number, title, description, body) {
		const audienceClass = number === "1" ? " ecs-audience-card" : "";
		const formClass = number === "1" ? "" : " ecs-form-card";
		return "<section class='ecs-card" + audienceClass + formClass + "' id='ecs-step-" + number + "' data-step='" + number + "'><div class='ecs-card-head'><div class='ecs-step'>" + number + "</div><div><h3>" + title + "</h3><p>" + description + "</p></div></div><div class='ecs-card-body'>" + body + "</div></section>";
	}

	makeForms() {
		const change = () => {
			if (!this.applyingBootstrap) this.updateSummary();
		};
		const topicChange = () => {
			if (this.applyingBootstrap) return;
			this.preview = null;
			this.updateSummary();
			this.queuePreview();
		};
		this.segmentForm = this.makeForm("#ecs-segment-form", [
			{
				fieldname: "segment_name",
				label: "",
				fieldtype: "Link",
				options: "Reach Segment",
				description: __("Optional. Selecting a segment replaces your current rules."),
				change: () => {
					if (this.applyingBootstrap || this.applyingSegmentSelection) return;
					const segment = this.segmentForm.get_value("segment_name");
					if (segment) {
						this.loadSegment(segment);
					} else {
						this.activeStaticSegment = false;
						this.handleAudienceRuleChange(true);
					}
				},
			},
		]);
		this.contentForm = this.makeForm("#ecs-content-form", [
			{ fieldname: "campaign_title", label: __("Campaign Title"), fieldtype: "Data", reqd: 1, description: __("An internal name used to identify this campaign in lists and reports."), change },
			{ fieldtype: "Column Break" },
			{
				fieldname: "subscription_topic",
				label: __("Subscription Topic"),
				fieldtype: "Link",
				options: "Subscription Topic",
				reqd: 1,
				description: __("Leads unsubscribed from this topic are automatically excluded."),
				get_query: () => ({ filters: { disabled: 0 } }),
				change: topicChange,
			},
			{ fieldtype: "Section Break", label: __("Email content") },
			{
				fieldname: "email_template",
				label: __("Email Template"),
				fieldtype: "Link",
				options: "Email Template",
				reqd: 1,
				description: __("Select the standard or visual-builder email that recipients will receive."),
				get_query: () => ({ filters: [["Email Template", "custom_reference_doctype", "in", ["", "Lead"]]] }),
				change: () => {
					change();
					// Bootstrap sets this field programmatically; the final bootstrap step
					// renders its state once after every dependent value is available.
					if (!this.applyingBootstrap) this.showTemplateState();
				},
			},
			{ fieldtype: "Column Break" },
			{ fieldname: "subject_override", label: __("Subject Override"), fieldtype: "Data", description: __("Optional—leave blank to use the template subject."), change },
			{ fieldtype: "Section Break" },
			{ fieldname: "template_state", fieldtype: "HTML" },
		]);
		this.senderForm = this.makeForm("#ecs-sender-form", [
			{
				fieldname: "email_account",
				label: __("Outgoing Email Account"),
				fieldtype: "Autocomplete",
				reqd: 1,
				description: __("The enabled outgoing mailbox used to send this campaign."),
				change,
			},
			{ fieldtype: "Column Break" },
			{ fieldname: "sender_name", label: __("Sender Name"), fieldtype: "Data", description: __("The name recipients will see."), change },
			{ fieldtype: "Column Break" },
			{ fieldname: "reply_to", label: __("Reply-To"), fieldtype: "Data", options: "Email", description: __("Optional address that receives replies instead of the sending mailbox."), change },
		]);
		this.scheduleForm = this.makeForm("#ecs-schedule-form", [
			{ fieldname: "start_date", label: __("Start Date"), fieldtype: "Date", reqd: 1, description: __("The first date on which this campaign may begin sending."), change },
			{ fieldname: "start_time", label: __("Start Time"), fieldtype: "Time", reqd: 1, description: __("The time when the first eligible batch becomes due."), change },
			{ fieldtype: "Column Break" },
			{ fieldname: "batch_size", label: __("Emails per Batch"), fieldtype: "Int", default: 100, reqd: 1, description: __("Recipients assigned to each scheduled batch. No Studio maximum is enforced."), change },
			{ fieldtype: "Column Break" },
			{ fieldname: "repeat_every", label: __("Repeat Every"), fieldtype: "Int", default: 1, reqd: 1, description: __("Planned time between batches. No Studio rate limit or scheduler-resolution minimum is enforced."), change },
			{ fieldname: "repeat_unit", label: __("Interval Unit"), fieldtype: "Select", options: "Minutes\nHours\nDays", default: "Hours", reqd: 1, description: __("The time unit applied to the repeat interval above."), change },
			{ fieldtype: "Section Break" },
			{ fieldname: "capacity_note", fieldtype: "HTML" },
			{ fieldtype: "Section Break" },
			{ fieldname: "day_picker", fieldtype: "HTML" },
			{ fieldname: "send_monday", fieldtype: "Check", default: 1, hidden: 1, change },
			{ fieldname: "send_tuesday", fieldtype: "Check", default: 1, hidden: 1, change },
			{ fieldname: "send_wednesday", fieldtype: "Check", default: 1, hidden: 1, change },
			{ fieldname: "send_thursday", fieldtype: "Check", default: 1, hidden: 1, change },
			{ fieldname: "send_friday", fieldtype: "Check", default: 1, hidden: 1, change },
			{ fieldname: "send_saturday", fieldtype: "Check", default: 0, hidden: 1, change },
			{ fieldname: "send_sunday", fieldtype: "Check", default: 0, hidden: 1, change },
			{ fieldtype: "Section Break", label: __("Optional Daily Sending Window") },
			{ fieldname: "window_note", fieldtype: "HTML", options: "<div class='ecs-window-note'>" + __("Leave this off to send batches whenever they become due, or limit delivery to a daily time range.") + "</div>" },
			{ fieldname: "window_toggle", fieldtype: "HTML" },
			{ fieldname: "restrict_sending_window", fieldtype: "Check", default: 0, hidden: 1, change },
			{ fieldtype: "Column Break" },
			{ fieldname: "window_start", label: __("Starts At"), fieldtype: "Time", depends_on: "eval:doc.restrict_sending_window", description: __("Earliest time of day when a due batch may be released."), change },
			{ fieldtype: "Column Break" },
			{ fieldname: "window_end", label: __("Ends At"), fieldtype: "Time", depends_on: "eval:doc.restrict_sending_window", description: __("Latest time of day when a due batch may be released."), change },
		]);
		this.trackingForm = this.makeForm("#ecs-tracking-form", [
			{ fieldname: "tracking_note", fieldtype: "HTML", options: "<div class='ecs-tracking-note'><strong>" + __("Built-in attribution") + "</strong><span>" + __("Every eligible website link receives your UTM values automatically. Signed redirect links measure individual clicks safely.") + "</span></div>" },
			{ fieldtype: "Section Break" },
			{ fieldname: "tracking_toggles", fieldtype: "HTML" },
			{ fieldname: "enable_open_tracking", fieldtype: "Check", default: 1, hidden: 1, change },
			{ fieldname: "enable_click_tracking", fieldtype: "Check", default: 1, hidden: 1, change },
			{ fieldtype: "Column Break" },
			{ fieldname: "utm_source", label: __("UTM Source"), fieldtype: "Data", default: "newsletter", reqd: 1, description: __("Identifies this campaign traffic source in analytics."), change },
			{ fieldname: "utm_medium", label: __("UTM Medium"), fieldtype: "Data", default: "email", reqd: 1, description: __("Identifies email as the marketing channel in analytics."), change },
		]);
		this.setupScheduleDayPicker();
		this.setupOptionToggles();
		this.updateSummary();
	}

	makeForm(selector, fields) {
		const form = new frappe.ui.FieldGroup({
			fields: fields,
			body: this.$root.find(selector),
		});
		form.make();
		return form;
	}

	setupScheduleDayPicker() {
		const days = [
			["send_monday", __("Mon"), __("Monday")],
			["send_tuesday", __("Tue"), __("Tuesday")],
			["send_wednesday", __("Wed"), __("Wednesday")],
			["send_thursday", __("Thu"), __("Thursday")],
			["send_friday", __("Fri"), __("Friday")],
			["send_saturday", __("Sat"), __("Saturday")],
			["send_sunday", __("Sun"), __("Sunday")],
		];
		const field = this.scheduleForm.get_field("day_picker");
		const calendarIcon = "<svg viewBox='0 0 24 24' fill='none' aria-hidden='true'><rect x='3.5' y='5.5' width='17' height='15' rx='2.5' stroke-width='1.8'/><path d='M7.5 3.5v4M16.5 3.5v4M3.5 10h17M8.5 15l2 2 4.5-5' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/></svg>";
		field.html(
			"<section class='ecs-days-wrap' aria-labelledby='ecs-days-title'>" +
			"<div class='ecs-days-header'><span class='ecs-days-icon'>" + calendarIcon + "</span><div class='ecs-days-copy'><h4 id='ecs-days-title'>" + __("Sending days") + "</h4><p>" + __("Select the weekdays when campaign batches may be released.") + "</p></div><span class='ecs-days-count' id='ecs-days-count'></span></div>" +
			"<div class='ecs-day-picker'>" + days.map((day) => {
				return "<button type='button' class='ecs-day-pill' data-day-field='" + day[0] + "' aria-pressed='false' title='" + __("Toggle campaign delivery on {0}", [day[2]]) + "'><span class='ecs-day-check' aria-hidden='true'>✓</span><strong>" + day[1] + "</strong><small>" + day[2] + "</small></button>";
			}).join("") + "</div>" +
			"<div class='ecs-days-note' id='ecs-days-note'><i>i</i><span>" + __("Batches are scheduled only on selected days.") + "</span></div></section>"
		);

		const sync = () => {
			let selectedCount = 0;
			days.forEach((day) => {
				const active = Boolean(Number(this.scheduleForm.get_value(day[0])));
				if (active) selectedCount += 1;
				this.$root.find(`[data-day-field="${day[0]}"]`)
					.toggleClass("active", active)
					.attr("aria-pressed", active ? "true" : "false");
			});
			this.$root.find("#ecs-days-count").text(__("{0} selected", [selectedCount]));
			this.$root.find("#ecs-days-note")
				.toggleClass("warn", selectedCount === 0)
				.find("span")
				.text(selectedCount ? __("Batches are scheduled only on selected days.") : __("Select at least one sending day."));
		};
		this.$root.off("click.ecs-days", ".ecs-day-pill").on("click.ecs-days", ".ecs-day-pill", (event) => {
			const fieldname = $(event.currentTarget).data("day-field");
			const active = !Boolean(Number(this.scheduleForm.get_value(fieldname)));
			Promise.resolve(this.scheduleForm.set_value(fieldname, active ? 1 : 0)).then(() => {
				sync();
				this.updateSummary();
			});
		});
		sync();
		setTimeout(sync, 0);
	}

	setupOptionToggles() {
		const groups = {
			schedule: {
				form: this.scheduleForm,
				field: "window_toggle",
				items: [
					["restrict_sending_window", "◷", __("Restrict sending hours"), __("Only release batches inside the daily time range.")],
				],
			},
			tracking: {
				form: this.trackingForm,
				field: "tracking_toggles",
				items: [
					["enable_open_tracking", "◉", __("Track opens"), __("Uses a lightweight tracking pixel.")],
					["enable_click_tracking", "↗", __("Track clicks"), __("Uses signed campaign redirect links.")],
				],
			},
		};
		Object.entries(groups).forEach(([groupName, group]) => {
			group.form.get_field(group.field).html(
				"<div class='ecs-toggle-stack'>" + group.items.map((item) => {
					return "<button type='button' class='ecs-toggle-card' data-option-group='" + groupName + "' data-option-field='" + item[0] + "' aria-pressed='false' title='" + item[3] + "'><i class='ecs-toggle-icon'>" + item[1] + "</i><span class='ecs-toggle-copy'><strong>" + item[2] + "</strong><small>" + item[3] + "</small></span><span class='ecs-switch' aria-hidden='true'><i></i></span></button>";
				}).join("") + "</div>"
			);
		});

		const sync = () => {
			Object.entries(groups).forEach(([groupName, group]) => {
				group.items.forEach((item) => {
					const active = Boolean(Number(group.form.get_value(item[0])));
					this.$root.find(`[data-option-group="${groupName}"][data-option-field="${item[0]}"]`)
						.toggleClass("active", active)
						.attr("aria-pressed", active ? "true" : "false");
				});
			});
		};
		this.$root.off("click.ecs-toggles", ".ecs-toggle-card").on("click.ecs-toggles", ".ecs-toggle-card", (event) => {
			const $button = $(event.currentTarget);
			const group = groups[$button.data("option-group")];
			const fieldname = $button.data("option-field");
			if (!group || !fieldname) return;
			const active = !Boolean(Number(group.form.get_value(fieldname)));
			group.form.set_value(fieldname, active ? 1 : 0).then(() => {
				sync();
				this.updateSummary();
			});
		});
		sync();
		setTimeout(sync, 0);
	}

	makeActions() {
		// Wrap in Promise.resolve so page.js btn_disable_enable() receives a native
		// promise. reviewAndSchedule()/createCampaign() return jQuery promises, which
		// expose .then/.always but not .finally, and page.js calls .finally on any
		// thenable return value ("response.finally is not a function" otherwise).
		this.page.set_primary_action(__("Review & Schedule"), () => Promise.resolve(this.reviewAndSchedule()), "send");
		this.page.set_secondary_action(__("Save Draft"), () => Promise.resolve(this.createCampaign("draft")));
		this.goToCampaignButton = this.page.add_inner_button(__("Go to Campaign"), () => this.openCampaign({ campaign: this.sourceCampaign }));
		this.page.add_inner_button(__("Create New Campaign"), () => this.openNewCampaign());
		this.page.add_inner_button(__("Campaign List"), () => frappe.set_route("List", "Campaign"));
		this.updateCampaignNavigation();
		this.$root.on("click", "#ecs-preview-btn", () => this.previewAudience());
		this.$root.on("click", "#ecs-add-or-group", () => this.addIncludeFilterGroup());
		this.$root.on("click", "#ecs-add-exclude-or-group", () => this.addExcludeFilterGroup());
		this.$root.on("click", "#ecs-save-segment-btn", () => this.showSaveSegmentDialog());
		this.$root.on("click", "#ecs-health-btn", () => this.showAudienceHealth());
		this.$root.on("click", "#ecs-launch-btn", () => this.reviewAndSchedule());
		this.$root.on("click", "#ecs-draft-btn", () => this.createCampaign("draft"));
		this.$root.on("click", "#ecs-email-preview-btn", () => this.showEmailPreviewDialog());
		this.$root.on("click", "#ecs-test-btn", () => this.showTestDialog());
		this.$root.on("click", "[data-audience-preset]", (event) => {
			this.applyAudiencePreset($(event.currentTarget).data("audience-preset"));
		});
		this.$root.on(
			"click change input",
			"#ecs-filter-builder .filter-box :input, #ecs-filter-builder .add-filter, #ecs-filter-builder .clear-filters, #ecs-filter-builder .remove-filter, #ecs-exclude-filter-builder .filter-box :input, #ecs-exclude-filter-builder .add-filter, #ecs-exclude-filter-builder .clear-filters, #ecs-exclude-filter-builder .remove-filter",
			(event) => {
				if (event.originalEvent) this.handleAudienceRuleChange();
			}
		);
		this.$root.on("click", "[data-scroll-step]", (event) => {
			const target = this.$root.find("#ecs-step-" + $(event.currentTarget).data("scroll-step"))[0];
			target?.scrollIntoView({ behavior: "smooth", block: "start" });
		});
	}

	updateCampaignNavigation() {
		if (this.goToCampaignButton) {
			this.goToCampaignButton.toggle(Boolean(this.sourceCampaign));
		}
	}

	openNewCampaign() {
		const session = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
		frappe.route_options = {};
		window.history.pushState(null, null, "/desk/email-campaign-studio?new=" + session);
		frappe.router.route();
	}

	applyAudiencePreset(preset) {
		if (!this.filterGroups) return;
		const presets = {
			"active-email": [
				["Lead", "disabled", "=", 0],
				["Lead", "email_id", "is", "set"],
			],
			"all-email": [["Lead", "email_id", "is", "set"]],
			clear: [],
		};
		const presetFilters = (presets[preset] || []).map((filter) => filter.slice());
		this.applyingAudiencePreset = true;
		this.presetFilters = preset === "clear" ? null : [presetFilters];
		this.clearSelectedSegment();
		this.$root.find("[data-audience-preset]").removeClass("active");
		if (preset !== "clear") {
			this.$root.find(`[data-audience-preset="${preset}"]`).addClass("active");
		}
		return this.applyIncludeFilterGroups(presetFilters.length ? [presetFilters] : []).then(
			() => {
				this.applyingAudiencePreset = false;
				this.handleAudienceRuleChange(true);
			},
			(error) => {
				this.applyingAudiencePreset = false;
				this.clearAudiencePresetState();
				throw error;
			}
		);
	}

	clearAudiencePresetState() {
		if (this.presetFilters === null) return;
		this.presetFilters = null;
		this.$root.find("[data-audience-preset]").removeClass("active");
	}

	makeLeadFilters() {
		this.filtersReady = new Promise((resolve) => frappe.model.with_doctype("Lead", () => {
			const onFilterChange = () => this.handleAudienceRuleChange();
			this.filterGroups = [];
			this.excludeFilterGroups = [];
			this.addIncludeFilterGroup([], onFilterChange);
			this.addExcludeFilterGroup([], onFilterChange);
			this.updateFilterCount();
			resolve();
		}));
	}

	normalizeFilterGroups(filters) {
		if (!Array.isArray(filters) || !filters.length) return [];
		if (Array.isArray(filters[0]) && typeof filters[0][0] === "string") return [filters];
		return filters.filter((group) => Array.isArray(group));
	}

	addIncludeFilterGroup(filters = [], onChange) {
		const callback = onChange || (() => this.handleAudienceRuleChange());
		const $group = $("<section class='ecs-filter-rule-group mb-4'><div class='flex justify-between items-center mb-2'><strong>" + __("Group") + " " + ((this.filterGroups || []).length + 1) + "</strong><button type='button' class='btn btn-xs btn-default ecs-remove-group-btn'>" + __("Remove") + "</button></div><div class='ecs-filter-rule-group-body'></div></section>");
		this.$root.find("#ecs-filter-groups").append($group);
		const filterGroup = this.makeEmbeddedFilterGroup($group.find(".ecs-filter-rule-group-body"), callback);
		this.filterGroups.push({ filterGroup, $group });
		$group.find(".ecs-remove-group-btn").on("click", () => {
			if (this.filterGroups.length === 1) return;
			this.filterGroups = this.filterGroups.filter((item) => item.filterGroup !== filterGroup);
			$group.remove();
			this.handleAudienceRuleChange();
		});
		if (!filters.length) return Promise.resolve(filterGroup);
		this.applyingAudiencePreset = true;
		return filterGroup.add_filters(filters).then(() => filterGroup).finally(() => {
			this.applyingAudiencePreset = false;
		});
	}

	addExcludeFilterGroup(filters = [], onChange) {
		const callback = onChange || (() => this.handleAudienceRuleChange());
		const $group = $("<section class='ecs-filter-rule-group mb-4'><div class='flex justify-between items-center mb-2'><strong>" + __("Group") + " " + ((this.excludeFilterGroups || []).length + 1) + "</strong><button type='button' class='btn btn-xs btn-default ecs-remove-group-btn'>" + __("Remove") + "</button></div><div class='ecs-filter-rule-group-body'></div></section>");
		this.$root.find("#ecs-exclude-filter-groups").append($group);
		const filterGroup = this.makeEmbeddedFilterGroup($group.find(".ecs-filter-rule-group-body"), callback);
		this.excludeFilterGroups.push({ filterGroup, $group });
		$group.find(".ecs-remove-group-btn").on("click", () => {
			if (this.excludeFilterGroups.length === 1) return;
			this.excludeFilterGroups = this.excludeFilterGroups.filter((item) => item.filterGroup !== filterGroup);
			$group.remove();
			this.handleAudienceRuleChange();
		});
		if (!filters.length) return Promise.resolve(filterGroup);
		this.applyingAudiencePreset = true;
		return filterGroup.add_filters(filters).then(() => filterGroup).finally(() => {
			this.applyingAudiencePreset = false;
		});
	}

	handleAudienceRuleChange(preservePreset = false) {
		if (this.applyingBootstrap || this.applyingAudiencePreset) return;
		if (!preservePreset) this.clearSelectedSegment();
		// FilterGroup emits its own callback and embedded controls bubble DOM events.
		// Coalesce both so one edit produces one preview after controls settle.
		if (this.audienceChangeFrame) return;
		this.audienceChangeFrame = requestAnimationFrame(() => {
			this.audienceChangeFrame = null;
			if (this.applyingBootstrap || this.applyingAudiencePreset) return;
			if (!preservePreset) this.clearAudiencePresetState();
			this.preview = null;
			this.updateFilterCount();
			this.queuePreview();
		});
	}

	clearSelectedSegment() {
		this.activeStaticSegment = false;
		if (
			!this.segmentForm
			|| !this.segmentForm.get_value("segment_name")
			|| this.applyingSegmentSelection
		) return;
		this.applyingSegmentSelection = true;
		Promise.resolve(this.segmentForm.set_value("segment_name", "")).then(
			() => { this.applyingSegmentSelection = false; },
			() => { this.applyingSegmentSelection = false; }
		);
	}

	makeEmbeddedFilterGroup(selector, onChange) {
		const filterGroup = new frappe.ui.FilterGroup({
			parent: typeof selector === "string" ? this.$root.find(selector) : selector,
			doctype: "Lead",
			on_change: onChange,
		});

		// Frappe's FilterGroup is primarily written for list-view filter buttons.
		// Embedded groups have no filter_button, but add_filters() still calls
		// update_filter_button(). Keep the instance contract safe without changing
		// Frappe core.
		filterGroup.update_filter_button = function () {};

		return filterGroup;
	}

	waitForPreviousBootstrap(promise, timeoutMs = 1500) {
		return new Promise((resolve) => {
			let settled = false;
			const finish = () => {
				if (settled) return;
				settled = true;
				clearTimeout(timer);
				resolve();
			};
			const timer = setTimeout(finish, timeoutMs);
			Promise.resolve(promise).then(finish, finish);
		});
	}

	withBootstrapTimeout(promise, timeoutMs = 15000, label = "Campaign workspace controls") {
		let timer;
		const timeout = new Promise((resolve, reject) => {
			timer = setTimeout(
				() => reject(new Error(label + " did not finish loading")),
				timeoutMs
			);
		});
		return Promise.race([Promise.resolve(promise), timeout]).finally(() => clearTimeout(timer));
	}

	async runBootstrapStep(label, callback) {
		try {
			return await this.withBootstrapTimeout(
				Promise.resolve().then(callback),
				10000,
				label
			);
		} catch (error) {
			const detail = error && error.message ? error.message : String(error || __("Unknown error"));
			throw new Error(label + ": " + detail);
		}
	}

	async setBootstrapFormValues(form, values) {
		for (const [fieldname, value] of Object.entries(values)) {
			await form.set_value(fieldname, value);
		}
	}

	loadBootstrap(routeState) {
		const route = typeof routeState === "string"
			? { campaign: routeState, key: "campaign:" + routeState + ":legacy" }
			: (routeState || { campaign: "", key: "new:direct" });
		const campaignName = route.campaign || "";
		const requestId = ++this.bootstrapRequest;
		this.routeKey = route.key;
		this.sourceCampaign = campaignName;
		this.updateCampaignNavigation();
		clearTimeout(this.previewTimer);
		this.previewTimer = null;
		this.previewRequest += 1;
		this.previewQueuedKey = null;
		this.previewInFlight = null;
		this.previewInFlightKey = null;
		this.templateStateRequest += 1;
		this.preview = null;
		this.previewFailed = false;
		this.routeLoading = true;
		this.page.btn_primary.add(this.page.btn_secondary).prop("disabled", true);
		this.$root.find("#ecs-launch-btn,#ecs-draft-btn,#ecs-test-btn,#ecs-email-preview-btn").prop("disabled", true);
		this.$root.attr("data-loading-label", __("Loading campaign workspace…")).addClass("ecs-route-loading");
		const previousApply = this.bootstrapApplyQueue;
		return frappe.call({
			method: this.method + "get_bootstrap",
			args: { campaign_name: campaignName },
		}).then((response) => {
			if (requestId !== this.bootstrapRequest || route.key !== this.routeKey) return null;
			const data = response.message || {};
			this.emailGroupOptions = data.email_groups || [];
			this.senderForm.get_field("email_account").set_data(data.email_accounts || []);
			this.defaultTestRecipient = data.default_test_recipient || "";
			const apply = this.waitForPreviousBootstrap(previousApply).then(() => {
				return this.filtersReady || Promise.resolve();
			}).then(() => {
				if (requestId !== this.bootstrapRequest || route.key !== this.routeKey) return null;
				const operation = data.campaign
					? this.applyCampaignData(data.campaign)
					: this.applyNewCampaignDefaults(data);
				return this.withBootstrapTimeout(operation, 30000);
			}).then(() => {
				if (requestId !== this.bootstrapRequest || route.key !== this.routeKey) return null;
				this.bootstrapLoaded = true;
				this.updateSummary();
				this.updateDeliveryCapacity();
				if (this.getFilters().length) this.queuePreview();
				return data;
			}).catch((error) => {
				if (requestId !== this.bootstrapRequest || route.key !== this.routeKey) return null;
				this.bootstrapLoaded = false;
				this.setEditableState(false, __("Load failed"));
				this.$root.find("#ecs-state-banner").addClass("visible").html(
					"<strong>" + __("Load failed") + "</strong><span>" +
					__("The campaign data could not be applied to the workspace. Reopen the Studio to retry safely.") +
					"</span>"
				);
				console.error("Email Campaign Studio bootstrap apply failed", error);
				const detail = error && error.message ? error.message : __("Unknown client error");
				frappe.msgprint({
					title: __("Campaign workspace could not be loaded"),
					message: __("The campaign data could not be applied.") + "<br><small>" +
						frappe.utils.escape_html(detail) + "</small>",
					indicator: "red",
				});
				return null;
			}).finally(() => {
				if (requestId !== this.bootstrapRequest || route.key !== this.routeKey) return;
				this.routeLoading = false;
				this.$root.removeClass("ecs-route-loading").removeAttr("data-loading-label");
				this.updateDeliveryCapacity();
			});
			this.bootstrapApplyQueue = apply;
			return apply;
		}, (error) => {
			if (requestId === this.bootstrapRequest && route.key === this.routeKey) {
				this.bootstrapLoaded = false;
				this.routeLoading = false;
				this.setEditableState(false, __("Load failed"));
				this.$root.removeClass("ecs-route-loading").removeAttr("data-loading-label");
				console.error("Email Campaign Studio bootstrap request failed", error);
				frappe.msgprint(__("The campaign workspace could not be loaded. Please reopen it from Campaign List."));
			}
			return null;
		});
	}

	async applyNewCampaignDefaults(data) {
		this.sourceCampaign = "";
		this.updateCampaignNavigation();
		this.presetFilters = null;
		this.$root.find("[data-audience-preset]").removeClass("active");
		this.applyingBootstrap = true;
		try {
			await this.runBootstrapStep(__("Preparing workspace controls"), () => this.setEditableState(true, "Draft"));
			await this.runBootstrapStep(__("Loading campaign segment"), () => this.setBootstrapFormValues(this.segmentForm, {
				segment_name: "",
			}));
			await this.runBootstrapStep(__("Loading campaign content"), () => this.setBootstrapFormValues(this.contentForm, {
				campaign_title: "",
				subscription_topic: "",
				email_template: "",
				subject_override: "",
			}));
			await this.runBootstrapStep(__("Loading sender identity"), () => this.setBootstrapFormValues(this.senderForm, {
				email_account: data.default_email_account || "",
				sender_name: "",
				reply_to: "",
			}));
			await this.runBootstrapStep(__("Loading delivery plan"), () => this.setBootstrapFormValues(this.scheduleForm, {
				start_date: data.start_date,
				start_time: data.start_time,
				batch_size: 100,
				repeat_every: 1,
				repeat_unit: "Hours",
				send_monday: 1,
				send_tuesday: 1,
				send_wednesday: 1,
				send_thursday: 1,
				send_friday: 1,
				send_saturday: 0,
				send_sunday: 0,
				restrict_sending_window: 0,
				window_start: "",
				window_end: "",
			}));
			await this.runBootstrapStep(__("Loading tracking settings"), () => this.setBootstrapFormValues(this.trackingForm, {
				enable_open_tracking: 1,
				enable_click_tracking: 1,
				utm_source: "newsletter",
				utm_medium: "email",
			}));
			await this.runBootstrapStep(__("Loading filters"), () => this.applyIncludeFilterGroups([]));
			await this.runBootstrapStep(__("Loading exclusions"), () => this.applyExcludeFilterGroups([]));
		} finally {
			this.applyingBootstrap = false;
		}
		this.preview = null;
		this.renderPreview(null);
		this.syncCustomControls();
		this.showTemplateState();
	}

	async applyCampaignData(campaign) {
		this.sourceCampaign = campaign.name || "";
		this.updateCampaignNavigation();
		const editable = Boolean(campaign.editable);
		const status = campaign.broadcast_status || "Draft";
		this.presetFilters = null;
		this.$root.find("[data-audience-preset]").removeClass("active");
		this.applyingBootstrap = true;
		try {
			await this.runBootstrapStep(__("Preparing workspace controls"), () => this.setEditableState(true, status));
			await this.runBootstrapStep(__("Loading campaign segment"), () => this.setBootstrapFormValues(this.segmentForm, {
				segment_name: campaign.segment_name || "",
			}));
			await this.runBootstrapStep(__("Loading campaign content"), () => this.setBootstrapFormValues(this.contentForm, {
				campaign_title: campaign.campaign_title || "",
				subscription_topic: campaign.subscription_topic || "",
				email_template: campaign.email_template || "",
				subject_override: campaign.subject_override || "",
			}));
			await this.runBootstrapStep(__("Loading sender identity"), () => this.setBootstrapFormValues(this.senderForm, {
				email_account: campaign.email_account || "",
				sender_name: campaign.sender_name || "",
				reply_to: campaign.reply_to || "",
			}));
			await this.runBootstrapStep(__("Loading delivery plan"), () => this.setBootstrapFormValues(this.scheduleForm, {
				start_date: campaign.start_date || frappe.datetime.get_today(),
				start_time: campaign.start_time || "09:00:00",
				batch_size: campaign.batch_size || 100,
				repeat_every: campaign.repeat_every || 1,
				repeat_unit: campaign.repeat_unit || "Hours",
				send_monday: campaign.send_monday,
				send_tuesday: campaign.send_tuesday,
				send_wednesday: campaign.send_wednesday,
				send_thursday: campaign.send_thursday,
				send_friday: campaign.send_friday,
				send_saturday: campaign.send_saturday,
				send_sunday: campaign.send_sunday,
				restrict_sending_window: campaign.restrict_sending_window || 0,
				window_start: campaign.window_start || "",
				window_end: campaign.window_end || "",
			}));
			await this.runBootstrapStep(__("Loading tracking settings"), () => this.setBootstrapFormValues(this.trackingForm, {
				enable_open_tracking: campaign.enable_open_tracking,
				enable_click_tracking: campaign.enable_click_tracking,
				utm_source: campaign.utm_source || "newsletter",
				utm_medium: campaign.utm_medium || "email",
			}));
			await this.runBootstrapStep(__("Loading filters"), () => this.applyIncludeFilterGroups(campaign.filters || []));
			await this.runBootstrapStep(__("Loading exclusions"), () => this.applyExcludeFilterGroups(campaign.exclude_filters || []));
			await this.runBootstrapStep(__("Freezing scheduled campaign controls"), () => this.setEditableState(editable, status));
		} finally {
			this.applyingBootstrap = false;
		}
		this.syncCustomControls();
		this.showTemplateState();
		frappe.show_alert({
			message: __("Loaded campaign {0}", [campaign.name]),
			indicator: "blue",
		}, 4);
	}

	setEditableState(editable, status) {
		this.editable = editable;
		this.$root.toggleClass("ecs-readonly", !editable);
		const $banner = this.$root.find("#ecs-state-banner");
		if (editable) {
			$banner.removeClass("visible").empty();
		} else {
			$banner.addClass("visible").html(
				"<strong>" + frappe.utils.escape_html(status) + "</strong><span>" +
				__("Audience, content and delivery settings were frozen when this campaign was scheduled. Use Campaign actions to pause, resume, cancel or retry without changing its audit history.") +
				"</span>"
			);
		}
		[this.segmentForm, this.contentForm, this.senderForm, this.scheduleForm, this.trackingForm]
			.filter(Boolean)
			.forEach((form) => (form.fields_list || []).forEach((field) => {
				if (!field.df.fieldname || ["HTML", "Section Break", "Column Break"].includes(field.df.fieldtype)) return;
				field.df.read_only = editable ? 0 : 1;
				field.refresh();
			}));
		this.page.btn_primary.toggle(editable);
		this.page.btn_secondary.toggle(editable);
		this.$root.find("#ecs-launch-btn,#ecs-draft-btn").toggle(editable);
	}

	applyFilters(filterGroup, filters) {
		if (!filterGroup) return Promise.resolve();
		filterGroup.clear_filters();
		filterGroup.toggle_empty_filters(!filters.length);
		if (!filters.length) return Promise.resolve();
		this.applyingAudiencePreset = true;
		return filterGroup.add_filters(filters).then(() => {
			filterGroup.toggle_empty_filters(false);
		}).finally(() => {
			this.applyingAudiencePreset = false;
		});
	}

	applyIncludeFilterGroups(groups) {
		this.$root.find("#ecs-filter-groups").empty();
		this.filterGroups = [];
		if (!groups || !groups.length) groups = [[]];
		return groups.reduce(
			(promise, group) => promise.then(() => this.addIncludeFilterGroup(group)),
			Promise.resolve()
		).then(() => this.updateFilterCount());
	}

	applyExcludeFilterGroups(groups) {
		this.$root.find("#ecs-exclude-filter-groups").empty();
		this.excludeFilterGroups = [];
		if (!groups || !groups.length) groups = [[]];
		return groups.reduce(
			(promise, group) => promise.then(() => this.addExcludeFilterGroup(group)),
			Promise.resolve()
		).then(() => this.updateFilterCount());
	}

	loadSegment(segmentName) {
		return frappe.call({
			method: "finbyzreach.segments.get_segment_filters",
			args: { segment_name: segmentName },
		}).then((response) => {
			const segment = response.message || {};
			this.presetFilters = null;
			this.activeStaticSegment = segment.segment_type === "Static";
			return this.applyIncludeFilterGroups(segment.filters || []).then(() => {
				return this.applyExcludeFilterGroups(segment.exclude_filters || []);
			}).then(() => {
				frappe.show_alert({
					message: __("Loaded {0} segment", [segment.segment_type || __("saved")]),
					indicator: "blue",
				}, 3);
				this.handleAudienceRuleChange(true);
			});
		}).finally(() => {
			this.applyingSegmentSelection = false;
		});
	}

	showSaveSegmentDialog() {
		const filters = this.getFilters();
		if (!filters.length) {
			frappe.msgprint(__("Add at least one include filter before saving a segment."));
			return;
		}
		const exclude_filters = this.getExcludeFilters();
		const exclude_email_groups = this.exclude_email_groups || [];

		const dialog = new frappe.ui.Dialog({
			title: __("Save Audience as Segment"),
			fields: [
				{
					fieldname: "segment_name",
					label: __("Segment Name"),
					fieldtype: "Data",
					reqd: 1,
				},
				{
					fieldname: "segment_type",
					label: __("Segment Type"),
					fieldtype: "Select",
					options: "Active\nStatic",
					default: "Active",
					description: __("Active evaluates rules when used. Static keeps the Leads matching these rules now."),
				},
			],
			primary_action_label: __("Save Segment"),
			primary_action: (values) => {
				dialog.get_primary_btn().prop("disabled", true);
				frappe.call({
					method: "finbyzreach.segments.create_segment",
					type: "POST",
					args: {
						segment_name: values.segment_name,
						segment_type: values.segment_type,
						filter_groups: JSON.stringify(filters),
						exclude_filters: JSON.stringify(exclude_filters),
						exclude_email_groups: JSON.stringify(exclude_email_groups),
					},
					freeze: true,
					freeze_message: __("Saving segment…"),
				}).then((response) => {
					const segment = response.message || {};
					dialog.hide();
					return this.segmentForm.set_value("segment_name", segment.name).then(() => {
						frappe.show_alert({ message: __("Segment saved"), indicator: "green" }, 4);
					});
				}).always(() => dialog.get_primary_btn().prop("disabled", false));
			},
		});
		dialog.show();
	}

	syncCustomControls() {
		this.setupScheduleDayPicker();
		this.setupOptionToggles();
		this.updateFilterCount();
		this.updateSummary();
	}

	getFilters() {
		if (this.presetFilters !== null) {
			return this.presetFilters.map((group) => group.map((filter) => filter.slice()));
		}
		const filters = (this.filterGroups || []).map((item) => item.filterGroup.get_filters()).filter((group) => group.length);
		if (!filters.length && this.activeStaticSegment) {
			const segmentName = this.segmentForm.get_value("segment_name");
			if (segmentName) {
				return [[["Lead", "name", "in", ["#STATIC_SEGMENT#", segmentName]]]];
			}
		}
		return filters;
	}

	getExcludeFilters() {
		return (this.excludeFilterGroups || []).map((item) => item.filterGroup.get_filters()).filter((group) => group.length);
	}

	getBlacklistValues() {
		return {
			exclude_filters: this.getExcludeFilters(),
			exclude_email_groups: this.exclude_email_groups || [],
		};
	}

	updateFilterCount() {
		const groups = this.getFilters();
		const count = groups.reduce((total, group) => total + group.length, 0);
		const excludeGroups = this.getExcludeFilters();
		const excludeCount = excludeGroups.reduce((total, group) => total + group.length, 0);
		const emailGroupCount = 0;
		const totalExclusions = excludeCount + emailGroupCount;
		const displayCount = this.activeStaticSegment ? 0 : count;
		this.$root.find("#ecs-filter-count").text(displayCount + " " + (displayCount === 1 ? __("filter") : __("filters")));
		this.$root.find("#ecs-exclude-filter-count").text(totalExclusions + " " + (totalExclusions === 1 ? __("rule") : __("rules")));
		const hasAudience = count > 0 || this.activeStaticSegment;
		this.$root.find("#ecs-preview-btn").prop("disabled", !hasAudience);
		this.$root.find("#ecs-health-btn").prop("disabled", !hasAudience);
		this.$root.find("#ecs-filter-builder").toggle(!this.activeStaticSegment);
		this.$root.find("#ecs-save-segment-btn").prop("disabled", this.activeStaticSegment);
		this.$root.find("#ecs-audience-state-dot").toggleClass("ready", hasAudience).removeClass("warn");
		let state = __("Choose a preset or add at least one include filter.");
		if (this.activeStaticSegment) {
			state = __("Targeting static segment. Visual filters are disabled for performance.");
		} else if (count && totalExclusions) {
			state = __("Ready to preview: {0} conditions in {1} OR group(s), plus {2} exclusions.", [count, groups.length, totalExclusions]);
		} else if (count) {
			state = __("Ready to preview. No optional exclusions are applied.");
		}
		this.$root.find("#ecs-audience-state-text").text(state);
	}


	getAudiencePreviewRequest(pagination) {
		const filters = this.getFilters();
		const segmentName = this.segmentForm ? (this.segmentForm.get_value("segment_name") || "") : "";
		const frozenCampaign = !this.editable && Boolean(this.sourceCampaign);
		if (!filters.length && !segmentName && !frozenCampaign) return null;
		const blacklist = this.getBlacklistValues();
		const pageState = pagination || {};
		const searchText = String(pageState.search_text ?? pageState.searchText ?? "").trim().slice(0, 140);
		const args = {
			filters: JSON.stringify(filters),
			segment_name: segmentName,
			exclude_filters: JSON.stringify(blacklist.exclude_filters),
			exclude_email_groups: JSON.stringify(blacklist.exclude_email_groups),
			subscription_topic: this.contentForm.get_value("subscription_topic"),
			eligible_page: Math.max(1, Number(pageState.page || pageState.eligible_page || 1) || 1),
			eligible_page_length: Math.max(1, Number(pageState.pageLength || pageState.eligible_page_length || 8) || 8),
			excluded_page: Math.max(1, Number(pageState.excluded_page || pageState.excludedPage || 1) || 1),
			search_text: searchText,
			campaign_name: this.editable ? "" : (this.sourceCampaign || ""),
		};
		return { args, key: JSON.stringify(args) };
	}

	queuePreview() {
		clearTimeout(this.previewTimer);
		this.previewTimer = null;
		const request = this.getAudiencePreviewRequest();
		if (!request) {
			this.previewRequest += 1;
			this.previewQueuedKey = null;
			this.preview = null;
			this.previewFailed = false;
			this.setPreviewLoading(false);
			this.updateSummary();
			this.renderPreview(null);
			return;
		}
		if (this.previewQueuedKey === request.key || this.previewInFlightKey === request.key) return;
		this.previewRequest += 1;
		this.preview = null;
		this.previewFailed = false;
		this.setPreviewLoading(false);
		this.updateSummary();
		this.renderPreviewPending();
		this.previewQueuedKey = request.key;
		this.previewTimer = setTimeout(() => {
			this.previewTimer = null;
			if (this.previewQueuedKey !== request.key) return;
			this.previewQueuedKey = null;
			this.previewAudience(true, null, request);
		}, 650);
	}

	previewAudience(silent, pagination, preparedRequest) {
		clearTimeout(this.previewTimer);
		this.previewTimer = null;
		this.previewQueuedKey = null;
		const request = preparedRequest || this.getAudiencePreviewRequest(pagination);
		if (!request) {
			this.previewRequest += 1;
			this.preview = null;
			this.previewFailed = false;
			this.setPreviewLoading(false);
			if (!silent) frappe.msgprint(__("Add at least one Lead filter or select a segment first."));
			this.renderPreview(null);
			return Promise.resolve(null);
		}
		if (this.previewInFlightKey === request.key && this.previewInFlight) return this.previewInFlight;
		const requestId = ++this.previewRequest;
		this.previewFailed = false;
		this.setPreviewLoading(true);
		const call = frappe.call({
			method: this.method + "preview_audience",
			type: "POST",
			args: request.args,
		}).then((response) => {
			if (requestId !== this.previewRequest) return null;
			this.preview = response.message;
			this.previewFailed = false;
			this.renderPreview(this.preview);
			this.updateSummary();
			return this.preview;
		}, () => {
			if (requestId !== this.previewRequest) return null;
			this.preview = null;
			this.previewFailed = true;
			this.renderPreviewError();
			this.updateSummary();
			return null;
		}).always(() => {
			if (requestId === this.previewRequest) this.setPreviewLoading(false);
			if (this.previewInFlightKey === request.key) {
				this.previewInFlight = null;
				this.previewInFlightKey = null;
			}
		});
		this.previewInFlight = call;
		this.previewInFlightKey = request.key;
		return call;
	}


	fetchAudienceHealth(pagination) {
		const request = this.getAudiencePreviewRequest(pagination);
		if (!request) {
			frappe.msgprint(__("Add at least one Lead filter or select a segment first."));
			return Promise.resolve(null);
		}
		const requestId = ++this.healthPreviewRequest;
		return frappe.call({
			method: this.method + "preview_audience",
			type: "POST",
			args: request.args,
		}).then((response) => {
			if (requestId !== this.healthPreviewRequest) return undefined;
			return response.message || {};
		}, () => {
			if (requestId !== this.healthPreviewRequest) return undefined;
			return null;
		});
	}

	setPreviewLoading(loading) {
		const hasAudience = Boolean(this.getAudiencePreviewRequest());
		this.$root.find("#ecs-preview-panel").toggleClass("ecs-loading", loading);
		this.$root.find("#ecs-preview-btn")
			.prop("disabled", loading || !hasAudience)
			.text(loading ? __("Calculating…") : __("Preview Audience"));
		this.$root.find("#ecs-health-btn")
			.prop("disabled", loading || !hasAudience)
			.text(loading ? __("Checking Audience…") : __("View Full Audience Health"));
		let status = hasAudience ? __("Ready to preview") : __("Waiting for filters");
		if (this.preview) {
			status = Number(this.preview.eligible_count) > 0 ? __("Audience ready") : __("No eligible recipients");
		} else if (this.previewFailed) {
			status = __("Preview failed");
		}
		this.$root.find("#ecs-preview-status").text(loading ? __("Calculating audience…") : status);
	}

	renderPreviewPending() {
		this.$root.find("#ecs-preview-dot").removeClass("ready warn");
		this.$root.find("#ecs-preview-status").text(__("Recalculating audience…"));
		this.$root.find("#ecs-preview-panel").html(
			"<div class='ecs-preview-empty'>" + __("Audience rules changed. A fresh eligibility check is being prepared.") + "</div>"
		);
	}

	renderPreviewError() {
		this.$root.find("#ecs-preview-dot").removeClass("ready").addClass("warn");
		this.$root.find("#ecs-preview-status").text(__("Preview failed"));
		this.$root.find("#ecs-preview-panel").html(
			"<div class='ecs-preview-empty'>" + __("The audience could not be calculated. Review the filters and try again.") + "</div>"
		);
	}

	renderPreview(data) {
		const $panel = this.$root.find("#ecs-preview-panel");
		const $dot = this.$root.find("#ecs-preview-dot");
		$dot.removeClass("ready warn");
		if (!data) {
			$panel.html("<div class='ecs-preview-empty'>" + __("Add Lead filters or select a segment, then preview the campaign audience.") + "</div>");
			this.$root.find("#ecs-preview-status").text(__("Waiting for filters"));
			this.updateFilterCount();
			return;
		}
		$dot.addClass(data.eligible_count ? "ready" : "warn");
		this.$root.find("#ecs-preview-status").text(data.eligible_count ? __("Audience ready") : __("No eligible recipients"));
		this.$root.find("#ecs-audience-state-dot").removeClass("ready warn").addClass(data.eligible_count ? "ready" : "warn");
		this.$root.find("#ecs-audience-state-text").text(
			data.eligible_count
				? (data.frozen
					? __("{0} recipients were frozen when this campaign was scheduled.", [data.eligible_count])
					: __("{0} of {1} candidates are eligible to receive this email.", [data.eligible_count, data.candidate_count]))
				: __("No eligible recipients remain after exclusions and compliance checks.")
		);
		const reasons = Object.entries(data.excluded_reasons || {}).map((entry) => {
			return "<div class='ecs-reason'><span>" + frappe.utils.escape_html(entry[0]) + "</span><strong>" + entry[1] + "</strong></div>";
		}).join("");
		$panel.html(
			"<div class='ecs-metrics'><div class='ecs-metric'><strong>" + data.candidate_count + "</strong><span>" + __("Candidates") + "</span></div><div class='ecs-metric eligible'><strong>" + data.eligible_count + "</strong><span>" + __("Eligible") + "</span></div><div class='ecs-metric excluded'><strong>" + data.excluded_count + "</strong><span>" + __("Excluded") + "</span></div></div>" +
				(reasons ? "<div class='ecs-reasons'>" + reasons + "</div>" : "")
		);
	}


	showAudienceHealth() {
		if (!this.getAudiencePreviewRequest()) {
			frappe.msgprint(__("Add at least one Lead filter or select a segment first."));
			return Promise.resolve(null);
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Audience Health"),
			size: "large",
			fields: [{ fieldname: "health_details", fieldtype: "HTML" }],
			primary_action_label: __("Close"),
			primary_action: () => dialog.hide(),
		});
		const $details = dialog.get_field("health_details").$wrapper;
		let currentPageLength = 10;
		let currentSearchText = "";
		let currentEligiblePage = 1;
		let currentExcludedPage = 1;
		let searchTimeout = null;
		let loadingTimeout = null;

		const pageLengthOptions = [10, 25, 50, 100, 500, 1000].map((option) => {
			return "<option value='" + option + "' " + (currentPageLength === option ? "selected" : "") + ">" + option + "</option>";
		}).join("");
		$details.html(
			"<div class='ecs-health-toolbar'>" +
				"<div class='ecs-health-search-wrap'><input type='search' class='form-control input-sm' id='ecs-health-search-input' autocomplete='off' placeholder='" + __("Search by lead, company, or email…") + "'><button type='button' class='btn btn-xs ecs-health-search-clear' data-health-search-clear aria-label='" + __("Clear search") + "'>×</button></div>" +
				"<label class='ecs-page-size'><span>" + __("Rows per page") + "</span><select class='form-control input-xs' data-health-page-length>" + pageLengthOptions + "</select></label>" +
			"</div>" +
			"<div class='ecs-health-results' id='ecs-health-results'><div class='ecs-preview-empty'>" + __("Checking the current audience…") + "</div></div>"
		);
		const $results = $details.find("#ecs-health-results");
		const $search = $details.find("#ecs-health-search-input");
		const $searchWrap = $details.find(".ecs-health-search-wrap");

		const syncSearchClear = () => {
			$searchWrap.toggleClass("has-value", Boolean(String($search.val() || "")));
		};
		const setLoading = (loading) => {
			$results.toggleClass("ecs-loading", loading);
			dialog.$wrapper.find("[data-health-page],[data-excluded-page],[data-health-page-length]").prop("disabled", loading);
		};
		const loadPage = () => {
			setLoading(true);
			if (loadingTimeout) clearTimeout(loadingTimeout);
			loadingTimeout = setTimeout(() => {
				if ($results.children().length) $results.css("opacity", "0.55");
			}, 250);

			return this.fetchAudienceHealth({
				page: currentEligiblePage,
				pageLength: currentPageLength,
				excluded_page: currentExcludedPage,
				search_text: currentSearchText,
			}).then((data) => {
				if (typeof data === "undefined") return;
				if (loadingTimeout) clearTimeout(loadingTimeout);
				$results.css("opacity", "");
				setLoading(false);
				if (!data) {
					$results.html("<div class='ecs-preview-empty'>" + __("Audience health could not be loaded. Please review the filters and try again.") + "</div>");
					return;
				}
				currentPageLength = Number(data.eligible_page_length || currentPageLength);
				currentEligiblePage = Number(data.eligible_page || currentEligiblePage);
				currentExcludedPage = Number(data.excluded_page || currentExcludedPage);
				$results.html(this.audienceHealthDetails(data, currentSearchText));
			});
		};

		dialog.$wrapper.on("click.ecs-health-page", "[data-health-page]", (event) => {
			if ($(event.currentTarget).prop("disabled")) return;
			const nextPage = Number($(event.currentTarget).data("health-page"));
			if (nextPage > 0) {
				currentEligiblePage = nextPage;
				loadPage();
			}
		});
		dialog.$wrapper.on("click.ecs-health-page", "[data-excluded-page]", (event) => {
			if ($(event.currentTarget).prop("disabled")) return;
			const nextPage = Number($(event.currentTarget).data("excluded-page"));
			if (nextPage > 0) {
				currentExcludedPage = nextPage;
				loadPage();
			}
		});
		dialog.$wrapper.on("change.ecs-health-page", "[data-health-page-length]", (event) => {
			currentPageLength = Math.max(1, Number($(event.currentTarget).val()) || 10);
			currentEligiblePage = 1;
			currentExcludedPage = 1;
			loadPage();
		});
		dialog.$wrapper.on("input.ecs-health-page", "#ecs-health-search-input", () => {
			syncSearchClear();
			if (searchTimeout) clearTimeout(searchTimeout);
			searchTimeout = setTimeout(() => {
				currentSearchText = String($search.val() || "").trim().slice(0, 140);
				currentEligiblePage = 1;
				currentExcludedPage = 1;
				loadPage();
			}, 350);
		});
		dialog.$wrapper.on("click.ecs-health-page", "[data-health-search-clear]", () => {
			if (searchTimeout) clearTimeout(searchTimeout);
			$search.val("");
			currentSearchText = "";
			currentEligiblePage = 1;
			currentExcludedPage = 1;
			syncSearchClear();
			$search.trigger("focus");
			loadPage();
		});
		dialog.$wrapper.on("hidden.bs.modal", () => {
			if (searchTimeout) clearTimeout(searchTimeout);
			if (loadingTimeout) clearTimeout(loadingTimeout);
			this.healthPreviewRequest += 1;
			dialog.$wrapper.off(".ecs-health-page");
		});

		dialog.show();
		syncSearchClear();
		return loadPage();
	}

	audienceHealthDetails(data, currentSearchText = "") {
		const escape = (value) => frappe.utils.escape_html(String(value || ""));
		const searchText = String(currentSearchText || "").trim();
		const filterNote = searchText
			? "<div class='ecs-health-filter-note'><span>" + __("Filtered audience results") + "</span><strong title='" + escape(searchText) + "'>“" + escape(searchText) + "”</strong></div>"
			: "";
		const metricHtml =
			"<div class='ecs-metrics'><div class='ecs-metric'><strong>" + Number(data.candidate_count || 0) + "</strong><span>" + __("Candidates") + "</span></div><div class='ecs-metric eligible'><strong>" + Number(data.eligible_count || 0) + "</strong><span>" + __("Eligible") + "</span></div><div class='ecs-metric excluded'><strong>" + Number(data.excluded_count || 0) + "</strong><span>" + __("Excluded") + "</span></div></div>";
		const reasonRows = Object.entries(data.excluded_reasons || {}).map(([reason, count]) => {
			return "<div class='ecs-health-row'><strong>" + escape(reason) + "</strong><small>" + Number(count || 0) + " " + __("Leads") + "</small></div>";
		}).join("");
		const reasons = "<section class='ecs-health-section'><div class='ecs-health-section-head'><h4>" + __("Exclusion breakdown") + "</h4><span>" + Number(data.excluded_count || 0) + " " + __("excluded") + "</span></div><div class='ecs-health-list'>" + (reasonRows || "<div class='ecs-health-empty'>" + (searchText ? __("No exclusion reasons match this search.") : __("No compliance or blacklist exclusions were found.")) + "</div>") + "</div></section>";
		const recipientRows = (data.eligible_samples || []).map((row) => {
			const route = "/app/lead/" + encodeURIComponent(row.name);
			const label = escape(row.lead_name || row.name);
			const company = escape(row.company_name || "");
			const email = escape(row.email_id || "");
			return "<a class='ecs-health-row' href='" + route + "'><span><strong>" + label + "</strong>" + (company ? "<small style='text-align:left'>" + company + "</small>" : "") + "</span><small title='" + email + "'>" + (email || "—") + "</small></a>";
		}).join("");
		const currentPage = Number(data.eligible_page || 1);
		const totalPages = Number(data.eligible_total_pages || 0);
		const pageLength = Number(data.eligible_page_length || 10);
		const eligibleCount = Number(data.eligible_count || 0);
		const firstResult = eligibleCount ? ((currentPage - 1) * pageLength) + 1 : 0;
		const lastResult = Math.min(currentPage * pageLength, eligibleCount);
		const pagination = eligibleCount
			? "<div class='ecs-health-pagination'><span>" + __("Showing {0}–{1} of {2}", [firstResult, lastResult, eligibleCount]) + "</span><div><button type='button' class='btn btn-default btn-sm' data-health-page='" + (currentPage - 1) + "' " + (currentPage <= 1 ? "disabled" : "") + ">" + __("Previous") + "</button><strong>" + __("Page {0} of {1}", [currentPage, Math.max(totalPages, 1)]) + "</strong><button type='button' class='btn btn-default btn-sm' data-health-page='" + (currentPage + 1) + "' " + (currentPage >= totalPages ? "disabled" : "") + ">" + __("Next") + "</button></div></div>"
			: "";
		const recipients = "<section class='ecs-health-section'><div class='ecs-health-section-head'><h4>" + __("Eligible recipients") + "</h4><span>" + eligibleCount + " " + __("eligible") + "</span></div><div class='ecs-health-list'>" + (recipientRows || "<div class='ecs-health-empty'>" + (searchText ? __("No eligible recipients match this search.") : __("No eligible recipients are available.")) + "</div>") + "</div>" + pagination + "</section>";

		const excludedRows = (data.excluded_samples || []).map((row) => {
			const route = "/app/lead/" + encodeURIComponent(row.name);
			const label = escape(row.lead_name || row.name);
			const company = escape(row.company_name || "");
			const email = escape(row.email_id || "");
			const reason = escape(row.reason || __("Excluded by audience rules"));
			return "<a class='ecs-health-row' href='" + route + "'><span><strong>" + label + "</strong>" + (company ? "<small style='text-align:left'>" + company + "</small>" : "") + "<small style='text-align:left'>" + reason + "</small></span><small title='" + email + "'>" + (email || "—") + "</small></a>";
		}).join("");
		const currentExcludedPage = Number(data.excluded_page || 1);
		const totalExcludedPages = Number(data.excluded_total_pages || 0);
		const excludedCount = Number(data.excluded_count || 0);
		const firstExcludedResult = excludedCount ? ((currentExcludedPage - 1) * pageLength) + 1 : 0;
		const lastExcludedResult = Math.min(currentExcludedPage * pageLength, excludedCount);
		const excludedPagination = excludedCount
			? "<div class='ecs-health-pagination'><span>" + __("Showing {0}–{1} of {2}", [firstExcludedResult, lastExcludedResult, excludedCount]) + "</span><div><button type='button' class='btn btn-default btn-sm' data-excluded-page='" + (currentExcludedPage - 1) + "' " + (currentExcludedPage <= 1 ? "disabled" : "") + ">" + __("Previous") + "</button><strong>" + __("Page {0} of {1}", [currentExcludedPage, Math.max(totalExcludedPages, 1)]) + "</strong><button type='button' class='btn btn-default btn-sm' data-excluded-page='" + (currentExcludedPage + 1) + "' " + (currentExcludedPage >= totalExcludedPages ? "disabled" : "") + ">" + __("Next") + "</button></div></div>"
			: "";
		const excludedRecipients = (excludedCount || searchText)
			? "<section class='ecs-health-section'><div class='ecs-health-section-head'><h4>" + __("Excluded recipients") + "</h4><span>" + excludedCount + " " + __("excluded") + "</span></div><div class='ecs-health-list'>" + (excludedRows || "<div class='ecs-health-empty'>" + __("No excluded recipients match this search.") + "</div>") + "</div>" + excludedPagination + "</section>"
			: "";
		const topicCount = Number(data.topic_unsubscribed_count || 0);
		const topicRows = (data.topic_unsubscribed_samples || []).map((row) => {
			const route = "/app/lead/" + encodeURIComponent(row.name);
			const label = escape(row.lead_name || row.name);
			const email = escape(row.email_id || "");
			return "<a class='ecs-health-row' href='" + route + "'><strong>" + label + "</strong><small title='" + email + "'>" + (email || "—") + "</small></a>";
		}).join("");
		const topicMore = Number(data.topic_unsubscribed_more || 0);
		const topicSection = topicCount
			? "<section class='ecs-health-section'><div class='ecs-health-section-head'><h4>" + __("Topic unsubscribes") + "</h4><span>" + topicCount + " · " + escape(data.subscription_topic) + "</span></div><div class='ecs-health-list'>" + topicRows + (topicMore ? "<div class='ecs-health-empty'>+ " + topicMore + " " + __("more Leads") + "</div>" : "") + "</div></section>"
			: "";
		return "<div class='ecs-health-dialog'>" + filterNote + metricHtml + reasons + topicSection + recipients + excludedRecipients + "</div>";
	}

	formValues(form, validateRequired) {
		if (validateRequired) return form.get_values();
		return (form.fields_list || []).reduce((values, field) => {
			if (field.df.fieldname && !["HTML", "Section Break", "Column Break"].includes(field.df.fieldtype)) {
				values[field.df.fieldname] = form.get_value(field.df.fieldname);
			}
			return values;
		}, {});
	}

	collectPayload(requireReady = true, requireTitle = true) {
		const content = this.formValues(this.contentForm, requireReady);
		const sender = this.formValues(this.senderForm, requireReady);
		const schedule = this.formValues(this.scheduleForm, requireReady);
		const tracking = this.formValues(this.trackingForm, requireReady);
		if (!content || !sender || !schedule || !tracking) return null;
		if (requireTitle && !String(content.campaign_title || "").trim()) {
			frappe.msgprint(__("Give the draft a Campaign Title before saving."));
			return null;
		}
		const filters = this.getFilters();
		if (requireReady && !filters.length) {
			frappe.msgprint(__("Add at least one Lead filter before continuing."));
			return null;
		}
		return Object.assign({}, content, sender, schedule, tracking, this.getBlacklistValues(), {
			filters: filters,
			segment_name: this.segmentForm ? (this.segmentForm.get_value("segment_name") || "") : "",
			source_campaign: this.sourceCampaign || "",
		});
	}

	estimateBatchCount(recipientCount, batchSize) {
		const recipients = Math.max(0, Number(recipientCount) || 0);
		const batch = Math.max(1, Number(batchSize) || 1);
		return recipients ? Math.ceil(recipients / batch) : 0;
	}

	updateSummary() {
		const title = this.contentForm ? this.contentForm.get_value("campaign_title") : "";
		const template = this.contentForm ? this.contentForm.get_value("email_template") : "";
		const topic = this.contentForm ? this.contentForm.get_value("subscription_topic") : "";
		const account = this.senderForm ? this.senderForm.get_value("email_account") : "";
		const date = this.scheduleForm ? this.scheduleForm.get_value("start_date") : "";
		const time = this.scheduleForm ? this.scheduleForm.get_value("start_time") : "";
		const batchSize = Number(this.scheduleForm ? this.scheduleForm.get_value("batch_size") : 100) || 100;
		const eligible = this.preview ? this.preview.eligible_count : 0;
		const batches = this.estimateBatchCount(eligible, batchSize);
		const rows = [
			[__("Campaign"), title || __("Not named")],
			[__("Template"), template || __("Not selected")],
			[__("Topic"), topic || __("Not selected")],
			[__("Sender"), account || __("Not selected")],
			[__("Audience"), this.preview ? eligible + " " + __("eligible") : __("Not previewed")],
			[__("Batches"), batches || "—"],
			[__("Starts"), date && time ? date + " " + time : __("Not set")],
		];
		this.$root.find("#ecs-summary-rows").html(rows.map((row) => {
			return "<div class='ecs-summary-row'><span>" + row[0] + "</span><strong>" + frappe.utils.escape_html(String(row[1])) + "</strong></div>";
		}).join(""));
		this.updateDeliveryCapacity();
		this.updateProgress();
	}

	updateDeliveryCapacity() {
		if (!this.scheduleForm) return;
		const batchSize = Number(this.scheduleForm.get_value("batch_size") || 0);
		const repeatEvery = Number(this.scheduleForm.get_value("repeat_every") || 0);
		const repeatUnit = this.scheduleForm.get_value("repeat_unit") || "Hours";
		const unitMinutes = { Minutes: 1, Hours: 60, Days: 1440 }[repeatUnit];
		const intervalMinutes = repeatEvery * (unitMinutes || 0);
		const eligible = Number(this.preview && this.preview.eligible_count || 0);
		const batches = batchSize > 0 && eligible ? this.estimateBatchCount(eligible, batchSize) : 0;
		const validBatch = Number.isInteger(batchSize) && batchSize > 0;
		const validInterval = Number.isInteger(repeatEvery) && repeatEvery > 0 && Boolean(unitMinutes);
		this.deliveryPlanValid = validBatch && validInterval;

		let tone = "";
		let heading = __("Delivery plan");
		let message;
		if (!validBatch) {
			tone = "danger";
			message = __("Emails per Batch must be a whole number greater than zero.");
		} else if (!validInterval) {
			tone = "danger";
			message = __("Repeat Every must be a whole number greater than zero and use Minutes, Hours, or Days.");
		} else {
			const rate = intervalMinutes > 0 ? batchSize / intervalMinutes : 0;
			const plan = batches
				? (batches === 1 ? __("1 batch") : __("{0} batches", [batches]))
				: __("preview the audience to calculate batches");
			message = __("{0} · planned average {1} emails/minute. No application-level maximum batch, per-minute rate, pending-queue cap, or daily campaign cap is enforced. Frappe Email Queue and your email provider still control actual sending throughput.", [plan, rate.toFixed(2)]);
		}
		const field = this.scheduleForm.get_field("capacity_note");
		if (field) {
			field.html("<div class='ecs-capacity-note " + tone + "'><span><strong>" + heading + "</strong><br>" + frappe.utils.escape_html(message) + "</span></div>");
		}
		this.$root.find("#ecs-launch-btn").prop("disabled", this.busy || this.routeLoading || !this.deliveryPlanValid);
		this.$root.find("#ecs-draft-btn,#ecs-test-btn,#ecs-email-preview-btn").prop("disabled", this.busy || this.routeLoading);
		this.page.btn_primary.prop("disabled", this.busy || this.routeLoading || !this.deliveryPlanValid);
		this.page.btn_secondary.prop("disabled", this.busy || this.routeLoading);
	}
	updateProgress() {
		if (!this.contentForm || !this.senderForm || !this.scheduleForm || !this.trackingForm) return;
		const hasSendingDay = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
			.some((day) => Boolean(Number(this.scheduleForm.get_value("send_" + day))));
		const readyByStep = {
			1: Boolean(this.preview && this.preview.eligible_count),
			2: Boolean(this.contentForm.get_value("campaign_title") && this.contentForm.get_value("email_template") && this.contentForm.get_value("subscription_topic")),
			3: Boolean(this.senderForm.get_value("email_account")),
			4: Boolean(this.scheduleForm.get_value("start_date") && this.scheduleForm.get_value("start_time") && this.scheduleForm.get_value("batch_size") && this.scheduleForm.get_value("repeat_every") && this.scheduleForm.get_value("repeat_unit") && hasSendingDay && (!Number(this.scheduleForm.get_value("restrict_sending_window")) || (this.scheduleForm.get_value("window_start") && this.scheduleForm.get_value("window_end")))),
			5: Boolean(this.trackingForm.get_value("utm_source") && this.trackingForm.get_value("utm_medium")),
		};
		let priorStepsComplete = true;
		let currentStep = null;
		Object.entries(readyByStep).forEach(([step, ready]) => {
			const complete = priorStepsComplete && ready;
			if (!complete && currentStep === null) currentStep = step;
			priorStepsComplete = complete;
			this.$root.find(`[data-scroll-step="${step}"]`).toggleClass("complete", complete);
			this.$root.find(`#ecs-step-${step}`).toggleClass("complete", complete);
		});
		this.$root.find("[data-scroll-step]").removeClass("current").removeAttr("aria-current");
		this.$root.find(".ecs-card[data-step]").removeClass("current");
		if (currentStep !== null) {
			this.$root.find(`[data-scroll-step="${currentStep}"]`).addClass("current").attr("aria-current", "step");
			this.$root.find(`#ecs-step-${currentStep}`).addClass("current");
		}
	}

	showTemplateState() {
		const template = this.contentForm.get_value("email_template");
		const field = this.contentForm.get_field("template_state");
		const requestId = ++this.templateStateRequest;
		if (!template) {
			field.html("");
			return;
		}
		frappe.db.get_value("Email Template", template, ["custom_builder_mode", "custom_preheader_text"]).then((response) => {
			if (requestId !== this.templateStateRequest || template !== this.contentForm.get_value("email_template")) return;
			const values = response.message || {};
			const mode = values.custom_builder_mode || "Standard";
			field.html("<div class='alert alert-light border small mb-0'><strong>" + frappe.utils.escape_html(mode) + "</strong> · " + (values.custom_preheader_text ? frappe.utils.escape_html(values.custom_preheader_text) : __("Template is ready for Lead personalization")) + "</div>");
		});
	}

	reviewAndSchedule() {
		if (this.reviewPending || this.busy) return;
		const payload = this.collectPayload();
		if (!payload) return;
		this.reviewPending = true;
		const resetReview = () => {
			this.reviewPending = false;
		};
		const proceed = (preview, currentPayload) => {
			const count = Number(preview && preview.eligible_count) || 0;
			if (!count) {
				resetReview();
				frappe.msgprint(__("No eligible recipients remain after exclusions and compliance checks."));
				return;
			}
			const batches = this.estimateBatchCount(count, Number(currentPayload.batch_size) || 100);
			return frappe.confirm(
				__("Schedule this campaign for {0} eligible recipients in approximately {1} batches?", [count, batches]),
				() => {
					resetReview();
					this.createCampaign("schedule", currentPayload);
				},
				resetReview
			);
		};
		return this.previewAudience().then((data) => {
			if (!data) {
				resetReview();
				return;
			}
			const currentPayload = this.collectPayload();
			if (!currentPayload) {
				resetReview();
				return;
			}
			this.updateDeliveryCapacity();
			if (!this.deliveryPlanValid) {
				resetReview();
				frappe.msgprint(__("Fix the delivery plan fields before scheduling this campaign."));
				return;
			}
			return proceed(data, currentPayload);
		});
	}

	createCampaign(mode, preparedPayload) {
		if (this.busy || this.routeLoading) return Promise.resolve(null);
		if (!this.editable) {
			frappe.msgprint(__("Scheduled campaigns are immutable. Use Campaign actions for delivery controls."));
			return Promise.resolve(null);
		}
		const payload = preparedPayload || this.collectPayload(mode !== "draft");
		if (!payload) return;
		this.setBusy(true);
		return frappe.call({
			method: this.method + "create_campaign",
			type: "POST",
			args: { payload: JSON.stringify(payload), launch: mode },
			freeze: true,
			freeze_message: mode === "schedule" ? __("Freezing audience and building batches…") : __("Saving campaign draft…"),
		}).then((response) => {
			const result = response.message || {};
			if (!result.campaign) {
				frappe.throw(__("Campaign was saved, but the server did not return its document name."));
			}
			this.sourceCampaign = result.campaign;
			this.updateCampaignNavigation();
			this.preview = result.preview || this.preview;
			frappe.show_alert({
				message: mode === "schedule"
					? __("Campaign scheduled successfully")
					: (result.created ? __("Campaign draft created") : __("Campaign draft saved")),
				indicator: "green",
			}, 6);
			if (mode === "draft") {
				this.rememberCampaignInStudio(result.campaign);
				this.updateSummary();
				return result;
			}
			this.rememberCampaignInStudio(result.campaign);
			this.setEditableState(false, result.status || __("Scheduled"));
			this.updateSummary();
			this.updateDeliveryCapacity();
			return result;
		}).always(() => this.setBusy(false));
	}

	rememberCampaignInStudio(campaign) {
		frappe.route_options = {};
		const params = new URLSearchParams(window.location.search || "");
		const session = params.get("studio_session") || params.get("new") ||
			(Date.now().toString(36) + Math.random().toString(36).slice(2, 8));
		const path = "/desk/email-campaign-studio?studio_campaign=" + encodeURIComponent(campaign) +
			"&studio_session=" + encodeURIComponent(session);
		window.history.replaceState(window.history.state, "", path);
		this.routeKey = "campaign:" + campaign + ":" + session;
	}

	openCampaign(result) {
		const campaign = result && result.campaign;
		if (!campaign) {
			frappe.msgprint(__("Campaign was saved, but the server did not return a Campaign name. Open it from Campaign List."));
			return Promise.resolve();
		}
		frappe.route_options = {};
		return frappe.set_route(["Form", "Campaign", campaign]);
	}

	showEmailPreviewDialog() {
		const payload = this.collectPayload(false, false);
		if (!payload) return;
		if (this.editable && !payload.email_template) {
			frappe.msgprint(__("Select an Email Template before opening the preview."));
			return;
		}
		const previewLead = this.preview && this.preview.eligible_samples && this.preview.eligible_samples[0];
		const dialog = new frappe.ui.Dialog({
			title: __("Email Preview"),
			size: "extra-large",
			fields: [
				{
					fieldname: "sample_lead",
					label: __("Personalize Using Lead"),
					fieldtype: "Link",
					options: "Lead",
					reqd: 1,
					default: previewLead && previewLead.name || "",
					description: __("Preview only: no email is queued or sent."),
				},
				{ fieldname: "preview_html", fieldtype: "HTML" },
			],
			primary_action_label: __("Render Preview"),
			primary_action: (values) => {
				const $button = dialog.get_primary_btn();
				$button.prop("disabled", true);
				const $preview = dialog.get_field("preview_html").$wrapper;
				$preview.html("<div class='ecs-preview-empty'>" + __("Rendering personalized email…") + "</div>");
				frappe.call({
					method: this.method + "preview_email",
					type: "POST",
					args: {
						payload: JSON.stringify(payload),
						sample_lead: values.sample_lead,
					},
				}).then((response) => {
					const data = response.message || {};
					const frozenLabel = data.frozen ? __("Frozen scheduled content") : __("Current draft content");
					$preview.html(
						"<div class='ecs-email-preview'>" +
						"<div class='ecs-email-preview-meta'><span>" + __("Subject") + "</span><strong>" + frappe.utils.escape_html(data.subject || "") + "</strong><span>" + __("Preheader") + "</span><strong>" + frappe.utils.escape_html(data.preheader || __("Not set")) + "</strong><span>" + __("Preview data") + "</span><strong>" + frappe.utils.escape_html((data.sample_lead_label || data.sample_lead || "") + " · " + frozenLabel) + "</strong></div>" +
						"<div class='ecs-email-preview-toolbar'><small>" + __("Links include final UTM values; previewing never records opens or clicks.") + "</small><div><button type='button' class='btn btn-default btn-sm active' data-email-viewport='desktop'>" + __("Desktop") + "</button> <button type='button' class='btn btn-default btn-sm' data-email-viewport='mobile'>" + __("Mobile") + "</button></div></div>" +
						"<div class='ecs-email-preview-stage'><iframe class='ecs-email-preview-frame' title='" + __("Rendered email preview") + "' sandbox='allow-popups'></iframe></div></div>"
					);
					$preview.find(".ecs-email-preview-frame")[0].srcdoc = data.html || "";
				}).always(() => $button.prop("disabled", false));
			},
		});
		dialog.$wrapper.on("click.ecs-email-viewport", "[data-email-viewport]", (event) => {
			const viewport = $(event.currentTarget).data("email-viewport");
			dialog.$wrapper.find("[data-email-viewport]").removeClass("active");
			$(event.currentTarget).addClass("active");
			dialog.$wrapper.find(".ecs-email-preview-frame").toggleClass("mobile", viewport === "mobile");
		});
		dialog.$wrapper.on("hidden.bs.modal", () => dialog.$wrapper.off(".ecs-email-viewport"));
		dialog.show();
	}

	showTestDialog() {
		const payload = this.collectPayload();
		if (!payload) return;
		const dialog = new frappe.ui.Dialog({
			title: __("Send Campaign Test"),
			fields: [
				{ fieldname: "recipient", label: __("Test Recipient"), fieldtype: "Data", options: "Email", reqd: 1, default: this.defaultTestRecipient },
				{ fieldname: "sample_lead", label: __("Personalize Using Lead"), fieldtype: "Link", options: "Lead", reqd: 1 },
			],
			primary_action_label: __("Queue Test"),
			primary_action: (values) => {
				dialog.get_primary_btn().prop("disabled", true);
				frappe.call({
					method: this.method + "send_test",
					type: "POST",
					args: {
						payload: JSON.stringify(payload),
						recipient: values.recipient,
						sample_lead: values.sample_lead,
					},
				}).then(() => {
					dialog.hide();
					frappe.show_alert({ message: __("Test email queued"), indicator: "green" });
				}).always(() => dialog.get_primary_btn().prop("disabled", false));
			},
		});
		dialog.show();
	}

	setBusy(busy) {
		this.busy = busy;
		this.$root.find("#ecs-launch-btn,#ecs-draft-btn,#ecs-test-btn,#ecs-email-preview-btn").prop("disabled", busy);
		this.page.btn_primary.add(this.page.btn_secondary).prop("disabled", busy);
		this.updateDeliveryCapacity();
	}
}
