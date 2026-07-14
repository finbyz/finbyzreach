import frappe


AI_AGENTS = [{'agent_type': 'LangChain Chain',
  'docstatus': 0,
  'doctype': 'AI Agent',
  'enable_memory': 0,
  'gemini_cache': None,
  'knowledge_base': None,
  'lc_agent_type': None,
  'llm': 'perplexity/sonar',
  'llm_provider': 'Perplexity',
  'max_iterations': 0,
  'max_tokens': 0,
  'memory_type': None,
  'messages': [{'content': 'You are an expert Technical Sales Consultant for Megasol, specialized '
                           'in solar energy solutions, BIPV (Building Integrated Photovoltaics), '
                           'and renewable energy infrastructure.\n'
                           '\n'
                           'Your goal is to analyze a lead and provide a pre-call consultative '
                           'strategy for the sales team. You must determine what the company does, '
                           "their pain points, and how Megasol's specific solutions fit into their "
                           'strategic goals.\n'
                           '\n'
                           'IMPORTANT:\n'
                           'You MUST use the "Extract main content from url" tool to extract the '
                           "content from the lead's website URL.\n"
                           'Do not guess or hallucinate.\n'
                           'Scrape the website first, then analyze the content!\n'
                           '\n'
                           'MEGASOL KNOWLEDGE BASE\n'
                           '\n'
                           'Target Audience:\n'
                           '\n'
                           '* Installers / EPC:\n'
                           '  Looking for reliable, high-quality solar modules and mounting '
                           'systems.\n'
                           '\n'
                           '* Architects / Specifiers:\n'
                           '  Interested in aesthetics, BIPV, custom solar facades, and '
                           'sustainable building design.\n'
                           '\n'
                           '* Developers / Investors:\n'
                           '  Focused on ROI, large-scale deployment, and long-term warranties.\n'
                           '\n'
                           '* Commercial / Industrial:\n'
                           '  Interested in roof-top solar to offset energy costs and ESG '
                           'compliance.\n'
                           '\n'
                           'ANALYSIS INSTRUCTIONS\n'
                           '\n'
                           'Analyze the provided company and website.\n'
                           'Generate a report with the following sections:\n'
                           '\n'
                           '1. Operational Profile & Lead Type\n'
                           '\n'
                           '* What is their primary business?\n'
                           '  Examples:\n'
                           '\n'
                           '  * Solar Installer\n'
                           '  * Architectural Firm\n'
                           '  * Real Estate Developer\n'
                           '\n'
                           '2. Consultative Fit (The "Why Megasol?" Pitch)\n'
                           '\n'
                           '* Identify their likely pain points based on their profile.\n'
                           '  Examples:\n'
                           '\n'
                           '  * Need for custom-sized solar panels\n'
                           '  * High aesthetic requirements\n'
                           '  * Sustainability compliance\n'
                           '  * Commercial energy optimization\n'
                           '\n'
                           '3. Recommended Megasol Solutions\n'
                           '\n'
                           '* Map their activities to specific Megasol products or solutions.\n'
                           '\n'
                           '4. Buying Signals & Triggers\n'
                           '   Look for keywords such as:\n'
                           '\n'
                           '* Sustainability\n'
                           '* Green Building\n'
                           '* BIPV\n'
                           '* Solar Facades\n'
                           '* Energy Independence\n'
                           '\n'
                           'ERPNext Data Classification:\n'
                           '\n'
                           'You must select one or more lead types from the following exact '
                           'options:\n'
                           '{available_lead_types}\n'
                           '\n'
                           'You must select exactly one industry from the following list:\n'
                           '{available_industry_types}\n'
                           '\n'
                           'Do NOT invent industry names.\n',
                'content_type': 'text',
                'type': 'system'},
               {'content': 'Research the company "{company}" (website: {website}) and the person '
                           '"{full_name}" located in {city}, {state}, {territory}, {country}.\n'
                           '\n'
                           'Your task is to identify solar energy sales opportunities for Megasol '
                           'Energy Ltd.\n'
                           '\n'
                           'Analyze their business:\n'
                           '- What is their primary business activity? (e.g., Solar Installer, '
                           'Architectural Firm, Real Estate Developer, EPC Contractor, Facility '
                           'Manager)\n'
                           '- Based on their company type, what solar energy needs might they '
                           'have? (e.g., BIPV for new construction, rooftop PV for warehouses, '
                           'facade-integrated solar for commercial buildings, custom solar modules '
                           'for architectural projects)\n'
                           '- What are their likely pain points related to energy, sustainability, '
                           'or building design?\n'
                           '\n'
                           'Match to Megasol:\n'
                           '- Which specific Megasol solution would address their energy or design '
                           'needs?\n'
                           '- What is the best conversation opener based on their business '
                           'profile?\n'
                           '\n'
                           'Classification Rules (CRITICAL):\n'
                           '- You MUST classify the lead_type using ONLY one of these exact '
                           'values: {available_lead_types}. If none fit perfectly, choose the '
                           'closest match.\n'
                           '- You MUST classify the industry_type using ONLY one of these exact '
                           'values: {available_industry_types}. If none fit perfectly, choose the '
                           'closest match.\n'
                           '- Output the JSON strictly according to the schema.',
                'content_type': 'text',
                'type': 'human'}],
  'modified': '2026-05-28 11:24:47.540519',
  'name': 'Company Research',
  'output_schema': '{\n'
                   '    "properties": {\n'
                   '        "company_overview": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "Company Overview"\n'
                   '        },\n'
                   '        "industry_type": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "Industry Type"\n'
                   '        },\n'
                   '        "lead_type": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "Lead Type"\n'
                   '        },\n'
                   '        "country": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "Country"\n'
                   '        },\n'
                   '        "state": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "State"\n'
                   '        },\n'
                   '        "city": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "City"\n'
                   '        },\n'
                   '        "website": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "Website"\n'
                   '        },\n'
                   '        "designation": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "Designation"\n'
                   '        },\n'
                   '        "no_of_employees": {\n'
                   '            "anyOf": [\n'
                   '                {\n'
                   '                    "type": "string"\n'
                   '                },\n'
                   '                {\n'
                   '                    "type": "null"\n'
                   '                }\n'
                   '            ],\n'
                   '            "title": "No Of Employees"\n'
                   '        }\n'
                   '    },\n'
                   '    "required": [\n'
                   '        "company_overview",\n'
                   '        "industry_type",\n'
                   '        "lead_type",\n'
                   '        "country",\n'
                   '        "state",\n'
                   '        "city",\n'
                   '        "website",\n'
                   '        "designation",\n'
                   '        "no_of_employees"\n'
                   '    ],\n'
                   '    "title": "CompanyResearch",\n'
                   '    "type": "object"\n'
                   '}',
  'temperature': 0.0,
  'title': 'Company Research',
  'tools': [{'tool': 'Extract main content from url'}],
  'verbose_mode': 0},
 {'agent_type': 'LangChain Chain',
  'docstatus': 0,
  'doctype': 'AI Agent',
  'enable_memory': 0,
  'gemini_cache': None,
  'knowledge_base': None,
  'lc_agent_type': '',
  'llm': 'perplexity/sonar',
  'llm_provider': 'Perplexity',
  'max_iterations': 0,
  'max_tokens': 0,
  'memory_type': 'Buffer Memory',
  'messages': [{'content': 'You are a B2B sales intelligence and prospect research assistant '
                           'specialized in the solar energy and renewable energy industry.\n'
                           '\n'
                           'Your task is to research a specific person and return ONLY structured, '
                           "factual, sales-relevant insights that will help Megasol Energy Ltd.'s "
                           'sales team prepare for outreach.\n'
                           '\n'
                           'Focus on:\n'
                           '- Current role, responsibilities, and seniority level\n'
                           '- Decision-making authority or influence level (technical, financial, '
                           'procurement, or executive)\n'
                           '- Company context relevant to solar energy sales (e.g., sustainability '
                           'initiatives, building projects, energy procurement)\n'
                           '- Recent professional activity or signals (last 6–12 months if '
                           'available): job changes, promotions, company expansions, '
                           'sustainability commitments, new construction projects\n'
                           '- Clear potential sales opportunities or conversation starters based '
                           "on their role and how Megasol's solutions (BIPV, facade solar, rooftop "
                           'PV, custom solar modules) could fit their needs\n'
                           '\n'
                           'Use reliable, publicly available sources only.\n'
                           'If information is uncertain or inferred, clearly state assumptions.\n'
                           'Do NOT hallucinate facts.\n'
                           'Do NOT include opinions, fluff, or generic descriptions.\n'
                           '\n'
                           'Return output strictly according to the provided JSON schema.',
                'content_type': 'text',
                'type': 'system'},
               {'content': 'Research the person "{full_name}" based in {city}, {territory}, '
                           '{country}, currently working at "{company}".\n'
                           '\n'
                           'Deliver:\n'
                           '1. A concise, sales-focused research summary relevant for B2B solar '
                           'energy outreach by Megasol Energy Ltd.\n'
                           '2. Recent professional signals (job change, promotion, hiring '
                           'activity, company initiatives, sustainability commitments, building '
                           'projects, energy procurement, ESG reporting, etc.)\n'
                           '3. Potential sales opportunities or conversation starters aligned with '
                           "their role and how Megasol's solutions (BIPV, facade-integrated solar, "
                           "rooftop PV, architectural solar) could address their company's needs\n"
                           '4. The most likely LinkedIn profile URL ONLY if it clearly matches the '
                           "person's name, company, role, and location\n"
                           '\n'
                           'Rules:\n'
                           '- Keep insights practical and actionable for a sales call\n'
                           '- Avoid generic role descriptions\n'
                           '- Focus on signals that indicate readiness for solar/sustainability '
                           'investment\n'
                           '- If LinkedIn profile cannot be confidently identified, return an '
                           'empty string ""\n'
                           '- Do NOT guess personal details\n'
                           '- Output MUST strictly match the JSON schema',
                'content_type': 'text',
                'type': 'human'}],
  'modified': '2026-01-13 07:15:44.930773',
  'name': 'Person Research',
  'output_schema': '{\r\n'
                   '\t"properties": {\r\n'
                   '\t\t"linkedin_profile": {\r\n'
                   '\t\t\t"default": "LinkedIn profile url",\r\n'
                   '\t\t\t"title": "Linkedin Profile",\r\n'
                   '\t\t\t"type": "string"\r\n'
                   '\t\t},\r\n'
                   '\t\t"research_summary": {\r\n'
                   '\t\t\t"default": "Research summary about Person",\r\n'
                   '\t\t\t"title": "Research Summary",\r\n'
                   '\t\t\t"type": "string"\r\n'
                   '\t\t}\r\n'
                   '\t},\r\n'
                   '\t"title": "PersonResearch",\r\n'
                   '\t"type": "object"\r\n'
                   '}',
  'temperature': 0.0,
  'title': 'Person Research',
  'tools': [],
  'verbose_mode': 0}]


def after_install():
	create_ai_agents()


def create_ai_agents():
	for agent in AI_AGENTS:
		if frappe.db.exists("AI Agent", agent["name"]):
			continue

		agent = agent.copy()
		agent.pop("modified", None)
		frappe.get_doc(agent).insert(ignore_permissions=True)
