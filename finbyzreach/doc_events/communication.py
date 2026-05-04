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
    try:
        doc = frappe.get_doc("Communication", doc_name)
    except frappe.DoesNotExistError:
        frappe.logger().info(f"Communication {doc_name} no longer exists, skipping analysis.")
        return

    if not doc.reference_doctype or not doc.reference_name:
        return
    
    # Get the content to analyze
    content = doc.content or doc.text_content or doc.subject
    if not content:
        return
    
    try:
        # Determine communication category and description using AI
        result = get_communication_category(content, doc.subject, doc.reference_doctype)
        
        if not result:
            frappe.logger().info(f"Could not determine category for communication {doc_name}")
            return
        
        category = result.get("category")
        description = result.get("description", "")
        
        if not category:
            frappe.logger().info(f"No category returned for communication {doc_name}")
            return
        
        # Update the reference document based on its type
        updated = update_reference_document(doc.reference_doctype, doc.reference_name, category, description)
        
        if updated:
            reference_doc_url = frappe.utils.get_url_to_form(doc.reference_doctype, doc.reference_name)
            msg = f"""Communication categorized as <b>{category}</b>.<br>
                      Updated Link: <a href="{reference_doc_url}" style="font-weight: bold;">{doc.reference_doctype} {doc.reference_name}</a>"""
            
            frappe.logger().info(f"Communication {doc_name} categorized as '{category}' and updated {doc.reference_doctype} {doc.reference_name}")
            
            if frappe.request:
                 frappe.msgprint(msg, title="Analysis Success", indicator="green")
        else:
            frappe.logger().info(f"Communication {doc_name} categorized as '{category}' but Reference document {doc.reference_doctype} {doc.reference_name} unchanged")
            if frappe.request:
                frappe.msgprint(f"Category determined as <b>{category}</b> (No update required).", title="Analysis Result", indicator="blue")
             
        return category
        
    except Exception as e:
        frappe.log_error(f"Error analyzing communication {doc_name}: {str(e)}", "Communication Analysis Error")
        if frappe.request:
            frappe.throw(f"Error: {str(e)}")


def get_communication_category(content, subject="", reference_doctype="Opportunity"):
    """
    Use AI Agent to categorize the communication and generate a short description.
    
    Args:
        content: Email body content
        subject: Email subject
        reference_doctype: The Doctype this communication is linked to
        
    Returns:
        dict with 'category' and 'description' keys, or None on failure
    """
    try:
        # 1. Get Agent Name from AI Agent Settings (required)
        ai_agent_name = None
        if frappe.get_meta("AI Agent Settings").has_field("communication_analyzer"):
            settings = frappe.get_single("AI Agent Settings")
            ai_agent_name = settings.communication_analyzer

        if not ai_agent_name:
            frappe.log_error("Communication Analyzer not configured in AI Agent Settings", "Communication Analysis Error")
            return None

        if not frappe.db.exists("AI Agent", ai_agent_name):
            frappe.log_error(f"AI Agent '{ai_agent_name}' not found", "Communication Analysis Error")
            return None
            
        ai_agent_doc = frappe.get_doc("AI Agent", ai_agent_name)
        agent = ai_agent_doc.agent_service
        
        # 2. Define Options dynamically based on Doctype
        valid_options = []
        
        if reference_doctype == "Opportunity":
            valid_options = frappe.get_all("Opportunity Type", pluck="name")
            
        elif reference_doctype in ["Sales Order", "Quotation"]:
            meta = frappe.get_meta(reference_doctype)
            if meta.has_field("order_type"):
                field = meta.get_field("order_type")
                if field.options:
                    valid_options = [opt.strip() for opt in field.options.split("\n") if opt.strip()]
        
        if not valid_options:
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
        
        # Extract response from result
        response_text = ""
        if hasattr(result, 'content'):
            response_text = result.content
        elif isinstance(result, dict):
            response_text = result.get('output') or result.get('text') or result.get('response') or str(result)
        else:
            response_text = str(result)
             
        if not response_text:
            return None
             
        response_text = response_text.strip()
        
        # Parse JSON response from AI
        # Strip markdown code blocks if present (e.g., ```json ... ```)
        import json
        import re
        
        clean_text = response_text
        # Remove markdown code block wrapper
        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
        if code_block_match:
            clean_text = code_block_match.group(1).strip()
        
        try:
            parsed = json.loads(clean_text)
            ai_category = parsed.get("category", "").strip()
            ai_description = parsed.get("description", "").strip()
        except json.JSONDecodeError:
            # Fallback: assume it's just the category (old format)
            ai_category = response_text
            ai_description = ""
        
        # Validate category
        matched_category = None
        for valid in valid_options:
            if valid.lower() == ai_category.lower():
                matched_category = valid
                break
        
        if not matched_category:
            for valid in valid_options:
                if valid.lower() in ai_category.lower():
                    matched_category = valid
                    break
        
        if not matched_category:
            frappe.logger().info(f"AI returned category '{ai_category}' which did not match valid options: {valid_options}")
            return None
        
        return {
            "category": matched_category,
            "description": ai_description
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting communication category: {str(e)}", "AI Agent Error")
        return None


def update_reference_document(doctype, docname, category, description=""):
    """
    Update the reference document with the communication category and description.
    Uses frappe.db.set_value for direct database update, bypassing validation
    and field editability constraints. This is safe for background jobs.
    
    Args:
        doctype: Reference doctype
        docname: Reference document name
        category: Communication category (Should be a valid option)
        description: Short description of the email (2-3 lines)
    Returns:
        bool: True if updated, False otherwise
    """
    try:
        field_to_update = None
        new_value = None
        current_value = None
        updated = False
        
        if doctype == "Opportunity":
            if frappe.db.exists("Opportunity Type", category):
                current_value = frappe.db.get_value(doctype, docname, "opportunity_type")
                if current_value != category:
                    frappe.db.set_value(doctype, docname, "opportunity_type", category, update_modified=False)
                    updated = True
                
                # Store description in customer_application field
                if description:
                    frappe.db.set_value(doctype, docname, "customer_application", description, update_modified=False)
                    updated = True
            else:
                frappe.log_error(f"Opportunity Type '{category}' does not exist.", "Reference Update Error")
                return False
                
        elif doctype in ["Sales Order", "Quotation"]:
            current_value = frappe.db.get_value(doctype, docname, "order_type")
            if current_value != category:
                frappe.db.set_value(doctype, docname, "order_type", category, update_modified=False)
                updated = True
            
            # Log description for Sales Order/Quotation since they don't have a dedicated field
            if description:
                frappe.log_error(
                    f"Email Description for {doctype} {docname}:\nCategory: {category}\nDescription: {description}",
                    f"Communication Analysis - {doctype}"
                )
                
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
                frappe.db.set_value(doctype, docname, "request_type", new_type, update_modified=False)
                updated = True
            
        elif doctype == "Customer":
            frappe.logger().info(f"Customer {docname} communication categorized as {category}")
            return False
            
        if updated:
            frappe.db.commit()
            return True
            
        return False
            
    except Exception as e:
        frappe.log_error(f"Error updating {doctype} {docname}: {str(e)}", "Reference Update Error")
        return False
