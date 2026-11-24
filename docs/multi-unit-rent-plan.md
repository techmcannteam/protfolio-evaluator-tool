# RentCast-only multi-unit implementation

ATTOM has no active subscription. Keep `ENABLE_ATTOM=false`; retain its adapter for possible future use. No ATTOM HTTP calls or cached ATTOM AVMs contribute to new runs.

1. Preserve provider `features.unitCount`, parcel identifier, matched address, and endpoint-specific subject metadata. Missing unit counts stay unknown. Selective property-detail requests may recover fields discarded by old cache projections; existing AVM cache keys remain unchanged.
2. Resolve an exact whole-building record. Do not treat an apartment/unit record or Land record as a building. Multiple candidates, missing records, or incomplete unit evidence require agent review. Do not guess unit letters or average building bedrooms into an assumed unit layout.
3. Preserve provider/owner provenance and allow explicit owner overrides. For the authorized portfolio test, workbook unit counts are owner-provided inputs, with exact worksheet cells identified in the private manifest. Do not infer missing layouts. A unit mix needs a count, bedrooms, bathrooms, and optional per-unit area. Keep 2–4 units, 5+ units, and mixed-use distinct.
4. Request one representative rental AVM for each distinct verified residential unit type. Reuse identical types. Sum count × per-unit estimate; sum count × provider low/high only where every component has that bound. Label these as aggregated unit ranges, not a separate provider whole-building AVM. Never multiply a building-scoped metric again or mix it with a unit-scoped metric.
5. For an individual RentCast AVM, retain its own low/high bounds. One provider can support at most medium confidence. Preserve low confidence for mismatch/uncertainty. Do not synthesize missing bounds or blend in ATTOM.
6. Keep actual owner rent roll separate from modeled market rent. Separate commercial and residential income; unsupported commercial income is “needs agent review,” not zero. Do not calculate whole-building NOI/cap rate from partial rent. Retain the expense-placeholder warning.
7. Keep the single-family, townhouse and condo AVM query settings unchanged. Preserve caching and the ordinary per-provider daily cap. Use explicit batch ceilings, sequential execution, incremental output and no retries. Plan discovery separately from AVMs because unit-rent request counts depend on the verified layouts.
8. Validate all requested properties, unit counts/mixes, two known mismatch patterns, ranges, confidence and expense assumptions. Keep client answer keys and output reports outside the repo. Report missing-input coverage and accuracy limits. The updated owner instruction authorizes continuing the fixes and requested preview with missing layouts explicitly flagged for agent review; it does not authorize invented layouts or a claim that the accuracy target passed.

## Current implementation status

Implemented: budget/reset diagnostics, cached-rent preservation after a blocked value call, numeric HTTP audit status, unchanged cache keys, read-only cache planning, owner count/layout/actual-rent inputs and provenance, property unit-count preservation, whole-building matching in evaluation, distinct-layout AVM requests and rent summing, explicit metric scopes, mixed-use review, and single-provider bounds/confidence. The browser supports owner inputs, CSV count import, actual-versus-modeled rent labels, review states, and incomplete-income totals.

Synthetic tests exercise the summing path with complete layouts, studios, duplicate layouts, incomplete provider results and missing bounds. They also cover the two bad-match patterns end-to-end, scope mismatch, owner input validation, actual-rent separation and ATTOM-off routing. The private portfolio run uses owner counts but has no unit layouts, so modeled rents/cap rates correctly remain unavailable. Values are shown only for independently matched residential whole-building subjects; unsupported mixed-use values remain for agent review.

The private runner supports `--cache-only` with an explicit zero RentCast ceiling, so cache misses neither reserve daily calls nor invoke providers. It saves each result and a run receipt. Client-specific evidence, source files, manifests and comparison reports remain outside this repository.

For review, import one of the private owner-count CSV batches (maximum ten rows per upload) or enter counts/layouts directly. Production matching can be stricter than historic output: a missing/ambiguous subject is withheld, not silently replaced by a Land or unit-only estimate. No market-accuracy target is claimed from missing-layout results.

## Provider references

- [RentCast multifamily AVM scope](https://developers.rentcast.io/reference/property-valuation#avms-for-multi-family-properties)
- [Property record fields](https://developers.rentcast.io/reference/property-data-schema)
- [Property record search](https://developers.rentcast.io/reference/property-records)
- [Supported property types and commercial coverage](https://developers.rentcast.io/reference/property-types)
