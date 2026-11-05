"""Stack intact master pages under their equipment-type tab.

Operate after template restoration so Excel shapes and legacy logos survive.
Only copied-page coordinates move; master files and calculation logic do not.
"""
import io, zipfile, hashlib, posixpath, re
import xml.etree.ElementTree as ET
from copy import deepcopy
from openpyxl.formula.translate import Translator
from openpyxl.utils.cell import range_boundaries, get_column_letter
from abp_fidelity import NS, REL, DOCREL, sheet_paths, relpath, resolve

def q(name):return '{'+NS+'}'+name

def move_range(value, offset):
    def one(match):return match[1]+str(int(match[2])+offset)
    return re.sub(r'(\$?[A-Z]+\$?)(\d+)',one,value)

def group_template_sheets(data, origins):
    with zipfile.ZipFile(io.BytesIO(data)) as z:files={n:z.read(n) for n in z.namelist()}
    paths=sheet_paths(files);workbook=ET.fromstring(files['xl/workbook.xml'])
    sheets=workbook.find(q('sheets'));old_order=[s.attrib['name'] for s in sheets]
    groups={}
    for title,(source,original) in origins.items():
        groups.setdefault((hashlib.sha256(source).digest(),original),[]).append(title)
    renamed={};removed=set();extents={};keepers=set()
    for (_,original),titles in groups.items():
        first=titles[0];destpath=paths[first];dest=ET.fromstring(files[destpath])
        target=original
        occupied={s.attrib['name'] for s in sheets if s.attrib['name'] not in titles}
        suffix=2
        while target in occupied:
            target=original[:27]+' '+str(suffix);suffix+=1
        for s in sheets:
            if s.attrib['name']==first:
                s.set('name',target);keepers.add(s)
        renamed[first]=target
        if len(titles)==1:continue
        sd=dest.find(q('sheetData'))
        dimension=dest.find(q('dimension'))
        _,_,maxcol,height=range_boundaries(dimension.attrib['ref'])
        # All pages in a group originate from exactly the same master worksheet.
        # Retain any intentionally blank rows within its used range.
        height=max(height,max(int(r.attrib['r']) for r in sd))
        dlinks_path=relpath(destpath)
        dlinks=ET.fromstring(files[dlinks_path]) if dlinks_path in files else ET.Element('{'+REL+'}Relationships')
        def import_links(source_part,target_part,source_root,target_root):
            srp=relpath(source_part);trp=relpath(target_part)
            target_links=ET.fromstring(files[trp]) if trp in files else ET.Element('{'+REL+'}Relationships')
            mapping={}
            if srp in files:
                for link in ET.fromstring(files[srp]):
                    attrs=dict(link.attrib);newid='group'+str(len(target_links)+1)
                    mapping[attrs['Id']]=newid;attrs['Id']=newid
                    if attrs.get('TargetMode')!='External':attrs['Target']=posixpath.relpath(resolve(source_part,attrs['Target']),posixpath.dirname(target_part))
                    ET.SubElement(target_links,'{'+REL+'}Relationship',attrs)
            for el in source_root.iter():
                for key,value in list(el.attrib.items()):
                    if key.startswith('{'+DOCREL+'}') and value in mapping:el.set(key,mapping[value])
            files[trp]=ET.tostring(target_links,encoding='utf-8',xml_declaration=True)
        def merge_artwork(src,srcpath,offset):
            source_links={r.attrib['Id']:r for r in ET.fromstring(files[relpath(srcpath)])} if relpath(srcpath) in files else {}
            dest_links={r.attrib['Id']:r for r in ET.fromstring(files[dlinks_path])} if dlinks_path in files else {}
            for name in ('drawing','legacyDrawing'):
                sref=src.find(q(name));dref=dest.find(q(name))
                if sref is None:continue
                if dref is None:raise ValueError('Grouped pages have inconsistent artwork')
                sp=resolve(srcpath,source_links[sref.attrib['{'+DOCREL+'}id']].attrib['Target'])
                dp=resolve(destpath,dest_links[dref.attrib['{'+DOCREL+'}id']].attrib['Target'])
                sroot=ET.fromstring(files[sp]);droot=ET.fromstring(files[dp])
                import_links(sp,dp,sroot,droot)
                if name=='drawing':
                    ids=[int(e.attrib['id']) for e in droot.iter() if e.tag.endswith('}cNvPr')]
                    nextid=max(ids,default=0)+1
                    for anchor in sroot:
                        for e in anchor.iter():
                            if e.tag.endswith('}row'):e.text=str(int(e.text)+offset)
                            if e.tag.endswith('}cNvPr'):e.set('id',str(nextid));nextid+=1
                        droot.append(anchor)
                else:
                    # VML images use both cell anchors and point offsets.
                    default=float(dest.find(q('sheetFormatPr')).attrib.get('defaultRowHeight',15))
                    heights={int(r.attrib['r']):float(r.attrib.get('ht',default)) for r in sd}
                    points=sum(heights.get(row,default) for row in range(1,offset+1))
                    existing={e.attrib.get('id') for e in droot.iter()};counter=1025
                    for shape in sroot:
                        if not shape.tag.endswith('}shape'):continue
                        while '_x0000_s'+str(counter) in existing:counter+=1
                        newid='_x0000_s'+str(counter);existing.add(newid)
                        shape.set('id',newid)
                        for key in list(shape.attrib):
                            if key.endswith('}spid'):shape.set(key,newid)
                        style=shape.attrib.get('style','')
                        if 'margin-top:' in style:
                            style=re.sub(r'margin-top:([\d.]+)pt',lambda m:'margin-top:'+str(float(m[1])+points)+'pt',style)
                            shape.set('style',style)
                        for e in shape.iter():
                            if e.tag.endswith('}Anchor') and e.text:
                                coords=[int(v.strip()) for v in e.text.split(',')]
                                coords[2]+=offset;coords[6]+=offset;e.text=', '.join(map(str,coords))
                            elif e.tag.endswith('}Row') and e.text:e.text=str(int(e.text)+offset)
                        droot.append(shape)
                files[dp]=ET.tostring(droot,encoding='utf-8',xml_declaration=True)
        for page,title in enumerate(titles[1:],1):
            offset=page*height;srcpath=paths[title];src=ET.fromstring(files[srcpath])
            if offset+height>1048576:raise ValueError('Equipment group exceeds Excel row limit')
            for row in src.find(q('sheetData')):
                row=deepcopy(row);row.set('r',str(int(row.attrib['r'])+offset))
                for cell in row:
                    old=cell.attrib['r'];cell.set('r',move_range(old,offset))
                    formula=cell.find(q('f'))
                    if formula is not None:
                        if formula.text:formula.text=Translator('='+formula.text,origin=old).translate_formula(row_delta=offset)[1:]
                        if 'ref' in formula.attrib:formula.set('ref',move_range(formula.attrib['ref'],offset))
                        if 'si' in formula.attrib:formula.set('si',str(int(formula.attrib['si'])+page*100000))
                    cached=cell.find(q('v'))
                    if formula is not None and cached is not None:cell.remove(cached)
                sd.append(row)
            for name,childname,attrs in [('mergeCells','mergeCell',['ref']),('dataValidations','dataValidation',['sqref']),('hyperlinks','hyperlink',['ref'])]:
                source=src.find(q(name))
                if source is None:continue
                container=dest.find(q(name))
                if container is None:
                    container=ET.SubElement(dest,q(name))
                for child in source:
                    child=deepcopy(child)
                    if name=='hyperlinks' and '{'+DOCREL+'}id' in child.attrib:
                        raise ValueError('Grouped template contains external hyperlinks; explicit support required')
                    for attr in attrs:
                        if attr in child.attrib:child.set(attr,move_range(child.attrib[attr],offset))
                    container.append(child)
                if name!='hyperlinks':container.set('count',str(len(container)))
            for cf in src.findall(q('conditionalFormatting')):
                cf=deepcopy(cf);cf.set('sqref',move_range(cf.attrib['sqref'],offset))
                for f in cf.iter(q('formula')):
                    if f.text:f.text=Translator('='+f.text,origin='A1').translate_formula(row_delta=offset)[1:]
                dest.append(cf)
            breaks=dest.find(q('rowBreaks'))
            if breaks is None:breaks=ET.SubElement(dest,q('rowBreaks'))
            ET.SubElement(breaks,q('brk'),id=str(offset),min='0',max='16383',man='1')
            source_breaks=src.find(q('rowBreaks'))
            if source_breaks is not None:
                for brk in source_breaks:
                    brk=deepcopy(brk);brk.set('id',str(int(brk.attrib['id'])+offset));breaks.append(brk)
            breaks.set('count',str(len(breaks)));breaks.set('manualBreakCount',str(len(breaks)))
            merge_artwork(src,srcpath,offset)
            removed.add(title)
        dimension.set('ref','A1:'+get_column_letter(maxcol)+str(height*len(titles)))
        extents[first]=(maxcol,height*len(titles))
        setup=dest.find(q('pageSetup'))
        if setup is not None and setup.attrib.get('fitToHeight')=='1':setup.set('fitToHeight','0')
        # Keep worksheet children in the ECMA worksheet sequence.
        order='sheetPr dimension sheetViews sheetFormatPr cols sheetData sheetCalcPr sheetProtection protectedRanges scenarios autoFilter sortState dataConsolidate customSheetViews mergeCells phoneticPr conditionalFormatting dataValidations hyperlinks printOptions pageMargins pageSetup headerFooter rowBreaks colBreaks customProperties cellWatches ignoredErrors smartTags drawing legacyDrawing legacyDrawingHF picture oleObjects controls webPublishItems tableParts extLst'.split()
        dest[:]=sorted(dest,key=lambda e:order.index(e.tag.split('}')[-1]) if e.tag.split('}')[-1] in order else len(order))
        files[destpath]=ET.tostring(dest,encoding='utf-8',xml_declaration=True)
    for s in list(sheets):
        # A renamed keeper can share a title with a page that is about to be stacked.
        if s.attrib['name'] in removed and s not in keepers:sheets.remove(s)
    new_order=[s.attrib['name'] for s in sheets]
    names=workbook.find(q('definedNames'))
    if names is None:names=ET.SubElement(workbook,q('definedNames'))
    for name in list(names):
        old_index=name.attrib.get('localSheetId')
        if old_index is not None:
            old_title=old_order[int(old_index)]
            if old_title in removed or old_title in extents and name.attrib['name']=='_xlnm.Print_Area':names.remove(name);continue
            name.set('localSheetId',str(new_order.index(renamed.get(old_title,old_title))))
        if name.text:
            for old,new in renamed.items():name.text=name.text.replace("'"+old.replace("'","''")+"'!","'"+new.replace("'","''")+"'!")
    for title,(col,row) in extents.items():
        target=renamed.get(title,title)
        name=ET.SubElement(names,q('definedName'),name='_xlnm.Print_Area',localSheetId=str(new_order.index(target)))
        name.text="'"+target.replace("'","''")+"'!$A$1:$"+get_column_letter(col)+'$'+str(row)
    files['xl/workbook.xml']=ET.tostring(workbook,encoding='utf-8',xml_declaration=True)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in files.items():z.writestr(name,value)
    return out.getvalue()
