// Folder navigation augments the native list; its rows and controls stay native.
frappe.provide("frappe.reach_folder_sidebar");

(() => {
    const CONFIG = {
        "Form": {folder: "FP Form Folder", field: "folder", parent: "parent_fp_form_folder", root: ""},
        "Automation Workflow": {folder: "Automation Workflow Folder", field: "folder", parent: "parent_folder", root: "", path: true},
        "Reach Segment": {folder: "Reach Segment Folder", field: "folder", parent: "parent_reach_segment_folder", root: "All Reach Segment Folders"},
        "Email Template Master": {folder: "Email Template Folder", field: "folder", parent: "parent_email_template_folder", root: "All Email Template Folders"},
        "Email Template": {folder: "Email Folder", field: "custom_folder", parent: "parent_email_folder", root: "All Email Folders"},
    };
    const PAGE_SIZE = 50;
    const escape = value => frappe.utils.escape_html(String(value ?? ""));
    const request = async (method, args) => (await frappe.call({method, type: "GET", args})).message;

    class FolderSidebar {
        constructor(list) {
            this.list = list;
            this.config = CONFIG[list.doctype];
            this.branches = new Map();
            this.expanded = new Set();
            const $layout = list.page.main.closest(".layout-main").addClass("reach-folder-layout");
            this.$root = $('<aside class="reach-folder-sidebar" aria-label="' + escape(__("Folders")) + '"></aside>').prependTo($layout);
            this.$root.html('<nav class="reach-folder-nav"></nav><div class="reach-folder-footer"></div>');
            list.page.add_menu_item(__("Refresh folders"), () => this.reload());
            if (frappe.model.can_read(this.config.folder)) {
                list.page.add_menu_item(__("Manage folders"), () => frappe.set_route(this.config.path ? "List" : "Tree", this.config.folder));
            }
            this.$root.on("click", "[data-select]", event => this.select($(event.currentTarget).attr("data-select")));
            this.$root.on("click", "[data-expand]", event => this.toggle($(event.currentTarget).attr("data-expand")));
            this.$root.on("click", "[data-more]", event => this.load($(event.currentTarget).attr("data-more"), true));
            this.$root.on("click", '[data-action="new"]', () => this.new_folder());
            const previous = list.settings.refresh;
            list.settings.refresh = view => {
                previous?.(view);
                this.refresh();
            };
            this.reload();
        }

        filters() {
            return this.list.filter_area.get().map(filter => filter.slice(0, 4));
        }

        selected() {
            const filter = this.filters().find(f => f[0] === this.list.doctype && f[1] === this.config.field);
            if (!filter) return "@all";
            if (filter[2] === "is" && filter[3] === "not set") return "@without";
            return filter[2] === "=" ? `folder:${filter[3]}` : null;
        }

        folder_filter(value) {
            return [this.list.doctype, this.config.field,
                value === "@without" ? "is" : "=",
                value === "@without" ? "not set" : value.slice("folder:".length)];
        }

        async select(value) {
            const filters = this.filters().filter(f => !(f[0] === this.list.doctype && f[1] === this.config.field));
            if (value !== "@all") filters.push(this.folder_filter(value));
            // Native APIs preserve unrelated filters and persist the route normally.
            await this.list.filter_area.clear(false);
            await this.list.filter_area.set(filters);
            this.list.start = 0;
            this.list.on_filter_change();
            await this.list.refresh();
            this.render();
        }

        async reload() {
            this.branches.clear();
            this.expanded.clear();
            if (frappe.model.can_read(this.config.folder)) await this.load(this.config.root);
            else await this.refresh();
        }

        async load(parent, more = false) {
            const branch = this.branches.get(parent) || {rows: []};
            if (branch.loading) return;
            branch.loading = true;
            this.branches.set(parent, branch);
            const filters = [parent ? [this.config.parent, "=", parent] : [this.config.parent, "is", "not set"]];
            if (more && branch.rows.length) filters.push(["name", ">", branch.rows.at(-1).name]);
            try {
                const rows = await request("frappe.client.get_list", {doctype: this.config.folder,
                    fields: ["name", "folder_name"], filters, order_by: "name asc", limit_page_length: PAGE_SIZE + 1});
                branch.rows = (more ? branch.rows : []).concat(rows.slice(0, PAGE_SIZE));
                branch.more = rows.length > PAGE_SIZE;
                branch.error = false;
            } catch (error) {
                branch.error = true;
            } finally {
                branch.loading = false;
                this.render();
            }
            await this.refresh();
        }

        async toggle(name) {
            if (this.expanded.has(name)) this.expanded.delete(name);
            else {
                this.expanded.add(name);
                if (!this.branches.has(name)) await this.load(name);
            }
            this.render();
        }

        row(value, label, depth = 0, folder = false) {
            const key = folder ? `folder:${value}` : value;
            const active = this.selected() === key;
            const count = this.counts?.[key];
            return `<div class="reach-folder-row${active ? " active" : ""}" style="--folder-depth:${depth}">
                ${folder ? `<button type="button" class="reach-folder-toggle" data-expand="${escape(value)}" aria-expanded="${this.expanded.has(value)}" aria-label="${escape(__("Expand folder {0}", [label]))}">${frappe.utils.icon(this.expanded.has(value) ? "chevron-down" : "chevron-right", "xs")}</button>` : ""}
                <button type="button" class="reach-folder-select" data-select="${escape(key)}" ${active ? 'aria-current="page"' : ""} title="${escape(label)}">${frappe.utils.icon(folder || value === "@without" ? "folder-normal" : "list", "sm")}<span class="reach-folder-label">${escape(label)}</span></button>
                <span class="reach-folder-count text-muted">${count == null ? "" : escape(count)}</span></div>`;
        }

        renderBranch(parent, depth = 0, seen = new Set()) {
            if (seen.has(parent) || depth > 30) return "";
            const branch = this.branches.get(parent);
            if (!branch) return "";
            const visited = new Set([...seen, parent]);
            return branch.rows.map(row => this.row(row.name, row.folder_name, depth, true) +
                (this.expanded.has(row.name) ? this.renderBranch(row.name, depth + 1, visited) : "")).join("") +
                (branch.loading ? `<p class="text-muted">${__("Loading…")}</p>` : "") +
                (branch.error ? `<p class="text-muted">${__("Folders unavailable. Refresh to retry.")}</p>` : "") +
                (branch.more ? `<button type="button" class="reach-folder-action" data-more="${escape(parent)}">${__("Load more folders")}</button>` : "");
        }

        render() {
            this.$root.find(".reach-folder-nav").html(this.row("@all", __("All")) +
                this.row("@without", __("Without Folder")) + this.renderBranch(this.config.root));
            this.$root.find(".reach-folder-footer").html(
                frappe.model.can_create(this.config.folder) ? `<button type="button" class="reach-folder-action" data-action="new">${frappe.utils.icon("plus", "sm")}<span>${__("New folder")}</span></button>` : "");
        }

        async refresh() {
            this.render();
            const sequence = this.countSequence = (this.countSequence || 0) + 1;
            const filters = this.filters().filter(f => !(f[0] === this.list.doctype && f[1] === this.config.field));
            const names = [...this.branches.values()].flatMap(branch => branch.rows.map(row => row.name));
            try {
                const [all, without, grouped] = await Promise.all([
                    request("frappe.client.get_count", {doctype: this.list.doctype, filters}),
                    request("frappe.client.get_count", {doctype: this.list.doctype, filters: [...filters, this.folder_filter("@without")]}),
                    names.length ? request("frappe.client.get_list", {doctype: this.list.doctype,
                        fields: [this.config.field, {COUNT: "name", as: "folder_count"}], group_by: this.config.field,
                        filters: [...filters, [this.list.doctype, this.config.field, "in", names]], limit_page_length: names.length}) : [],
                ]);
                if (sequence !== this.countSequence) return;
                this.counts = {"@all": all, "@without": without};
                for (const name of names) this.counts[`folder:${name}`] = 0;
                for (const row of grouped) this.counts[`folder:${row[this.config.field]}`] = row.folder_count;
                this.render();
            } catch (error) {
                // Counts are optional; folder navigation remains usable.
                if (sequence === this.countSequence) { this.counts = {}; this.render(); }
            }
        }

        new_folder() {
            if (!frappe.model.can_create(this.config.folder)) return;
            const selected = this.selected();
            frappe.prompt([
                {fieldname: "folder_name", fieldtype: "Data", label: __("Folder Name"), reqd: 1},
                {fieldname: "parent", fieldtype: "Link", options: this.config.folder, label: __("Parent Folder"),
                    default: selected?.startsWith("folder:") ? selected.slice("folder:".length) : this.config.root, reqd: this.config.root ? 1 : 0},
            ], async values => {
                await frappe.call({method: "frappe.client.insert", args: {doc: {doctype: this.config.folder,
                    folder_name: values.folder_name.trim(), [this.config.parent]: values.parent || null,
                    ...(this.config.path ? {path: [values.parent, values.folder_name.trim()].filter(Boolean).join("/")} : {})}}});
                const parent = values.parent || this.config.root;
                this.branches.delete(parent);
                this.expanded.add(parent);
                await this.load(parent);
                frappe.show_alert({message: __("Folder created"), indicator: "green"});
            }, __("New Folder"), __("Create"));
        }
    }

    frappe.reach_folder_sidebar.setup = list => {
        if (!CONFIG[list.doctype] || !frappe.model.can_read(list.doctype) || list.folder_sidebar) return;
        list.folder_sidebar = new FolderSidebar(list);
    };
    frappe.reach_folder_sidebar.FolderSidebar = FolderSidebar;
})();
