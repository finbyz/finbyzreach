// WF-04: "Start workflow…" on the Lead, Contact and Customer lists, for the selected records.
frappe.provide("frappe.manual_workflow_start");

(() => {
    const API = "finbyzai.workflow_builder.api.";
    const DOCTYPES = ["Lead", "Contact", "Customer"];

    frappe.manual_workflow_start.workflows = async doctype => {
        const {message} = await frappe.call({method: API + "manual_start_workflows", type: "GET", args: {doctype}});
        return message || [];
    };

    // Shared by the list action and the segment form: ask which workflow, confirm, run.
    frappe.manual_workflow_start.ask = async function ({doctype, subject, run}) {
        let workflows;
        try { workflows = await frappe.manual_workflow_start.workflows(doctype); }
        catch (error) { return; }
        if (!workflows.length) {
            return frappe.msgprint(__("There is no published workflow with a manual start for {0} records. Publish one with the trigger “Manual start” first.", [__(doctype)]));
        }
        const dialog = new frappe.ui.Dialog({
            title: __("Start workflow"),
            fields: [
                {fieldname: "workflow", fieldtype: "Select", label: __("Workflow"), reqd: 1,
                    options: workflows.map(w => ({value: w.name, label: w.title})), default: workflows[0].name},
                {fieldname: "note", fieldtype: "HTML", options: `<p class="text-muted small">${frappe.utils.escape_html(subject)} ${__("Records already in the workflow, or not eligible, are skipped.")}</p>`},
            ],
            primary_action_label: __("Start workflow"),
            primary_action: async values => {
                dialog.get_primary_btn().prop("disabled", true);
                try {
                    const result = await run(values.workflow, frappe.utils.get_random(16));
                    dialog.hide();
                    frappe.manual_workflow_start.report(result);
                } catch (error) {
                    dialog.get_primary_btn().prop("disabled", false);
                }
            },
        });
        dialog.show();
    };

    frappe.manual_workflow_start.report = function (result) {
        if (!result) return;
        if (result.queued) {
            return frappe.show_alert({message: __("Starting {0} records in the background.", [result.size]), indicator: "blue"});
        }
        const skipped = result.skipped_count || 0;
        const reasons = (result.skipped || []).slice(0, 5)
            .map(row => `${frappe.utils.escape_html(row.record)}: ${frappe.utils.escape_html(row.reason)}`).join("<br>");
        frappe.msgprint({
            title: __("Workflow started"), indicator: skipped ? "orange" : "green",
            message: __("{0} started, {1} skipped.", [result.enrolled || 0, skipped]) + (reasons ? `<br><br>${reasons}` : ""),
        });
    };

    function addAction(listview) {
        if (!listview || listview._manual_start_added || !DOCTYPES.includes(listview.doctype)) return;
        if (typeof listview.page?.add_action_item !== "function") return;
        listview._manual_start_added = true;
        listview.page.add_action_item(__("Start workflow…"), () => {
            const names = listview.get_checked_items().map(row => row.name);
            if (!names.length) return frappe.msgprint(__("Select at least one record first."));
            if (names.length > 500) return frappe.msgprint(__("Select up to 500 records, or start the workflow for a segment."));
            frappe.manual_workflow_start.ask({
                doctype: listview.doctype,
                subject: __("{0} selected record(s) will be started.", [names.length]),
                run: async (workflow, key) => (await frappe.call({method: API + "enroll_manual_records", type: "POST", freeze: true,
                    args: {workflow_id: workflow, record_names: JSON.stringify(names), idempotency_key: key}})).message,
            });
        });
    }

    // A list view has no per-DocType hook that survives other apps' list settings, so look at the page that opened.
    function watch(attempt = 0) {
        const route = frappe.get_route();
        if (route[0] !== "List" || !DOCTYPES.includes(route[1])) return;
        const listview = window.cur_list;
        if (listview && listview.doctype === route[1]) return addAction(listview);
        if (attempt < 25) setTimeout(() => watch(attempt + 1), 200);
    }
    if (frappe.router && frappe.router.on) frappe.router.on("change", () => watch());
    $(document).on("app_ready", () => watch());
})();
