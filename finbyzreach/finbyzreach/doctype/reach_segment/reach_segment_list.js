frappe.listview_settings["Reach Segment"] = {
    filters: [["archived", "=", 0]],
    add_fields: ["member_count", "segment_type", "audience_doctype", "folder", "last_definition_change", "last_definition_changed_by", "owner", "creation"],
    hide_name_column: true,
    // SEG-29: one search bar for the segment name; the ID filter would only duplicate it.
    hide_name_filter: true,
    // SEG-33: one dialog for name, type, folder and description before the filters.
    primary_action() {
        frappe.reach_segment_library.create_segment({ folder: cur_list?.get_filter_value?.("folder") || "" });
    },
    async onload(list) {
        frappe.reach_folder_sidebar.setup(list);
        await list.setup_columns([
            {fieldname:"name",label:__("Name"),width:240}, {fieldname:"member_count"}, {fieldname:"segment_type"},
            {fieldname:"audience_doctype"}, {fieldname:"last_definition_change"},
            {fieldname:"last_definition_changed_by"}, {fieldname:"owner",label:__("Created by")},
            {fieldname:"creation",label:__("Created on")}
        ]);
        list.refresh();
    }
};
