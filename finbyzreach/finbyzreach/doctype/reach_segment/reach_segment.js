// Copyright (c) 2026, Finbyz Tech Pvt Ltd and contributors
// For license information, please see license.txt

class ReachSegmentBuilder {
	constructor(frm) {
		this.frm = frm;
		this.includeFilterGroups = [];
		this.excludeFilterGroups = [];
		this.setup();
	}

	setup() {
		// Always clean up existing UI states so it renders cleanly
		this.frm.remove_custom_button(__("Refresh Leads from Filters"));
		this.frm.remove_custom_button(__("Preview Leads"));
		if (this.frm.get_field("static_leads_json")) {
			this.frm.get_field("static_leads_json").$wrapper.empty();
		}

		this.makeUI();
		this.loadFilters();
		if (this.frm.doc.segment_type === "Static") {
			this.makeStaticUI();
		} else if (this.frm.doc.segment_type === "Active") {
			this.makeActiveUI();
		}
	}

	makeUI() {
		const can_write = this.frm.perm[0].write;
		const $wrapper = this.frm.get_field("filter_groups_json").$wrapper;
		
		$wrapper.empty().html(`
			<div class="reach-segment-builder" style="padding: 15px; border: 1px solid var(--border-color); border-radius: 8px; margin-bottom: 15px; background: var(--card-bg, #fff); ${!can_write ? 'pointer-events: none; opacity: 0.8;' : ''}">
				<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
					<h4 style="margin: 0; color: #15803d; font-size: 13px; font-weight: 700;">
						<span style="display: inline-block; width: 24px; height: 24px; background: #dcfce7; text-align: center; border-radius: 6px; margin-right: 8px; line-height: 24px;">+</span>
						${__("Include Leads")}
					</h4>
					${can_write ? `<button class="btn btn-default btn-sm" id="rs-add-include-group">${__("Add OR Group")}</button>` : ""}
				</div>
				<div id="rs-include-filters"></div>
			</div>
			
			<div class="reach-segment-builder" style="padding: 15px; border: 1px solid var(--border-color); border-radius: 8px; margin-bottom: 15px; background: var(--card-bg, #fff); ${!can_write ? 'pointer-events: none; opacity: 0.8;' : ''}">
				<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
					<h4 style="margin: 0; color: #c2410c; font-size: 13px; font-weight: 700;">
						<span style="display: inline-block; width: 24px; height: 24px; background: #ffedd5; text-align: center; border-radius: 6px; margin-right: 8px; line-height: 24px;">−</span>
						${__("Exclude Leads")}
					</h4>
					${can_write ? `<button class="btn btn-default btn-sm" id="rs-add-exclude-group">${__("Add OR Group")}</button>` : ""}
				</div>
				<div id="rs-exclude-filters"></div>
			</div>
		`);

		this.$includeContainer = $wrapper.find("#rs-include-filters");
		this.$excludeContainer = $wrapper.find("#rs-exclude-filters");

		$wrapper.find("#rs-add-include-group").off("click").on("click", (e) => {
			if (!can_write) return;
			e.preventDefault();
			this.addIncludeFilterGroup();
		});

		$wrapper.find("#rs-add-exclude-group").off("click").on("click", (e) => {
			if (!can_write) return;
			e.preventDefault();
			this.addExcludeFilterGroup();
		});
	}

	makeStaticUI() {
		const can_write = this.frm.perm[0].write;
		if (can_write) {
			this.frm.add_custom_button(__("Refresh Leads from Filters"), () => {
				if (this.frm.is_dirty()) {
					frappe.msgprint(__("Please save the document before refreshing leads."));
					return;
				}
				frappe.confirm(__("Are you sure you want to refresh the static segment? Any manually removed leads will be reset based on the current filters."), () => {
					frappe.call({
						method: "finbyzreach.segments.refresh_static_segment_leads",
						args: { segment_name: this.frm.doc.name },
						freeze: true,
						freeze_message: __("Refreshing Leads…")
					}).then((response) => {
						frappe.show_alert({message: __("Leads Refreshed"), indicator: "green"});
						this.frm.reload_doc();
					});
				});
			});
		}

		this.frm.add_custom_button(__("Preview Leads"), () => {
			const staticLeads = frappe.utils.parse_json(this.frm.doc.static_leads_json || "[]");
			this.showPreviewDialog(staticLeads, true, can_write);
		});

		// Inline static members list (basic IDs only)
		const $leadsWrapper = this.frm.get_field("static_leads_json").$wrapper;
		this.staticLeads = frappe.utils.parse_json(this.frm.doc.static_leads_json || "[]");
		this.staticPage = 0;
		this.staticPageSize = 50;

		let leadsHTML = `<div style="padding: 15px; border: 1px solid var(--border-color); border-radius: 8px; margin-top: 15px; background: var(--card-bg, #fff);">
			<h4 style="margin: 0 0 15px 0;">${__("Static Segment Members")} (<span id="rs-static-count">${this.staticLeads.length}</span>)</h4>
			<div id="rs-static-members-list" style="height: 300px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 4px; padding: 10px; background: var(--control-bg, #f4f5f6);">
			</div>
			<div style="margin-top: 10px; display: flex; justify-content: center; align-items: center; gap: 10px;">
				<button class="btn btn-xs btn-default" id="rs-static-prev" disabled>← ${__("Prev")}</button>
				<span id="rs-static-page-info" style="font-size: 12px; color: var(--text-muted);"></span>
				<button class="btn btn-xs btn-default" id="rs-static-next" disabled>${__("Next")} →</button>
			</div>
		</div>`;
		
		$leadsWrapper.empty().html(leadsHTML);
		this.$staticList = $leadsWrapper.find("#rs-static-members-list");
		this.$staticPrev = $leadsWrapper.find("#rs-static-prev");
		this.$staticNext = $leadsWrapper.find("#rs-static-next");
		this.$staticPageInfo = $leadsWrapper.find("#rs-static-page-info");

		if (this.staticLeads.length === 0) {
			this.$staticList.html(`<div class="text-muted" style="padding: 10px;">${__("No members in this segment.")}</div>`);
			this.$staticPageInfo.text("0 of 0");
		} else {
			this.loadStaticLeadsPage();
		}

		this.$staticPrev.off("click").on("click", (e) => {
			e.preventDefault();
			if (this.staticPage > 0) {
				this.staticPage--;
				this.loadStaticLeadsPage();
			}
		});

		this.$staticNext.off("click").on("click", (e) => {
			e.preventDefault();
			if ((this.staticPage + 1) * this.staticPageSize < this.staticLeads.length) {
				this.staticPage++;
				this.loadStaticLeadsPage();
			}
		});

		$leadsWrapper.off("click", ".rs-remove-member").on("click", ".rs-remove-member", (e) => {
			if (!can_write) return;
			e.preventDefault();
			const $item = $(e.currentTarget).closest(".rs-static-member");
			const lead = $item.data("lead");
			const currentLeads = frappe.utils.parse_json(this.frm.doc.static_leads_json || "[]");
			const newLeads = currentLeads.filter(l => l !== lead);
			this.frm.set_value("static_leads_json", JSON.stringify(newLeads));
			this.frm.set_value("member_count", newLeads.length);
			
			this.staticLeads = newLeads;
			this.frm.dirty();
			$leadsWrapper.find("#rs-static-count").text(newLeads.length);
			
			const totalPages = Math.ceil(this.staticLeads.length / this.staticPageSize);
			if (this.staticPage >= totalPages && this.staticPage > 0) {
				this.staticPage = totalPages - 1;
			}
			
			if (this.staticLeads.length === 0) {
				this.$staticList.html(`<div class="text-muted" style="padding: 10px;">${__("No members in this segment.")}</div>`);
				this.$staticPageInfo.text("0 of 0");
				this.$staticPrev.prop("disabled", true);
				this.$staticNext.prop("disabled", true);
			} else {
				this.loadStaticLeadsPage();
			}
		});
	}

	loadStaticLeadsPage() {
		const start = this.staticPage * this.staticPageSize;
		const end = start + this.staticPageSize;
		const pageIds = this.staticLeads.slice(start, end);
		
		if (pageIds.length === 0) {
			this.$staticList.empty();
			return;
		}
		const can_write = this.frm.perm[0].write;

		let html = "";
		pageIds.forEach(leadId => {
			html += `
				<div class="rs-static-member" data-lead="${leadId}" style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; margin-bottom: 5px; background: #fff; border: 1px solid var(--border-color); border-radius: 4px;">
					<span style="font-weight: 500; font-size: 12px;">${leadId}</span>
					${can_write ? `<button class="btn btn-xs btn-danger rs-remove-member" style="padding: 2px 6px;" title="Remove Lead">×</button>` : ""}
				</div>
			`;
		});

		this.$staticList.html(html);
		
		const totalPages = Math.ceil(this.staticLeads.length / this.staticPageSize);
		this.$staticPageInfo.text(`${__("Page")} ${this.staticPage + 1} ${__("of")} ${totalPages}`);
		this.$staticPrev.prop("disabled", this.staticPage === 0);
		this.$staticNext.prop("disabled", (this.staticPage + 1) * this.staticPageSize >= this.staticLeads.length);
	}

	makeActiveUI() {
		this.frm.add_custom_button(__("Preview Leads"), () => {
			if (this.frm.is_dirty()) {
				frappe.msgprint(__("Please save the document before previewing leads."));
				return;
			}
			frappe.call({
				method: "finbyzreach.segments.preview_segment_audience",
				args: { segment_name: this.frm.doc.name },
				freeze: true,
				freeze_message: __("Fetching Leads…")
			}).then((response) => {
				const leads = response.message || [];
				this.showPreviewDialog(leads, false, false);
			});
		});
	}

	showPreviewDialog(leads, isStatic = false, canWrite = false) {
		if (this.previewDialog) {
			this.previewDialog.$wrapper.remove();
		}
		
		this.previewLeads = leads;
		this.previewPage = 0;
		this.previewPageSize = 20;
		this.previewSearchTerm = "";
		this.isPreviewStatic = isStatic;
		this.previewCanWrite = canWrite;
		
		const can_read_lead = frappe.model.can_read("Lead");
		
		let leadsHTML = `
			<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
				<strong>${__("Total Count:")} <span id="rs-preview-count">${this.previewLeads.length}</span></strong>
				${can_read_lead ? `<input type="text" id="rs-preview-search" class="form-control input-sm" placeholder="${__("Search by Name or Email...")}" style="width: 250px;">` : ""}
			</div>
			<div id="rs-preview-members-list" style="height: 400px; max-height: 400px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 4px; padding: 10px; background: var(--control-bg, #f4f5f6);">
			</div>
			<div style="margin-top: 10px; display: flex; justify-content: center; align-items: center; gap: 10px;">
				<button class="btn btn-xs btn-default" id="rs-preview-prev" disabled>← ${__("Prev")}</button>
				<span id="rs-preview-page-info" style="font-size: 12px; color: var(--text-muted);"></span>
				<button class="btn btn-xs btn-default" id="rs-preview-next" disabled>${__("Next")} →</button>
			</div>
		`;

		this.previewDialog = new frappe.ui.Dialog({
			title: __("Segment Leads Preview"),
			fields: [
				{
					fieldname: "html",
					fieldtype: "HTML",
					options: leadsHTML
				}
			],
			primary_action_label: __("Close"),
			primary_action: () => this.previewDialog.hide()
		});
		this.previewDialog.show();

		this.$previewList = this.previewDialog.$wrapper.find("#rs-preview-members-list");
		this.$previewPrev = this.previewDialog.$wrapper.find("#rs-preview-prev");
		this.$previewNext = this.previewDialog.$wrapper.find("#rs-preview-next");
		this.$previewPageInfo = this.previewDialog.$wrapper.find("#rs-preview-page-info");

		if (can_read_lead) {
			let searchTimeout;
			this.previewDialog.$wrapper.find("#rs-preview-search").off("input").on("input", (e) => {
				clearTimeout(searchTimeout);
				searchTimeout = setTimeout(() => {
					this.previewSearchTerm = $(e.currentTarget).val();
					this.previewPage = 0;
					this.$previewList.empty();
					this.loadPreviewPage();
				}, 300);
			});
		}

		if (this.previewLeads.length === 0) {
			this.$previewList.html(`<div class="text-muted" style="padding: 10px;">${__("No matching leads found.")}</div>`);
			this.$previewPageInfo.text("0");
		} else {
			this.loadPreviewPage();
		}

		this.$previewPrev.off("click").on("click", (e) => {
			e.preventDefault();
			if (this.previewPage > 0) {
				this.previewPage--;
				this.loadPreviewPage();
			}
		});

		this.$previewNext.off("click").on("click", (e) => {
			e.preventDefault();
			this.previewPage++;
			this.loadPreviewPage();
		});

		if (isStatic && canWrite) {
			this.$previewList.off("click", ".rs-remove-member").on("click", ".rs-remove-member", (e) => {
				e.preventDefault();
				const $item = $(e.currentTarget).closest(".rs-preview-member");
				const lead = $item.data("lead");
				
				// Update doc
				const currentLeads = frappe.utils.parse_json(this.frm.doc.static_leads_json || "[]");
				const newLeads = currentLeads.filter(l => l !== lead);
				this.frm.set_value("static_leads_json", JSON.stringify(newLeads));
				this.frm.set_value("member_count", newLeads.length);
				this.frm.dirty();
				
				// Update dialog state
				this.previewLeads = this.previewLeads.filter(l => l !== lead);
				this.previewDialog.$wrapper.find("#rs-preview-count").text(this.previewLeads.length);
				
				const totalPreviewPages = Math.ceil(this.previewLeads.length / this.previewPageSize);
				if (this.previewPage >= totalPreviewPages && this.previewPage > 0) {
					this.previewPage = totalPreviewPages - 1;
				}
				
				this.loadPreviewPage();

				// Update inline list state if we're on the static segment
				if (this.staticLeads) {
					this.staticLeads = newLeads;
					const $leadsWrapper = this.frm.get_field("static_leads_json").$wrapper;
					$leadsWrapper.find("#rs-static-count").text(newLeads.length);
					
					const totalPages = Math.ceil(this.staticLeads.length / this.staticPageSize);
					if (this.staticPage >= totalPages && this.staticPage > 0) {
						this.staticPage = totalPages - 1;
					}
					
					if (this.staticLeads.length === 0) {
						this.$staticList.html(`<div class="text-muted" style="padding: 10px;">${__("No members in this segment.")}</div>`);
						this.$staticPageInfo.text("0 of 0");
						this.$staticPrev.prop("disabled", true);
						this.$staticNext.prop("disabled", true);
					} else {
						this.loadStaticLeadsPage();
					}
				}
			});
		}
	}

	loadPreviewPage() {
		if (this.previewLeads.length === 0) {
			this.$previewList.empty();
			return;
		}

		this.$previewPrev.prop("disabled", true);
		this.$previewNext.prop("disabled", true);
		this.$previewPageInfo.text(__("Loading..."));

		if (!frappe.model.can_read("Lead")) {
			const start = this.previewPage * this.previewPageSize;
			const end = start + this.previewPageSize;
			const pageIds = this.previewLeads.slice(start, end);
			
			let html = "";
			pageIds.forEach(leadId => {
				html += `
					<div class="rs-preview-member" data-lead="${leadId}" style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; margin-bottom: 5px; background: #fff; border: 1px solid var(--border-color); border-radius: 4px;">
						<div style="flex-grow: 1;">
							<div style="font-weight: 500;">${leadId}</div>
							<div style="font-size: 11px; color: var(--text-muted);">${__("No permission to view lead details")}</div>
						</div>
						${(this.isPreviewStatic && this.previewCanWrite) ? `<button class="btn btn-xs btn-danger rs-remove-member" style="padding: 2px 6px;" title="Remove Lead">×</button>` : ""}
					</div>
				`;
			});
			this.$previewList.html(html);
			
			const totalPages = Math.ceil(this.previewLeads.length / this.previewPageSize);
			this.$previewPageInfo.text(`${__("Page")} ${this.previewPage + 1} ${__("of")} ${totalPages}`);
			this.$previewPrev.prop("disabled", this.previewPage === 0);
			this.$previewNext.prop("disabled", (this.previewPage + 1) * this.previewPageSize >= this.previewLeads.length);
			
			return;
		}

		let filters = [];
		let or_filters = [];
		let limit_start = 0;
		if (this.previewSearchTerm) {
			filters.push(["Lead", "name", "in", this.previewLeads]);
			or_filters.push(["Lead", "name", "like", `%${this.previewSearchTerm}%`]);
			or_filters.push(["Lead", "lead_name", "like", `%${this.previewSearchTerm}%`]);
			or_filters.push(["Lead", "email_id", "like", `%${this.previewSearchTerm}%`]);
			limit_start = this.previewPage * this.previewPageSize;
		} else {
			const start = this.previewPage * this.previewPageSize;
			const end = start + this.previewPageSize;
			const pageIds = this.previewLeads.slice(start, end);
			filters.push(["Lead", "name", "in", pageIds]);
			limit_start = 0; // already sliced
		}

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Lead",
				filters: filters,
				or_filters: or_filters,
				fields: ["name", "lead_name", "email_id", "status"],
				limit_start: limit_start,
				limit_page_length: this.previewPageSize
			}
		}).then((r) => {
			const details = r.message || [];
			let html = "";
			
			if (this.previewPage === 0 && details.length === 0) {
				html = `<div class="text-muted" style="padding: 10px;">${__("No matching leads found.")}</div>`;
			} else {
				details.forEach(d => {
					html += `
						<div class="rs-preview-member" data-lead="${d.name}" style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; margin-bottom: 5px; background: #fff; border: 1px solid var(--border-color); border-radius: 4px;">
							<div style="flex-grow: 1;">
								<div style="font-weight: 500;"><a href="/app/lead/${d.name}" target="_blank">${d.name}</a> ${d.lead_name ? `- ${d.lead_name}` : ""}</div>
								<div style="font-size: 11px; color: var(--text-muted);">${d.email_id || __("No Email")} • <span class="badge badge-default">${d.status}</span></div>
							</div>
							${(this.isPreviewStatic && this.previewCanWrite) ? `<button class="btn btn-xs btn-danger rs-remove-member" style="padding: 2px 6px;" title="Remove Lead">×</button>` : ""}
						</div>
					`;
				});
			}

			this.$previewList.html(html);

			this.$previewPageInfo.text(`${__("Page")} ${this.previewPage + 1}`);
			this.$previewPrev.prop("disabled", this.previewPage === 0);
			// Since we don't know total backend count when filtering, we just disable next if returned items are less than page size
			this.$previewNext.prop("disabled", details.length < this.previewPageSize);
		});
	}

	loadFilters() {
		frappe.model.with_doctype("Lead", () => {
			const includeFilters = frappe.utils.parse_json(this.frm.doc.filter_groups_json || "[]");
			const excludeFilters = frappe.utils.parse_json(this.frm.doc.exclude_filters_json || "[]");

			// Support legacy format if it's not an array of arrays
			const normalizedInclude = this.normalizeFilterGroups(includeFilters);
			if (normalizedInclude.length) {
				normalizedInclude.forEach(filters => this.addIncludeFilterGroup(filters));
			} else {
				this.addIncludeFilterGroup();
			}

			const normalizedExclude = this.normalizeFilterGroups(excludeFilters);
			if (normalizedExclude.length) {
				normalizedExclude.forEach(filters => this.addExcludeFilterGroup(filters));
			} else {
				this.addExcludeFilterGroup();
			}
		});
	}

	normalizeFilterGroups(filters) {
		if (!Array.isArray(filters) || !filters.length) return [];
		if (Array.isArray(filters[0]) && typeof filters[0][0] === "string") return [filters];
		return filters.filter((group) => Array.isArray(group));
	}

	makeFilterGroup($container, onRemove) {
		const can_write = this.frm.perm[0].write;
		const $group = $(`
			<div class="rs-filter-group" style="padding: 10px; border: 1px dashed var(--border-color); border-radius: 6px; margin-bottom: 10px; background: var(--control-bg, #f4f5f6);">
				<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
					<strong style="font-size: 11px; text-transform: uppercase;">${__("Rule Group")}</strong>
					${can_write ? `<button class="btn btn-xs btn-default rs-remove-group">${__("Remove")}</button>` : ""}
				</div>
				<div class="rs-filter-body" style="background: var(--card-bg, #fff); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px;"></div>
			</div>
		`);
		$container.append($group);

		const filterGroup = new frappe.ui.FilterGroup({
			parent: $group.find(".rs-filter-body"),
			doctype: "Lead",
			on_change: () => this.frm.dirty()
		});
		
		// Disable the default standard Filter button behavior in embedded mode
		filterGroup.update_filter_button = function () {};

		$group.find(".rs-remove-group").off("click").on("click", (e) => {
			e.preventDefault();
			if (onRemove() !== false) {
				$group.remove();
				this.frm.dirty();
			}
		});

		return { filterGroup, $group };
	}

	addIncludeFilterGroup(filters = []) {
		const item = this.makeFilterGroup(this.$includeContainer, () => {
			if (this.includeFilterGroups.length > 1) {
				this.includeFilterGroups = this.includeFilterGroups.filter(i => i !== item);
				return true;
			} else {
				frappe.msgprint(__("You must have at least one include rule group."));
				return false;
			}
		});
		if (filters.length) {
			item.filterGroup.add_filters(filters);
		}
		this.includeFilterGroups.push(item);
	}

	addExcludeFilterGroup(filters = []) {
		const item = this.makeFilterGroup(this.$excludeContainer, () => {
			this.excludeFilterGroups = this.excludeFilterGroups.filter(i => i !== item);
			return true;
		});
		if (filters.length) {
			item.filterGroup.add_filters(filters);
		}
		this.excludeFilterGroups.push(item);
	}

	getFilters() {
		return this.includeFilterGroups
			.map(item => item.filterGroup.get_filters())
			.filter(filters => filters.length > 0);
	}

	getExcludeFilters() {
		return this.excludeFilterGroups
			.map(item => item.filterGroup.get_filters())
			.filter(filters => filters.length > 0);
	}
}

frappe.ui.form.on("Reach Segment", {
	refresh(frm) {
		frm.builder = new ReachSegmentBuilder(frm);
	},
	segment_type(frm) {
		frm.trigger('refresh');
	},
	validate(frm) {
		if (frm.builder) {
			const includeFilters = frm.builder.getFilters();
			const excludeFilters = frm.builder.getExcludeFilters();
			
			if (includeFilters.length === 0) {
				frappe.msgprint(__("Add at least one include filter."));
				frappe.validated = false;
				return;
			}

			frm.set_value("filter_groups_json", JSON.stringify(includeFilters));
			frm.set_value("exclude_filters_json", JSON.stringify(excludeFilters));
		}
	}
});
