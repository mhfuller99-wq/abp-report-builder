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
tags recommend the water-coil template. KH, KEF and TEF tags also recommend
appropriate hood or exhaust forms. Different tag names across plans and
submittals are not automatically treated as the same equipment. Schedule tables
stored as drawing graphics still require review.

Run `python -m unittest -v test_reports.py` for regression checks.
