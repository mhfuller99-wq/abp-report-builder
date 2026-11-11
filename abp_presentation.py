"""Requested report presentation. No formula, drawing or style changes."""
import io,re,zipfile,xml.etree.ElementTree as ET
from abp_fidelity import NS,sheet_paths


def header_text(text, project, location):
    # Excel formatting selectors and encoded newlines are controls, not text.
    parts=re.split(r'(_x[0-9a-fA-F]{4}_|&"[^"]*")',text or '')
    text=''.join(p if re.fullmatch(r'_x[0-9a-fA-F]{4}_|&"[^"]*"',p) else p.upper() for p in parts)
    lines=re.split(r'(_x000a_|\r?\n)',text)
    for i,line in enumerate(lines):
        for label,value in [('PROJECT:',project),('LOCATION:',location)]:
            if label in line:
                prefix,tail=line.split(label,1)
                # Only fill a genuine blank project/location field; never
                # replace another document's nonempty text or print controls.
                if not tail.strip():lines[i]=prefix+label+' '+str(value or '').upper().replace('&','&&')
    return ''.join(lines)


def finish_headers(data, project, location):
    with zipfile.ZipFile(io.BytesIO(data)) as z:parts={n:z.read(n) for n in z.namelist()}
    for path in sheet_paths(parts).values():
        root=ET.fromstring(parts[path])
        for node in root.findall('.//{'+NS+'}headerFooter/*'):
            if node.text:node.text=header_text(node.text,project,location)
        parts[path]=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in parts.items():z.writestr(name,value)
    return out.getvalue()


def uppercase_cells(wb):
    for ws in wb:
        for row in ws:
            for cell in row:
                if isinstance(cell.value,str) and cell.data_type!='f':cell.value=cell.value.upper()
