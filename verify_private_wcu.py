"""Opt-in local integration probe; never uploads or copies customer sources.

Usage: python verify_private_wcu.py SOURCE_DIRECTORY OUTPUT_DIRECTORY
Outputs are local TEST ONLY evidence and must not be committed.
"""
import io
import json
import hashlib
import sys
from collections import Counter
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
import abp_server as app
from abp_design import UNIT_FORMS


def main(source, output):
    source=Path(source);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    names=['*STAMPED DRAWINGS*.pdf','*Addendum*.pdf','Submittal/*Exhaust Fans.pdf',
           'Submittal/*Grilles Registers*.pdf','Submittal/*Unit Heater.pdf',
           'Submittal/SUB-DSS*.pdf','Submittal/SUB-RTUs*.pdf']
    paths=[p for pattern in names for p in source.glob(pattern)]
    if len(paths)!=7:raise ValueError('Expected the seven WCU test source PDFs')
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    handles=[(p.name,p.open('rb')) for p in paths]
    try:scan=app.read_sources(handles)
    finally:
        for _,handle in handles:handle.close()
    (output/'scan.json').write_text(json.dumps(scan,indent=2),encoding='utf-8')
    records=[]
    for original in scan['records']:
        r={**original,**original['proposed'],**original.get('text_proposed',{})}
        # Test-only simulated review of mapped design proposals. Unmapped EUH
        # and outdoor MSHP stay unresolved, not silently verified/excluded.
        r['status']='VERIFIED' if r.get('template') else 'UNVERIFIED'
        records.append(r)
    supported={r['tag'] for r in records if r['status']=='VERIFIED'}
    assert supported=={'PAHU-1','PAHU-2','PAHU-3','MSAH-1','EF-1','EF-2'},supported
    templates=[x['name'] for x in app.suggested_templates(scan['tags'],scan['signals'])['recommended']]
    assigned={r.get('template') for r in records if r.get('template')}
    templates=[t for t in templates if t not in UNIT_FORMS or t in assigned]
    templates=list(dict.fromkeys(templates+list(assigned)))
    # Exercise export on ONE explicitly named source revision only. No duct
    # network, room, or current-revision approval is inferred by this probe.
    original_name=next(p.name for p in paths if 'STAMPED DRAWINGS' in p.name)
    outlets=[{**d,'include':d['source']==original_name} for d in scan['diffusers']]
    payload={'project':'WCU TEST ONLY - original drawing export, revision review pending',
             'location':'Hattiesburg, MS','records':records,'templates':templates,'diffusers':outlets}
    (output/'test-review.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    data=app.build(payload);(output/'WCU_TEST_ONLY.xlsx').write_bytes(data)
    wb=load_workbook(io.BytesIO(data));known={r['tag'] for r in records}
    populated={c.value for ws in wb for row in ws for c in row if isinstance(c.value,str) and c.value in known}
    assert populated==supported,populated
    assert wb['EXHAUST FANS SMALL']['C10'].value==50
    assert wb['EXHAUST FANS SMALL']['E10'].value==200
    assert wb['FAN COIL UNITS DX']['C11'].value==450
    assert wb['COIL DX HP ELE']['D22'].value==99.79
    assert wb['COIL DX HP ELE']['D27'].value==88.7
    assert 'EXHAUST FAN' not in wb.sheetnames
    assert 'FAN COIL UNITS DX ELE' not in wb.sheetnames
    included=[d for d in outlets if d['include']]
    sheet=wb['SUPPLY DIFFUSERS'];exported=[]
    for off in range(0,sheet.max_row,42):
        for row in range(6+off,27+off):
            if sheet.cell(row,3).value is not None:exported.append(sheet.cell(row,7).value)
            assert sheet.cell(row,6).value is None
            assert sheet.cell(row,8).value is None
    assert sorted(exported)==sorted(d['design_cfm'] for d in included)
    # Independently compare all formula cells with the original master and
    # expected copied-page translation; reject added/missing calculations.
    checked=0;actual_blanks=0
    for template in templates:
        master=load_workbook(app.LOOKUP[template])
        for src in master:
            if src.title not in wb.sheetnames:continue
            dst=wb[src.title];expected={}
            for off in range(0,dst.max_row,src.max_row):
                for row in src:
                    for cell in row:
                        if cell.data_type=='f':
                            target=dst.cell(cell.row+off,cell.column)
                            expected[target.coordinate]=Translator(cell.value,origin=cell.coordinate).translate_formula(row_delta=off)
                for row in src:
                    for cell in row:
                        if str(cell.value or '').upper()=='ACTUAL':
                            # Only input cells; original formulas are tested separately.
                            for r in range(cell.row+1,min(src.max_row,cell.row+27)+1):
                                target=dst.cell(r+off,cell.column)
                                if src.cell(r,cell.column).value is None and target.data_type!='f':
                                    assert target.value is None,(dst.title,target.coordinate)
                                    actual_blanks+=1
            actual={c.coordinate:c.value for row in dst for c in row if c.data_type=='f'}
            assert actual==expected,dst.title
            checked+=len(expected)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    result={'mode':'LOCAL TEST ONLY; simulated review, not a production or field-ready report',
            'source_files':len(paths),'source_hashes':hashes,'source_files_unchanged':True,
            'detected_tags':scan['tags'],'populated_tags':sorted(populated),
            'unresolved_tags':[r['tag'] for r in records if r['status']!='VERIFIED'],
            'outlet_candidates_by_source':dict(Counter(d['source'] for d in outlets)),
            'exported_outlets_from_original_drawing_only':len(exported),
            'outlet_systems_and_rooms':'Unassigned; require duct tracing and revision review',
            'formula_cells_checked':checked,'actual_input_blanks_checked':actual_blanks,
            'sheets':wb.sheetnames,'warnings':scan['warnings']}
    (output/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_hashes','warnings')},indent=2))


if __name__=='__main__':main(*sys.argv[1:])
