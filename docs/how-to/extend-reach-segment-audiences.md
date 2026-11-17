# Extending and operating Reach Segment audiences

This guide implements chapter 19 SEG-12 for the `megasol` / `finbyzreach` subproject. It describes the current source, including the approved native Frappe permission policy and the detail layout: filters on the left and members on the right on wide screens (stacked below 1200 px).

## Current model

| Concern | Authority |
| --- | --- |
| Supported record types | `segment_service.AUDIENCE_TYPES` and the Reach Segment `audience_doctype` Select |
| Active membership | `member_query`: saved expression or legacy groups, union preserved Manual rows, then exclusions and native record visibility |
| Static membership | Published `snapshot_generation` in Reach Segment Snapshot Row, plus Manual rows; legacy snapshots continue using Reach Segment Member |
| Observation and notifications | Reach Segment Member and its `is_current` flag, processed under a segment row lock |
| Individual exclusions | Reach Segment Exclusion, independent of snapshots |
| Membership audit | Append-only Reach Segment Membership Event: Entered, Left, Excluded, Restored |
| Definition audit | Native Frappe Version history on Reach Segment; exclusion changes also update definition metadata |
| Size history | One Reach Segment Size Sample per segment/day |
| Access | Native role/document permissions; export checks Read and Export, mutations check Write |

Manual additions are permitted only for Static segments. Static-to-Active conversion retains Manual records. Active-to-Static preparation captures the former Active definition. Snapshot candidates retain excluded records so later Restore can work without losing the original candidate. Exclusions remain authoritative during recalculation and type changes.

## Add another object type

1. Look up the exact DocType schema, child tables, native permissions and available identity fields. Choose a stable record ID, display field and optional email field. Never infer field names from another audience.
2. Add the DocType to `AUDIENCE_TYPES` in `segment_service.py` and to the `audience_doctype` Select in `reach_segment.json`. Do not change or rename existing segment audiences. Run schema synchronization through a migration; existing segments retain their stored audience and cannot change it after creation.
3. Add its display/search mapping in `segments.preview_segment_page` and the display/email mapping in `effective_columns`. The shared field-filter validators use `AUDIENCE_TYPES` and native metadata, including declared child tables. Keep their operator and request-size limits.
4. Define only real connected-object relationships in `related_condition` and expose those choices in `ReachSegmentBuilder.relatedDialog`. Handle nullable links, native related-record visibility, and any/all semantics. For contacts, Customer matching must use the explicitly selected main Customer, not an arbitrary Dynamic Link.
5. Decide which activity adapters can resolve the new object. Map email/webinar identities explicitly; website/store adapters require configured tracking visitor fields. Unsupported activity identities must fail clearly. Store purchases require ecommerce goal ID zero and a nonempty order ID; an optional tracking site ID narrows that source.
6. Register `capture_change` for updates and deletion of the new audience. Add related-record fan-out for any relationship its filters depend on. Fan-out must page records and coalesce identity work rather than synchronously enumerate a large customer base. Cover cancellation where relevant.
7. Add the audience to `segment_membership.js` and the shared `doctype_list_js` hook so record widgets and list actions load after native list settings. Preserve existing handlers. Update/create selection requests in chunks of at most 500 records.
8. If workflows can enroll this DocType, add it to the `crm.segment.entered` context in FinbyzAI's workflow registry. Keep the segment picker restricted to unarchived segments. Use the existing workflow eligibility checks; never expand all events indiscriminately.
9. Template membership predicates require the template's reference DocType to match the segment audience. Validate read access and archive state. **Campaign delivery is a separate extension:** implement email resolution, deduplication, opt-outs, subscription consent, personalization, preference language, signed links and reporting before allowing a new recipient type. Do not merely expand the Campaign Select.
10. Add indexed relationship and history queries through an idempotent patch. Register it in `patches.txt`; update fresh-install setup where necessary. Use native DocType synchronization and Frappe query builder. Preserve native permission settings.

Current Opportunity/Sales Order segments illustrate the distinction: their own fields and connected Customer filters work, and their record widgets, reports and exports are available. Marketing recipient validation remains limited to Lead/Contact/Customer.

## Required regression checks

- Active entry and exit after direct field changes, related-object changes, cancellation/deletion and referenced/excluded segment changes.
- Static creation with and without filters, no automatic additions from ordinary record saves, filter recalculation retaining Manual members, both type conversions and both duplicate options.
- Individual exclusions survive recalculation and type changes; restoring an excluded candidate works even after a Static snapshot rebuild.
- Mixed nested field/segment/activity/related groups round-trip through the editor, and editing a deep field preserves sibling conditions without marking an untouched form dirty.
- Native row visibility applies to preview, filters, widgets, related objects, export and history. Read-only users can inspect exclusions/history, but cannot mutate them.
- Preview and default export columns match; explicit export selection contains exactly those fields. Native Export permission is checked again in the worker.
- More than 50 exclusions and more than 50 readable segment definitions are reachable through pagination. Large manual selection is sent in bounded requests.
- Retried/concurrent jobs do not emit a second entry for an already observed current member. A genuine exit and later return emit a new entry.
- Verify at least 20k–30k records: save probes at most 1,001 candidates; snapshot jobs process at most 500; reconciliation uses 200; widget definitions use pages of 50; history and exclusions use pages of 50.
- Test actual MariaDB query plans and browser behavior on the target site before production acceptance. SQLite and mocked tests are not substitutes for those checks.

## Snapshot recovery and timing

Small Static snapshots publish in the save transaction. Above 1,000 candidates, the save records Queued state and keeps the last complete generation while preparation runs. The form polls status; exports, mailing selection, member mutation and duplication wait for preparation to finish. Definition edits are blocked during preparation. The worker stages 500 candidates per call, then atomically changes the published generation pointer. Unchanged Manual rows keep their source.

The scheduler recovers Queued/Building work from the last committed staging cursor. Failed work retains its pending generation and shows a Retry action to editors. Stale jobs cannot publish over a newer generation. Old staging generations are removed in bounded cleanup jobs. The queue and database must both be healthy for automatic completion.

Candidate queries run as preparation pages execute; this is not a cross-job database snapshot taken at the exact instant of Save. Concurrent CRM changes during a large build can affect the captured candidates. Define an acceptable preparation window or add an authoritative source-version mechanism if the business requires an exact historical point-in-time snapshot.

Member observation, event insertion and state changes share one database transaction under the segment lock. Excluded Manual rows remain stored with `is_current = 0`; Restore marks them current and prevents the following reconciliation from emitting a duplicate entry. Exclusion actions record the acting user. Other membership history records the user processing the change. No historical membership is invented for records created before this feature.

Daily sizes start when sampling/reconciliation first runs. Archived segments are skipped by scheduled reconciliation and sampling, and are hidden from target selectors. Restoring an Active segment queues immediate reconciliation. Native role permissions, rather than custom User checkboxes, remain the access-control authority.
