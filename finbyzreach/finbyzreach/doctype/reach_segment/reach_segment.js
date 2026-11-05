// Saved filters remain the authority for Active membership.
class ReachSegmentBuilder {
    constructor(frm) {
        this.frm = frm;
        this.groups = [];
        this.exclusions = [];
        this.specials = [];
        this.cursors = [null];
        this.page = 0;
        this.sequence = 0;
        this.ready = false;
        this.build();
    }
    get doctype() { return this.frm.doc.audience_doctype || "Lead"; }
    get canWrite() { return Boolean(this.frm.perm?.some(p => p.write)); }
    build() {
        const escape = frappe.utils.escape_html;
        this.frm.toggle_display("static_leads_json", false);
        this.frm.toggle_display("exclude_filters_json", false);
        this.$root = this.frm.get_field("filter_groups_json").$wrapper.empty();
        this.$root.html(`<div class="rs-layout">
            <section class="rs-filters"><h4>${__("Filters")}</h4>
                <div class="rs-match-control"><label for="rs-match">${__("Match groups")}</label><select id="rs-match" class="form-control rs-match"><option value="OR">${__("Any")}</option><option value="AND">${__("All")}</option></select></div>
                <div class="rs-include"></div><button type="button" class="btn btn-default btn-sm rs-add">${__("Add group")}</button>
                <div class="rs-special-actions"><button type="button" class="btn btn-default btn-sm rs-add-segment">${__("Segment condition")}</button><button type="button" class="btn btn-default btn-sm rs-add-related">${__("Connected object")}</button><button type="button" class="btn btn-default btn-sm rs-add-activity">${__("Activity")}</button></div><div class="rs-specials"></div>
                <h4>${__("Exclusions")}</h4><p class="text-muted">${__("Exclusions always take precedence, including over manual additions.")}</p>
                <div class="rs-exclude"></div><button type="button" class="btn btn-default btn-sm rs-add-exclude">${__("Add exclusion group")}</button>
                <div class="rs-excluded-segments"></div>
            </section>
            <section class="rs-records"><div class="rs-toolbar">
                <strong class="rs-count"></strong><input type="search" class="form-control rs-search" aria-label="${escape(__("Search members"))}" placeholder="${escape(__("Search members"))}">
                <button type="button" class="btn btn-default btn-sm rs-refresh">${__("Refresh")}</button></div>
                <div class="rs-results"></div><div class="rs-pagination">
                <button type="button" class="btn btn-default btn-sm rs-prev">${__("Previous")}</button>
                <span class="rs-page"></span><button type="button" class="btn btn-default btn-sm rs-next">${__("Next")}</button></div>
            </section></div>`);
        this.$root.find(".rs-add").on("click", () => this.addGroup([], false));
        this.$root.find(".rs-add-exclude").on("click", () => this.addGroup([], true));
        this.$root.find(".rs-add-segment").on("click", () => frappe.prompt([
            {fieldname:"segment",fieldtype:"Link",options:"Reach Segment",label:__("Segment"),reqd:1,get_query:()=>({filters:{audience_doctype:this.doctype,name:["!=",this.frm.doc.name]}})},
            {fieldname:"operator",fieldtype:"Select",options:"in\nnot in",label:__("Membership"),default:"in",reqd:1}
        ], values => this.addSpecial({kind:"segment",...values})));
        this.$root.find(".rs-add-related").on("click", () => this.relatedDialog());
        this.$root.find(".rs-add-activity").on("click", () => frappe.prompt([
            {fieldname:"event",fieldtype:"Select",options:"Opened\nClicked\nReplied\nSent\nUnsubscribed\nWebsite visit\nWebinar attended\nStore purchase",label:__("Event"),reqd:1,default:"Opened"},
            {fieldname:"days",fieldtype:"Int",label:__("In the last days"),default:30,reqd:1},
            {fieldname:"campaign",fieldtype:"Link",options:"Campaign",label:__("Campaign (optional)")}
        ], values => this.addSpecial({kind:"activity",...values})));
        this.$root.find(".rs-match").on("change", () => this.changed());
        this.$root.find(".rs-search").on("input", () => this.schedulePreview());
        this.$root.find(".rs-refresh").on("click", () => this.load(true));
        this.$root.find(".rs-prev").on("click", () => { if (this.page) { this.page--; this.load(false); } });
        this.$root.find(".rs-next").on("click", () => { this.page++; this.load(false); });
        this.$root.find(".rs-results").on("click", "[data-exclude]", e => this.mutate([$(e.currentTarget).attr("data-exclude")], "exclude"));
        this.$root.find(".rs-results").on("click", "[data-restore]", e => this.mutate([$(e.currentTarget).attr("data-restore")], "restore"));
        frappe.model.with_doctype(this.doctype, () => {
            const expression = frappe.utils.parse_json(this.frm.doc.filter_expression_json || "null");
            if (expression?.conditions && expression.conditions.every(g => g.kind || g.conditions?.every(c => Array.isArray(c)))) {
                this.$root.find(".rs-match").val(expression.operator);
                expression.conditions.forEach(g => g.kind ? this.addSpecial(g) : this.addGroup(g.conditions, false, g.operator));
            } else {
                this.normalize(this.frm.doc.filter_groups_json).forEach(g => this.addGroup(g, false));
            }
            if (!this.groups.length) this.addGroup([], false);
            this.normalize(this.frm.doc.exclude_filters_json).forEach(g => this.addGroup(g, true));
            this.ready = true;
            this.load(true);
        });
        this.segmentExclusionControl = frappe.ui.form.make_control({
            parent: this.$root.find(".rs-excluded-segments"), render_input: true,
            df: {fieldname: "segments", fieldtype: "MultiSelectList", label: __("Exclude segments"),
                get_data: txt => frappe.db.get_link_options("Reach Segment", txt, {audience_doctype: this.doctype, name: ["!=", this.frm.doc.name]}),
                onchange: () => { if (this.ready) { this.frm.doc.exclude_segments_json = JSON.stringify(this.segmentExclusionControl.get_value()); this.changed(); } }}
        });
        this.segmentExclusionControl.set_value(frappe.utils.parse_json(this.frm.doc.exclude_segments_json || "[]"));
        if (!this.canWrite) this.$root.find(".rs-filters :input,.rs-add,.rs-add-exclude").prop("disabled", true);
        this.actions();
    }
    normalize(value) {
        const groups = frappe.utils.parse_json(value || "[]");
        return groups.length && typeof groups[0][0] === "string" ? [groups] : groups;
    }
    addGroup(filters, excluded, match="AND") {
        const items = excluded ? this.exclusions : this.groups;
        const $group = $(`<div class="rs-rule"><div class="rs-rule-head"><select class="form-control rs-rule-match" aria-label="${__("Match conditions")}"><option value="AND">${__("All conditions")}</option><option value="OR">${__("Any condition")}</option></select><button type="button" class="btn btn-default btn-sm">${__("Remove")}</button></div><div class="rs-rule-body"></div></div>`);
        this.$root.find(excluded ? ".rs-exclude" : ".rs-include").append($group);
        const item = {match, $group};
        item.filter = new frappe.ui.FilterGroup({parent: $group.find(".rs-rule-body"), doctype: this.doctype, on_change: () => this.changed()});
        item.filter.update_filter_button = () => {};
        if (filters.length) item.filter.add_filters(filters).then(() => item.filter.toggle_empty_filters(false));
        $group.find(".rs-rule-match").val(match).prop("disabled", excluded || !this.canWrite).on("change", e => { item.match = e.target.value; this.changed(); });
        $group.find(".rs-rule-head > button").prop("disabled", !this.canWrite).on("click", () => { items.splice(items.indexOf(item), 1); $group.remove(); this.changed(); });
        items.push(item);
        this.changed();
    }
    addSpecial(condition) {
        this.specials.push(condition);
        const escape = frappe.utils.escape_html;
        const title = condition.kind === "segment" ? `${condition.operator}: ${condition.segment}` : condition.kind === "related" ? `${condition.quantifier}: ${condition.doctype}` : `${condition.event}: ${condition.days} ${__("days")}`;
        const $row = $(`<div class="rs-rule rs-special-rule"><strong>${escape(title)}</strong><button type="button" class="btn btn-default btn-sm">${__("Remove")}</button></div>`);
        this.$root.find(".rs-specials").append($row);
        $row.find("button").prop("disabled", !this.canWrite).on("click", () => { this.specials.splice(this.specials.indexOf(condition),1); $row.remove(); this.changed(); });
        this.changed();
    }
    relatedDialog() {
        const targets = this.doctype === "Lead" ? "Customer\nOpportunity" : this.doctype === "Contact" ? "Customer\nOpportunity\nSales Order" : "Opportunity\nSales Order";
        frappe.prompt({fieldname:"doctype",fieldtype:"Select",options:targets,label:__("Connected object"),reqd:1}, ({doctype}) => {
            frappe.model.with_doctype(doctype, () => {
                const dialog = new frappe.ui.Dialog({title:__("Connected object filters"),fields:[
                    {fieldname:"quantifier",fieldtype:"Select",options:"any\nall",default:"any",label:__("Matching related records")},
                    {fieldname:"rules",fieldtype:"HTML"}
                ],primary_action_label:__("Add condition"),primary_action:values=>{
                    const filters = filter.get_filters();
                    if (!filters.length) return frappe.msgprint(__("Add at least one condition"));
                    this.addSpecial({kind:"related",doctype,quantifier:values.quantifier,filters:[filters]}); dialog.hide();
                }});
                const filter = new frappe.ui.FilterGroup({parent:dialog.fields_dict.rules.$wrapper,doctype});
                filter.update_filter_button=()=>{};
                dialog.show();
            });
        });
    }
    serialize() {
        const groups = this.groups.map(i => ({operator: i.match, conditions: i.filter.get_filters()})).filter(i => i.conditions.length);
        const legacy = groups.map(i => i.conditions);
        groups.push(...this.specials);
        this.frm.doc.filter_groups_json = JSON.stringify(legacy);
        const custom = this.specials.length || this.$root.find(".rs-match").val() === "AND" || groups.some(g => g.operator === "OR");
        this.frm.doc.filter_expression_json = custom && groups.length ? JSON.stringify({operator: this.$root.find(".rs-match").val(), conditions: groups}) : "";
        this.frm.doc.exclude_filters_json = JSON.stringify(this.exclusions.map(i => i.filter.get_filters()).filter(g => g.length));
    }
    changed() {
        if (!this.ready || !this.canWrite) return;
        this.serialize();
        this.frm.dirty();
        this.schedulePreview();
    }
    schedulePreview() {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.load(true), 400);
    }
    async load(reset) {
        const sequence = ++this.sequence;
        if (reset) { this.page = 0; this.cursors = [null]; }
        const args = {segment_name: this.frm.is_new() ? null : this.frm.doc.name, after: this.cursors[this.page], page_length: 50, search: this.$root.find(".rs-search").val(), include_count: reset ? 1 : 0};
        if (this.frm.is_dirty() || this.frm.is_new()) {
            this.serialize();
            args.definition = JSON.stringify({audience_doctype: this.doctype, filter_groups_json: this.frm.doc.filter_groups_json,
                filter_expression_json: this.frm.doc.filter_expression_json, exclude_filters_json: this.frm.doc.exclude_filters_json,
                exclude_segments_json: this.frm.doc.exclude_segments_json, exclude_email_groups_json: this.frm.doc.exclude_email_groups_json});
        }
        this.$root.find(".rs-results").text(__("Loading…"));
        this.$root.find(".rs-next,.rs-prev").prop("disabled", true);
        try {
            const {message: data} = await frappe.call({method: "finbyzreach.segments.preview_segment_page", args});
            if (sequence !== this.sequence) return;
            const escape = frappe.utils.escape_html;
            if (data.count !== null) this.$root.find(".rs-count").text(__("{0} members · {1} excluded", [data.count, data.excluded_count ?? 0]));
            const showActions = this.canWrite && !this.frm.is_new();
            const columns = data.columns.map(c => `<col class="${c === "name" ? "rs-name-column" : "rs-data-column"}">`).join("");
            const minWidth = data.columns.reduce((width, c) => width + (c === "name" ? 280 : 180), showActions ? 100 : 0);
            const head = data.columns.map(c => {
                const label = c === "name" ? __("ID") : __(frappe.meta.get_docfield(this.doctype, c)?.label || c);
                return `<th title="${escape(label)}">${escape(label)}</th>`;
            }).join("");
            const rows = data.rows.map(row => {
                const cells = data.columns.map(c => {
                    const value = escape(String(row[c] ?? ""));
                    const content = c === "name" ? `<a href="/app/${frappe.router.slug(this.doctype)}/${encodeURIComponent(row.name)}">${value}</a>` : value;
                    return `<td title="${value}">${content}</td>`;
                }).join("");
                const action = showActions ? `<td><button type="button" class="btn btn-default btn-sm" data-exclude="${escape(row.name)}">${__("Exclude")}</button></td>` : "";
                return `<tr>${cells}${action}</tr>`;
            }).join("");
            this.$root.find(".rs-results").html(rows ? `<table class="table table-bordered" style="min-width:${minWidth}px"><colgroup>${columns}${showActions ? '<col class="rs-action-column">' : ""}</colgroup><thead><tr>${head}${showActions ? `<th><span class="sr-only">${__("Actions")}</span></th>` : ""}</tr></thead><tbody>${rows}</tbody></table>` : `<p>${__("No matching records")}</p>`);
            this.cursors[this.page+1] = data.next_cursor;
            this.$root.find(".rs-page").text(__("Page {0}", [this.page+1]));
            this.$root.find(".rs-prev").prop("disabled", !this.page);
            this.$root.find(".rs-next").prop("disabled", !data.has_more);
        } catch (error) {
            if (sequence === this.sequence) this.$root.find(".rs-results").text(__("Preview unavailable. Check the filters and try again."));
        }
    }
    async mutate(records, action) {
        if (this.frm.is_dirty()) return frappe.msgprint(__("Save the segment before changing members."));
        await frappe.call({method: "finbyzreach.segments.change_segment_members", args: {segment_name: this.frm.doc.name, records: JSON.stringify(records), action}});
        this.frm.reload_doc();
    }
    actions() {
        if (this.frm.is_new() || !this.canWrite) return;
        this.frm.add_custom_button(__("Excluded"), async () => {
            const {message: rows} = await frappe.call({method: "finbyzreach.segments.excluded_segment_records", type: "GET", args: {segment_name: this.frm.doc.name}});
            const escape = frappe.utils.escape_html;
            const dialog = new frappe.ui.Dialog({title: __("Manual exclusions"), fields: [{fieldtype: "HTML", fieldname: "records"}]});
            dialog.fields_dict.records.$wrapper.html(rows.map(r => `<div>${escape(r.record_name)} · ${escape(r.reason || "")} · ${escape(r.owner)} · ${escape(String(r.creation || ""))} ${r.manual ? `<button type="button" class="btn btn-default btn-sm" data-name="${escape(r.record_name)}">${__("Restore")}</button>` : ""}</div>`).join("") || __("No manual exclusions"));
            dialog.fields_dict.records.$wrapper.on("click", "button", e => { dialog.hide(); this.mutate([$(e.currentTarget).attr("data-name")], "restore"); });
            dialog.show();
        });
        if (this.frm.doc.segment_type === "Static") {
            this.frm.add_custom_button(__("Add members"), () => {
                const dialog = new frappe.ui.Dialog({title: __("Add members"), fields: [{fieldname: "records", fieldtype: "MultiSelectList", label: __("Records"), get_data: txt => frappe.db.get_link_options(this.doctype, txt)}], primary_action_label: __("Add"), primary_action: values => { dialog.hide(); this.mutate(values.records, "add"); }});
                dialog.show();
            });
        }
        this.frm.add_custom_button(__("Columns"), () => {
            const fields = frappe.meta.get_docfields(this.doctype).filter(f => !frappe.model.no_value_type.includes(f.fieldtype));
            const current = frappe.utils.parse_json(this.frm.doc.columns_json || "[]");
            const dialog = new frappe.ui.Dialog({title: __("Visible and exported columns"), fields: [{fieldname: "columns", fieldtype: "MultiSelectList", label: __("Columns"), get_data: txt => fields.filter(f => (f.label || f.fieldname).toLowerCase().includes((txt || "").toLowerCase())).map(f => ({value: f.fieldname, description: f.label}))}], primary_action_label: __("Save"), primary_action: async values => { await this.frm.set_value("columns_json", JSON.stringify(values.columns)); dialog.hide(); await this.frm.save(); }});
            dialog.show(); dialog.set_value("columns", current);
        });
        for (const format of ["csv", "xlsx"]) this.frm.add_custom_button(__("Export {0}", [format.toUpperCase()]), async () => {
            await frappe.call({method:"finbyzreach.segments.request_segment_export",args:{segment_name:this.frm.doc.name,file_format:format}});
            frappe.show_alert(__("Preparing export in the background"));
        }, __("Export"));
        this.frm.add_custom_button(__("Duplicate"), () => frappe.prompt([{fieldname: "new_name", fieldtype: "Data", label: __("New name"), reqd: 1}, {fieldname: "copy_members", fieldtype: "Check", label: __("Copy current static members")}], async values => {
            const {message} = await frappe.call({method: "finbyzreach.segments.duplicate_segment", args: {segment_name: this.frm.doc.name, ...values}});
            frappe.set_route("Form", "Reach Segment", message);
        }));
    }
}
frappe.ui.form.on("Reach Segment", {
    refresh(frm) { frm.builder = new ReachSegmentBuilder(frm); },
    audience_doctype(frm) { if (frm.is_new()) { frm.doc.filter_groups_json = "[]"; frm.doc.filter_expression_json = ""; frm.trigger("refresh"); } },
    validate(frm) { frm.builder?.serialize(); }
});
