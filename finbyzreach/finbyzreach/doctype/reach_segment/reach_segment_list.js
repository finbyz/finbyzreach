frappe.listview_settings["Reach Segment"] = {
    filters: [["archived", "=", 0]],
    add_fields: ["member_count", "segment_type", "audience_doctype", "folder", "last_definition_change", "last_definition_changed_by", "owner", "creation"],
    hide_name_column: true,
    async onload(list) {
        await list.setup_columns([
            {fieldname:"name",label:__("Name")}, {fieldname:"member_count"}, {fieldname:"segment_type"},
            {fieldname:"audience_doctype"}, {fieldname:"last_definition_change"},
            {fieldname:"last_definition_changed_by"}, {fieldname:"owner",label:__("Created by")},
            {fieldname:"creation",label:__("Created on")}
        ]);
        list.refresh();
    }
};
