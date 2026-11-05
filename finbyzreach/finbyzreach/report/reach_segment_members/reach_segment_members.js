frappe.query_reports["Reach Segment Members"] = {
    filters: [
        {fieldname:"segment",label:__("Segment"),fieldtype:"Link",options:"Reach Segment",reqd:1,get_query:()=>({filters:{archived:0}})},
        {fieldname:"after",label:__("After record"),fieldtype:"Data"}
    ]
};
