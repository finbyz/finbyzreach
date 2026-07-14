# Finbyz Reach Subproject Overview

Generated from the local bench on 2026-07-17.

## Registry

| Field | Value |
| --- | --- |
| Project | `megasol` |
| App key | `finbyzreach` |
| Display name | Finbyz Reach |
| Registry description | Outreach and communication app |
| Repo path | `apps/finbyzreach` |

## Purpose

AI-Powered Follow-ups and Smart Email Outreach

## Source Layout

| Area | Local findings |
| --- | --- |
| Frappe modules | `Finbyzreach`, `AI Email Outreach` |
| Important directories | `ai_email_outreach`, `api`, `config`, `doc_events`, `finbyzreach`, `fixtures`, `public`, `tasks`, `templates`, `utils`, `docs` |
| Frappe hook integrations | DocType client scripts, Document event hooks, Scheduled jobs |

## Feature Signals

- ai outreach and email automation.

## Frappe Data Model

### DocTypes

- `AI Email Campaign`
- `AI Email Campaign Schedules`
- `Communication Email`
- `Email Accounts`
- `Email Sending Schedule`
- `Followup Settings`
- `Lead Followup Setting`
- `Outbound Email`

### Pages

- None found in the local source tree.

## Public and Frontend Assets

- `finbyzreach/public/js/communication.js`
- `finbyzreach/public/js/contact.js`
- `finbyzreach/public/js/customer.js`
- `finbyzreach/public/js/lead.js`

## Existing Documentation

- `README.md`

## Test Coverage Pointers

- `finbyzreach/ai_email_outreach/doctype/ai_email_campaign/test_ai_email_campaign.py`
- `finbyzreach/ai_email_outreach/doctype/email_accounts/test_email_accounts.py`
- `finbyzreach/ai_email_outreach/doctype/followup_settings/test_followup_settings.py`
- `finbyzreach/ai_email_outreach/doctype/lead_followup_setting/test_lead_followup_setting.py`
- `finbyzreach/ai_email_outreach/doctype/outbound_email/test_outbound_email.py`

## Maintenance Notes

- Keep this file aligned with `project-memory.yaml` whenever the app key, description, or repo path changes.
- Add focused feature docs under `apps/finbyzreach/docs` when implementing workflows that span multiple modules or DocTypes.
- Re-run documentation indexing with `index_docs({"project": "megasol", "app": "finbyzreach", "force": true})` after significant documentation changes.
