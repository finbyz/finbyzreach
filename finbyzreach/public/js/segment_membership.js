frappe.reach_segment_membership = frappe.reach_segment_membership || {};
frappe.reach_segment_membership.report = function(action, excluded, segment) {
    if (action === "add" && excluded) {
        frappe.msgprint(__("{0} record(s) were not added because they are excluded from {1}. Undo the exclusion in the segment's Excluded tab first.",
            [excluded, frappe.utils.escape_html(segment)]));
        return;
    }
    frappe.show_alert({message:__(action === "add" ? "Members added" : "Members removed"), indicator:"green"});
};
frappe.reach_segment_membership.setup_list = function(doctype) {
    const previous = frappe.listview_settings[doctype] || {};
    if (previous._reachSegmentActions) return;
    frappe.listview_settings[doctype] = {...previous, _reachSegmentActions:true, onload(list) {
        previous.onload?.(list);
        if (!frappe.model.can_write("Reach Segment")) return;
        list.page.add_action_item(__("Create segment from selection"), () => {
            const records = list.get_checked_items().map(row => row.name);
            if (!records.length) return frappe.msgprint(__("Select records first"));
            frappe.prompt({fieldname:"name",fieldtype:"Data",label:__("Segment name"),reqd:1}, async values => {
                const {message} = await frappe.call({method:"finbyzreach.segments.create_segment",args:{segment_name:values.name,segment_type:"Static",filter_groups:"[]",audience_doctype:doctype}});
                for (let start=0;start<records.length;start+=500) await frappe.call({method:"finbyzreach.segments.change_segment_members",args:{segment_name:message.name,records:JSON.stringify(records.slice(start,start+500)),action:"add"}});
                frappe.set_route("Form","Reach Segment",message.name);
            });
        });
        for (const [label,action] of [["Add to segment","add"],["Remove from segment","exclude"]]) {
            list.page.add_action_item(__(label), () => {
                const records = list.get_checked_items().map(row=>row.name);
                if (!records.length) return frappe.msgprint(__("Select records first"));
                frappe.prompt({fieldname:"segment",fieldtype:"Link",options:"Reach Segment",label:__("Static segment"),reqd:1,
                    get_query:()=>({filters:{audience_doctype:doctype,segment_type:"Static",archived:0}})},async values=>{
                    let excluded = 0;
                    for (let start=0;start<records.length;start+=500) {
                        const {message} = await frappe.call({method:"finbyzreach.segments.change_segment_members",
                            args:{segment_name:values.segment,records:JSON.stringify(records.slice(start,start+500)),action}});
                        excluded += message?.still_excluded || 0;
                    }
                    frappe.reach_segment_membership.report(action, excluded, values.segment);
                });
            });
        }
    }};
};

for (const doctype of ["Lead", "Contact", "Customer", "Opportunity", "Sales Order"]) {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            if (frm.is_new() || !frappe.model.can_read("Reach Segment")) return;
            const load = async after => {
                const {message} = await frappe.call({method:"finbyzreach.segments.record_segments",type:"GET",args:{doctype,name:frm.doc.name,after,paginated:1}});
                for (const segment of message.segments || []) frm.add_custom_button(segment,()=>frappe.set_route("Form","Reach Segment",segment),__("Segments"));
                if (message.next_cursor) frm.add_custom_button(__("Load more segments"),()=>{
                    frm.remove_custom_button(__("Load more segments"),__("Segments"));load(message.next_cursor);
                },__("Segments"));
            };
            load();
        }
    });
    frappe.reach_segment_membership.setup_list(doctype);
}

frappe.realtime.on("reach_segment_export_ready", data => {
    const url = String(data.file_url || "");
    if (!url.startsWith("/private/files/")) return;
    frappe.msgprint({title:__("Segment export ready"),message:`<a href="${frappe.utils.escape_html(url)}" download>${__("Download export")}</a>`});
});
