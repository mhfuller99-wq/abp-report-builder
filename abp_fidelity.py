"""Preserve template worksheet artwork that openpyxl cannot round-trip."""
import io,zipfile,posixpath
import xml.etree.ElementTree as ET
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
DOCREL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'

def sheet_paths(files):
    rels=ET.fromstring(files['xl/_rels/workbook.xml.rels'])
    links={r.attrib['Id']:resolve('xl/workbook.xml',r.attrib['Target']) for r in rels}
    return {s.attrib['name']:links[s.attrib['{'+DOCREL+'}id']] for s in ET.fromstring(files['xl/workbook.xml']).find('{'+NS+'}sheets')}

def resolve(parent,target):
    return target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(parent),target))

def relpath(part):
    return posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')

def preserve_template_parts(data, origins):
    """Restore original drawing/VML/chart/media relationships without rendering.

    origins: destination sheet -> (original XLSX bytes, original sheet name).
    Worksheet formulas are separately compared byte-for-byte at XML text level.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as z:files={n:z.read(n) for n in z.namelist()}
    destinations=sheet_paths(files);ct=ET.fromstring(files['[Content_Types].xml'])
    workbook=ET.fromstring(files['xl/workbook.xml'])
    for index,(title,(source,original_title)) in enumerate(origins.items()):
        with zipfile.ZipFile(io.BytesIO(source)) as z:src={n:z.read(n) for n in z.namelist()}
        srcpath=sheet_paths(src)[original_title];dstpath=destinations[title]
        original=ET.fromstring(src[srcpath]);dest=ET.fromstring(files[dstpath])
        if original_title=='NOTES':
            # Bound Notes to the original cells. The declared dimension and
            # row metadata include an unused row above its first actual cell.
            # Keep that blank row outside the printed form to avoid spillover.
            names=workbook.find('{'+NS+'}definedNames')
            if names is None:
                names=ET.Element('{'+NS+'}definedNames')
                calc=workbook.find('{'+NS+'}calcPr')
                workbook.insert(list(workbook).index(calc) if calc is not None else len(workbook),names)
            index=str(list(destinations).index(title))
            if not any(n.get('name')=='_xlnm.Print_Area' and n.get('localSheetId')==index for n in names):
                from openpyxl.utils.cell import absolute_coordinate,range_boundaries,get_column_letter
                name=ET.SubElement(names,'{'+NS+'}definedName',name='_xlnm.Print_Area',localSheetId=index)
                c1,_,c2,r2=range_boundaries(original.find('{'+NS+'}dimension').get('ref'))
                r1=min(range_boundaries(cell.get('r'))[1] for cell in original.iter('{'+NS+'}c'))
                area=get_column_letter(c1)+str(r1)+':'+get_column_letter(c2)+str(r2)
                name.text="'"+title.replace("'","''")+"'!"+absolute_coordinate(area)
        formulas=lambda root:{c.attrib['r']:ET.tostring(c.find('{'+NS+'}f'),encoding='unicode') for c in root.iter('{'+NS+'}c') if c.find('{'+NS+'}f') is not None}
        # openpyxl expands shared formulas and omits Excel calculation flags.
        # Restore the original formula XML after the semantic guard at build time.
        def fmap(root):
            return {c.attrib['r']:(c.find('{'+NS+'}f').text,dict(c.find('{'+NS+'}f').attrib)) for c in root.iter('{'+NS+'}c') if c.find('{'+NS+'}f') is not None}
        from copy import deepcopy
        src_cells={c.attrib['r']:c for c in original.iter('{'+NS+'}c')}
        dst_cells={c.attrib['r']:c for c in dest.iter('{'+NS+'}c')}
        for address,cell in src_cells.items():
            formula=cell.find('{'+NS+'}f')
            if formula is None:continue
            if address not in dst_cells:raise ValueError('Template formula cell missing: '+title+'!'+address)
            target=dst_cells[address]
            for child in list(target):
                if child.tag in ('{'+NS+'}f','{'+NS+'}v'):target.remove(child)
            target.insert(0,deepcopy(formula))
            target.attrib.pop('t',None)
        if fmap(original)!=fmap(dest):raise ValueError('Template formula preservation failed: '+title)
        # openpyxl turns every stored row height into customHeight=1 and drops
        # descent metadata. Those flags affect print pagination even when the
        # numeric heights compare equal. Restore the exact original row flags,
        # retaining remapped styles and the requested diffuser-row hiding.
        original_rows={row.get('r'):row for row in original.find('{'+NS+'}sheetData')}
        for row in dest.find('{'+NS+'}sheetData'):
            source_row=original_rows.get(row.get('r'))
            if source_row is None:continue
            style=row.get('s');hidden=row.get('hidden')
            compact=(original_title=='SUPPLY DIFFUSERS' and 6<=int(row.get('r'))<=26 and hidden=='1')
            row.attrib.clear();row.attrib.update(source_row.attrib)
            row.attrib.pop('s',None)
            if style is not None:row.set('s',style)
            if compact:row.set('hidden','1')
        # Preserve view/print/protection flags even when the library omits
        # disabled settings during serialization. These have no style indices.
        metadata={'sheetViews','sheetFormatPr','sheetProtection','printOptions','pageMargins',
                  'headerFooter','rowBreaks','colBreaks','dataValidations'}
        for name in metadata:
            old=dest.find('{'+NS+'}'+name);new=original.find('{'+NS+'}'+name)
            if old is not None:
                position=list(dest).index(old);dest.remove(old)
            else:
                source_order=[e.tag for e in original];rank=source_order.index(new.tag) if new is not None else len(source_order)
                position=next((i for i,e in enumerate(dest) if e.tag in source_order and source_order.index(e.tag)>rank),len(dest))
            if new is not None:dest.insert(position,deepcopy(new))
        source_ct=ET.fromstring(src['[Content_Types].xml'])
        overrides={x.attrib['PartName'].lstrip('/'):x.attrib['ContentType'] for x in source_ct if x.tag.endswith('Override')}
        defaults={x.attrib['Extension']:x.attrib['ContentType'] for x in source_ct if x.tag.endswith('Default')}
        copied={}
        def clone(part):
            if part in copied:return copied[part]
            new=f'xl/template_assets/{index}/'+part;copied[part]=new
            files[new]=src[part]
            typ=overrides.get(part) or defaults.get(part.rsplit('.',1)[-1])
            if typ:ET.SubElement(ct,'{'+CT+'}Override',PartName='/'+new,ContentType=typ)
            rp=relpath(part)
            if rp in src:
                links=ET.fromstring(src[rp])
                for link in links:
                    if link.attrib.get('TargetMode')=='External':continue
                    child=clone(resolve(part,link.attrib['Target']))
                    link.set('Target',posixpath.relpath(child,posixpath.dirname(new)))
                files[relpath(new)]=ET.tostring(links,encoding='utf-8',xml_declaration=True)
            return new
        # Original drawing children also include shapes and WMF images omitted by
        # the workbook library. Retain their original XML and complete graph.
        tags={'drawing','legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','pageSetup'}
        children=[e for e in original if e.tag.rsplit('}',1)[-1] in tags]
        if children:
            for child in list(dest):
                if child.tag.rsplit('}',1)[-1] in tags:dest.remove(child)
            dr=relpath(dstpath)
            links=ET.fromstring(files[dr]) if dr in files else ET.Element('{'+REL+'}Relationships')
            source_links={r.attrib['Id']:r for r in ET.fromstring(src[relpath(srcpath)])} if relpath(srcpath) in src else {}
            for child in children:
                for element in child.iter():
                    for key,value in list(element.attrib.items()):
                        if key.startswith('{'+DOCREL+'}'):
                            link=source_links[value];new_id=f'template{index}_{len(links)}'
                            attrs=dict(link.attrib);attrs['Id']=new_id
                            if attrs.get('TargetMode')!='External':attrs['Target']=posixpath.relpath(clone(resolve(srcpath,attrs['Target'])),posixpath.dirname(dstpath))
                            ET.SubElement(links,'{'+REL+'}Relationship',attrs);element.set(key,new_id)
                source_order=[e.tag for e in original];rank=source_order.index(child.tag)
                position=next((i for i,e in enumerate(dest) if e.tag in source_order and source_order.index(e.tag)>rank),len(dest))
                dest.insert(position,child)
            files[dr]=ET.tostring(links,encoding='utf-8',xml_declaration=True)
        files[dstpath]=ET.tostring(dest,encoding='utf-8',xml_declaration=True)
    files['xl/workbook.xml']=ET.tostring(workbook,encoding='utf-8',xml_declaration=True)
    files['[Content_Types].xml']=ET.tostring(ct,encoding='utf-8',xml_declaration=True)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in files.items():z.writestr(name,value)
    return out.getvalue()
