frappe.treeview_settings["Reach Segment Folder"] = {
    ignore_fields: ["parent_reach_segment_folder"],
    extend_toolbar: true,
    toolbar: [{
        label: __("Segments"),
        condition: () => frappe.model.can_read("Reach Segment"),
        click(node) {
            frappe.route_options = { archived: 0 };
            if (!node.is_root) frappe.route_options.folder = node.label;
            frappe.set_route("List", "Reach Segment");
        },
    }],
};
