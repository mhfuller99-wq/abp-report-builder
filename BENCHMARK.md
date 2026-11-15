# Private real-project acceptance

`abp_benchmark.py` compares unchanged website review exports with independently
reviewed source answers. It never imports the extraction engine or infers expected
answers from the office workbook. Keep every client file and fixture outside this
repository, or in the ignored `benchmark-private/` directory.

```powershell
python abp_benchmark.py --suite PRIVATE_SUITE --reports PRIVATE_INDEX --commit CANDIDATE_SHA --output PRIVATE_RESULT
```

The command exits 1 unless every project passes. Its output separates candidate
accuracy, missing manual information, source-answer completeness, and workbook
acceptance. A matching airflow total alone is insufficient: each outlet is matched
by source, page and displayed PDF coordinates before checking its fields. Missing,
extra, duplicate, wrongly assigned and conflicting values remain visible failures.
Unknown image schemas fail closed. Image candidates remain unverified.

The suite JSON has `version: 1` and `projects`. Each project provides an `id`,
`split` (`regression` or `holdout`), `truth_status`, `sources`, `truth_artifacts`,
optional `references`, and `expected`. Artifact entries contain `path` and
`sha256`; sources also contain their upload `name`. Expected answers include
`outlets`, `equipment`, `excluded_equipment`, `outlet_inventory_complete` and
`equipment_inventory_complete`. An outlet has a unique `id`, `source`, `page`,
`position`, required `values`, optional `review_fields` and `must_withhold` fields.
Blank review fields are recorded as manual work; wrong populated fields fail.
Equipment values are checked against their exact source/page and equipment tag.
Unresolved source questions stay in `unresolved_source_questions`.

The report index has `version: 1` and `reports`. Each entry includes `project_id`,
`path`, `sha256`, `commit`, `suite_sha256`, and `mode: live_raw`. Save the raw export
before clicking acceptance controls or entering any corrections. Old commits,
changed sources/answers/reports, missing projects and absent holdouts cannot pass.
Version frozen suites instead of overwriting them; record the reason for a change.

A separate `workbook_audit` entry must identify its audit JSON (`path`, `sha256`),
`commit` and `review_sha256`. The audit JSON repeats the commit and review hash,
binds the actual `workbook` and `original_templates` by path/hash, and records true
for `original_formulas_preserved`, `blank_actuals`, `original_layout_preserved`,
`grouped_equipment`, and `required_traverses`. These assertions must come from an
actual workbook comparison. This evaluator validates that evidence and its file
bindings; it does not perform the spreadsheet comparison itself.

Public CI runs synthetic tests, including tests of this evaluator, inside the
production container's 512 MiB limit. It cannot run the private archive corpus.
The private gate is a local release check, not a GitHub branch-protection rule.
A failed gate blocks a claim that the application is generally ready; a narrowly
scoped correction must still state its verified scope and unresolved limitations.
Reserve new validation projects after using a held-out project to develop a fix.

Reviewed workflow acceptance is a separate, explicit mode. Set a report entry's
`acceptance_mode` to `reviewed_workflow` and provide `reviewed_review` with its
path, hash, commit, `raw_review_sha256` and `mode: website_reviewed`. Keep the raw
export unchanged. Its errors and automatic readiness remain visible even when
the independently checked reviewed inventory and workbook pass. The reviewed
inventory is compared against complete frozen source answers, including physical
quantity, per-unit locations, deliberate blanks, page accounting and approval
bound to the exact inventory. This evaluator does not call the application gate.

For this mode the workbook audit binds the reviewed export's hash and also records
`raw_review_sha256` and the actual `website_job_id`. It must affirm
`exact_design_values`, `all_caps`, `diffuser_totals_adjacent`,
`no_unnecessary_comments` and `no_unexplained_omissions` in addition to the original
template checks above. These are evidence requirements, not automatic assertions.
Set suite-level `required_holdouts: 2` when two qualified held-out projects are
required. Neither reviewed acceptance nor a passing suite upgrades automatic scan
coverage or certifies field measurements.

Repeated annotations such as `TYP-20` remain a single unresolved source witness.
They may not be included as one outlet or silently expanded into identical rows.
The browser's repeated-callout review retains the original count observations,
requires an explicit reviewed count and distinct physical locators, and starts
every resulting physical row unchecked. The original annotation remains excluded
in the review log. Save/restore and retries retain those identities; missing or
duplicated physical rows block both partial and fully reviewed builds. For these
cases, private expected outlets can identify each physical row with an
`instance_locator` in addition to its common source/page/annotation position.

Exhaust grille rows are a separate `exhaust_outlets` inventory, with the same
independent physical source anchors and field expectations. They cannot satisfy
supply outlet matches. Reviewed rows also require their source SHA, a distinct
physical locator, evidence, and one verified exhaust fan. The genuine original
`Exhaust Grills.xlsx` form has 29 inlet rows per page and no total formula; the
writer preserves that design. The older similarly named pack file contains a fan
form and cannot substitute for it. A suite can bind `required_exhaust_template`
by name and SHA in addition to checking the downloaded workbook. Manual exhaust
entries remain manual work and cannot turn a failed raw scan into a raw pass.
