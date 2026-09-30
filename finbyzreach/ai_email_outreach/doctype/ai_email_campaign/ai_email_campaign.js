// Copyright (c) 2026, Finbyz and contributors
// For license information, please see license.txt

const SEL = "finbyzreach.ai_email_outreach.campaign_selection";
const PROM = "finbyzreach.ai_email_outreach.campaign_promotion";

function show_counts(frm) {
	frappe.call({
		method: `${SEL}.candidate_counts`,
		args: { campaign_name: frm.doc.name },
	}).then((r) => {
		const counts = r.message || {};
		if (frm.dashboard.clear_indicators) frm.dashboard.clear_indicators();
		const colour = {
			Suggested: "orange", Approved: "blue", Promoted: "green",
			Rejected: "gray", Skipped: "gray",
		};
		Object.keys(colour).forEach((status) => {
			if (counts[status])
				frm.dashboard.add_indicator(`${__(status)}: ${counts[status]}`, colour[status]);
		});
	});
}

function render_progress(frm, data) {
	if (!frm) return;

	const title = data.title || (data.step === "scoring" ? __("AI Relevance Scoring") : __("Finding Project Candidates"));

	// 1. Native Frappe modal progress dialog
	if (data.step === "completed") {
		frappe.hide_progress();
	} else if (data.step === "failed") {
		frappe.hide_progress();
	} else {
		frappe.show_progress(
			title,
			data.completed || data.percent || 1,
			data.total || 100,
			data.message || ""
		);
	}

	// 2. In-page Dashboard banner
	let $target = (frm.dashboard && frm.dashboard.wrapper && frm.dashboard.wrapper.length)
		? frm.dashboard.wrapper
		: frm.page.main;
	let $wrapper = $target.find(".campaign-live-progress");

	if (!$wrapper.length) {
		$wrapper = $(`
			<div class="campaign-live-progress" style="margin: 12px 0; padding: 14px 18px; border-radius: 8px; border: 1px solid var(--border-color, #d1d5db); background: var(--fg-color, #ffffff); box-shadow: var(--shadow-sm, 0 1px 2px 0 rgba(0, 0, 0, 0.05)); z-index: 10;">
				<div class="d-flex align-items-center justify-content-between mb-2">
					<div class="d-flex align-items-center">
						<span class="progress-status-icon spinner-border spinner-border-sm text-primary mr-2" role="status" style="width: 14px; height: 14px;"></span>
						<strong class="progress-title" style="font-size: 13px; color: var(--text-color, #1f2937);">${title}</strong>
					</div>
					<span class="progress-percent badge badge-primary font-weight-bold" style="font-size: 12px; border-radius: 12px; padding: 3px 9px;">0%</span>
				</div>
				<div class="progress" style="height: 7px; border-radius: 4px; background: var(--bg-light-gray, #e5e7eb); overflow: hidden; margin-bottom: 8px;">
					<div class="progress-bar progress-bar-striped progress-bar-animated bg-primary" role="progressbar" style="width: 0%; transition: width 0.3s ease;"></div>
				</div>
				<div class="progress-msg text-muted" style="font-size: 12px;">${__("Starting process…")}</div>
			</div>
		`).prependTo($target);
	}

	if (data.step === "completed") {
		$wrapper.find(".progress-status-icon")
			.removeClass("spinner-border spinner-border-sm text-primary")
			.addClass("fa fa-check text-success font-weight-bold mr-2");
		$wrapper.find(".progress-bar")
			.removeClass("progress-bar-striped progress-bar-animated bg-primary")
			.addClass("bg-success")
			.css("width", "100%");
		$wrapper.find(".progress-percent")
			.removeClass("badge-primary")
			.addClass("badge-success")
			.text("100%");
		$wrapper.find(".progress-title").text(__("Process Completed"));
		$wrapper.find(".progress-msg").text(data.message || __("All done."));

		show_counts(frm);
		frappe.show_alert({ message: data.message || __("Done"), indicator: "green" });

		// Smoothly fade out after 6 seconds
		setTimeout(() => {
			if ($wrapper.length) {
				$wrapper.slideUp(400, () => $wrapper.remove());
			}
		}, 6000);
		return;
	}

	if (data.step === "failed") {
		$wrapper.find(".progress-status-icon")
			.removeClass("spinner-border spinner-border-sm text-primary")
			.addClass("fa fa-times text-danger font-weight-bold mr-2");
		$wrapper.find(".progress-bar")
			.removeClass("progress-bar-striped progress-bar-animated bg-primary")
			.addClass("bg-danger");
		$wrapper.find(".progress-percent")
			.removeClass("badge-primary")
			.addClass("badge-danger")
			.text(__("Failed"));
		$wrapper.find(".progress-title").text(__("Process Failed"));
		$wrapper.find(".progress-msg").text(data.message || __("Error occurred."));
		frappe.show_alert({ message: data.message || __("Failed"), indicator: "red" });
		return;
	}

	// Ongoing steps: finding / scoring
	$wrapper.find(".progress-title").text(title);
	$wrapper.find(".progress-bar").css("width", `${data.percent || 0}%`);

	const counter = (data.total > 0) ? ` (${data.completed}/${data.total})` : "";
	$wrapper.find(".progress-percent").text(`${data.percent || 0}%${counter}`);
	$wrapper.find(".progress-msg").text(data.message || "");
}

function run(frm, method, args, label) {
	return frm
		.call({ method, args, freeze: false })
		.then((r) => {
			const res = r.message || {};
			if (res.ok === false) {
				frappe.msgprint({
					title: __("Did not complete"),
					indicator: "red",
					message: res.message || __("Failed to start."),
				});
			} else {
				frappe.show_alert({
					message: res.message || __("Started in background…"),
					indicator: "blue",
				});
			}
		});
}

frappe.ui.form.on("AI Email Campaign", {
	refresh(frm) {
		if (frm.is_new()) return;
		show_counts(frm);

		// Listen to realtime candidate discovery & AI scoring events
		frappe.realtime.off("campaign_candidate_progress");
		frappe.realtime.on("campaign_candidate_progress", (data) => {
			if (!data || data.campaign_name !== frm.doc.name) return;
			render_progress(frm, data);
		});

		frm.add_custom_button(__("Find Candidates"), () => {
			if (!frm.doc.description) {
				frappe.msgprint(__("Add a campaign description first — the AI scores against it."));
				return;
			}
			frappe.confirm(
				__("Find everyone the criteria match and score them against the brief?<br><br>Nothing is contacted — candidates are stored for review."),
				() => run(frm, `${SEL}.build_candidates`,
					{ campaign_name: frm.doc.name, score_with_ai: 1 },
					__("Finding candidates…"))
			);
		}, __("Candidates"));

		frm.add_custom_button(__("Score Again"), () =>
			run(frm, `${SEL}.trigger_scoring`, { campaign_name: frm.doc.name, force: 1 }, __("Starting scoring…")),
			__("Candidates"));

		frm.add_custom_button(__("Review Candidates"), () =>
			frappe.set_route("List", "Campaign Candidate", {
				ai_email_campaign: frm.doc.name, status: "Suggested",
			}), __("Candidates"));

		frm.add_custom_button(__("Promote Approved"), () => {
			frappe.confirm(
				__("Turn every approved candidate into a Lead and start their outreach?<br><br>In <b>Review Before Sending</b> mode the emails are still held for approval."),
				() => run(frm, `${PROM}.promote`, { campaign_name: frm.doc.name }, __("Promoting…"))
			);
		}, __("Candidates")).addClass("btn-primary");

		if (frm.doc.approval_mode === "Send Automatically") {
			frm.dashboard.set_headline_alert(
				__("This campaign sends without review. Approved candidates will be emailed automatically."),
				"orange"
			);
		}
	},
});
