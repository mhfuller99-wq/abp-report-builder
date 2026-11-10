# abp-report-builder

## Reports based on an approved reference

Choose **Use an approved report as the design and layout reference**, upload the
same project's approved `.xlsx`, and click **Review reference report**. Confirm
the equipment list and design basis, then build the report. This path keeps the
reference's report sheets, grouped Design/Actual columns, design data, styling,
equipment diagrams and print settings. It clears prior actual/initial measurements, serial
numbers, technician/date signoffs and old issue notes. Empty worksheets are
omitted and printed pages are marked as pre-field drafts.

The reference is authoritative in this mode. Drawing scans and master-template
selections do not override it. Uploads are processed in memory and not stored on
the server or included in this repository. Reference mode requires reselecting
the workbook when returning to the app; project JSON save/restore belongs to
source-document mode.

Supported reference families: chillers, fan coils, exhaust fans/grilles, pumps,
air-moving equipment and makeup air, DX/gas coils, supply diffusers, rectangular
duct traverses, kitchen hoods, small exhaust fans, notes and standard project
documentation. Repeating equipment pages are cleared independently. Hood and
traverse calculated results remain blank until readings are supplied; hood test
conversion factors and the selected test instrument must be entered for the new
visit. Motor adjustments and field nameplate FLA, filter condition and historical
comments are cleared. Reference equipment ratings, sizes and design columns
remain subject to the user's design-basis review.

The supported cover form is marked pre-field, with certification language,
approval names and signature imagery removed. Old calibration certificates and
instrument serial/calibration entries are removed; select current instruments
before testing. Old cover page references are cleared because certificate pages
have changed. Unknown sheet families are rejected
rather than silently leaving historical field measurements in the output.

Source-document mode reads text schedules from PDF drawings and submittals.
Rows are taken from visual lines, so a grille mark cannot combine with a
distant dimension. VRF indoor units, dedicated outside-air units and exhaust
fans map to the DX fan-coil, air-moving and standard exhaust forms. Design targets and manufacturer selected performance remain separate;
conflicting values are left blank for review; fan speed is not
motor RPM and unit MCA is not motor FLA. Extracted values stay unverified
until the reviewer accepts them. Manufacturer and model are not written into
the pre-field workbook. The workbook is project information, notes, the
applicable equipment forms, then rectangular and round traverse sheets.
EXTRACTION CANDIDATES and other audit tabs are not exported. Client drawings
and submittals are not stored in this repository. Point `ABP_PRIVATE_SOURCES`
at a local folder to opt in to a private scan of those PDFs.

Run `python -m unittest -v test_reports.py` for regression checks.

## Rules derived from the project archive

The local archive review identifies recurring equipment designations and report
layouts. It does not train a language model, make old readings into new design
values, or upload the archive to the hosted app. Client files, file inventories,
report fingerprints and extraction audits remain in the local workspace.

Source mode can now read explicitly labeled design cells from CSV/XLSX schedules
and repeating Design/Actual report panels. Each candidate retains its source
file and cell address. Actual, measured, initial and final columns are excluded;
formula cells without independent reviewed values are not guessed. Different
revision values remain separate candidates. **Use undisputed candidates** fills
only empty review fields with a single agreed candidate and keeps the record
Unverified. Verify the current job's design before building.

Equipment prefixes are recommendations, not proof of equipment type. Select a
unit form in each review row. Supported automatic unit forms are air-moving
equipment, standard/small exhaust fans, water/DX fan coils, kitchen hoods and
air-cooled chillers (design GPM). A verified record with no supported selected
form fails clearly instead of silently disappearing from the report. Pumps,
VAVs and other unsupported unit layouts need an approved reference or manually
prepared worksheets. Supporting coil worksheets are checked from the scan when they apply. Coil
and outside-air design values are still filled only for verified air-moving
units. The initial workbook also carries blank traverse forms so measured
values are not invented.

After a scan, the worksheet checkboxes are set from the documents. Equipment
boxes can still be changed before building. The exported workbook order is
Project Info, Notes, the equipment sheets left checked for this job, then
30 rectangular duct-traverse forms and 15 round duct-traverse forms. Cover,
abbreviations, project summary, the pre-tab checklist, instrument sheets, and
the audit tabs (build info, takeoff review, source evidence, airflow check,
and extraction candidates) are not exported. Extraction candidates are left
out of reference reports as well. Project Info shares the equipment color
scheme, so it stays in the same workbook; a template with a different palette
keeps its own colors as explicit values. When a scan has little or no readable
text, the pack still checks Project Info, Notes, Air Moving Equipment, and
both traverses, plus fan-coil, exhaust, and coil sheets when tags suggest
them. VAV, supply-diffuser, and unit-heater sheets are checked only when that
master template is in the workbook folder.

The source reader remains text based. Graphic/scanned schedules require manual
takeoff; sparse pages with no readable tags are flagged. Image-only drawings
still receive the default pre-field worksheet pack above. The hosted website
cannot browse the computer's OneDrive folders. Upload the current job's files
or use an approved same-job reference. Historical jobs never supply default
equipment quantities, manufacturer/model values, or airflow requirements for
an unrelated new job.

Run `python -m unittest -v test_reports.py test_design.py` for the complete suite.

The 2026 archive review adds AH, ACU, PAC and KSF tag recognition with reviewed
form recommendations. Decimal and letter suffixes remain part of the equipment
ID, so IU-1.01 and IU-1.02 cannot collapse into a single IU-1 record. These aliases
still require an explicit unit form and verified current-job design values.

Saved project reviews are validated before replacing the active review. Changing
source files clears previous equipment entries, and an explicitly cleared unit
form stays unset until the reviewer selects a form. API errors and expired
sessions produce readable messages. Worksheet display names omit filename
extensions; the original master filenames and workbook contents are preserved.

Run `node test_ui_helpers.cjs` for saved-review and API-message checks.

Source-built reports use one tab per master equipment form. Existing multi-unit
Design/Actual slots are filled first (eight small exhaust fans, four fan coils).
Additional master pages continue vertically on the same applicable tab, with
page breaks and repeated artwork. Original master files are never edited.
Repeated formulas use Excel-style relative reference translation only; their
operators, constants, absolute references and calculation logic are retained.
Approved-reference reports retain their existing sheet arrangement.

Source uploads accumulate across file-picker selections and drops. The visible
list supports individual removal and a combined 200 MB limit. Exact duplicates
(name, size, modified time) are not added twice.

The supply diffuser master is a sanitized copy of the user-approved ABP
reference layout. Job values and measurements are removed; its original
31 formulas, including the row-27 totals, are retained unchanged.
The system goes in A5; room, outlet number, type, numeric round-neck size and
design CFM occupy the existing input cells. Initial/Actual inputs remain blank.
Outlets are grouped by reviewed system, 21 per original form; further forms
continue on the same tab and numbering restarts for each system. Copied pages
translate relative references without changing formula logic.
PDF outlet fields can be corrected in the review table before building. Blank
airflow or system fields remain blank rather than borrowing a unit total.
Scanned type-A symbols are candidates, not confirmed supply outlets. They
start unchecked, with no automatic system or room assignment. Confirm the
duct connection and room, then use Include; exhaust symbols stay unchecked.
Nearby room names and sheet unit tags are evidence for review only. The parser
does not automatically trace ducts or extract every grille type.
More than 500 detected outlets fails explicitly instead of silently truncating.

Document requests run one at a time per service process. A simultaneous request
gets a retry message before its body is read; health checks remain available.
Multipart files stream to temporary storage in 64 KiB chunks, are analyzed one
at a time, and are removed after the request, including failures. The combined
200 MB upload limit is unchanged. Reference uploads are limited before reading,
and worksheet dimensions are checked before loading cell objects. Workbook
cycles and the PDF cache are cleared between jobs. Request start/finish logs
identify the endpoint and elapsed time without recording uploaded contents.


## Packaged-unit and alternate drawing notation review

The source scanner recognizes PAHU and MSAH equipment from labeled schedules,
reads fan values by column headings, and supports explicit shared PAHU submittal
tag lists. Outdoor MSHP equipment stays visible for review without automatically
creating another indoor TAB form. EUH candidates use the supplied electric unit-heater form.
Equipment cannot be verified with an empty form selection.

The DX/heat-pump/electric companion form has separate heat-pump and electric-strip
temperature inputs. A per-unit companion-form choice prevents mixed systems
from being copied to both gas and electric forms. Formula cells are never replaced
with schedule capacities or inferred electrical data.

Stacked ceiling-diffuser and keyed duct-grille callouts are unselected review
candidates. Neck sizes come from the same document's legend when available.
Missing legends, room assignments, duct connections, and drawing revisions require
review. Multiple documents' outlets are never silently combined or superseded.
The download status reports unresolved equipment and selected outlet counts.

Synthetic regressions: `python -m unittest test_mechanical` and
`node test_mechanical_ui.cjs`. The opt-in local integration probe is
`python verify_private_wcu.py SOURCE_DIRECTORY OUTPUT_DIRECTORY`. It produces
TEST ONLY evidence with a simulated review of six supported equipment units and
one explicitly selected drawing revision. Keep its output outside this repository;
it does not approve source revisions or make the report field-ready. Original
customer PDFs and completed reports are never uploaded or committed.


### General schedule review

Text PDF schedules use displayed page coordinates, unit marks, and column headers,
including IU/DSS decimal identifiers, stacked marks, and explicit fan lists/ranges.
Vendor-neutral labeled DOAS selection pages require a unique explicit unit mark.
Requested airflow and selected performance remain separate from field readings.
Conflicts stay blank for review; no scan certifies a complete takeoff.
Diffuser legends provide neck sizes or supply-device classifications, never duct
associations. Compare every schedule and plan with the detected list.

Synthetic regressions contain no private drawing data. Passing these tests is not
private-project acceptance. Customer source files and completed masters stay local.


### Supplied unit-heater forms

The original Unit Heater ELE, GAS, and WTR workbooks are included without byte
changes. EUH tags select electric and GUH tags select gas. Generic UH/CUH tags
require an explicit heating type or a reviewer-selected form; they do not default
to water heat. Electric pages have three unit slots; gas/water pages have four.
Additional units continue on intact repeated pages under the same worksheet tab.

Only reviewed inputs are populated. Heater volts, phases, amps, stages, heating
airflow, temperatures, water flow, and pressure drop map to their printed design
cells. Rated kW and BTU remain source evidence when their form cells are formulas.
No amperage, airflow, or temperature is back-calculated from those ratings. Actual
inputs, serial numbers and signoffs remain blank; original formulas and print
settings are retained. Reference imports recognize UNIT ID and clear all electric
phase-leg readings while retaining design values.

Run `python -m unittest test_heaters -v` and `node test_heater_ui.cjs` for heater
regressions. The opt-in WCU probe now checks the electric heater along with the
previous six supported units; it never approves drawing revisions or uploads
customer files.

### Additional schedule formats and coverage limits

ID headers, stacked airflow columns and multi-part blower-coil identifiers are
supported. Conflicting drawing revisions remain separate candidates for review.
Explicit repeated outlet quantities remain unselected until each physical
location and supply connection is checked. Symbol-key examples are excluded.

Companion coil selection follows unit-specific electric, gas or hydronic evidence.
Unconfirmed coil types stay unselected. Hydronic companion sheets retain the
original preheat, cooling and reheat formulas and leave actual inputs blank.
Raster schedules and plans with little readable text produce coverage warnings:
a visible drawing can contain outlined labels that text extraction cannot read.
Compare these sheets manually; completed report readings are not design inputs.

PDF layout text is bounded by extracted words and the MuPDF resource cache is
released between text passes. This reduces retained resources but does not
establish the cause of a past server restart.



## Bounded image reading and hood review

The source scan now runs image reading in a separate process with a 65-second
shared scan budget, 256 MiB address-space limit, CPU limit and one concurrent
OCR job. Each PDF permits up to 12 raster pages, 8 million pixels per full-page
render, 6 million per discovery preview, 3 million per table crop, and 16 million
cumulative pixels per page. The PDF-wide cap remains 40 million pixels. Up to
24 OCR regions (6 per page) can be attempted; coverage retains up to 240 region
entries with explicit omission counts. OCR PDFs larger than 40 MB are skipped with a warning;
normal source handling remains separate. Temporary image/job files are deleted.
The Docker image installs Tesseract and English data. Missing OCR or an exhausted
budget leaves a visible manual-review warning rather than claiming completeness.

An explicit hood schedule with single-line EXHAUST CFM / MAKEUP CFM columns
produces separate, unverified values. Supported KH tags can be added only after
checking the source-confirmation box; they still need equipment verification.
Makeup air stays evidence only and never becomes outside air. Other detected
hood tag formats are labeled manual-only without silently renaming equipment.
OCR diffuser candidates use the existing conservative symbol readers; their
system and room stay blank and inclusion is unchecked. Low-confidence OCR flow
values stay blank. Image/hood candidates are saved with project reviews.

The queue is not a complete equipment or outlet takeoff. Dense, rotated,
multiline or unusual tables and poor scans can be missed. Existing native PDF
processing is unchanged and is not covered by the OCR worker's resource limits.
Actual readings and template formulas are not populated by image recognition.
Run `python -m unittest test_ocr_hood -v` and `node test_image_review.cjs` for
focused checks, then run the existing full Python and JavaScript regressions.


Project reviews save as compact JSON. Save and restore enforce the same 2 MB
UTF-8 limit on the complete project, including ordinary equipment and image
candidates. Oversized reviews are rejected before download without changing the
current review; split the source set rather than discarding evidence silently.

The production OCR worker processes page words one page at a time instead of
retaining all native/OCR word arrays until the document ends. Its address-space
limit applies to each process, not combined service memory. A Tesseract child and
the web server consume additional memory. Hosted aggregate-memory/load validation
is still required. OCR runs while the existing document-operation lock is held
for up to the remaining 65-second scan budget; competing document requests can
receive the existing busy response, while health requests remain responsive.

## Targeted image reading and page coverage

Image recognition remains a separate, unverified review queue. On native-rich
pages, small marginal images can be skipped as likely branding; this is a
heuristic, not a guarantee that the image is irrelevant. Check those images
manually if necessary. Larger raster regions remain eligible for examination.

The image reader can locate ruled raster tables and examine bounded crops rather
than shrinking an entire large sheet. Supported multirow `HOOD INFORMATION`
tables retain the exact `HD-…` identity and keep total exhaust CFM distinct from
total supply CFM. Low-confidence fields remain blank with source evidence for
review. Adding a checked hood candidate to the ordinary review can transfer only
its reviewed exhaust candidate into design CFM. Supply and makeup air never
populate exhaust or outside-air fields. The new record remains unverified.

The image coverage panel reports pages, selected regions, skips, failures, and
unsupported content. It is saved with the project review and cleared when source
files change. Region coordinates are displayed PDF points. Page numbers refer
to the uploaded file; if that file is a subset, retain its original-page mapping
in the source name or review notes. Native text processing is separate. A page
with a recognized table is not a complete takeoff, and areas outside selected
regions still require review. If the coverage display reaches its 1,000-page
limit, the scan warns that remaining pages require manual review.

Resource budgets and the existing supervised worker remain mandatory. Temporary
raster buffers and MuPDF cache entries are released between render operations;
local measurements do not replace full-container memory validation. Private
client drawing sets are not bundled with this repository, and
customer PDFs must not be added to tests or published artifacts.
