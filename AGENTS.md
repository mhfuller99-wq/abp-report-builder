# ABP validation and release rules

Preserve original template files, formulas, blank field measurements, grouped
equipment tabs, and both required traverse sheets. Never modify project archive
files or commit client documents, office reports, private expected answers or
private benchmark outputs.

For extraction, source-review, or workbook behavior changes:

1. Establish the current main/live revision and create an isolated checkout.
2. Freeze the private benchmark source hashes and independently reviewed answers
   before evaluating the candidate. Office measurements are not source truth.
3. Run every regression project and the reserved holdouts against the same final
   revision. A project used to tune a fix becomes a regression case; reserve a new
   holdout before claiming generalization. Never tune a holdout then call it unseen.
4. Run the full production-container regression suite under its 512 MiB limit.
5. Run `python abp_benchmark.py --suite PRIVATE_SUITE --reports PRIVATE_INDEX
   --commit CANDIDATE_SHA --output PRIVATE_RESULT`. A nonzero exit blocks a claim
   of release readiness. Missing, stale, or manually corrected raw evidence must
   not be presented as a passing extraction test. Record unresolved cases; do not
   edit expected answers to agree with the scanner.
6. A candidate extraction pass is not a complete report pass. Verify the reviewed
   workbook against original formulas, layout, blank actuals, grouping and traverses.
   Record manual review separately from automatic extraction coverage.

The private corpus currently lives on the user's computer, outside this repo.
The public GitHub workflow runs synthetic checks only; it does not automatically
enforce the private release gate. Do not describe that CI badge as real-project
acceptance. Changes limited to benchmark tooling may be merged after the benchmark
tool tests pass; they do not establish readiness of the extraction application.
