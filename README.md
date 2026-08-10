<div align="center">
  <h1>Finbyzreach 🚀</h1>
  <p><strong>AI-Powered Smart CRM Outreach, Enrichment, and Automated Follow-ups for Frappe</strong></p>
</div>

## 🌟 Overview

**Finbyzreach** supercharges your Frappe CRM by automating the most tedious parts of sales: researching prospects and writing highly personalized follow-up emails. Built on top of [FinByz AI](https://github.com/finbyz/finbyzai), Finbyzreach acts as an autonomous Sales Development Representative (SDR) operating directly within your ERPNext / Frappe environment.

It intelligently detects stalled Opportunities, autonomously researches the target Company and Person using AI Agents (like Perplexity), analyzes past CRM activities, and drafts hyper-personalized outbound emails—all running seamlessly in the background.

## ✨ Key Features

- **🧠 Autonomous Prospect Research**: Automatically enriches `Lead`, `Customer`, and `Contact` records with missing data (Industry, Employee Count, Location, LinkedIn Profiles, and detailed company overviews) using dedicated Research AI Agents.
- **⏱️ Smart Stale-Opportunity Detection**: A daily scheduled job evaluates all open Opportunities. If no communication has occurred within a configured threshold (e.g., 5 days), it flags the record for follow-up.
- **✉️ Context-Aware Email Drafting**: Analyzes the prospect's background research alongside recent CRM activities (CRM Notes, past Emails) to generate incredibly contextual, human-like follow-up emails via the Email Agent.
- **⚡ Automated Outbound Queuing**: Emails are securely drafted as Frappe `Communication` records and queued for dispatch, supporting custom email accounts and signatures.
- **🔗 Deep FinByz AI Integration**: Leverages `finbyzai`'s `AgentService` to dynamically route research queries to the best LLMs available.

## ⚙️ How It Works (The Workflow)

1. **Trigger Evaluation**: At 4:00 PM daily, the `smart_followup` job scans for `Lead` or `Customer` records with open `Opportunity` documents lacking recent communication.
2. **Context Gathering & Enrichment**:
   - The **Person Research Agent** investigates the contact's background and LinkedIn profile.
   - The **Company Research Agent** investigates the company, updating the CRM record with missing firmographic data (Industry, Size, Website).
3. **Activity Compilation**: The system gathers the last 5 `CRM Note`s and `Communication`s to understand the exact context of the deal.
4. **Email Generation**: The **Email Agent** takes the prospect research and activity history, invoking the LLM to draft a highly personalized, context-aware email.
5. **Draft & Send**: The resulting email is attached to the target record and queued for the 10-minute outbound mail dispatcher.

## 🚀 Installation

### Prerequisites
Finbyzreach requires **FinByz AI** to function. Ensure `finbyzai` is installed on your bench first.

### Setup

```bash
cd $PATH_TO_YOUR_BENCH

# Fetch the application from the repository
bench get-app https://github.com/finbyz/finbyzreach.git --branch main

# Install the application on your target site
bench --site [your-site-name] install-app finbyzreach
```

## 🛠️ Configuration Guide

### 1. Configure the AI Agents
Ensure you have created the required agents in the **AI Agent** doctype (provided by `finbyzai`):
- `Person Research Agent` (Recommended LLM: Perplexity or GPT-4o with Search tools).
- `Company Research Agent`.
- `Email Drafting Agent`.

### 2. Followup Settings
Navigate to **Lead Followup Setting** (or Followup Settings) in Frappe Desk:
1. Toggle **Is Enable** to turn on the background automation.
2. Set the **Days Since Last Activity** (e.g., `5` days). If an opportunity has no activity for this duration, it triggers the follow-up process.
3. Select the default **Email Account** to use for dispatching emails.
4. Map your configured AI Agents for Company Research, Person Research, and Email Drafting.

## ⏱️ Scheduled Jobs

Finbyzreach relies on Frappe's scheduler to operate autonomously:
- `00 16 * * *` (Daily at 4:00 PM): Runs the `smart_followup.run_followup_job` to identify stale opportunities, conduct research, and draft emails.
- `*/10 * * * *` (Every 10 Minutes): Runs the `enqueue_outbound_emails` job to dispatch drafted communications.

*Ensure your bench scheduler is active (`bench enable-scheduler`).*

## 🤝 Contributing

We welcome contributions! Please ensure your code adheres to standard Frappe formatting and that any new AI agent integrations remain decoupled via the `AgentService`.

## 📄 License

This project is licensed under the **MIT** License.
