# Foreign R&D Ledger Hardening Design

## Scope

This change fixes three immediate P1 defects on PR #24:

1. A month with foreign R&D expense but no submitted domestic allocation must still return ledger totals.
2. Foreign aggregation failures must fail visibly instead of being converted to zero or an empty list.
3. Concurrent first saves for the same foreign R&D month must not create duplicate documents.

Two deferred risks are tracked as GitHub issues: cumulative daily foreign hours above eight and OCR decompression-bomb protection. The native Frappe endpoint bypass is added to the existing security issue #28 rather than duplicated.

## Design

### Foreign-only ledger

The get_allocation function will calculate foreign stage totals before deciding whether a domestic allocation exists. If no domestic document exists, it returns the normal monthly response shape with zero domestic lines and the foreign totals. Existing responses for months with domestic allocations remain unchanged.

### Visible aggregation failures

The broad exception handlers in _foreign_stage_totals and _foreign_dashboard_lines will be removed. A legitimate month with no foreign data already returns empty totals through the called functions; unexpected import, database, or calculation failures will propagate to the API and be logged by Frappe instead of producing incorrect financial zeroes.

### Concurrent monthly creation

New Foreign RD Expense documents will use a deterministic name derived from the normalized period: FRD-YYYY-MM. Existing documents keep their names. Two simultaneous first saves therefore contend on the same database primary key; one succeeds and the other receives a duplicate/conflict error instead of creating a second document. Existing-document saves continue using Frappe timestamp conflict protection.

The API will translate a duplicate insert into a clear refresh-and-retry message. It will not automatically overwrite the winning save.

## Compatibility

- No existing document is renamed.
- Domestic allocation calculations and submitted allocation records are unchanged.
- Successful foreign calculations keep the same response fields and monetary values.
- Failures become visible, which is intentional because silently returning zero corrupts financial reporting.

## Testing

- A regression test proves a foreign-only month returns foreign stage totals with no domestic allocation document.
- Regression tests prove stage and dashboard calculation exceptions propagate.
- A controller test proves new documents receive one deterministic name per period.
- An API test proves duplicate insert conflicts do not trigger an overwrite.
