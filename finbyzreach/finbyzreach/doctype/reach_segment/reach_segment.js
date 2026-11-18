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
                <div class="rs-special-actions"><button type="button" class="btn btn-primary btn-sm rs-add-pick">${__("Add condition")}</button><button type="button" class="btn btn-default btn-sm rs-add-segment">${__("Segment condition")}</button><button type="button" class="btn btn-default btn-sm rs-add-related">${__("Connected object")}</button><button type="button" class="btn btn-default btn-sm rs-add-activity">${__("Activity")}</button></div><div class="rs-specials"></div>
                <h4>${__("Exclusions")}</h4><p class="text-muted">${__("Exclusions always take precedence, including over manual additions.")}</p>
                <div class="rs-exclude"></div><button type="button" class="btn btn-default btn-sm rs-add-exclude">${__("Add exclusion group")}</button>
                <div class="rs-excluded-segments"></div>
            </section>
            <section class="rs-records"><div class="rs-toolbar" role="tablist">
                <button type="button" class="btn btn-default btn-sm" role="tab" data-tab="members">${__("Members")}</button>
                <button type="button" class="btn btn-default btn-sm" role="tab" data-tab="excluded">${__("Excluded")}</button>
                <button type="button" class="btn btn-default btn-sm" role="tab" data-tab="used">${__("Used in")}</button>
                <button type="button" class="btn btn-default btn-sm" role="tab" data-tab="history">${__("History")}</button>
            </div><p class="rs-summary text-muted"></p><div class="rs-members-view"><div class="rs-toolbar">
                <strong class="rs-count"></strong><input type="search" class="form-control rs-search" aria-label="${escape(__("Search members"))}" placeholder="${escape(__("Search members"))}">
                <button type="button" class="btn btn-default btn-sm rs-refresh">${__("Refresh")}</button></div>
                <div class="rs-results"></div><div class="rs-pagination">
                <button type="button" class="btn btn-default btn-sm rs-prev">${__("Previous")}</button>
                <span class="rs-page"></span><button type="button" class="btn btn-default btn-sm rs-next">${__("Next")}</button></div>
            </div><div class="rs-excluded-view" hidden><div class="rs-toolbar">
                <strong class="rs-excluded-count"></strong><input type="search" class="form-control rs-excluded-search" aria-label="${escape(__("Search excluded records"))}" placeholder="${escape(__("Search excluded records"))}">
                <button type="button" class="btn btn-default btn-sm rs-excluded-columns">${__("Columns")}</button>
                <button type="button" class="btn btn-default btn-sm rs-excluded-export">${__("Export")}</button></div><div class="rs-excluded-results"></div><div class="rs-pagination">
                <button type="button" class="btn btn-default btn-sm rs-excluded-prev">${__("Previous")}</button><span class="rs-excluded-page"></span>
                <button type="button" class="btn btn-default btn-sm rs-excluded-next">${__("Next")}</button>
            </div></div><div class="rs-used-view" hidden><div class="rs-used-results"></div></div><div class="rs-history-view" hidden><div class="rs-chart"></div><div class="rs-history-results"></div>
                <button type="button" class="btn btn-default btn-sm rs-history-next">${__("Next changes")}</button>
            </div></section></div>`);
        this.$root.on("click","[data-tab]",e=>this.setTab($(e.currentTarget).attr("data-tab")));
        this.excludedPage = this.frm._segment_excluded_page || 0;
        this.$root.find(".rs-excluded-prev").on("click",()=>{ if(this.excludedPage){this.excludedPage--;this.loadExcluded();} });
        this.$root.find(".rs-excluded-next").on("click",()=>{this.excludedPage++;this.loadExcluded();});
        this.$root.find(".rs-excluded-results").on("click","[data-restore]",e=>this.mutate([$(e.currentTarget).attr("data-restore")],"restore"));
        this.$root.find(".rs-history-next").on("click",()=>this.loadHistory(this.historyCursor));
        this.$root.find(".rs-excluded-search").on("input",()=>{ clearTimeout(this.excludedTimer); this.excludedTimer=setTimeout(()=>{this.excludedPage=0;this.loadExcluded();},400); });
        this.$root.find(".rs-excluded-columns").on("click",()=>this.columnsDialog());
        this.$root.find(".rs-excluded-export").on("click",()=>this.exportDialog("xlsx","excluded"));
        this.$root.find(".rs-add").on("click", () => this.addGroup([], false));
        this.$root.find(".rs-add-exclude").on("click", () => this.addGroup([], true));
        this.$root.find(".rs-add-pick").on("click", () => this.pickerDialog());
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
        const $group = $(`<div class="rs-rule"><div class="rs-rule-head"><select class="form-control rs-rule-match" aria-label="${__("Match conditions")}"><option value="AND">${__("All conditions")}</option><option value="OR">${__("Any condition")}</option></select><button type="button" class="btn btn-default btn-sm rs-remove-group">${__("Remove")}</button></div><div class="rs-rule-body"></div><div class="rs-group-specials"></div><div class="rs-children"></div>${excluded ? "" : `<div class="rs-special-actions"><button type="button" class="btn btn-primary btn-xs rs-group-pick">${__("Add condition")}</button><button type="button" class="btn btn-default btn-xs rs-group-segment">${__("Segment condition")}</button><button type="button" class="btn btn-default btn-xs rs-group-related">${__("Connected object")}</button><button type="button" class="btn btn-default btn-xs rs-group-activity">${__("Activity")}</button><button type="button" class="btn btn-default btn-xs rs-subgroup">${__("Add subgroup")}</button></div>`}</div>`);
        (parent ? parent.$group.find(".rs-children") : this.$root.find(excluded ? ".rs-exclude" : ".rs-include")).append($group);
        const item = {match, $group, children:[], specials:[]};
        item.filter = new frappe.ui.FilterGroup({parent: $group.find(".rs-rule-body"), doctype: this.doctype, on_change: () => this.changed()});
        item.filter.update_filter_button = () => {};
        const initialized = filters.length ? item.filter.add_filters(filters).then(() => item.filter.toggle_empty_filters(false)) : Promise.resolve();
        $group.find(".rs-rule-match").val(match).prop("disabled", excluded || !this.canWrite).on("change", e => { item.match = e.target.value; this.changed(); });
        $group.find(".rs-remove-group").prop("disabled", !this.canWrite).on("click", () => { items.splice(items.indexOf(item), 1); $group.remove(); this.changed(); });
        $group.find(".rs-group-pick").prop("disabled",!this.canWrite).on("click",()=>this.pickerDialog(item));
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
        const title = condition.kind === "subscription" ? `${condition.topic}: ${__(condition.status || "Subscribed")}` : condition.kind === "segment" ? `${condition.operator}: ${condition.segment}` : condition.kind === "related" ? `${condition.quantifier}: ${condition.doctype}` : `${condition.event}: ${condition.days} ${__("days")}`;
        const $row = $(`<div class="rs-rule rs-special-rule"><strong>${escape(title)}</strong><button type="button" class="btn btn-default btn-sm">${__("Remove")}</button></div>`);
        (group ? group.$group.find(".rs-group-specials") : this.$root.find(".rs-specials")).append($row);
        $row.find("button").prop("disabled", !this.canWrite).on("click", () => { items.splice(items.indexOf(condition),1); $row.remove(); this.changed(); });
        this.changed();
    }
    segmentDialog(group=null, operator="in") {
        frappe.prompt([
            {fieldname:"segment",fieldtype:"Link",options:"Reach Segment",label:__("Segment"),reqd:1,get_query:()=>({filters:{audience_doctype:this.doctype,archived:0,name:["!=",this.frm.doc.name]}})},
            {fieldname:"operator",fieldtype:"Select",options:"in\nnot in",label:__("Membership"),default:operator,reqd:1}
        ], values => this.addSpecial({kind:"segment",...values},group));
    }
    activityDialog(group=null, event="Opened") {
        frappe.prompt([
            {fieldname:"event",fieldtype:"Select",options:"Opened\nClicked\nReplied\nSent\nUnsubscribed\nWebsite visit\nWebinar attended\nStore purchase",label:__("Event"),reqd:1,default:event},
            {fieldname:"days",fieldtype:"Int",label:__("In the last days"),default:30,reqd:1},
            {fieldname:"campaign",fieldtype:"Link",options:"Campaign",label:__("Campaign (optional)")},
            {fieldname:"site",fieldtype:"Int",label:__("Tracking site ID (optional)")}
        ], values => this.addSpecial({kind:"activity",...values},group));
    }
    relatedTargets() {
        return ["Opportunity","Sales Order"].includes(this.doctype) ? ["Customer"] : this.doctype === "Lead" ? ["Customer","Quotation","Opportunity"]
            : this.doctype === "Contact" ? ["Customer","Quotation","Opportunity","Sales Order"] : ["Quotation","Opportunity","Sales Order"];
    }
    relatedDialog(group=null, preset=null) {
        const open = ({doctype}) => {
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
                if (preset?.field) filter.add_filter(doctype, preset.field);
            });
        };
        if (preset?.doctype) return open({doctype: preset.doctype});
        frappe.prompt({fieldname:"doctype",fieldtype:"Select",options:this.relatedTargets().join("\n"),label:__("Connected object"),reqd:1}, open);
    }
    async subscriptionDialog(group, topic) {
        frappe.prompt({fieldname:"status",fieldtype:"Select",label:__("Status for {0}", [topic]),reqd:1,default:"Subscribed",
            options:"Subscribed\nNot subscribed\nUnsubscribed\nPending"}, ({status}) => this.addSpecial({kind:"subscription",topic,status},group));
    }
    async pickerDialog(group=null) {
        // Briefing 4.6 / SEG-13: one searchable field picker, grouped like the prototype.
        const target = group || this.groups[0];
        const fieldsOf = doctype => frappe.meta.get_docfields(doctype).filter(f => f.label && !frappe.model.no_value_type.includes(f.fieldtype) && !f.hidden);
        const linkLabel = {Customer:__("Linked company (Customer)"), Quotation:__("Linked quotations"), "Sales Order":__("Linked sales orders"), Opportunity:__("Linked opportunities")};
        const targets = this.relatedTargets();
        await Promise.all(targets.map(dt => frappe.model.with_doctype(dt).catch(() => null)));
        let topics = [];
        if (["Lead","Contact","Customer"].includes(this.doctype)) {
            try { topics = await frappe.db.get_list("Subscription Topic", {filters:{disabled:0, category:["!=","System"]}, fields:["name","category"], limit:100}); } catch (e) { topics = []; }
        }
        const items = [];
        for (const f of fieldsOf(this.doctype)) items.push({group:__("{0} fields", [__(this.doctype)]), label:__(f.label), run:() => this.addField(target, f.fieldname)});
        for (const t of topics) items.push({group:__("Subscriptions"), label:`${t.name}${t.category === "Topic" ? " · " + __("Topic") : ""}`, run:() => this.subscriptionDialog(group, t.name)});
        for (const dt of targets) for (const f of (frappe.meta.docfield_list[dt] ? fieldsOf(dt) : [])) items.push({group:linkLabel[dt], label:__(f.label), run:() => this.relatedDialog(group, {doctype:dt, field:f.fieldname})});
        for (const e of ["Opened","Clicked","Replied","Sent","Unsubscribed"]) items.push({group:__("Email activity"), label:__("Email {0}", [__(e).toLowerCase()]), run:() => this.activityDialog(group, e)});
        for (const e of ["Website visit","Store purchase","Webinar attended"]) items.push({group:__("Website & forms"), label:__(e), run:() => this.activityDialog(group, e)});
        items.push({group:__("Segment membership"), label:__("Is member of segment"), run:() => this.segmentDialog(group, "in")});
        items.push({group:__("Segment membership"), label:__("Is not member of segment"), run:() => this.segmentDialog(group, "not in")});
        const escape = frappe.utils.escape_html;
        const dialog = new frappe.ui.Dialog({title:__("Add condition"), fields:[{fieldname:"search",fieldtype:"Data",label:__("Search fields")},{fieldname:"list",fieldtype:"HTML"}]});
        const $list = dialog.fields_dict.list.$wrapper.addClass("rs-picker");
        const render = () => {
            const q = (dialog.get_value("search") || "").toLowerCase();
            const shown = items.map((item, index) => ({...item, index})).filter(item => !q || item.label.toLowerCase().includes(q) || item.group.toLowerCase().includes(q));
            let html = "", last = null;
            for (const item of shown.slice(0, 300)) {
                if (item.group !== last) { html += `<div class="rs-picker-group">${escape(item.group)}</div>`; last = item.group; }
                html += `<button type="button" class="btn btn-default btn-xs rs-picker-item" data-pick="${item.index}">${escape(item.label)}</button>`;
            }
            $list.html(html || `<p class="text-muted">${__("No field found")}</p>`);
        };
        $list.on("click", "[data-pick]", e => { const item = items[+$(e.currentTarget).attr("data-pick")]; dialog.hide(); item.run(); });
        dialog.fields_dict.search.$input.on("input", render);
        render();
        dialog.show();
        setTimeout(() => dialog.fields_dict.search.$input.trigger("focus"), 100);
    }
    async addField(group, fieldname) {
        const item = group || this.groups[0] || null;
        if (!item) { await this.addGroup([[this.doctype, fieldname, "=", ""]], false); return; }
        await item.filter.add_filter(this.doctype, fieldname);
        this.changed();
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
        if (this.tab === "used") return this.loadUsage();
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
        const {message} = await frappe.call({method: "finbyzreach.segments.change_segment_members", args: {segment_name: this.frm.doc.name, records: JSON.stringify(records), action}});
        if (action === "add" && message?.still_excluded) frappe.reach_segment_membership?.report("add", message.still_excluded, this.frm.doc.name);
        this.frm.reload_doc();
    }
    setTab(tab, load=true) {
        this.tab = tab;
        this.frm._segment_tab = tab;
        for (const name of ["members","excluded","used","history"]) this.$root.find(`.rs-${name}-view`).prop("hidden",name !== tab);
        if (load) this.load(true);
    }
    async loadExcluded() {
        if (this.frm.is_new()) return;
        const sequence = ++this.sequence;
        this.frm._segment_excluded_page = this.excludedPage;
        const {message:data} = await frappe.call({method:"finbyzreach.segments.excluded_segment_records",type:"GET",
            args:{segment_name:this.frm.doc.name,start:this.excludedPage*50,with_paging:1,search:this.$root.find(".rs-excluded-search").val() || ""}});
        if (this.disposed || sequence !== this.sequence) return;
        const escape = frappe.utils.escape_html;
        const columns = data.columns || ["name"];
        const label = c => c === "name" ? __("ID") : __(frappe.meta.get_docfield(this.doctype, c)?.label || c);
        const cell = (row, c) => {
            const value = escape(String((c === "name" ? row.record_name : row.values?.[c]) ?? ""));
            return c === "name" ? `<a href="/app/${frappe.router.slug(this.doctype)}/${encodeURIComponent(row.record_name)}">${value}</a>` : value;
        };
        const canExport = frappe.model.can_export?.("Reach Segment", this.frm);
        this.$root.find(".rs-excluded-export").prop("hidden", !canExport);
        this.$root.find(".rs-excluded-columns").prop("hidden", !this.canWrite);
        this.$root.find(".rs-excluded-count").text(__("{0} excluded", [this.frm.doc.excluded_count || 0]));
        this.$root.find(".rs-excluded-results").html(data.rows.length ? `<table class="table table-bordered"><thead><tr>${columns.map(c=>`<th>${escape(label(c))}</th>`).join("")}<th>${__("Reason")}</th><th>${__("By")}</th><th>${__("When")}</th><th></th></tr></thead><tbody>${data.rows.map(row=>`<tr>${columns.map(c=>`<td>${cell(row,c)}</td>`).join("")}<td>${escape(row.reason || "")}</td><td>${escape(row.owner || "")}</td><td>${escape(String(row.creation || ""))}</td><td>${row.manual && this.canWrite ? `<button type="button" class="btn btn-default btn-xs" data-restore="${escape(row.record_name)}">${__("Restore")}</button>`:""}</td></tr>`).join("")}</tbody></table>` : `<p>${__("No excluded records")}</p>`);
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
    async fetchUsage() {
        if (this.frm.is_new()) return null;
        if (!this.usagePromise) this.usagePromise = Promise.resolve().then(() => frappe.call({method:"finbyzreach.segments.segment_usage",type:"GET",
            args:{segment_name:this.frm.doc.name}})).then(r => r?.message || null).catch(() => { this.usagePromise = null; return null; });
        return this.usagePromise;
    }
    async showUsageWarning() {
        // SEG-41 / SEG-43: warn before editing, naming what depends on this segment.
        const usage = await this.fetchUsage();
        if (!usage || this.disposed) return;
        if (!this.frm.dashboard?.set_headline_alert) return;
        const names = [...usage.workflows.map(w => w.title), ...usage.campaigns.filter(c => c.live || c.status === "Draft").map(c => c.title)];
        if (!names.length) return;
        const escape = frappe.utils.escape_html;
        const message = usage.live
            ? __("Used in live automations or scheduled emails: {0}. Changes apply to them immediately; it cannot be deleted or archived.", [escape(names.join(", "))])
            : __("Used in: {0}. Changes affect these drafts.", [escape(names.join(", "))]);
        this.frm.dashboard.set_headline_alert(message, usage.live ? "red" : "orange");
    }
    async loadUsage() {
        if (this.frm.is_new()) return;
        const sequence = ++this.sequence;
        this.usagePromise = null;
        const usage = await this.fetchUsage();
        if (!usage || this.disposed || sequence !== this.sequence) return;
        const escape = frappe.utils.escape_html;
        const rows = [];
        for (const w of usage.workflows) rows.push([__("Workflow"), `/app/automation-workflow-designer/${encodeURIComponent(w.name)}`, w.title, __(w.status || ""), w.live]);
        for (const c of usage.campaigns) {
            const draft = c.status === "Draft";
            const url = draft ? `/app/email-campaign-studio?studio_campaign=${encodeURIComponent(c.name)}` : `/app/email-campaign-report?campaign=${encodeURIComponent(c.name)}`;
            rows.push([c.role === "exclude" ? __("Email (excluded)") : __("Email"), url, c.title, __(c.status), c.live]);
        }
        for (const name of usage.segments) rows.push([__("Segment"), `/app/reach-segment/${encodeURIComponent(name)}`, name, __("References this segment"), false]);
        const hidden = usage.hidden_campaigns + usage.hidden_segments;
        this.$root.find(".rs-used-results").html(rows.length || hidden ? `<table class="table table-bordered"><thead><tr><th>${__("Type")}</th><th>${__("Name")}</th><th>${__("Status")}</th><th>${__("Effect")}</th></tr></thead><tbody>${rows.map(r => `<tr><td>${escape(r[0])}</td><td><a href="${r[1]}">${escape(r[2])}</a></td><td>${escape(r[3])}</td><td>${r[4] ? __("Cannot be deleted or archived while live") : __("Editing possible")}</td></tr>`).join("")}</tbody></table>${hidden ? `<p class="text-muted">${__("{0} more items you do not have access to.", [hidden])}</p>` : ""}` : `<p>${__("Not used yet")}</p>`);
    }
    async exportDialog(format, scope="members") {
        const {message:data} = await frappe.call({method:"finbyzreach.segments.segment_columns",type:"GET",args:{segment_name:this.frm.doc.name}});
        const dialog = new frappe.ui.Dialog({title:scope === "excluded" ? __("Export excluded records") : __("Export columns"),fields:[{fieldname:"columns",fieldtype:"MultiSelectList",label:__("Columns"),reqd:1,
            get_data:txt=>data.fields.filter(field=>(field.description || field.value).toLowerCase().includes((txt || "").toLowerCase()))},
            {fieldname:"header_language",fieldtype:"Select",label:__("Column headers"),options:[{value:"",label:__("Field names")},{value:"DE",label:"DE"},{value:"FR",label:"FR"},{value:"IT",label:"IT"},{value:"EN",label:"EN"}],default:"EN"}],
            primary_action_label:__("Export"),primary_action:async values=>{
                await frappe.call({method:"finbyzreach.segments.request_segment_export",args:{segment_name:this.frm.doc.name,file_format:format,columns:JSON.stringify(values.columns),header_language:values.header_language || "",scope}});
                dialog.hide();frappe.show_alert(__("Preparing export in the background"));
            }});
        dialog.show();dialog.set_value("columns",data.columns);
    }
    columnsDialog() {
        if (!this.canWrite) return;
        const fields = frappe.meta.get_docfields(this.doctype).filter(f => !frappe.model.no_value_type.includes(f.fieldtype));
        const current = frappe.utils.parse_json(this.frm.doc.columns_json || "[]");
        // Searchable list: doctypes have many fields (SEG-37).
        const dialog = new frappe.ui.Dialog({title: __("Visible and exported columns"), fields: [{fieldname: "columns", fieldtype: "MultiSelectList", label: __("Columns"), get_data: txt => fields.filter(f => (f.label || f.fieldname).toLowerCase().includes((txt || "").toLowerCase())).map(f => ({value: f.fieldname, description: f.label}))}], primary_action_label: __("Save"), primary_action: async values => { await this.frm.set_value("columns_json", JSON.stringify(values.columns)); dialog.hide(); await this.frm.save(); }});
        dialog.show(); dialog.set_value("columns", current);
    }
    actions() {
        if (this.frm.is_new()) return;
        if (frappe.model.can_export("Reach Segment", this.frm)) {
            for (const format of ["csv", "xlsx"]) this.frm.add_custom_button(__("Export {0}", [format.toUpperCase()]),()=>this.exportDialog(format), __("Export"));
        }
        this.frm.add_custom_button(__("Excluded"),()=>this.setTab("excluded"));
        this.showUsageWarning();
        const doc = this.frm.doc;
        const usable = !doc.archived && !doc.snapshot_pending_generation && doc.snapshot_status !== "Failed";
        if (usable && ["Lead","Contact","Customer"].includes(this.doctype) && frappe.model.can_create?.("Campaign")) {
            this.frm.add_custom_button(__("Send email"), () => {
                frappe.route_options = {reach_segment: doc.name, reach_audience: this.doctype};
                frappe.set_route("email-campaign-studio");
            });
        }
        if (usable && frappe.model.can_create?.("Automation Workflow")) {
            this.frm.add_custom_button(__("Use in workflow"), async () => {
                const {message} = await frappe.call({method:"finbyzreach.segments.create_workflow_for_segment",args:{segment_name:doc.name},
                    freeze:true,freeze_message:__("Creating workflow…")});
                frappe.set_route("automation-workflow-designer", message);
            });
            // WF-04: start an existing manual workflow for everyone in this segment, right now.
            if (frappe.manual_workflow_start) this.frm.add_custom_button(__("Start workflow…"), () => frappe.manual_workflow_start.ask({
                doctype: this.doctype,
                subject: __("Every member of “{0}” ({1}) will be started.", [doc.name, doc.member_count || 0]),
                run: async (workflow, key) => (await frappe.call({method: "finbyzai.workflow_builder.api.enroll_manual_segment", type: "POST", freeze: true,
                    args: {workflow_id: workflow, segment_name: doc.name, idempotency_key: key}})).message,
            }));
        }
        if (!this.canWrite) return;
        if (this.frm.doc.snapshot_status === "Failed") this.frm.add_custom_button(__("Retry membership preparation"),async()=>{
            await frappe.call({method:"finbyzreach.segments.retry_segment_snapshot",args:{segment_name:this.frm.doc.name}});
            this.frm.reload_doc();
        });
        if (this.frm.doc.segment_type === "Static") {
            this.frm.add_custom_button(__("Add members"), () => {
                const dialog = new frappe.ui.Dialog({title: __("Add members"), fields: [{fieldname: "records", fieldtype: "MultiSelectList", label: __("Records"), get_data: txt => frappe.db.get_link_options(this.doctype, txt)}], primary_action_label: __("Add"), primary_action: values => { if (!values.records?.length) return frappe.msgprint(__("Choose at least one record")); dialog.hide(); this.mutate(values.records, "add"); }});
                dialog.show();
            });
        }
        this.frm.add_custom_button(__("Columns"), () => this.columnsDialog());
        this.frm.add_custom_button(__("Duplicate"), () => frappe.prompt([{fieldname: "new_name", fieldtype: "Data", label: __("New name"), reqd: 1}, {fieldname: "copy_members", fieldtype: "Check", label: __("Copy current static members")}], async values => {
            const {message} = await frappe.call({method: "finbyzreach.segments.duplicate_segment", args: {segment_name: this.frm.doc.name, ...values}});
            frappe.set_route("Form", "Reach Segment", message);
        }));
    }
}
// The filter editor draws into the read-only filter_groups_json field, and Frappe hides a
// read-only field without a value. A new segment has none, so the editor stayed hidden and an
// Active segment could not be saved ("needs at least one filter group"). Start with an empty list.
function ensureFilterField(frm) {
    if (frm.doc.filter_groups_json) return false;
    frm.doc.filter_groups_json = "[]";
    return true;
}
frappe.ui.form.on("Reach Segment", {
    onload(frm) { ensureFilterField(frm); },
    refresh(frm) {
        if (ensureFilterField(frm)) frm.refresh_field("filter_groups_json");
        frm.builder?.dispose();
        frm.builder = new ReachSegmentBuilder(frm);
    },
    audience_doctype(frm) { if (frm.is_new()) { frm.doc.filter_groups_json = "[]"; frm.doc.filter_expression_json = ""; frm.trigger("refresh"); } },
    async validate(frm) {
        await frm.builder?.initialized;
        frm.builder?.serialize();
    }
});
