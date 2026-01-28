import frappe
from frappe import _


def after_insert(doc, method):
    """
    Hook to analyze incoming communications and update reference documents.
    Only processes received communications that are not replies.
    """
    # Only process received communications
    if doc.sent_or_received != "Received":
        return
    
    # Skip if it's a reply to an existing thread
    if doc.in_reply_to:
        return
    
    # Skip if no reference document is linked
    if not doc.reference_doctype or not doc.reference_name:
        return
    
    # Only process for specific doctypes
    supported_doctypes = ["Opportunity", "Sales Order", "Quotation"]
    if doc.reference_doctype not in supported_doctypes:
        return
    
    # Enqueue the analysis to avoid blocking
    frappe.enqueue(
        "finbyzreach.doc_events.communication.analyze_communication",
        doc_name=doc.name,
        queue="short",
        job_name=f"Analyze Communication - {doc.name}"
    )

@frappe.whitelist()
def analyze_communication(doc_name):
    """
    Analyze a communication using AI and update the reference document.
    
    Args:
        doc_name: Name of the Communication document
    """
    doc = frappe.get_doc("Communication", doc_name)
    
    if not doc.reference_doctype or not doc.reference_name:
        return
    
    # Get the content to analyze
    content = doc.content or doc.text_content or doc.subject
    if not content:
        return
    
    try:
        # Determine communication category using AI
        # Pass reference_doctype to context
        category = get_communication_category(content, doc.subject, doc.reference_doctype)
        
        if not category:
            frappe.logger().info(f"Could not determine category for communication {doc_name}")
            return
        
        # Update the reference document based on its type
        updated = update_reference_document(doc.reference_doctype, doc.reference_name, category)
        
        if updated:
            reference_doc_url = frappe.utils.get_url_to_form(doc.reference_doctype, doc.reference_name)
            msg = f"""Communication categorized as <b>{category}</b>.<br>
                      Updated Link: <a href="{reference_doc_url}" style="font-weight: bold;">{doc.reference_doctype} {doc.reference_name}</a>"""
            
            frappe.logger().info(f"Communication {doc_name} categorized as '{category}' and updated {doc.reference_doctype} {doc.reference_name}")
            
            # Show popup only if request (Manual Trigger) to avoid background noise, though msgprint handles context usually
            if frappe.request:
                 frappe.msgprint(msg, title="Analysis Success", indicator="green")
        else:
            frappe.logger().info(f"Communication {doc_name} categorized as '{category}' but Reference document {doc.reference_doctype} {doc.reference_name} unchanged")
            if frappe.request:
                frappe.msgprint(f"Category determined as <b>{category}</b> (No update required).", title="Analysis Result", indicator="blue")
             
        return category
        
    except Exception as e:
        frappe.log_error(f"Error analyzing communication {doc_name}: {str(e)}", "Communication Analysis Error")
        # Only throw if it's a direct whitelist call to inform the user, but we are often in background job.
        # If in request (manual button), throw ensures UI error.
        if frappe.request:
            frappe.throw(f"Error: {str(e)}")


def get_communication_category(content, subject="", reference_doctype="Opportunity"):
    """
    Use AI Agent to categorize the communication.
    
    Args:
        content: Email body content
        subject: Email subject
        reference_doctype: The Doctype this communication is linked to
        
    Returns:
        Category string or None
    """
    try:
        # 1. Get Agent Name from Settings
        ai_agent_name = "Communication Analyzer" # Default
        if frappe.get_meta("AI Agent Settings").has_field("communication_analyzer"):
             settings = frappe.get_single("AI Agent Settings")
             if settings.communication_analyzer:
                 ai_agent_name = settings.communication_analyzer

        if not frappe.db.exists("AI Agent", ai_agent_name):
            frappe.log_error(f"AI Agent '{ai_agent_name}' not found", "Communication Analysis Error")
            return None
            
        ai_agent_doc = frappe.get_doc("AI Agent", ai_agent_name)
        agent = ai_agent_doc.agent_service
        
        # 2. Define Options dynamically based on Doctype
        valid_options = []
        
        if reference_doctype == "Opportunity":
            # Fetch names of all Opportunity Types
            valid_options = frappe.get_all("Opportunity Type", pluck="name")
            
        elif reference_doctype in ["Sales Order", "Quotation"]:
            # Fetch options from 'order_type' Select field
            meta = frappe.get_meta(reference_doctype)
            if meta.has_field("order_type"):
                field = meta.get_field("order_type")
                if field.options:
                    # Options are newline separated string
                    valid_options = [opt.strip() for opt in field.options.split("\n") if opt.strip()]
        
        if not valid_options:
             # Default fallback if no options found or generic doctype
             valid_options = ["Sales", "Parts", "Service", "Support", "Administrative"]

        options_str = ", ".join(valid_options)

        # 3. Prepare input for the agent
        ai_input_data = {
            "content": content,
            "subject": subject,
            "doctype": reference_doctype,
            "options": options_str
        }
        
        # Invoke AI Agent
        result = agent.invoke(subject, **ai_input_data)
        
        # Extract category from result
        category = ""
        if hasattr(result, 'content'):
            category = result.content
        elif isinstance(result, dict):
            # Try common keys
            category = result.get('output') or result.get('text') or result.get('response') or str(result)
        else:
             category = str(result)
             
        if not category:
             category = ""
             
        category = category.strip()
        
        # Validate category (Exact match first, then Case-insensitive)
        for valid in valid_options:
            if valid.lower() == category.lower():
                return valid
        
        # Fallback partial match
        for valid in valid_options:
            if valid.lower() in category.lower():
                return valid
        
        frappe.logger().info(f"AI returned category '{category}' which did not match valid options: {valid_options}")
        return None
        
    except Exception as e:
        frappe.log_error(f"Error getting communication category: {str(e)}", "AI Agent Error")
        return None


def update_reference_document(doctype, docname, category):
    """
    Update the reference document with the communication category.
    Uses frappe.db.set_value for direct database update, bypassing validation
    and field editability constraints. This is safe for background jobs.
    
    Args:
        doctype: Reference doctype
        docname: Reference document name
        category: Communication category (Should be a valid option)
    Returns:
        bool: True if updated, False otherwise
    """
    try:
        field_to_update = None
        new_value = None
        current_value = None
        
        if doctype == "Opportunity":
            if frappe.db.exists("Opportunity Type", category):
                current_value = frappe.db.get_value(doctype, docname, "opportunity_type")
                if current_value != category:
                    field_to_update = "opportunity_type"
                    new_value = category
            else:
                frappe.log_error(f"Opportunity Type '{category}' does not exist.", "Reference Update Error")
                return False
                
        elif doctype in ["Sales Order", "Quotation"]:
            current_value = frappe.db.get_value(doctype, docname, "order_type")
            if current_value != category:
                field_to_update = "order_type"
                new_value = category
                
        elif doctype == "Lead":
            type_mapping = {
                "Sales": "Product Enquiry",
                "Parts": "Request for Information",
                "Service": "Request for Information",
                "Support": "Suggestions",
                "Administrative": "Request for Information"
            }
            new_type = type_mapping.get(category)
            if not new_type:
                category_lower = category.lower()
                if "part" in category_lower: 
                    new_type = "Request for Information"
                elif "service" in category_lower: 
                    new_type = "Request for Information"
                else: 
                    new_type = "Product Enquiry"

            current_value = frappe.db.get_value(doctype, docname, "request_type")
            if current_value != new_type:
                field_to_update = "request_type"
                new_value = new_type
            
        elif doctype == "Customer":
            frappe.logger().info(f"Customer {docname} communication categorized as {category}")
            return False
            
        if field_to_update and new_value:
            frappe.db.set_value(doctype, docname, field_to_update, new_value, update_modified=False)
            frappe.db.commit()
            return True
            
        return False
            
    except Exception as e:
        frappe.log_error(f"Error updating {doctype} {docname}: {str(e)}", "Reference Update Error")
        return False
