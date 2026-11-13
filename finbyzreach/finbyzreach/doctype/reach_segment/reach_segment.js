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
        this.initialized = this.build();
    }
    get doctype() { return this.frm.doc.audience_doctype || "Lead"; }
    get canWrite() { return Boolean(this.frm.perm?.some(p => p.write)); }
    async build() {
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
            <section class="rs-records"><div class="rs-toolbar" role="tablist">
                <button type="button" class="btn btn-default btn-sm" role="tab" data-tab="members">${__("Members")}</button>
                <button type="button" class="btn btn-default btn-sm" role="tab" data-tab="excluded">${__("Excluded")}</button>
                <button type="button" class="btn btn-default btn-sm" role="tab" data-tab="history">${__("History")}</button>
            </div><p class="rs-summary text-muted"></p><div class="rs-members-view"><div class="rs-toolbar">
                <strong class="rs-count"></strong><input type="search" class="form-control rs-search" aria-label="${escape(__("Search members"))}" placeholder="${escape(__("Search members"))}">
                <button type="button" class="btn btn-default btn-sm rs-refresh">${__("Refresh")}</button></div>
                <div class="rs-results"></div><div class="rs-pagination">
                <button type="button" class="btn btn-default btn-sm rs-prev">${__("Previous")}</button>
                <span class="rs-page"></span><button type="button" class="btn btn-default btn-sm rs-next">${__("Next")}</button></div>
            </div><div class="rs-excluded-view" hidden><div class="rs-excluded-results"></div><div class="rs-pagination">
                <button type="button" class="btn btn-default btn-sm rs-excluded-prev">${__("Previous")}</button><span class="rs-excluded-page"></span>
                <button type="button" class="btn btn-default btn-sm rs-excluded-next">${__("Next")}</button>
            </div></div><div class="rs-history-view" hidden><div class="rs-chart"></div><div class="rs-history-results"></div>
                <button type="button" class="btn btn-default btn-sm rs-history-next">${__("Next changes")}</button>
            </div></section></div>`);
        this.$root.on("click","[data-tab]",e=>this.setTab($(e.currentTarget).attr("data-tab")));
        this.excludedPage = this.frm._segment_excluded_page || 0;
        this.$root.find(".rs-excluded-prev").on("click",()=>{ if(this.excludedPage){this.excludedPage--;this.loadExcluded();} });
        this.$root.find(".rs-excluded-next").on("click",()=>{this.excludedPage++;this.loadExcluded();});
        this.$root.find(".rs-excluded-results").on("click","[data-restore]",e=>this.mutate([$(e.currentTarget).attr("data-restore")],"restore"));
        this.$root.find(".rs-history-next").on("click",()=>this.loadHistory(this.historyCursor));
        this.$root.find(".rs-add").on("click", () => this.addGroup([], false));
        this.$root.find(".rs-add-exclude").on("click", () => this.addGroup([], true));
        this.$root.find(".rs-add-segment").on("click", () => this.segmentDialog());
        this.$root.find(".rs-add-related").on("click", () => this.relatedDialog());
        this.$root.find(".rs-add-activity").on("click", () => this.activityDialog());
        this.$root.find(".rs-match").on("change", () => this.changed());
        this.$root.find(".rs-search").on("input", () => this.schedulePreview());
        this.$root.find(".rs-refresh").on("click", () => this.load(true));
        this.$root.find(".rs-prev").on("click", () => { if (this.page) { this.page--; this.load(false); } });
        this.$root.find(".rs-next").on("click", () => { this.page++; this.load(false); });
        this.$root.find(".rs-results").on("click", "[data-exclude]", e => this.mutate([$(e.currentTarget).attr("data-exclude")], "exclude"));
        this.$root.find(".rs-results").on("click", "[data-restore]", e => this.mutate([$(e.currentTarget).attr("data-restore")], "restore"));
        await frappe.model.with_doctype(this.doctype);
        if (this.disposed) return;
        const pending = [];
        const expression = frappe.utils.parse_json(this.frm.doc.filter_expression_json || "null");
        if (expression) {
            this.$root.find(".rs-match").val(expression.operator || "OR");
            const nodes = expression.conditions && !expression.kind ? expression.conditions : [expression];
            nodes.forEach(node => pending.push(this.hydrateNode(node)));
        } else {
            this.normalize(this.frm.doc.filter_groups_json).forEach(g => pending.push(this.addGroup(g, false)));
        }
        if (!this.groups.length) pending.push(this.addGroup([], false));
        this.normalize(this.frm.doc.exclude_filters_json).forEach(g => pending.push(this.addGroup(g, true)));
        this.segmentExclusionControl = frappe.ui.form.make_control({
            parent: this.$root.find(".rs-excluded-segments"), render_input: true,
            df: {fieldname: "segments", fieldtype: "MultiSelectList", label: __("Exclude segments"),
                get_data: txt => frappe.db.get_link_options("Reach Segment", txt, {audience_doctype: this.doctype, name: ["!=", this.frm.doc.name]}),
                onchange: () => this.changed() }
        });
        pending.push(this.segmentExclusionControl.set_value(frappe.utils.parse_json(this.frm.doc.exclude_segments_json || "[]")));
        await Promise.all(pending);
        if (this.disposed) return;
        // Loading saved controls is not a user edit. Remember their canonical
        // values so delayed/repeated native callbacks cannot dirty the form.
        this.definitionSignature = JSON.stringify(this.definition());
        this.ready = true;
        if (!this.canWrite || this.frm.doc.snapshot_pending_generation || this.frm.doc.archived) this.$root.find(".rs-filters :input,.rs-add,.rs-add-exclude").prop("disabled", true);
        this.actions();
        this.setTab(this.frm._segment_tab || "members",false);
        this.load(true);
    }
    dispose() {
        this.disposed = true;
        this.ready = false;
        ++this.sequence;
        clearTimeout(this.timer);
        clearTimeout(this.snapshotTimer);
    }
    normalize(value) {
        const groups = frappe.utils.parse_json(value || "[]");
        return groups.length && typeof groups[0][0] === "string" ? [groups] : groups;
    }
    hydrateNode(node, parent=null) {
        if (Array.isArray(node)) return this.addGroup([node], false, "AND", parent);
        if (node.kind) { this.addSpecial(node, parent); return Promise.resolve(); }
        return this.addGroup((node.conditions || []).filter(Array.isArray), false, node.operator, parent,
            (node.conditions || []).filter(child => !Array.isArray(child)));
    }
    addGroup(filters, excluded, match="AND", parent=null, nodes=[]) {
        const items = excluded ? this.exclusions : parent ? parent.children : this.groups;
        const $group = $(`<div class="rs-rule"><div class="rs-rule-head"><select class="form-control rs-rule-match" aria-label="${__("Match conditions")}"><option value="AND">${__("All conditions")}</option><option value="OR">${__("Any condition")}</option></select><button type="button" class="btn btn-default btn-sm rs-remove-group">${__("Remove")}</button></div><div class="rs-rule-body"></div><div class="rs-group-specials"></div><div class="rs-children"></div>${excluded ? "" : `<div class="rs-special-actions"><button type="button" class="btn btn-default btn-xs rs-group-segment">${__("Segment condition")}</button><button type="button" class="btn btn-default btn-xs rs-group-related">${__("Connected object")}</button><button type="button" class="btn btn-default btn-xs rs-group-activity">${__("Activity")}</button><button type="button" class="btn btn-default btn-xs rs-subgroup">${__("Add subgroup")}</button></div>`}</div>`);
        (parent ? parent.$group.find(".rs-children") : this.$root.find(excluded ? ".rs-exclude" : ".rs-include")).append($group);
        const item = {match, $group, children:[], specials:[]};
        item.filter = new frappe.ui.FilterGroup({parent: $group.find(".rs-rule-body"), doctype: this.doctype, on_change: () => this.changed()});
        item.filter.update_filter_button = () => {};
        const initialized = filters.length ? item.filter.add_filters(filters).then(() => item.filter.toggle_empty_filters(false)) : Promise.resolve();
        $group.find(".rs-rule-match").val(match).prop("disabled", excluded || !this.canWrite).on("change", e => { item.match = e.target.value; this.changed(); });
        $group.find(".rs-remove-group").prop("disabled", !this.canWrite).on("click", () => { items.splice(items.indexOf(item), 1); $group.remove(); this.changed(); });
        $group.find(".rs-group-segment").prop("disabled",!this.canWrite).on("click",()=>this.segmentDialog(item));
        $group.find(".rs-group-related").prop("disabled",!this.canWrite).on("click",()=>this.relatedDialog(item));
        $group.find(".rs-group-activity").prop("disabled",!this.canWrite).on("click",()=>this.activityDialog(item));
        $group.find(".rs-subgroup").prop("disabled",!this.canWrite).on("click",()=>this.addGroup([],false,"AND",item));
        items.push(item);
        const pending = nodes.map(node => this.hydrateNode(node,item));
        this.changed();
        return Promise.all([initialized,...pending]);
    }
    addSpecial(condition, group=null) {
        const items = group ? group.specials : this.specials;
        items.push(condition);
        const escape = frappe.utils.escape_html;
        const title = condition.kind === "segment" ? `${condition.operator}: ${condition.segment}` : condition.kind === "related" ? `${condition.quantifier}: ${condition.doctype}` : `${condition.event}: ${condition.days} ${__("days")}`;
        const $row = $(`<div class="rs-rule rs-special-rule"><strong>${escape(title)}</strong><button type="button" class="btn btn-default btn-sm">${__("Remove")}</button></div>`);
        (group ? group.$group.find(".rs-group-specials") : this.$root.find(".rs-specials")).append($row);
        $row.find("button").prop("disabled", !this.canWrite).on("click", () => { items.splice(items.indexOf(condition),1); $row.remove(); this.changed(); });
        this.changed();
    }
    segmentDialog(group=null) {
        frappe.prompt([
            {fieldname:"segment",fieldtype:"Link",options:"Reach Segment",label:__("Segment"),reqd:1,get_query:()=>({filters:{audience_doctype:this.doctype,archived:0,name:["!=",this.frm.doc.name]}})},
            {fieldname:"operator",fieldtype:"Select",options:"in\nnot in",label:__("Membership"),default:"in",reqd:1}
        ], values => this.addSpecial({kind:"segment",...values},group));
    }
    activityDialog(group=null) {
        frappe.prompt([
            {fieldname:"event",fieldtype:"Select",options:"Opened\nClicked\nReplied\nSent\nUnsubscribed\nWebsite visit\nWebinar attended\nStore purchase",label:__("Event"),reqd:1,default:"Opened"},
            {fieldname:"days",fieldtype:"Int",label:__("In the last days"),default:30,reqd:1},
            {fieldname:"campaign",fieldtype:"Link",options:"Campaign",label:__("Campaign (optional)")},
            {fieldname:"site",fieldtype:"Int",label:__("Tracking site ID (optional)")}
        ], values => this.addSpecial({kind:"activity",...values},group));
    }
    relatedDialog(group=null) {
        const targets = ["Opportunity","Sales Order"].includes(this.doctype) ? "Customer" : this.doctype === "Lead" ? "Customer\nOpportunity" : this.doctype === "Contact" ? "Customer\nOpportunity\nSales Order" : "Opportunity\nSales Order";
        frappe.prompt({fieldname:"doctype",fieldtype:"Select",options:targets,label:__("Connected object"),reqd:1}, ({doctype}) => {
            frappe.model.with_doctype(doctype, () => {
                const dialog = new frappe.ui.Dialog({title:__("Connected object filters"),fields:[
                    {fieldname:"quantifier",fieldtype:"Select",options:"any\nall",default:"any",label:__("Matching related records")},
                    {fieldname:"rules",fieldtype:"HTML"}
                ],primary_action_label:__("Add condition"),primary_action:values=>{
                    const filters = filter.get_filters();
                    if (!filters.length) return frappe.msgprint(__("Add at least one condition"));
                    this.addSpecial({kind:"related",doctype,quantifier:values.quantifier,filters:[filters]},group); dialog.hide();
                }});
                const filter = new frappe.ui.FilterGroup({parent:dialog.fields_dict.rules.$wrapper,doctype});
                filter.update_filter_button=()=>{};
                dialog.show();
            });
        });
    }
    groupDefinition(item) {
        const conditions = [...item.filter.get_filters(), ...item.specials,
            ...item.children.map(child => this.groupDefinition(child)).filter(Boolean)];
        return conditions.length ? {operator:item.match, conditions} : null;
    }
    definition() {
        const groups = this.groups.map(item => this.groupDefinition(item)).filter(Boolean);
        const legacy = this.groups.map(item => item.filter.get_filters()).filter(group => group.length);
        const nested = this.groups.some(item => item.children.length || item.specials.length);
        groups.push(...this.specials);
        const custom = nested || this.specials.length || this.$root.find(".rs-match").val() === "AND" || groups.some(g => g.operator === "OR");
        return {
            filter_groups_json: JSON.stringify(legacy),
            filter_expression_json: custom && groups.length ? JSON.stringify({operator: this.$root.find(".rs-match").val(), conditions: groups}) : "",
            exclude_filters_json: JSON.stringify(this.exclusions.map(i => i.filter.get_filters()).filter(g => g.length)),
            exclude_segments_json: JSON.stringify(this.segmentExclusionControl.get_value() || []),
        };
    }
    serialize() {
        if (this.ready && !this.disposed) {
            const definition = this.definition();
            const signature = JSON.stringify(definition);
            // Preserve untouched saved JSON, including equivalent child order.
            // A description-only save must not start a Static recalculation.
            if (signature !== this.definitionSignature) {
                Object.assign(this.frm.doc,definition);
                this.definitionSignature = signature;
            }
        }
    }
    changed() {
        if (!this.ready || this.disposed || !this.canWrite) return;
        const definition = this.definition();
        const signature = JSON.stringify(definition);
        if (signature === this.definitionSignature) return;
        this.definitionSignature = signature;
        Object.assign(this.frm.doc, definition);
        this.frm.dirty();
        this.schedulePreview();
    }
    schedulePreview() {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.load(true), 400);
    }
    async load(reset) {
        if (!this.ready || this.disposed) return;
        if (this.tab === "excluded") return this.loadExcluded();
        if (this.tab === "history") return this.loadHistory();
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
            clearTimeout(this.snapshotTimer);
            if (!this.frm.is_dirty() && data.snapshot_status !== (this.frm.doc.snapshot_status || "Ready")) {
                this.frm.reload_doc();return;
            }
            if (["Queued","Building"].includes(data.snapshot_status)) this.snapshotTimer = setTimeout(()=>this.load(true),2000);
            const escape = frappe.utils.escape_html;
            this.columns = data.columns;
            this.$root.find(".rs-summary").text(`${__(data.segment_type || this.frm.doc.segment_type)} · ${__(data.snapshot_status || "Ready")}`);
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
    setTab(tab, load=true) {
        this.tab = tab;
        this.frm._segment_tab = tab;
        for (const name of ["members","excluded","history"]) this.$root.find(`.rs-${name}-view`).prop("hidden",name !== tab);
        if (load) this.load(true);
    }
    async loadExcluded() {
        if (this.frm.is_new()) return;
        const sequence = ++this.sequence;
        this.frm._segment_excluded_page = this.excludedPage;
        const {message:data} = await frappe.call({method:"finbyzreach.segments.excluded_segment_records",type:"GET",
            args:{segment_name:this.frm.doc.name,start:this.excludedPage*50,with_paging:1}});
        if (this.disposed || sequence !== this.sequence) return;
        const escape = frappe.utils.escape_html;
        this.$root.find(".rs-excluded-results").html(`<table class="table table-bordered"><thead><tr><th>${__("Record")}</th><th>${__("Reason")}</th><th>${__("By")}</th><th>${__("When")}</th><th></th></tr></thead><tbody>${data.rows.map(row=>`<tr><td>${escape(row.record_name)}</td><td>${escape(row.reason || "")}</td><td>${escape(row.owner || "")}</td><td>${escape(String(row.creation || ""))}</td><td>${row.manual && this.canWrite ? `<button type="button" class="btn btn-default btn-xs" data-restore="${escape(row.record_name)}">${__("Restore")}</button>`:""}</td></tr>`).join("")}</tbody></table>`);
        this.$root.find(".rs-excluded-prev").prop("disabled",!this.excludedPage);
        this.$root.find(".rs-excluded-next").prop("disabled",!data.has_more);
        this.$root.find(".rs-excluded-page").text(__("Page {0}",[this.excludedPage+1]));
    }
    async loadHistory(after=null) {
        if (this.frm.is_new()) return;
        const sequence = ++this.sequence;
        const {message:data} = await frappe.call({method:"finbyzreach.segments.segment_history",type:"GET",args:{segment_name:this.frm.doc.name,after}});
        if (this.disposed || sequence !== this.sequence) return;
        const escape = frappe.utils.escape_html;
        this.historyCursor = data.next_cursor;
        this.$root.find(".rs-history-next").prop("disabled",!data.next_cursor);
        this.$root.find(".rs-history-results").html(`<table class="table table-bordered"><thead><tr><th>${__("Record")}</th><th>${__("Change")}</th><th>${__("By")}</th><th>${__("When")}</th></tr></thead><tbody>${data.events.map(row=>`<tr><td>${escape(row.record_name || "")}</td><td>${escape(__(row.event))}</td><td>${escape(row.actor || "")}</td><td>${escape(String(row.event_time || ""))}</td></tr>`).join("")}</tbody></table>`);
        if (!after && data.samples.length && frappe.Chart) {
            this.$root.find(".rs-chart").empty();
            new frappe.Chart(this.$root.find(".rs-chart")[0],{type:"line",height:200,
                data:{labels:data.samples.map(row=>String(row.sample_date)),datasets:[{name:__("Members"),values:data.samples.map(row=>row.member_count)}]}});
        }
    }
    async exportDialog(format) {
        const {message:data} = await frappe.call({method:"finbyzreach.segments.segment_columns",type:"GET",args:{segment_name:this.frm.doc.name}});
        const dialog = new frappe.ui.Dialog({title:__("Export columns"),fields:[{fieldname:"columns",fieldtype:"MultiSelectList",label:__("Columns"),reqd:1,
            get_data:txt=>data.fields.filter(field=>(field.description || field.value).toLowerCase().includes((txt || "").toLowerCase()))}],
            primary_action_label:__("Export"),primary_action:async values=>{
                await frappe.call({method:"finbyzreach.segments.request_segment_export",args:{segment_name:this.frm.doc.name,file_format:format,columns:JSON.stringify(values.columns)}});
                dialog.hide();frappe.show_alert(__("Preparing export in the background"));
            }});
        dialog.show();dialog.set_value("columns",data.columns);
    }
    actions() {
        if (this.frm.is_new()) return;
        if (frappe.model.can_export("Reach Segment", this.frm)) {
            for (const format of ["csv", "xlsx"]) this.frm.add_custom_button(__("Export {0}", [format.toUpperCase()]),()=>this.exportDialog(format), __("Export"));
        }
        this.frm.add_custom_button(__("Excluded"),()=>this.setTab("excluded"));
        if (!this.canWrite) return;
        if (this.frm.doc.snapshot_status === "Failed") this.frm.add_custom_button(__("Retry membership preparation"),async()=>{
            await frappe.call({method:"finbyzreach.segments.retry_segment_snapshot",args:{segment_name:this.frm.doc.name}});
            this.frm.reload_doc();
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
        this.frm.add_custom_button(__("Duplicate"), () => frappe.prompt([{fieldname: "new_name", fieldtype: "Data", label: __("New name"), reqd: 1}, {fieldname: "copy_members", fieldtype: "Check", label: __("Copy current static members")}], async values => {
            const {message} = await frappe.call({method: "finbyzreach.segments.duplicate_segment", args: {segment_name: this.frm.doc.name, ...values}});
            frappe.set_route("Form", "Reach Segment", message);
        }));
    }
}
frappe.ui.form.on("Reach Segment", {
    refresh(frm) {
        frm.builder?.dispose();
        frm.builder = new ReachSegmentBuilder(frm);
    },
    audience_doctype(frm) { if (frm.is_new()) { frm.doc.filter_groups_json = "[]"; frm.doc.filter_expression_json = ""; frm.trigger("refresh"); } },
    async validate(frm) {
        await frm.builder?.initialized;
        frm.builder?.serialize();
    }
});
