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

Source-document mode remains a reviewed text-extraction workflow, not a complete
automatic drawing takeoff. BC, BCU, CH and pump tags are now recognized, and BCU/BC
tags offer water/DX coil templates for review. KH, KEF and TEF tags also recommend
appropriate hood or exhaust forms. Different tag names across plans and
submittals are not automatically treated as the same equipment. Schedule tables
stored as drawing graphics still require review.

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
prepared worksheets. Supporting coil, diffuser and traverse forms can be
included separately; they are not automatically allocated to every unit.

The source reader remains text based. Graphic/scanned schedules require manual
takeoff; sparse pages with no readable tags are flagged. The hosted website
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
