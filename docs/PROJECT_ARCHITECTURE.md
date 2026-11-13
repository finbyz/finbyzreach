# Finbyz Reach architecture

Project: `megasol` · App: `finbyzreach` · Updated: 2026-11-13

Finbyz Reach extends Frappe Desk with campaign preparation, subscription preferences, email templates and saved audience segments. App hooks register client assets, document change adapters and scheduled recovery. ERPNext owns the CRM/business records; FinbyzAI owns workflow enrollment and execution. Native Frappe roles and document permissions govern access.

## Reach Segment data and execution

`Reach Segment` stores immutable audience type, inclusion/exclusion definitions, display columns and preparation state. `segment_service.py` compiles permission-aware queries using Frappe query builder. Active audiences query current record data; Static audiences use published snapshot rows plus retained Manual membership. Exclusions take precedence in both modes.

`segment_snapshots.py` stages large Static snapshots in bounded pages and publishes a generation pointer after completion. A failed chunk rolls back to its savepoint and retains retry state. `segment_automation.py` captures changed identities, reconciles membership, follows segment dependencies and signals the FinbyzAI `crm.segment.entered` topic. Segment locks and current-member markers prevent duplicate entry notifications from repeated observation.

`Reach Segment Membership Event` stores subsequent observations and manual exclusion/restoration events. `Reach Segment Size Sample` stores one size sample per day. These storage DocTypes have no standalone user permissions: `segments.py` authorizes access through the parent segment and applicable audience records.

`reach_segment.js` uses native Frappe FilterGroup controls for field predicates and preserves recursive special/group expressions. Member, exclusion and history results use bounded pages. Desk assets provide record membership actions and a folder library. CSV/XLSX exports run in a background worker and recheck native Export permission.

Campaign preparation and delivery remain separate from segment snapshots. Campaign recipient types are Lead, Contact and Customer; Opportunity and Sales Order segment audiences support analysis and workflow use without introducing a marketing-consent adapter for those objects.

See [audience extension and recovery guide](how-to/extend-reach-segment-audiences.md) for integration points, limits and regression requirements, and [subproject overview](SUBPROJECT_OVERVIEW.md) for the wider app layout.
