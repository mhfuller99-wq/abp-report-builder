# abp-report-builder

## Reports based on an approved reference

Choose **Use an approved report as the design and layout reference**, upload the
same project's approved `.xlsx`, and click **Review reference report**. Confirm
the equipment list and design basis, then build the report. This path keeps the
reference's report sheets, grouped Design/Actual columns, design data, styling,
images and print settings. It clears prior actual/initial measurements, serial
numbers, technician/date signoffs and old issue notes. Empty worksheets are
omitted and printed pages are marked as pre-field drafts.

The reference is authoritative in this mode. Drawing scans and master-template
selections do not override it. Uploads are processed in memory and not stored on
the server or included in this repository. Reference mode requires reselecting
the workbook when returning to the app; project JSON save/restore belongs to
source-document mode.

Supported reference families: chillers, fan coils, exhaust fans/grilles, pumps,
notes and standard project documentation. Unknown sheet families are rejected
rather than silently leaving historical field measurements in the output.

Source-document mode remains a reviewed text-extraction workflow, not a complete
automatic drawing takeoff. BC, BCU, CH and pump tags are now recognized, and BCU/BC
tags recommend the water-coil template. Different tag names across plans and
submittals are not automatically treated as the same equipment. Schedule tables
stored as drawing graphics still require review.

Run `python -m unittest -v test_reports.py` for regression checks.
