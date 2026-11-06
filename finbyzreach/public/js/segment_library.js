// The same folder/subfolder navigation as the template library, using Desk controls.
frappe.provide("frappe.reach_segment_library");

(() => {
    const FOLDER = "Reach Segment Folder";
    const SEGMENT = "Reach Segment";
    const ROOT = "All Reach Segment Folders";
    const PAGE_SIZE = 50;
    const escape = value => frappe.utils.escape_html(String(value ?? ""));

    function new_folder(parent = ROOT, on_created) {
        if (!frappe.model.can_create(FOLDER)) return;
        frappe.prompt([
            { fieldname: "folder_name", fieldtype: "Data", label: __("Folder Name"), reqd: 1 },
            { fieldname: "parent", fieldtype: "Link", options: FOLDER, label: __("Parent Folder"), default: parent || ROOT, reqd: 1 },
        ], async values => {
            await frappe.call({ method: "frappe.client.insert", type: "POST", args: { doc: {
                doctype: FOLDER, folder_name: values.folder_name.trim(), parent_reach_segment_folder: values.parent,
            } } });
            frappe.show_alert({ message: __("Folder created"), indicator: "green" });
            on_created?.();
        }, __("New Folder"), __("Create"));
    }

    function move_segment(name, folder, on_moved) {
        frappe.prompt({ fieldname: "folder", fieldtype: "Link", options: FOLDER, label: __("Folder"),
            default: folder || "", description: __("Clear this field to move the segment to Without Folder.") }, async values => {
            await frappe.db.set_value(SEGMENT, name, "folder", values.folder || "");
            frappe.show_alert({ message: __("Segment moved"), indicator: "green" });
            on_moved?.();
        }, __("Move to Folder"), __("Move"));
    }

    class SegmentLibrary {
        constructor({ audience_doctype, on_select } = {}) {
            this.audience = audience_doctype;
            this.on_select = on_select;
            frappe.email_template_library.ensure_styles();
            this.path = [{ name: ROOT, label: __("All Folders") }];
            this.view_mode = "list";
            this.page = 0;
            this.sequence = 0;
            this.dialog = new frappe.ui.Dialog({ title: __("Segment Library"), size: "extra-large",
                fields: [{ fieldtype: "HTML", fieldname: "browser" }] });
            this.$root = this.dialog.fields_dict.browser.$wrapper;
            this.$root.html(`<div class="etl5 rs-library"><div class="etl5-main">
                <nav class="etl5-breadcrumb-container rs-library-breadcrumb" aria-label="${escape(__("Folder path"))}"></nav>
                <header class="etl5-toolbar rs-library-toolbar">
                    <div class="etl5-search-wrap">
                        <span class="etl5-search-icon">${frappe.utils.icon("search", "sm")}</span>
                        <input type="search" class="etl5-search rs-search" autocomplete="off" aria-label="${escape(__("Search segments and folders"))}" placeholder="${escape(__("Search segments and folders..."))}">
                        <button type="button" class="etl5-clear-search rs-library-clear" aria-label="${escape(__("Clear search"))}">×</button>
                    </div>
                    ${frappe.model.can_create(FOLDER) ? `<button type="button" class="btn btn-default btn-sm rs-library-new-folder">+ ${__("Folder")}</button>` : ""}
                    ${frappe.model.can_create(SEGMENT) ? `<button type="button" class="btn btn-primary btn-sm rs-library-new">+ ${__("Segment")}</button>` : ""}
                    <button type="button" class="btn btn-default btn-sm rs-library-tree" title="${escape(__("Manage Folders"))}" aria-label="${escape(__("Manage Folders"))}">${frappe.utils.icon("list", "sm")}</button>
                </header>
                <div class="etl5-content rs-library-body"></div>
                <div class="rs-pagination rs-library-pagination">
                    <button type="button" class="btn btn-default btn-sm rs-library-prev">${__("Previous")}</button>
                    <span class="rs-library-page"></span><button type="button" class="btn btn-default btn-sm rs-library-next">${__("Next")}</button>
                </div>
            </div></div>`);
            this.$root.on("click", "[data-folder]", event => {
                if ($(event.target).closest("[data-new-child]").length) return;
                const folder = this.folders[Number($(event.currentTarget).attr("data-folder"))];
                this.path.push({ name: folder.name, label: folder.folder_name });
                this.navigate();
            });
            this.$root.on("click", "[data-new-child]", event => {
                event.stopPropagation();
                const folder = this.folders[Number($(event.currentTarget).attr("data-new-child"))];
                new_folder(folder.name, () => this.load());
            });
            this.$root.on("keydown", ".etl5-folder-card", event => {
                if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    event.currentTarget.click();
                }
            });
            this.$root.on("click", "[data-view]", event => this.setView($(event.currentTarget).attr("data-view")));
            this.$root.on("click", "[data-crumb]", event => {
                this.path = this.path.slice(0, Number($(event.currentTarget).attr("data-crumb")) + 1);
                this.navigate();
            });
            this.$root.on("click", ".rs-library-unfiled", () => {
                this.path = [this.path[0], { name: "", label: __("Without Folder") }];
                this.navigate();
            });
            this.$root.on("click", "[data-segment]", event => {
                const row = this.segments[Number($(event.currentTarget).attr("data-segment"))];
                this.dialog.hide();
                if (this.on_select) this.on_select(row.name);
                else frappe.set_route("Form", SEGMENT, row.name);
            });
            this.$root.on("click", "[data-move]", event => {
                const row = this.segments[Number($(event.currentTarget).attr("data-move"))];
                move_segment(row.name, row.folder, () => this.load());
            });
            this.$root.find(".rs-search").on("input", () => {
                clearTimeout(this.searchTimer);
                ++this.sequence;
                this.searchTimer = setTimeout(() => { this.page = 0; this.load(); }, 300);
            });
            this.$root.find(".rs-library-clear").on("click", () => {
                clearTimeout(this.searchTimer);
                this.$root.find(".rs-search").val("");
                this.page = 0;
                this.load();
            });
            this.$root.find(".rs-library-prev").on("click", () => { if (this.page) { this.page--; this.load(); } });
            this.$root.find(".rs-library-next").on("click", () => { this.page++; this.load(); });
            this.$root.find(".rs-library-new-folder").on("click", () => new_folder(this.folder || ROOT, () => this.load()));
            this.$root.find(".rs-library-new").on("click", () => {
                this.dialog.hide();
                frappe.new_doc(SEGMENT, { folder: this.folder || "", ...(this.audience ? { audience_doctype: this.audience } : {}) });
            });
            this.$root.find(".rs-library-tree").on("click", () => { this.dialog.hide(); frappe.set_route("Tree", FOLDER); });
            this.dialog.show();
            this.load();
        }

        get folder() { return this.path[this.path.length - 1].name; }

        navigate() {
            clearTimeout(this.searchTimer);
            this.page = 0;
            this.$root.find(".rs-search").val("");
            this.load();
        }

        async load() {
            const request = ++this.sequence;
            const search = this.$root.find(".rs-search").val().trim();
            const folder = this.folder;
            const filters = [["archived", "=", 0], folder ? ["folder", "=", folder] : ["folder", "is", "not set"]];
            if (this.audience) filters.push(["audience_doctype", "=", this.audience]);
            if (search) filters.push(["name", "like", `%${search}%`]);
            const folderFilters = [["parent_reach_segment_folder", "=", folder]];
            if (search) folderFilters.push(["folder_name", "like", `%${search}%`]);
            const getList = async (doctype, fields, filters) => {
                const { message } = await frappe.call({ method: "frappe.client.get_list", type: "GET", args: {
                    doctype, fields, filters, order_by: "name asc", limit_start: this.page * PAGE_SIZE, limit_page_length: PAGE_SIZE + 1,
                } });
                return message || [];
            };
            this.$root.find(".rs-library-body").text(__("Loading…"));
            this.$root.find(".rs-library-prev,.rs-library-next").prop("disabled", true);
            this.$root.find(".rs-library-clear").toggle(Boolean(search));
            this.$root.find(".rs-library-breadcrumb").html(`<div class="etl5-breadcrumb">${this.path.map((crumb, index) =>
                `<button type="button" class="etl5-crumb ${index === this.path.length - 1 ? "current" : ""}" data-crumb="${index}" ${index === this.path.length - 1 ? 'aria-current="page" disabled' : ""}>${escape(crumb.label)}</button>`).join('<span class="etl5-divider">/</span>')}</div>`);
            try {
                const [folders, segments] = await Promise.all([
                    folder ? getList(FOLDER, ["name", "folder_name"], folderFilters) : Promise.resolve([]),
                    getList(SEGMENT, ["name", "folder", "audience_doctype", "segment_type", "member_count"], filters),
                ]);
                if (request !== this.sequence) return;
                this.folders = folders.slice(0, PAGE_SIZE);
                this.segments = segments.slice(0, PAGE_SIZE);
                this.search = search;
                this.moreFolders = folders.length > PAGE_SIZE;
                this.moreSegments = segments.length > PAGE_SIZE;
                this.render();
                this.$root.find(".rs-library-page").text(__("Page {0}", [this.page + 1]));
                this.$root.find(".rs-library-prev").prop("disabled", !this.page);
                this.$root.find(".rs-library-next").prop("disabled", folders.length > PAGE_SIZE || segments.length > PAGE_SIZE ? false : true);
            } catch (error) {
                if (request === this.sequence) this.$root.find(".rs-library-body").text(__("Unable to load folders. Check folder permissions and run the segment folder migration."));
            }
        }

        setView(mode) {
            if (!["list", "grid"].includes(mode) || mode === this.view_mode) return;
            this.view_mode = mode;
            if (this.folders && this.segments) this.render();
        }

        render() {
            const card = (label, index) => `<div class="etl5-folder-card ${index === null ? "etl5-no-folder rs-library-unfiled" : ""}" role="button" tabindex="0" ${index === null ? "" : `data-folder="${index}"`}>
                <div class="etl5-folder-icon">${frappe.utils.icon("folder-normal", "md")}</div>
                <div class="etl5-folder-text"><div class="etl5-folder-name" title="${escape(label)}">${escape(label)}</div></div>
                <div class="etl5-folder-arrow" aria-hidden="true">›</div>
                ${index !== null && frappe.model.can_create(FOLDER) ? `<button type="button" class="etl5-add-child" data-new-child="${index}" title="${escape(__("Add subfolder"))}" aria-label="${escape(__("Add subfolder"))}">+</button>` : ""}
            </div>`;
            const unfiled = this.folder === ROOT && this.page === 0 && (!this.search || __("Without Folder").toLowerCase().includes(this.search.toLowerCase()));
            const folderCount = this.folders.length + Number(unfiled);
            const folderSection = folderCount ? `<section class="etl5-section">
                <div class="etl5-section-head"><div class="rs-library-section-title">${__("Folders")} (${folderCount}${this.moreFolders ? "+" : ""})</div>
                    <div class="text-muted small flex align-items-center"><span>${__("View")}</span><div class="btn-group ml-2" role="group" aria-label="${escape(__("Folder view"))}">
                        ${["grid", "list"].map(mode => `<button type="button" class="btn btn-default btn-xs ${mode === this.view_mode ? "active" : ""}" data-view="${mode}" title="${escape(mode === "grid" ? __("Grid view") : __("List view"))}" aria-pressed="${mode === this.view_mode}">${frappe.utils.icon(mode, "sm")}</button>`).join("")}
                    </div></div>
                </div><div class="etl5-folder-grid ${this.view_mode === "list" ? "is-list-view" : ""}">
                    ${this.folders.map((row, index) => card(row.folder_name, index)).join("")}${unfiled ? card(__("Without Folder"), null) : ""}
                </div></section>` : "";
            const rows = this.segments.map((row, index) => `<tr>
                <td title="${escape(row.name)}"><button type="button" class="btn btn-link rs-library-segment" data-segment="${index}">${escape(row.name)}</button></td>
                <td>${escape(__(row.audience_doctype))}</td><td>${escape(__(row.segment_type))}</td><td>${escape(row.member_count)}</td>
                ${frappe.model.can_write(SEGMENT) ? `<td><button type="button" class="btn btn-default btn-xs" data-move="${index}">${__("Move")}</button></td>` : ""}</tr>`).join("");
            const empty = `<div class="etl5-empty"><div class="etl5-empty-title">${this.search ? __("No matching segments") : __("No segments in this folder")}</div><div class="etl5-empty-help">${this.search ? __("Try another search term.") : __("Create a segment to get started.")}</div></div>`;
            const segmentSection = this.segments.length || this.folder !== ROOT || this.search ? `<section class="etl5-section">
                <div class="etl5-section-head"><div class="rs-library-section-title">${__("Segments")} (${this.segments.length}${this.moreSegments ? "+" : ""})</div></div>
                ${rows ? `<div class="rs-library-table-wrap"><table class="table table-bordered rs-library-table"><thead><tr><th>${__("Segment")}</th><th>${__("Audience")}</th><th>${__("Type")}</th><th>${__("Members")}</th>${frappe.model.can_write(SEGMENT) ? `<th>${__("Actions")}</th>` : ""}</tr></thead><tbody>${rows}</tbody></table></div>` : empty}
            </section>` : "";
            this.$root.find(".rs-library-body").html(folderSection + segmentSection);
        }

    }

    frappe.reach_segment_library.open = options => {
        if (!frappe.model.can_read(SEGMENT) || !frappe.model.can_read(FOLDER)) return frappe.msgprint(__("Segment and folder read access is required."));
        return new SegmentLibrary(options);
    };
    frappe.reach_segment_library.new_folder = new_folder;
})();
