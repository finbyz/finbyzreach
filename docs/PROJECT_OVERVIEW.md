# Finbyz Reach — Overview

**Scope:** Subproject of `megasol`
**Repo path:** `apps/finbyzreach`

FinbyzReach provides CRM audience segmentation, email template authoring, subscription preferences, campaign preparation and marketing delivery through Frappe's Email Queue. See [the existing app inventory](SUBPROJECT_OVERVIEW.md) for the wider outreach modules.

Reach Segments support Lead, Contact, Customer, Opportunity and Sales Order records. Active membership uses current saved criteria. Static membership uses stored snapshots, preserves manual additions and always applies exclusions afterwards. Large Static snapshots run in bounded jobs and publish a complete generation atomically. Native Frappe role and document permissions govern access.

Marketing campaigns still use Lead, Contact or Customer recipients. Opportunity/Sales Order segments support audience organization, filtering, reports, exports and eligible workflow events; adding a segment audience does not automatically add a safe marketing-delivery adapter.

The detail view provides Members, Excluded and History tabs, saved columns, exact permission-aware counts, CSV/XLSX export and membership/size history. History starts when tracking is enabled; it does not reconstruct past changes.

See [the audience extension and operations guide](how-to/extend-reach-segment-audiences.md) for implementation boundaries, recovery and required regression checks.
