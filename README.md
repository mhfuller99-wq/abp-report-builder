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
fans map to the DX fan-coil, air-moving and standard exhaust forms. Submittal
unit totals and motor nameplate values outrank the plan; fan speed is not
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

The supply diffuser master is the original ABP 2022 form, identical to the
Company Knowledge / Report Templates copy (SHA-256
`4d110f77202e9d184ed7c2e1de44adc91de717542aaa2d82489fce701536d7ff`).
Only Area Served, Outlet No., Type, Size and Design CFM inputs are populated.
Initial/Actual inputs remain blank and percentage formulas are preserved.
Outlets are grouped by reviewed system, 28 per original form; further forms
continue on the same tab. No source text replaces calculation columns.
PDF outlet fields can be corrected in the review table before building. Blank
airflow or system fields remain blank rather than borrowing a unit total.
More than 500 detected outlets fails explicitly instead of silently truncating.
