frappe.pages["megasol-marketing-start"].on_page_load = function (wrapper) {
    wrapper.marketing_start = new MegasolMarketingStart(wrapper);
};
frappe.pages["megasol-marketing-start"].on_page_show = function (wrapper) {
    wrapper.marketing_start.load();
};

class MegasolMarketingStart {
    constructor(wrapper) {
        this.page = frappe.ui.make_app_page({parent: wrapper, title: __("Start"), single_column: true});
        this.page.main.addClass("marketing-start");
        this.request = 0;
        this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
        this.page.main.html(`<header class="ms-intro"><h2></h2><p>${__("Megasol Marketing · Emails, segments, workflows, forms and consent in one place.")}</p></header>
            <section class="ms-actions" aria-label="${__("Create")}">${[
                ["email", "mail", __("Send an email"), __("Send to segments now, schedule a sending, or spread it over time.")],
                ["segment", "users", __("Build a segment"), __("Group records for emails, workflows, reports and exports.")],
                ["workflow", "workflow", __("Create a workflow"), __("Connect triggers, conditions and actions in the visual editor.")],
                ["form", "file-text", __("Build a form"), __("Create a website form and manage its submissions.")],
            ].map(([key, icon, title, description]) => `<button type="button" class="ms-action" data-action="${key}" disabled>${frappe.utils.icon(icon, "md")}<strong>${title}</strong><span>${description}</span></button>`).join("")}</section>
            <p class="ms-status" role="status"></p><div class="ms-panels">
                <section class="ms-panel"><header class="ms-panel-head"><h3>${__("Coming up")}</h3><a class="btn btn-default btn-xs" href="/app/email-campaign-studio">${__("Campaign Studio")}</a></header><div class="ms-table-wrap"><table class="ms-table"><thead><tr><th>${__("Email")}</th><th>${__("Status")}</th><th>${__("Send time")}</th></tr></thead><tbody class="ms-upcoming"></tbody></table></div></section>
                <section class="ms-panel"><header class="ms-panel-head"><h3>${__("Last sent")}</h3><a class="btn btn-default btn-xs ms-statistics" href="/app/email-campaign-report">${__("All statistics")}</a></header><div class="ms-table-wrap"><table class="ms-table"><thead><tr><th>${__("Email")}</th><th class="num">${__("Delivered")}</th><th class="num">${__("Click rate")}</th><th class="num">${__("Unsubscribed")}</th><th class="num">${__("Skipped")}</th></tr></thead><tbody class="ms-recent"></tbody></table></div></section>
            </div><p class="ms-note">${__("Times: Europe/Zurich. Recent emails are ordered by latest scheduled send time. Delivered figures require provider delivery receipts.")}</p>`);
        this.page.main.on("click", "[data-action]", event => this.create(event.currentTarget.dataset.action));
    }

    esc(value) { return frappe.utils.escape_html(String(value ?? "")); }
    number(value) { return new Intl.NumberFormat().format(Number(value || 0)); }
    shell() { return frappe.app?.sidebar?.current_module || ""; }

    async load() {
        const request = ++this.request;
        this.page.main.find(".ms-status").text(__("Loading marketing activity…"));
        try {
            const response = await frappe.call({method: "finbyzreach.finbyzreach.page.megasol_marketing_start.megasol_marketing_start.get_start_data", type: "GET"});
            if (request !== this.request) return;
            this.data = response.message;
            this.page.main.find(".ms-intro h2").text(this.data.first_name ? __("Hello, {0}", [this.data.first_name]) : __("Welcome to Megasol Marketing"));
            for (const [key, allowed] of Object.entries(this.data.actions)) {
                this.page.main.find(`[data-action="${key}"]`).prop("disabled", !allowed).attr("title", allowed ? "" : __("Creation is unavailable for your current permissions or team membership."));
            }
            this.page.main.find(".ms-statistics").toggle(this.data.can_read_statistics);
            this.renderRows();
            this.page.main.find(".ms-status").text("");
        } catch (error) {
            if (request === this.request) this.page.main.find(".ms-status").text(__("Could not load marketing activity. Use Refresh to try again."));
        }
    }

    renderRows() {
        const empty = (columns, text) => `<tr><td colspan="${columns}" class="ms-empty">${this.esc(text)}</td></tr>`;
        const colors = {"Draft": "gray", "Preparing Audience": "orange", "Scheduled": "blue", "Sending": "orange", "Paused": "yellow"};
        this.page.main.find(".ms-upcoming").html(this.data.upcoming.length ? this.data.upcoming.map(row => `<tr>
            <td><a class="ms-link" href="/app/email-campaign-studio?studio_campaign=${encodeURIComponent(row.name)}" title="${this.esc(row.title)}">${this.esc(row.title)}</a></td>
            <td><span class="indicator-pill ${colors[row.status] || "gray"}">${this.esc(__(row.status))}</span></td>
            <td class="ms-time">${row.scheduled_at ? this.esc(frappe.datetime.str_to_user(row.scheduled_at)) : this.esc(__("Not scheduled"))}</td></tr>`).join("") : empty(3, this.data.can_read_campaigns ? __("No draft, scheduled or sending emails yet.") : __("Campaign access is required to view upcoming emails.")));
        this.page.main.find(".ms-recent").html(this.data.recent.length ? this.data.recent.map(row => `<tr>
            <td><a class="ms-link" href="/app/email-campaign-report?campaign=${encodeURIComponent(row.name)}" title="${this.esc(row.title)}">${this.esc(row.title)}</a></td>
            <td class="num">${row.delivered == null ? this.esc(__("Unavailable")) : this.number(row.delivered)}</td>
            <td class="num">${row.click_rate == null ? "—" : this.number(row.click_rate) + "%"}</td><td class="num">${this.number(row.unsubscribed)}</td><td class="num">${this.number(row.skipped)}</td></tr>`).join("") : empty(5, this.data.can_read_statistics ? __("Sent emails will appear here with their recorded results.") : __("Reporting access is required to view sent-email results.")));
    }

    create(action) {
        if (!this.data?.actions[action]) return;
        if (action === "email") return frappe.set_route("email-campaign-studio", {new: Date.now().toString(36)});
        if (action === "segment") return this.newSegment();
        if (action === "workflow") return this.newWorkflow();
        if (action === "form") return this.newForm();
    }

    newSegment() {
        frappe.prompt([
            {fieldname: "segment_name", fieldtype: "Data", label: __("Name"), reqd: 1},
            {fieldname: "audience_doctype", fieldtype: "Select", label: __("Object type"), options: "Lead\nContact\nCustomer", default: "Contact", reqd: 1},
            {fieldname: "segment_type", fieldtype: "Select", label: __("Segment type"), options: "Active\nStatic", default: "Active", reqd: 1},
            {fieldname: "folder", fieldtype: "Link", label: __("Folder"), options: "Reach Segment Folder", description: __("Optional. Leave empty for Without Folder.")},
            {fieldname: "description", fieldtype: "Small Text", label: __("Description")},
        ], values => frappe.new_doc("Reach Segment", values), __("New segment"), __("Continue to filters"));
    }

    newWorkflow() {
        frappe.prompt([
            {fieldname: "title", fieldtype: "Data", label: __("Name"), default: __("Untitled workflow")},
            {fieldname: "primary_doctype", fieldtype: "Select", label: __("Object type"), options: "Lead\nContact\nCustomer", default: "Contact", reqd: 1},
            {fieldname: "folder", fieldtype: "Link", label: __("Folder"), options: "Automation Workflow Folder"},
        ], async values => {
            const response = await frappe.call({method: "finbyzai.workflow_builder.api.create_workflow", type: "POST", args: {...values, title: values.title || __("Untitled workflow")}, freeze: true});
            if (response.message?.workflow) frappe.set_route("automation-workflow-designer", response.message.workflow, this.shell());
        }, __("New workflow"), __("Create draft"));
    }

    newForm() {
        frappe.prompt([
            {fieldname: "form_name", fieldtype: "Data", label: __("Name"), reqd: 1},
            {fieldname: "team_id", fieldtype: "Select", label: __("Team"), options: this.data.form_teams, default: this.data.form_teams[0]?.value, reqd: 1},
        ], async values => {
            const response = await frappe.call({method: "forms_pro.utils.form_generator.create_form", type: "POST", args: values, freeze: true});
            if (response.message?.form_document) frappe.set_route("forms-pro-designer", response.message.form_document, this.shell());
        }, __("New form"), __("Create draft"));
    }
}
