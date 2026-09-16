frappe.provide("frappe.email_template_library");

(function () {
	"use strict";

	
	// Exact DocType configuration supplied by the project
	

	const EMAIL = "Email Template";
	const MASTER = "Email Template Master";
	const FOLDER = "Email Template Folder";

	// This is a REAL persisted root document in Email Template Folder.
	const ROOT_FOLDER = "All Email Template Folders";

	// Exact Email Template Folder fields.
	const FOLDER_NAME_FIELD = "folder_name";
	const PARENT_FIELD = "parent_email_template_folder";
	const IS_GROUP_FIELD = "is_group";
	const LFT_FIELD = "lft";
	const RGT_FIELD = "rgt";

	const TEMPLATE_PAGE_LENGTH = 24;
	const FOLDER_FETCH_PAGE_LENGTH = 200;
	const SEARCH_DELAY = 300;
	const LOAD_MORE_THRESHOLD = 220;

	const REPORTVIEW_GET_LIST = "frappe.desk.reportview.get_list";

	// Keep existing custom business logic.
	const CREATE_EMAIL_FROM_MASTER_METHOD =
		"finbyzreach.email_template_builder.library.create_email_from_master";

	const CREATE_MASTER_FROM_EMAIL_METHOD =
		"finbyzreach.email_template_builder.library.create_master_from_email";

	const CREATE_VISUAL_TEMPLATE_METHOD =
		"finbyzreach.email_template_builder.api.create_visual_template";

	const GET_MASTER_PREVIEW_METHOD =
		"finbyzreach.email_template_builder.library.get_master_preview";

	
	// Helpers
	

	function escape_html(value) {
		return $("<div>").text(value == null ? "" : String(value)).html();
	}

	function escape_attr(value) {
		return escape_html(value).replace(/`/g, "&#96;");
	}

	function icon(name, size = "sm") {
		try {
			return frappe.utils?.icon?.(name, size) || "";
		} catch (e) {
			return "";
		}
	}

	function debounce(fn, wait) {
		let timer = null;

		return function (...args) {
			clearTimeout(timer);
			timer = setTimeout(() => fn.apply(this, args), wait);
		};
	}

	function pretty_date(value) {
		if (!value) return "";

		try {
			return frappe.datetime?.prettyDate?.(value) || value;
		} catch (e) {
			return value;
		}
	}

	function permission_error(action, doctype) {
		frappe.msgprint({
			title: __("Not Permitted"),
			message: __(
				"You do not have permission to {0} {1}.",
				[action, doctype]
			),
			indicator: "red",
		});
	}

	
	// Permission helpers
	
	//
	// These only control the UI. Report View, frappe.client.insert and the
	// project's custom methods still perform the real server-side checks.
	

	function get_boot_permission(action) {
		const user = frappe.boot?.user || {};

		const keys = {
			read: ["can_read"],
			write: ["can_write"],
			create: ["can_create"],
			delete: ["can_delete"],
			report: ["can_get_report", "can_report"],
		}[action] || [`can_${action}`];

		for (const key of keys) {
			if (user[key] !== undefined) {
				return user[key];
			}
		}

		return undefined;
	}

	function can(doctype, action) {
		const value = get_boot_permission(action);

		if (Array.isArray(value)) {
			return value.includes(doctype);
		}

		if (
			value &&
			typeof value === "object" &&
			Object.prototype.hasOwnProperty.call(value, doctype)
		) {
			return Boolean(value[doctype]);
		}

		try {
			const fn = frappe.model?.[`can_${action}`];

			if (typeof fn === "function") {
				return Boolean(fn(doctype));
			}
		} catch (e) {}

		// Avoid hiding valid actions if this Frappe build does not expose the
		// relevant permission array in boot. The server is still authoritative.
		return true;
	}

	function get_permissions() {
		return {
			master: {
				read: can(MASTER, "read"),
				create: can(MASTER, "create"),
				write: can(MASTER, "write"),
				delete: can(MASTER, "delete"),
			},
			email: {
				read: can(EMAIL, "read"),
				create: can(EMAIL, "create"),
				write: can(EMAIL, "write"),
			},
			folder: {
				read: can(FOLDER, "read"),
				create: can(FOLDER, "create"),
				write: can(FOLDER, "write"),
				delete: can(FOLDER, "delete"),
			},
		};
	}

	
	// Builder navigation
	

	function open_builder(template_name, template_doctype = EMAIL) {
		if (!template_name) return;

		const params = new URLSearchParams({
			template: template_name,
		});

		if (template_doctype === MASTER) {
			params.set("template_doctype", MASTER);
		}

		window.location.href = `/builder?${params.toString()}`;
	}

	
	// Create Email from Master
	

	function create_from_master(
		master_name,
		master_subject = "",
		{ on_cancel = null } = {}
	) {
		const perm = get_permissions();

		if (!perm.master.read) {
			permission_error("read", MASTER);
			return;
		}

		if (!perm.email.create) {
			permission_error("create", EMAIL);
			return;
		}

		let completed = false;

		const dialog = new frappe.ui.Dialog({
			title: __("Use Template"),
			fields: [
				{
					fieldname: "selected_master_html",
					fieldtype: "HTML",
					options: `
						<div style="padding:12px 14px;margin-bottom:8px;border:1px solid var(--border-color);border-radius:8px;background:var(--subtle-fg);">
							<div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;">${__("Selected master")}</div>
							<div style="margin-top:3px;font-weight:650;">${escape_html(master_name)}</div>
							${master_subject ? `<div style="margin-top:3px;font-size:12px;color:var(--text-muted);">${escape_html(master_subject)}</div>` : ""}
						</div>
					`,
				},
				{
					fieldname: "master_name",
					fieldtype: "Data",
					hidden: 1,
					default: master_name,
				},
				{
					fieldname: "template_name",
					fieldtype: "Data",
					label: __("New Email Name"),
					reqd: 1,
					default: `${master_name} - ${Math.random().toString(36).substring(2, 8).toUpperCase()}`,
					placeholder: __("Enter a unique name"),
					description: __("This creates a separate Email Template. Future master edits will not change it."),
				},
				{
					fieldname: "subject",
					fieldtype: "Data",
					label: __("Email Subject"),
					reqd: 1,
					default: master_subject || master_name,
					placeholder: __("Write the subject for this email"),
				},
			],
			primary_action_label: __("Create and Open Builder"),

			async primary_action(values) {
				try {
					const response = await frappe.call({
						method: CREATE_EMAIL_FROM_MASTER_METHOD,
						args: { ...values, master_name },
						freeze: true,
						freeze_message: __("Creating email from master..."),
					});

					if (!response.message?.name) return;

					completed = true;
					dialog.hide();

					if (response.message.route) {
						window.location.href = response.message.route;
						return;
					}

					open_builder(response.message.name, EMAIL);
				} catch (error) {
					completed = false;
					console.error(error);
				}
			},
		});

		dialog.onhide = () => {
			if (!completed && typeof on_cancel === "function") on_cancel();
		};

		dialog.show();
		dialog.fields_dict.template_name?.$input?.trigger("focus");
	}

	
	// New Master Template
	
	//
	// default_folder is preselected when creating inside a folder.
	// The Folder Link remains editable/clearable, so the user can intentionally
	// create the template without a folder.
	

	function new_master(default_folder = "") {
		const perm = get_permissions();

		if (!perm.master.create) {
			permission_error("create", MASTER);
			return;
		}

		let autofill_subject = true;

		const fields = [
			{
				fieldname: "template_name",
				fieldtype: "Data",
				label: __("Template Name"),
				reqd: 1,
			},
			{
				fieldname: "subject",
				fieldtype: "Data",
				label: __("Subject"),
				reqd: 1,
			},
		];

		if (perm.folder.read) {
			fields.push({
				fieldname: "folder",
				fieldtype: "Link",
				label: __("Folder"),
				options: FOLDER,
				default: default_folder || "",
				description: __(
					"Optional. Clear the folder to create this template without a folder."
				),
				get_query: () => ({
					filters: {
						[IS_GROUP_FIELD]: 1,
					},
				}),
			});
		}

		const dialog = new frappe.ui.Dialog({
			title: __("New Master Template"),
			fields,
			primary_action_label: __("Create and Open Builder"),

			async primary_action(values) {
				try {
					const response = await frappe.call({
						method: CREATE_VISUAL_TEMPLATE_METHOD,
						args: {
							...values,
							template_doctype: MASTER,
						},
						freeze: true,
						freeze_message: __("Creating master template..."),
					});

					if (!response.message?.name) return;

					dialog.hide();

					if (response.message.route) {
						window.location.href = response.message.route;
						return;
					}

					open_builder(response.message.name, MASTER);
				} catch (error) {
					console.error(error);
				}
			},
		});

		dialog.show();

		dialog.fields_dict.subject.$input.on("input", () => {
			autofill_subject = !dialog.get_value("subject");
		});

		dialog.fields_dict.template_name.$input.on("input", () => {
			if (autofill_subject) {
				void dialog.set_value(
					"subject",
					dialog.get_value("template_name") || ""
				);
			}
		});
	}

	
	// Create Folder / Subfolder
	
	//
	// Exact Tree rules from the supplied DocType:
	//   autoname: field:folder_name
	//   parent field: parent_email_template_folder
	//   every normal folder is a group
	//
	// The real root already exists as:
	//   All Email Template Folders
	//
	// Therefore:
	//   New folder from root -> parent = All Email Template Folders
	//   New folder in TEST   -> parent = TEST
	

	function create_folder({
		parent_folder = ROOT_FOLDER,
		on_created = null,
	} = {}) {
		const perm = get_permissions();

		if (!perm.folder.create) {
			permission_error("create", FOLDER);
			return;
		}

		const effective_parent = parent_folder || ROOT_FOLDER;

		const dialog = new frappe.ui.Dialog({
			title:
				effective_parent === ROOT_FOLDER
					? __("New Folder")
					: __("New Subfolder in {0}", [effective_parent]),

			fields: [
				{
					fieldname: FOLDER_NAME_FIELD,
					fieldtype: "Data",
					label: __("Folder Name"),
					reqd: 1,
				},
				{
					fieldname: PARENT_FIELD,
					fieldtype: "Link",
					label: __("Parent Folder"),
					options: FOLDER,
					reqd: 1,
					default: effective_parent,
					description: __(
						"Choose where this folder should be created."
					),
					get_query: () => ({
						filters: {
							[IS_GROUP_FIELD]: 1,
						},
					}),
				},
			],

			primary_action_label: __("Create Folder"),

			async primary_action(values) {
				const folder_name = (values[FOLDER_NAME_FIELD] || "").trim();
				const parent = values[PARENT_FIELD] || ROOT_FOLDER;

				if (!folder_name) return;

				if (folder_name === ROOT_FOLDER) {
					frappe.msgprint({
						title: __("Invalid Folder Name"),
						message: __(
							"{0} is the existing root folder.",
							[ROOT_FOLDER]
						),
						indicator: "orange",
					});
					return;
				}

				const doc = {
					doctype: FOLDER,
					[FOLDER_NAME_FIELD]: folder_name,
					[PARENT_FIELD]: parent,
					[IS_GROUP_FIELD]: 1,
				};

				try {
					const response = await frappe.call({
						method: "frappe.client.insert",
						args: { doc },
						freeze: true,
						freeze_message: __("Creating folder..."),
					});

					if (!response.message?.name) return;

					dialog.hide();

					if (typeof on_created === "function") {
						await on_created(response.message);
					}
				} catch (error) {
					console.error(error);
				}
			},
		});

		dialog.show();
	}

	function new_folder(parent_folder = ROOT_FOLDER) {
		create_folder({ parent_folder });
	}

	
	// Create Master from an existing Email
	

	function create_master_from_email(template_name, default_name = "") {
		const perm = get_permissions();

		if (!perm.master.create) {
			permission_error("create", MASTER);
			return;
		}

		const fields = [
			{
				fieldname: "master_name",
				fieldtype: "Data",
				label: __("Master Template Name"),
				reqd: 1,
				default: default_name || template_name,
			},
		];

		if (perm.folder.read) {
			fields.push({
				fieldname: "folder",
				fieldtype: "Link",
				label: __("Folder"),
				options: FOLDER,
				description: __("Optional"),
				get_query: () => ({
					filters: {
						[IS_GROUP_FIELD]: 1,
					},
				}),
			});
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Create Master from Email"),
			fields,
			primary_action_label: __("Create Master and Open Builder"),

			async primary_action(values) {
				try {
					const response = await frappe.call({
						method: CREATE_MASTER_FROM_EMAIL_METHOD,
						args: {
							...values,
							template_name,
						},
						freeze: true,
						freeze_message: __(
							"Creating independent master template..."
						),
					});

					if (!response.message?.name) return;

					dialog.hide();

					if (response.message.route) {
						window.location.href = response.message.route;
						return;
					}

					open_builder(response.message.name, MASTER);
				} catch (error) {
					console.error(error);
				}
			},
		});

		dialog.show();
	}

	
	// Styles
	

	function ensure_styles() {
		if ($("#email-template-library-tree-v5-styles").length) return;

		$("head").append(`
			<style id="email-template-library-tree-v5-styles">

				.etl5 {
					display:flex;
					height:min(77vh,840px);
					min-height:570px;
					overflow:hidden;
					background:var(--fg-color);
				}

				.etl5-main {
					min-width:0;
					flex:1;
					display:flex;
					flex-direction:column;
				}

				.etl5-toolbar {
					display:flex;
					align-items:center;
					gap:10px;
					min-height:68px;
					padding:12px 18px;
					border-bottom:1px solid var(--border-color);
					background:var(--fg-color);
				}

				.etl5-heading {
					min-width:190px;
					max-width:280px;
				}

				.etl5-title {
					overflow:hidden;
					font-size:14px;
					font-weight:650;
					text-overflow:ellipsis;
					white-space:nowrap;
				}

				.etl5-subtitle {
					margin-top:2px;
					color:var(--text-muted);
					font-size:11px;
				}

				.etl5-search-wrap {
					position:relative;
					min-width:190px;
					flex:1;
				}

				.etl5-search {
					width:100%;
					height:36px;
					padding:7px 34px;
					border:1px solid var(--border-color);
					border-radius:8px;
					outline:none;
					background:var(--control-bg);
					color:var(--text-color);
				}

				.etl5-search:focus {
					border-color:var(--primary);
					box-shadow:0 0 0 1px var(--primary);
				}

				.etl5-search-icon {
					position:absolute;
					left:11px;
					top:50%;
					display:flex;
					transform:translateY(-50%);
					color:var(--text-muted);
					pointer-events:none;
				}

				.etl5-clear-search {
					position:absolute;
					right:6px;
					top:50%;
					display:none;
					width:27px;
					height:27px;
					align-items:center;
					justify-content:center;
					transform:translateY(-50%);
					border:0;
					border-radius:6px;
					background:transparent;
					color:var(--text-muted);
					cursor:pointer;
				}

				.etl5-content {
					flex:1;
					overflow-y:auto;
					padding:18px 20px 24px;
					background:var(--fg-color);
				}

				.etl5-breadcrumb {
					display:flex;
					align-items:center;
					flex-wrap:wrap;
					gap:0;
					margin-bottom:0;
					font-size:13px;
				}

				.etl5-crumb {
					border:0;
					background:transparent;
					padding:0;
					color:var(--primary);
					cursor:pointer;
				}

				.etl5-crumb:hover {
					text-decoration:underline;
				}

				.etl5-crumb.current {
					color:var(--text-muted);
					font-weight:normal;
					cursor:default;
				}

				.etl5-crumb.current:hover {
					text-decoration:none;
				}

				.etl5-divider {
					color:var(--text-light);
					margin: 0 6px;
				}

				.etl5-section {
					margin-bottom:25px;
				}

				.etl5-section:last-child {
					margin-bottom:0;
				}

				.etl5-section-head {
					display:flex;
					align-items:center;
					justify-content:space-between;
					gap:12px;
					margin-bottom:11px;
				}

				.etl5-section-title {
					font-size:11px;
					font-weight:700;
					letter-spacing:.07em;
					text-transform:uppercase;
					color:var(--text-muted);
				}

				.etl5-folder-grid,
				.etl5-template-grid {
					display:grid;
					grid-template-columns:repeat(auto-fill,minmax(215px,1fr));
					gap:14px;
				}

				.etl5-folder-grid.is-list-view {
					grid-template-columns: 1fr;
				}

				.etl5-folder-card {
					position:relative;
					display:flex;
					min-height:88px;
					align-items:center;
					gap:13px;
					padding:14px 46px 14px 14px;
					border:1px solid var(--border-color);
					border-radius:10px;
					background:var(--card-bg,var(--fg-color));
					cursor:pointer;
					transition:
						transform .15s ease,
						border-color .15s ease,
						box-shadow .15s ease;
				}

				.etl5-folder-card:hover {
					transform:translateY(-1px);
					border-color:var(--primary);
					box-shadow:0 4px 14px rgba(0,0,0,.07);
				}

				.etl5-folder-icon {
					width:42px;
					height:42px;
					flex:none;
					display:flex;
					align-items:center;
					justify-content:center;
					border-radius:9px;
					background:var(--control-bg);
					color:var(--text-color);
				}

				.etl5-folder-text {
					min-width:0;
					flex:1;
				}

				.etl5-folder-name {
					overflow:hidden;
					font-size:13px;
					font-weight:650;
					text-overflow:ellipsis;
					white-space:nowrap;
				}

				.etl5-folder-help {
					margin-top:3px;
					color:var(--text-muted);
					font-size:11px;
				}

				.etl5-folder-arrow {
					color:var(--text-muted);
					font-size:18px;
				}

				.etl5-add-child {
					position:absolute;
					right:9px;
					top:50%;
					z-index:2;
					display:none;
					width:30px;
					height:30px;
					align-items:center;
					justify-content:center;
					transform:translateY(-50%);
					border:1px solid var(--border-color);
					border-radius:7px;
					background:var(--fg-color);
					color:var(--text-color);
					cursor:pointer;
				}

				.etl5-folder-card:hover .etl5-add-child {
					display:flex;
				}

				.etl5-no-folder {
					border-style:dashed;
				}

				.etl5-template-card {
					position:relative;
					overflow:hidden;
					border:1px solid var(--border-color);
					border-radius:10px;
					background:var(--card-bg,var(--fg-color));
					cursor:pointer;
					transition:
						transform .15s ease,
						border-color .15s ease,
						box-shadow .15s ease;
				}

				.etl5-template-card:hover {
					transform:translateY(-2px);
					border-color:var(--primary);
					box-shadow:0 6px 18px rgba(0,0,0,.08);
				}

				.etl5-preview {
					position:relative;
					height:158px;
					display:flex;
					align-items:center;
					justify-content:center;
					overflow:hidden;
					border-bottom:1px solid var(--border-color);
					background:var(--control-bg);
				}

				.etl5-preview img {
					width:100%;
					height:100%;
					object-fit:cover;
					object-position:top center;
				}

				.etl5-live-preview {
					position:absolute;
					inset:0;
					overflow:hidden;
					background:#fff;
				}

				.etl5-live-preview iframe {
					position:absolute;
					top:0;
					left:0;
					width:900px;
					height:650px;
					transform-origin: 0 0;
					border:0;
					background:#fff;
					pointer-events:none;
				}

				.etl5-preview-loading {
					width:72%;
					height:104px;
					border-radius:7px;
					background:linear-gradient(90deg,var(--control-bg),var(--fg-color),var(--control-bg));
					background-size:200% 100%;
					animation:etl5-shimmer 1.2s linear infinite;
				}

				@keyframes etl5-shimmer {
					to { background-position:-200% 0; }
				}

				.etl5-placeholder {
					text-align:center;
					color:var(--text-muted);
				}

				.etl5-overlay {
					position:absolute;
					inset:0;
					display:flex;
					align-items:center;
					justify-content:center;
					background:rgba(17,24,39,.52);
					opacity:0;
					transition:opacity .15s ease;
				}

				.etl5-template-card:hover .etl5-overlay {
					opacity:1;
				}

				.etl5-use {
					padding:8px 13px;
					border-radius:7px;
					background:#fff;
					color:#111827;
					font-size:12px;
					font-weight:650;
				}

				.etl5-template-body {
					padding:11px 12px 12px;
				}

				.etl5-template-name,
				.etl5-template-subject {
					overflow:hidden;
					text-overflow:ellipsis;
					white-space:nowrap;
				}

				.etl5-template-name {
					font-size:13px;
					font-weight:650;
				}

				.etl5-template-subject {
					margin-top:4px;
					color:var(--text-muted);
					font-size:11px;
				}

				.etl5-template-meta {
					display:flex;
					align-items:center;
					justify-content:space-between;
					gap:8px;
					margin-top:9px;
					color:var(--text-muted);
					font-size:10px;
				}

				.etl5-template-edit {
					position:absolute;
					right:7px;
					top:7px;
					z-index:2;
					display:none;
					width:30px;
					height:30px;
					align-items:center;
					justify-content:center;
					border:1px solid rgba(255,255,255,.8);
					border-radius:7px;
					background:#fff;
					color:#111827;
					cursor:pointer;
					box-shadow:0 2px 7px rgba(0,0,0,.1);
				}

				.etl5-template-card:hover .etl5-template-edit {
					display:flex;
				}

				.etl5-empty {
					min-height:235px;
					display:flex;
					flex-direction:column;
					align-items:center;
					justify-content:center;
					padding:28px;
					text-align:center;
					color:var(--text-muted);
				}

				.etl5-empty-title {
					margin-top:9px;
					color:var(--text-color);
					font-size:14px;
					font-weight:650;
				}

				.etl5-empty-help {
					max-width:410px;
					margin-top:5px;
					font-size:12px;
					line-height:1.5;
				}

				.etl5-pagination {
					display:flex;
					min-height:52px;
					align-items:center;
					justify-content:center;
					padding-top:12px;
				}

				.etl5-view-toggle.btn-group {
					background-color: var(--control-bg, #f3f4f6);
					border-radius: 14px;
					padding: 3px;
					display: inline-flex;
					border: none;
					box-shadow: none;
				}

				.etl5-view-toggle.btn-group .btn {
					border: none !important;
					background: transparent !important;
					box-shadow: none !important;
					color: var(--text-muted);
					border-radius: 12px !important;
					padding: 3px 10px !important;
					margin: 0 !important;
					display: flex;
					align-items: center;
					justify-content: center;
				}

				.etl5-view-toggle.btn-group .btn:hover {
					color: var(--text-color);
				}

				.etl5-view-toggle.btn-group .btn.active {
					background-color: var(--fg-color, #ffffff) !important;
					color: var(--text-color) !important;
					box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06) !important;
				}


				@media(max-width:850px) {
					.etl5-toolbar {
						flex-wrap:wrap;
					}

					.etl5-heading {
						width:100%;
						max-width:none;
					}

					.etl5-search-wrap {
						flex-basis:55%;
					}

					.etl5-folder-grid,
					.etl5-template-grid {
						grid-template-columns:repeat(auto-fill,minmax(175px,1fr));
					}

				}

				@media(max-width:600px) {
					.etl5-folder-grid,
					.etl5-template-grid {
						grid-template-columns:1fr;
					}
				}

			</style>
		`);
	}

	
	// Library
	

	function choose_master({ initial_action = "", initial_folder = ROOT_FOLDER } = {}) {
		const perm = get_permissions();

		if (!perm.master.read) {
			permission_error("read", MASTER);
			return;
		}

		ensure_styles();

		const state = {
			// Complete folder tree loaded from server.
			folders: [],
			folder_map: new Map(),

			// Current navigation location.
			current_folder: ROOT_FOLDER,
			virtual_no_folder: false,
			breadcrumb: [],
			view_mode: "list",

			// Search applies only to current location.
			search: "",

			// Template pagination.
			start: 0,
			page_length: TEMPLATE_PAGE_LENGTH,
			has_more: true,
			loading: false,
			loaded_count: 0,

			// Async stale-response protection.
			generation: 0,
		};

		const dialog = new frappe.ui.Dialog({
			title: __("Email Template Library"),
			size: "extra-large",
			on_hide: () => {
				preview_observer?.disconnect();
			},
			fields: [
				{
					fieldname: "library_html",
					fieldtype: "HTML",
				},
			],
		});

		const $wrapper = dialog.fields_dict.library_html.$wrapper;

		$wrapper.html(`
			<div class="etl5">

				<div class="etl5-main">
				
					<div class="etl5-breadcrumb-container" style="padding: 16px 18px 0;"></div>

					<header class="etl5-toolbar" style="padding-top: 10px; border-bottom: none;">

						<div class="etl5-search-wrap">

							<span class="etl5-search-icon">
								${icon("search", "sm")}
							</span>

							<input
								type="search"
								class="etl5-search"
								autocomplete="off"
								placeholder="${escape_attr(
									__("Search templates and folders...")
								)}"
							>

							<button
								type="button"
								class="etl5-clear-search"
								title="${escape_attr(__("Clear search"))}"
							>
								×
							</button>

						</div>

						${
							perm.folder.create
								? `
									<button
										type="button"
										class="btn btn-default btn-sm etl5-new-folder"
									>
										+ ${__("Folder")}
									</button>
								`
								: ""
						}

						${
							perm.master.create
								? `
									<button
										type="button"
										class="btn btn-primary btn-sm etl5-new-template"
									>
										+ ${__("Template")}
									</button>
								`
								: ""
						}

					</header>

					<div class="etl5-content"></div>

				</div>

			</div>
		`);

		const $content = $wrapper.find(".etl5-content");
		const $title = $wrapper.find(".etl5-title");
		const $subtitle = $wrapper.find(".etl5-subtitle");
		const $search = $wrapper.find(".etl5-search");
		const $clear_search = $wrapper.find(".etl5-clear-search");
		const preview_cache = new Map();
		const preview_requests = new Map();

		async function get_master_preview(master_name) {
			if (preview_cache.has(master_name)) {
				return preview_cache.get(master_name);
			}
			if (preview_requests.has(master_name)) {
				return preview_requests.get(master_name);
			}

			// frappe.call() returns a jQuery promise in some versions, which lacks .finally()
			const request = (async () => {
				try {
					const response = await frappe.call({
						method: GET_MASTER_PREVIEW_METHOD,
						type: "GET",
						args: { master_name },
					});
					const preview = response.message || {};
					preview_cache.set(master_name, preview);
					return preview;
				} finally {
					preview_requests.delete(master_name);
				}
			})();

			preview_requests.set(master_name, request);
			return request;
		}

		function with_preview_fit_styles(html) {
			const safe_html = (html || "")
				.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
				.replace(/\s+on[a-z]+=("[^"]*"|'[^']*'|[^\s>]+)/gi, "")
				.replace(/{%[\s\S]*?%}/g, "");
			
			const preview_styles = [
				'<style id="etb-preview-fit">',
				'html,body{height:auto!important;min-height:0!important;overflow:hidden!important;background:transparent!important;}',
				'body{display:block!important;margin:0!important;padding:0!important;}',
				'body>table[role="presentation"]{height:auto!important;min-height:0!important;background:transparent!important;}',
				'table.etb-content{height:auto!important;min-height:0!important;}',
				'</style>'
			].join("");

			return safe_html.includes("</head>")
				? safe_html.replace("</head>", preview_styles + "</head>")
				: preview_styles + safe_html;
		}

		async function hydrate_live_preview(element, master_name) {
			try {
				const preview = await get_master_preview(master_name);
				if (!element.isConnected || !String(preview.html || "").trim()) {
					$(element).find(".etl5-preview-loading").replaceWith(`
						<div class="etl5-placeholder">
							<div>${icon("mail", "lg") || "✉"}</div>
							<div style="margin-top:7px">${__("No preview available")}</div>
						</div>
					`);
					return;
				}

				const $live = $('<div class="etl5-live-preview"></div>');
				const $frame = $("<iframe>", {
					title: __("Preview of {0}", [master_name]),
					loading: "lazy",
					tabindex: "-1",
				});
				$frame.attr("sandbox", "");
				$frame.prop("srcdoc", with_preview_fit_styles(preview.html));
				const scale = element.clientWidth / 900;
				$frame.css("transform", `scale(${scale})`);
				$live.append($frame);
				$(element).find(".etl5-preview-loading, .etl5-placeholder").remove();
				$(element).prepend($live);
			} catch (error) {
				console.error(error);
				if (element.isConnected) {
					$(element).find(".etl5-preview-loading").replaceWith(`
						<div class="etl5-placeholder">${__("Preview unavailable")}</div>
					`);
				}
			}
		}

		const preview_observer = "IntersectionObserver" in window
			? new IntersectionObserver((entries) => {
				entries.forEach((entry) => {
					if (!entry.isIntersecting) return;
					preview_observer.unobserve(entry.target);
					void hydrate_live_preview(
						entry.target,
						entry.target.dataset.masterName
					);
				});
			}, { root: $content.get(0), rootMargin: "180px" })
			: null;

		// -----------------------------------------------------------------
		// Folder loading
		// -----------------------------------------------------------------

		async function fetch_all_folders() {
			if (!perm.folder.read) return [];

			const all = [];
			let start = 0;

			while (true) {
				const response = await frappe.call({
					method: REPORTVIEW_GET_LIST,
					args: {
						doctype: FOLDER,
						fields: [
							"name",
							FOLDER_NAME_FIELD,
							PARENT_FIELD,
							IS_GROUP_FIELD,
							LFT_FIELD,
							RGT_FIELD,
							"modified",
						],
						order_by: `${LFT_FIELD} asc`,
						start,
						page_length: FOLDER_FETCH_PAGE_LENGTH,
					},
				});

				const page = response.message || [];

				all.push(...page);

				if (page.length < FOLDER_FETCH_PAGE_LENGTH) {
					break;
				}

				start += page.length;
			}

			return all;
		}

		function rebuild_folder_index(folders) {
			state.folders = folders;
			state.folder_map = new Map(
				folders.map((folder) => [folder.name, folder])
			);
		}

		function get_folder(name) {
			return state.folder_map.get(name) || null;
		}

		function get_folder_label(folder) {
			return folder?.[FOLDER_NAME_FIELD] || folder?.name || "";
		}

		function get_direct_children(parent_name) {
			return state.folders.filter(
				(folder) => folder[PARENT_FIELD] === parent_name
			);
		}

		function build_breadcrumb(folder_name) {
			const crumbs = [];
			const seen = new Set();

			let current = get_folder(folder_name);

			while (current && !seen.has(current.name)) {
				seen.add(current.name);

				crumbs.unshift({
					name: current.name,
					label: get_folder_label(current),
				});

				if (current.name === ROOT_FOLDER) {
					break;
				}

				const parent_name = current[PARENT_FIELD];

				if (!parent_name) break;

				current = get_folder(parent_name);
			}

			// The supplied structure states that ROOT_FOLDER is the real root.
			// Always anchor breadcrumbs there.
			if (
				crumbs.length &&
				crumbs[0].name !== ROOT_FOLDER &&
				get_folder(ROOT_FOLDER)
			) {
				crumbs.unshift({
					name: ROOT_FOLDER,
					label: ROOT_FOLDER,
				});
			}

			return crumbs;
		}

		// -----------------------------------------------------------------
		// Search
		// -----------------------------------------------------------------

		function matches_search(...values) {
			if (!state.search) return true;

			const q = state.search.toLowerCase();

			return values.some((value) =>
				String(value || "")
					.toLowerCase()
					.includes(q)
			);
		}

		// -----------------------------------------------------------------
		// Breadcrumb
		// -----------------------------------------------------------------

		function render_breadcrumb() {
			const $breadcrumb = $('<div class="etl5-breadcrumb"></div>');

			const crumbs = state.virtual_no_folder
				? [
					{
						name: ROOT_FOLDER,
						label: ROOT_FOLDER,
					},
					{
						name: "__NO_FOLDER__",
						label: __("Without Folder"),
					},
				]
				: state.breadcrumb;

			crumbs.forEach((crumb, index) => {
				if (index > 0) {
					$breadcrumb.append(
						'<span class="etl5-divider">/</span>'
					);
				}

				const is_last = index === crumbs.length - 1;
				
				let display_label = crumb.label;
				if (crumb.name === ROOT_FOLDER) {
					display_label = __("All Folders");
				}

				const $button = $(`
					<button
						type="button"
						class="etl5-crumb ${is_last ? "current" : ""}"
					>
						${escape_html(display_label)}
					</button>
				`);

				if (!is_last) {
					$button.on("click", () => {
						if (crumb.name === ROOT_FOLDER) {
							open_folder(ROOT_FOLDER);
							return;
						}

						if (crumb.name !== "__NO_FOLDER__") {
							open_folder(crumb.name);
						}
					});
				}

				$breadcrumb.append($button);
			});

			return $breadcrumb;
		}

		// -----------------------------------------------------------------
		// Folder card
		// -----------------------------------------------------------------

		function render_folder_card(folder) {
			const name = folder.name;
			const label = get_folder_label(folder);
			const is_fake = folder.is_fake;

			const $card = $(`
				<div
					class="etl5-folder-card"
					role="button"
					tabindex="0"
				>
					<div class="etl5-folder-icon">
						${icon("folder-normal", "md") || icon("folder", "md") || "📁"}
					</div>

					<div class="etl5-folder-text">

						<div
							class="etl5-folder-name"
							title="${escape_attr(label)}"
						>
							${escape_html(label)}
						</div>

					</div>

					<div class="etl5-folder-arrow">›</div>

					${
						(perm.folder.create && !is_fake)
							? `
								<button
									type="button"
									class="etl5-add-child"
									title="${escape_attr(
										__("Add subfolder")
									)}"
								>
									+
								</button>
							`
							: ""
					}

				</div>
			`);

			function open() {
				if (is_fake) {
					open_no_folder();
				} else {
					open_folder(name);
				}
			}

			$card.on("click", (event) => {
				if ($(event.target).closest(".etl5-add-child").length) {
					return;
				}
				open();
			});

			$card.on("keydown", (event) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					open();
				}
			});

			$card.find(".etl5-add-child").on("click", (event) => {
				event.preventDefault();
				event.stopPropagation();

				create_folder({
					parent_folder: name,
					on_created: async (new_folder) => {
						await reload_folder_tree({ reopen_folder: state.current_folder });
						frappe.show_alert({ message: __("Folder created"), indicator: "green" });
					}
				});
			});

			return $card;
		}



		// -----------------------------------------------------------------
		// Template query
		// -----------------------------------------------------------------

		function build_template_filters() {
			const filters = [
				[MASTER, "enabled", "=", 1],
			];

			if (state.virtual_no_folder) {
				filters.push([
					MASTER,
					"folder",
					"is",
					"not set",
				]);
			} else if (state.current_folder !== ROOT_FOLDER) {
				// Filter by specific folder if we are not at the root
				filters.push([
					MASTER,
					"folder",
					"=",
					state.current_folder,
				]);
			}

			return filters;
		}

		function build_template_or_filters() {
			if (!state.search) return [];

			const like = `%${state.search}%`;

			return [
				[MASTER, "name", "like", like],
				[MASTER, "subject", "like", like],
			];
		}

		async function fetch_template_page(generation) {
			const response = await frappe.call({
				method: REPORTVIEW_GET_LIST,
				args: {
					doctype: MASTER,
					fields: [
						"name",
						"subject",
						"thumbnail",
						"folder",
						"modified",
					],
					filters: build_template_filters(),
					or_filters: build_template_or_filters(),
					order_by: "modified desc",
					start: state.start,
					page_length: state.page_length,
				},
			});

			if (generation !== state.generation) return null;

			return response.message || [];
		}

		// -----------------------------------------------------------------
		// Template card
		// -----------------------------------------------------------------

		function render_template_card(template) {
			const name = template.name || "";
			const subject = template.subject || name;

			const preview = template.thumbnail
				? `
					<img
						src="${escape_attr(template.thumbnail)}"
						alt="${escape_attr(name)}"
						loading="lazy"
					>
				`
				: '<div class="etl5-preview-loading" aria-label="Loading template preview"></div>';

			const actual_folder = template.folder;
			let location_label = __("No Folder");
			if (actual_folder) {
				const f = get_folder(actual_folder);
				location_label = f ? get_folder_label(f) : actual_folder;
			}

			const $card = $(`
				<div
					class="etl5-template-card"
					role="button"
					tabindex="0"
				>

					${
						perm.master.write
							? `
								<button
									type="button"
									class="etl5-template-edit"
									title="${escape_attr(
										__("Edit Master Template")
									)}"
								>
									${icon("edit", "sm") || "✎"}
								</button>
							`
							: ""
					}

					<div class="etl5-preview">
						${preview}

						${
							perm.email.create
								? `
									<div class="etl5-overlay">
										<div class="etl5-use">
											${__("Use Template")}
										</div>
									</div>
								`
								: ""
						}
					</div>

					<div class="etl5-template-body">

						<div
							class="etl5-template-name"
							title="${escape_attr(name)}"
						>
							${escape_html(name)}
						</div>

						<div
							class="etl5-template-subject"
							title="${escape_attr(subject)}"
						>
							${escape_html(subject)}
						</div>

						<div class="etl5-template-meta">
							<span>${escape_html(location_label)}</span>
							<span>${escape_html(pretty_date(template.modified))}</span>
						</div>

					</div>

				</div>
			`);
			const preview_element = $card.find(".etl5-preview").get(0);
			if (!template.thumbnail && preview_element) {
				preview_element.dataset.masterName = name;
				if (preview_observer) {
					preview_observer.observe(preview_element);
				} else {
					void hydrate_live_preview(preview_element, name);
				}
			}

			function use_template() {
				if (!perm.email.create) {
					permission_error("create", EMAIL);
					return;
				}

				dialog.hide();

				create_from_master(template.name, template.subject || "", {
					on_cancel: () => dialog.show(),
				});
			}

			$card.on("click", (event) => {
				if ($(event.target).closest(".etl5-template-edit").length) {
					return;
				}

				use_template();
			});

			$card.on("keydown", (event) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					use_template();
				}
			});

			$card.find(".etl5-template-edit").on("click", (event) => {
				event.preventDefault();
				event.stopPropagation();

				dialog.hide();
				open_builder(template.name, MASTER);
			});

			return $card;
		}

		// -----------------------------------------------------------------
		// Render current folder
		// -----------------------------------------------------------------

		function current_visible_children() {
			if (state.virtual_no_folder) return [];

			const children = get_direct_children(state.current_folder).slice();
			
			if (state.current_folder === ROOT_FOLDER) {
				children.push({
					name: "__NO_FOLDER__",
					[FOLDER_NAME_FIELD]: __("Without Folder"),
					is_fake: true
				});
			}

			return children.filter((folder) =>
				matches_search(
					folder[FOLDER_NAME_FIELD],
					folder.name
				)
			);
		}

		function render_shell() {
			preview_observer?.disconnect();
			$content.empty();
			
			$wrapper.find(".etl5-breadcrumb-container").empty().append(render_breadcrumb());

			const children = current_visible_children();

			if (children.length) {
				const count = children.length;

				const $folders = $(`
					<section class="etl5-section">

						<div class="etl5-section-head">
							<div class="etl5-section-title" style="color: var(--text-color); font-size: 13px; font-weight: 600; text-transform: none; letter-spacing: normal;">
								${__("Folders ({0})", [count])}
							</div>

							<div class="text-muted small" style="display: flex; align-items: center; gap: 8px;">
								<span>View</span>
								<div class="btn-group etl5-view-toggle" role="group">
									<button type="button" class="btn btn-default btn-xs etl5-view-btn ${state.view_mode === 'grid' ? 'active' : ''}" data-view="grid" style="padding: 2px 6px;">
										${icon("grid", "sm") || "⊞"}
									</button>
									<button type="button" class="btn btn-default btn-xs etl5-view-btn ${state.view_mode === 'list' ? 'active' : ''}" data-view="list" style="padding: 2px 6px;">
										${icon("list", "sm") || "☰"}
									</button>
								</div>
							</div>
						</div>

						<div class="etl5-folder-grid ${state.view_mode === 'list' ? 'is-list-view' : ''}"></div>

					</section>
				`);

				$folders.find(".etl5-view-btn").on("click", function () {
					const new_mode = $(this).data("view");
					if (state.view_mode !== new_mode) {
						state.view_mode = new_mode;
						render_shell();
						void load_more_templates();
					}
				});

				const $grid = $folders.find(".etl5-folder-grid");

				children.forEach((folder) => {
					$grid.append(render_folder_card(folder));
				});

				$content.append($folders);
			}

			const is_root = state.current_folder === ROOT_FOLDER && !state.virtual_no_folder;
			const show_templates = state.search || !is_root;

			if (show_templates) {
				$content.append(`
					<section class="etl5-section etl5-template-section">

						<div class="etl5-section-head">
							<div class="etl5-section-title" style="color: var(--text-color); font-size: 13px; font-weight: 600; text-transform: none; letter-spacing: normal;">
									${__("Templates")} <span class="etl5-template-count-bracket">(...)</span>
							</div>
						</div>

						<div class="etl5-template-grid"></div>

						<div class="etl5-pagination"></div>

					</section>
				`);
			}
		}

		function render_template_empty() {
			$content.find(".etl5-template-count-bracket").text("(0)");
			
			const $grid = $content.find(".etl5-template-grid");
			$grid.css("display", "block");
			
			$grid.html(`
				<div class="etl5-empty">

					<div style="color: var(--text-muted);">${icon("mail", "lg") || "✉"}</div>

					<div class="etl5-empty-title">
						${
							state.search
								? __("No matching templates")
								: __("No templates in this folder")
						}
					</div>

					<div class="etl5-empty-help">
						${
							state.search
								? __("Try another search term.")
								: __("Create a template to get started.")
						}
					</div>

				</div>
			`);
		}

		function render_pagination() {
			const $pagination = $content.find(".etl5-pagination");

			$pagination.empty();

			if (!state.has_more) return;

			const $button = $(`
				<button
					type="button"
					class="btn btn-default btn-sm"
				>
					${__("Load More")}
				</button>
			`);

			$button.on("click", () => void load_more_templates());

			$pagination.append($button);
		}

		// -----------------------------------------------------------------
		// Template pagination
		// -----------------------------------------------------------------

		async function load_more_templates() {
			if (state.loading || !state.has_more) return;

			const is_root = state.current_folder === ROOT_FOLDER && !state.virtual_no_folder;
			if (is_root && !state.search) {
				return;
			}

			state.loading = true;

			const generation = state.generation;
			const first_page = state.start === 0;

			try {
				const templates = await fetch_template_page(generation);

				if (templates === null) return;

				if (first_page && !templates.length) {
					state.has_more = false;
					state.loaded_count = 0;
					render_template_empty();
					return;
				}

				const $grid = $content.find(".etl5-template-grid");

				templates.forEach((template) => {
					$grid.append(render_template_card(template));
				});

				state.start += templates.length;
				state.loaded_count += templates.length;
				state.has_more =
					templates.length === state.page_length;

				$content
					.find(".etl5-template-count-bracket")
					.text(
						`(${state.has_more ? state.loaded_count + "+" : state.loaded_count})`
					);

				render_pagination();
			} catch (error) {
				console.error(error);

				if (generation === state.generation) {
					$content
						.find(".etl5-template-section")
						.html(`
							<div class="etl5-empty">
								<div class="etl5-empty-title">
									${__("Unable to load templates")}
								</div>

								<div class="etl5-empty-help">
									${__(
										"Frappe server permissions are applied automatically."
									)}
								</div>
							</div>
						`);
				}
			} finally {
				if (generation === state.generation) {
					state.loading = false;
				}
			}
		}

		function reset_template_pagination() {
			state.generation += 1;
			state.start = 0;
			state.loaded_count = 0;
			state.has_more = true;
			state.loading = false;
			$content.scrollTop(0);
		}

		// -----------------------------------------------------------------
		// Navigation
		// -----------------------------------------------------------------

		function update_heading() {
			// No longer updating heading, breadcrumb replaces it
		}

		function open_folder(folder_name) {
			const folder = get_folder(folder_name);

			if (!folder) return;

			state.virtual_no_folder = false;
			state.current_folder = folder_name;
			state.breadcrumb = build_breadcrumb(folder_name);

			state.search = "";
			$search.val("");
			$clear_search.hide();

			update_heading();

			reset_template_pagination();
			render_shell();

			void load_more_templates();
		}

		function open_no_folder() {
			state.virtual_no_folder = true;
			state.current_folder = ROOT_FOLDER;
			state.breadcrumb = [];

			state.search = "";
			$search.val("");
			$clear_search.hide();

			update_heading();

			reset_template_pagination();
			render_shell();

			void load_more_templates();
		}

		// -----------------------------------------------------------------
		// Creation in current location
		// -----------------------------------------------------------------

		function create_template_here() {
			if (!perm.master.create) {
				permission_error("create", MASTER);
				return;
			}

			const default_folder = state.virtual_no_folder
				? ""
				: state.current_folder;

			new_master(default_folder);
		}

		function create_folder_here() {
			if (!perm.folder.create) {
				permission_error("create", FOLDER);
				return;
			}

			const parent = state.virtual_no_folder
				? ROOT_FOLDER
				: state.current_folder;

			create_folder({
				parent_folder: parent,
				on_created: async (new_folder) => {
					await reload_folder_tree({ reopen_folder: state.current_folder });
					frappe.show_alert({ message: __("Folder created"), indicator: "green" });
				}
			});
		}

		$wrapper.find(".etl5-new-template").on(
			"click",
			create_template_here
		);

		$wrapper.find(".etl5-new-folder").on(
			"click",
			create_folder_here
		);

		// -----------------------------------------------------------------
		// Search
		// -----------------------------------------------------------------

		const perform_search = debounce(() => {
			state.search = ($search.val() || "").trim();

			$clear_search.css(
				"display",
				state.search ? "flex" : "none"
			);

			reset_template_pagination();
			render_shell();

			void load_more_templates();
		}, SEARCH_DELAY);

		$search.on("input", perform_search);

		$clear_search.on("click", () => {
			state.search = "";
			$search.val("");
			$clear_search.hide();

			reset_template_pagination();
			render_shell();

			void load_more_templates();
		});

		// -----------------------------------------------------------------
		// Infinite scroll for templates
		// -----------------------------------------------------------------

		$content.on("scroll", debounce(() => {
			if (state.loading || !state.has_more) return;

			const element = $content.get(0);

			if (!element) return;

			const remaining =
				element.scrollHeight -
				element.scrollTop -
				element.clientHeight;

			if (remaining <= LOAD_MORE_THRESHOLD) {
				void load_more_templates();
			}
		}, 50));

		// -----------------------------------------------------------------
		// Reload complete folder NestedSet
		// -----------------------------------------------------------------

		async function reload_folder_tree({
			reopen_folder = ROOT_FOLDER,
		} = {}) {
			const generation = ++state.generation;

			$content.html(`
				<div class="etl5-empty">
					<div class="etl5-empty-title">
						${__("Loading folders...")}
					</div>
				</div>
			`);

			try {
				const folders = await fetch_all_folders();

				if (generation !== state.generation) return;

				rebuild_folder_index(folders);

				/*
				 * Do not invent/synthesize a root. The provided project structure
				 * says ROOT_FOLDER is an actual Email Template Folder document.
				 */
				if (!get_folder(ROOT_FOLDER)) {
					$content.html(`
						<div class="etl5-empty">

							<div class="etl5-empty-title">
								${__("Root folder not found")}
							</div>

							<div class="etl5-empty-help">
								${__(
									'Expected the real root folder "{0}" to exist.',
									[ROOT_FOLDER]
								)}
							</div>

						</div>
					`);

					return;
				}

				const destination = get_folder(reopen_folder)
					? reopen_folder
					: ROOT_FOLDER;

				open_folder(destination);
				if (initial_action === "folder") {
					initial_action = "";
					show_inline_folder(destination);
				} else if (initial_action === "template") {
					initial_action = "";
					show_inline_template(
						get_folder(initial_folder) ? initial_folder : destination
					);
				}
			} catch (error) {
				console.error(error);

				if (generation !== state.generation) return;

				$content.html(`
					<div class="etl5-empty">
						<div class="etl5-empty-title">
							${__("Unable to load template folders")}
						</div>

						<div class="etl5-empty-help">
							${__(
								"Check Email Template Folder read permission."
							)}
						</div>
					</div>
				`);
			}
		}

		// -----------------------------------------------------------------
		// Initial load
		// -----------------------------------------------------------------

		dialog.show();

		void reload_folder_tree({
			reopen_folder: ROOT_FOLDER,
		});

		setTimeout(() => {
			$search.trigger("focus");
		}, 150);
	}

	
	// Public API
	

	Object.assign(frappe.email_template_library, {
		choose_master,
		create_from_master,
		create_master_from_email,
		new_master: (folder = ROOT_FOLDER) => choose_master({
			initial_action: "template",
			initial_folder: folder || ROOT_FOLDER,
		}),
		new_folder: (parent_folder = ROOT_FOLDER) => choose_master({
			initial_action: "folder",
			initial_folder: parent_folder || ROOT_FOLDER,
		}),
		open_builder,
		can,
		get_permissions,

		// Export exact tree config for any other custom JS that needs it.
		ROOT_FOLDER,
		FOLDER_NAME_FIELD,
		PARENT_FIELD,
	});
})();