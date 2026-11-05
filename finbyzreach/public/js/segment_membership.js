for (const doctype of ["Lead", "Contact", "Customer"]) {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            if (frm.is_new() || !frappe.model.can_read("Reach Segment")) return;
            frappe.call({method: "finbyzreach.segments.record_segments", type: "GET", args: {doctype, name: frm.doc.name}}).then(({message}) => {
                for (const segment of message || []) frm.add_custom_button(segment, () => frappe.set_route("Form", "Reach Segment", segment), __("Segments"));
            });
        }
    });
    const previous = frappe.listview_settings[doctype] || {};
    frappe.listview_settings[doctype] = {...previous, onload(list) {
        previous.onload?.(list);
        if (!frappe.model.can_write("Reach Segment")) return;
        list.page.add_action_item(__("Create segment from selection"), () => {
            const records = list.get_checked_items().map(row => row.name);
            if (!records.length) return frappe.msgprint(__("Select records first"));
            frappe.prompt({fieldname:"name",fieldtype:"Data",label:__("Segment name"),reqd:1}, async values => {
                const {message} = await frappe.call({method:"finbyzreach.segments.create_segment",args:{segment_name:values.name,segment_type:"Static",filter_groups:"[]",audience_doctype:doctype}});
                await frappe.call({method:"finbyzreach.segments.change_segment_members",args:{segment_name:message.name,records:JSON.stringify(records),action:"add"}});
                frappe.set_route("Form","Reach Segment",message.name);
            });
        });
        list.page.add_action_item(__("Add to segment"), () => {
            const records = list.get_checked_items().map(row => row.name);
            if (!records.length) return frappe.msgprint(__("Select records first"));
            frappe.prompt({fieldname: "segment", fieldtype: "Link", options: "Reach Segment", label: __("Static segment"), reqd: 1,
                get_query: () => ({filters: {audience_doctype: doctype, segment_type: "Static", archived: 0}})}, async values => {
                await frappe.call({method: "finbyzreach.segments.change_segment_members", args: {segment_name: values.segment, records: JSON.stringify(records), action: "add"}});
                frappe.show_alert(__("Members added"));
            });
        });
    }};
}

frappe.realtime.on("reach_segment_export_ready", data => {
    const url = String(data.file_url || "");
    if (!url.startsWith("/private/files/")) return;
    frappe.msgprint({title:__("Segment export ready"),message:`<a href="${frappe.utils.escape_html(url)}" download>${__("Download export")}</a>`});
});
