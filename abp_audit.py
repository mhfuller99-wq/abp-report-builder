"""Read-only final-download validation against original workbook forms.

No formula correction, recalculation, or file rewriting is performed here.
Failure prevents the download. Appended original pages may translate relative
references; original formula logic and first-page formula text must match.
"""
import colorsys, hashlib, io, zipfile, xml.etree.ElementTree as ET
from collections import OrderedDict
from copy import copy
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.cell.cell import MergedCell
from openpyxl.utils.cell import get_column_letter, range_boundaries

def palette(theme):
    if not theme:return None
    scheme=ET.fromstring(theme).find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}clrScheme')
    values=[next(iter(c)).get('lastClr',next(iter(c)).get('val')) for c in scheme]
    return [values[i] for i in (1,0,3,2,4,5,6,7,8,9,10,11)]

def xml_key(value,colors):
    root=copy(value).to_tree()
    for node in root.iter():
        if 'theme' in node.attrib and colors:
            rgb=colors[int(node.attrib.pop('theme'))];tint=float(node.attrib.pop('tint',0))
            r,g,b=(int(rgb[i:i+2],16)/255 for i in (0,2,4));h,l,s=colorsys.rgb_to_hls(r,g,b)
            l=l*(1+tint) if tint<0 else l*(1-tint)+tint
            node.set('rgb','FF'+''.join(f'{round(v*255):02X}' for v in colorsys.hls_to_rgb(h,l,s)))
    def key(node):return node.tag,tuple(sorted(node.attrib.items())),node.text or '',tuple(key(c) for c in node)
    return key(root)

def style_key(cell,colors):
    return tuple(xml_key(getattr(cell,k),colors) for k in ('font','fill','border','alignment','protection'))+(cell.number_format,)

def group_plan(origins):
    groups=OrderedDict();names=list(origins)
    for title,(data,original) in origins.items():groups.setdefault((hashlib.sha256(data).digest(),original),[]).append(title)
    plan=[]
    for (_,original),titles in groups.items():
        name=original;occupied=set(names)-set(titles);suffix=2
        while name in occupied:name=original[:27]+' '+str(suffix);suffix+=1
        names=[name if n==titles[0] else n for n in names if n not in titles[1:]]
        plan.append((name,origins[titles[0]][0],original,len(titles)))
    return plan

def measurement_cells(master,filename):
    if filename in ('NOTES','PROJECT INFO'):return set()
    from abp_reference import reset_measurements
    from abp_design import UNIT_FORMS
    probe=master.parent.copy_worksheet(master)
    sentinel='ABP_MEASUREMENT_PROBE_19'
    for row in probe:
        for cell in row:
            if not isinstance(cell,MergedCell) and cell.data_type!='f' and cell.value is None:cell.value=sentinel
    reset_measurements(probe)
    blanks={c.coordinate for row in probe for c in row if not isinstance(c,MergedCell) and c.value is None and master[c.coordinate].data_type!='f'}
    # Nameplate/design inputs may be intentionally populated from reviewed sources.
    for mapping in UNIT_FORMS.values():
        for address in mapping.values():blanks.discard(address)
    master.parent.remove(probe)
    return blanks

def audit_report(data,origins):
    report=load_workbook(io.BytesIO(data),keep_links=False)
    stats={'formulas':0,'measurement_inputs':0,'forms':0,'styles':0}
    output_colors=palette(report.loaded_theme);output_styles={}
    plan=group_plan(origins)
    def fail(text):raise ValueError('Template integrity check blocked the download: '+text)
    if set(report.sheetnames)!={p[0] for p in plan}:fail('worksheet grouping changed')
    if not any(s.startswith('DUCT TRAVERSE RECT') for s in report.sheetnames) or not any(s.startswith('DUCT TRAVERSE RND') for s in report.sheetnames):fail('required traverse sheets are missing')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        artwork={hashlib.sha256(archive.read(n)).digest() for n in archive.namelist() if '/media/' in n}
    for title,source,original,pages in plan:
        master_book=load_workbook(io.BytesIO(source),keep_links=False);master=master_book[original];ws=report[title]
        height=master.max_row;colors=palette(master_book.loaded_theme);styles={};merges=set()
        if ws.max_row!=height*pages:fail(title+' page extent changed')
        for key,dim in master.column_dimensions.items():
            actual=ws.column_dimensions[key]
            if (actual.width,actual.hidden)!=(dim.width,dim.hidden):fail(title+' column dimensions changed')
        if ws.page_setup!=master.page_setup or ws.page_margins!=master.page_margins:fail(title+' print settings changed')
        blank=measurement_cells(master,original)
        for page in range(pages):
            off=height*page;stats['forms']+=1
            for r,dim in master.row_dimensions.items():
                actual=ws.row_dimensions[r+off]
                if (actual.height,actual.hidden)!=(dim.height,dim.hidden):fail(title+' row dimensions changed')
            for area in master.merged_cells.ranges:
                c1,r1,c2,r2=range_boundaries(str(area));merges.add(f'{get_column_letter(c1)}{r1+off}:{get_column_letter(c2)}{r2+off}')
            for row in master:
                for cell in row:
                    actual=ws.cell(cell.row+off,cell.column)
                    if cell.data_type=='f':
                        stats['formulas']+=1
                        expected=cell.value if not off else Translator(cell.value,origin=cell.coordinate).translate_formula(row_delta=off)
                        if actual.value!=expected:fail(title+'!'+actual.coordinate+' formula changed')
                    elif actual.data_type=='f':fail(title+'!'+actual.coordinate+' gained a formula')
                    if cell.coordinate in blank:
                        stats['measurement_inputs']+=1
                        if actual.value not in (None,'--'):fail(title+'!'+actual.coordinate+' contains a measurement')
                    if cell.style_id not in styles:styles[cell.style_id]=style_key(cell,colors)
                    if actual.style_id not in output_styles:output_styles[actual.style_id]=style_key(actual,output_colors)
                    stats['styles']+=1
                    if styles[cell.style_id]!=output_styles[actual.style_id]:fail(title+'!'+actual.coordinate+' formatting changed')
        if {str(m) for m in ws.merged_cells.ranges}!=merges:fail(title+' merged layout changed')
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            expected={hashlib.sha256(archive.read(n)).digest() for n in archive.namelist() if '/media/' in n}
            if not expected<=artwork:fail(title+' original artwork is missing')
        master_book.close()
    report.close();return stats
