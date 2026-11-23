"""Source-reviewed exhaust inlets on the genuine original ABP grille form."""
import math,re

EXHAUST_TEMPLATE='Exhaust Grills.xlsx'
EXHAUST_FORMS=('Exhaust Fans _Std._.xlsx','Exhaust Fans _Sm._.xlsx')
EXHAUST_FIELDS=('include','type','size','system','location','design_cfm','source','reference','source_sha256',
    'evidence','position','position_coordinate_space','manual_locator','quantity','quantity_unresolved','exclusion_note','native_exhaust_callout')
EXHAUST_EXTRA=('review_history','review_notice','latest_observation','prior_inclusion')


def exhaust_errors(payload, *, require_review=True, check_sources=True):
    if not isinstance(payload,dict):return ['Invalid exhaust grille inventory']
    outlets=payload.get('exhaust_outlets',[])
    if not isinstance(outlets,list) or len(outlets)>500:return ['Invalid exhaust grille inventory']
    errors=[];seen=set()
    state=payload.get('scan_state') or {};sources=state.get('source_checkpoints',[]) if isinstance(state,dict) else []
    if not isinstance(sources,list):sources=[]
    records=payload.get('records',[])
    if not isinstance(records,list) or any(not isinstance(r,dict) for r in records):return ['Invalid equipment inventory for exhaust grilles']
    supply=payload.get('diffusers',[]);templates=payload.get('templates',[])
    if not isinstance(supply,list) or any(not isinstance(r,dict) for r in supply):return ['Invalid supply inventory for exhaust grille comparison']
    if not isinstance(templates,list):return ['Invalid exhaust grille worksheet selection']
    for item in outlets:
        if not isinstance(item,dict) or set(item)-set(EXHAUST_FIELDS+EXHAUST_EXTRA):
            errors.append('Invalid exhaust grille fields; measurements are not design inputs');continue
        if type(item.get('include'))!=bool:errors.append('Choose whether to include each exhaust grille')
        native=item.get('native_exhaust_callout') is True
        if 'native_exhaust_callout' in item and not native:errors.append('Invalid native exhaust observation')
        if native and (not item.get('position') or not item.get('type')):errors.append('A printed exhaust callout needs its type and drawing position')
        if 'prior_inclusion' in item and type(item['prior_inclusion'])!=bool:errors.append('Invalid prior exhaust grille inclusion')
        for key,limit in [('type',120),('size',120),('system',120),('location',120),('source',160),('reference',80),('manual_locator',120)]:
            if not isinstance(item.get(key,''),str) or len(item.get(key,''))>limit:errors.append('Invalid exhaust grille text')
        if item.get('quantity')!=1 or type(item.get('quantity'))!=int or item.get('quantity_unresolved') is not False:
            errors.append('Each exhaust grille row must identify one physical inlet')
        value=item.get('design_cfm');valid_number=isinstance(value,(int,float,str)) and not isinstance(value,bool)
        try:flow=float(value) if valid_number else math.nan
        except (ValueError,TypeError):flow=math.nan
        if not math.isfinite(flow) or not 0<flow<=100000:errors.append('Exhaust grille design CFM must be positive and no more than 100000')
        reference=item.get('reference');match=re.fullmatch(r'page ([1-9]\d{0,2})',reference) if isinstance(reference,str) else None
        digest=item.get('source_sha256')
        if not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest) or not match:
            errors.append('Exhaust grilles need their original source hash and page')
        elif check_sources:
            found=[s for s in sources if isinstance(s,dict) and s.get('name')==item.get('source') and s.get('sha256')==digest]
            if len(found)!=1 or type(found[0].get('pages'))!=int or int(match[1])>found[0]['pages']:
                errors.append('Exhaust grille source changed or is missing; review the original source again')
        note=item.get('evidence')
        if not isinstance(note,str) or not 20<=len(note.strip())<=500:errors.append('Record 20–500 characters of exhaust inlet source evidence')
        if (not native or item.get('include') is True) and not all(isinstance(item.get(k),str) and item[k].strip() for k in ('type','system','location','manual_locator')):
            errors.append('Exhaust grilles need a type, exhaust fan, room and distinct physical locator')
        if isinstance(item.get('type'),str) and re.match(r'^(?:SAG|SAD|SAR|RAG|SUPPLY|RETURN)(?:\W|\d|$)',item['type'],re.I):
            errors.append('Supply and return devices do not belong on the exhaust grille sheet')
        position=item.get('position')
        if position is not None and (not isinstance(position,list) or len(position)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=100000 for v in position)
                or item.get('position_coordinate_space')!='displayed_pdf_points'):
            errors.append('Invalid exhaust grille source position')
        key=tuple(str(item.get(k,'')) for k in ('source','reference','manual_locator'))
        if item.get('manual_locator') or not native:
            if key in seen:errors.append('Duplicate physical exhaust grille locator')
            seen.add(key)
        if item.get('include') is True:
            fans=[r for r in records if isinstance(r,dict) and r.get('tag')==item.get('system')
                  and r.get('template') in EXHAUST_FORMS and r.get('status')!='EXCLUDED']
            if len(fans)!=1 or require_review and fans[0].get('status')!='VERIFIED':
                errors.append('Every included exhaust grille must belong to one verified exhaust fan')
        elif require_review:
            reason=item.get('exclusion_note')
            if not isinstance(reason,str) or not 10<=len(reason.strip())<=500:errors.append('Every unchecked exhaust grille needs a source-based exclusion reason')
    included=[o for o in outlets if isinstance(o,dict) and o.get('include') is True]
    if included and EXHAUST_TEMPLATE not in templates:errors.append('Include the original Exhaust Grills worksheet for the exhaust inlets')
    # An excluded supply observation may remain as evidence of a corrected classification.
    physical=included+[o for o in supply if o.get('include') is True]
    for i,a in enumerate(included):
        for b in physical[i+1:]:
            if a.get('source')!=b.get('source') or a.get('reference')!=b.get('reference'):continue
            pa,pb=a.get('position'),b.get('position')
            if (isinstance(pa,list) and isinstance(pb,list) and len(pa)==len(pb)==2
                    and all(type(n) in (int,float) and math.isfinite(n) for n in pa+pb)
                    and math.dist(pa,pb)<1):errors.append('One physical inlet cannot be included twice or as both supply and exhaust')
    return list(dict.fromkeys(errors))


def populate_exhaust(wb,outlets,lookup,add,reset,safe):
    groups={}
    for item in outlets:
        if item.get('include') is True:groups.setdefault(item['system'],[]).append(item)
    first=next((s for s in wb if getattr(s,'_template_file',None)==EXHAUST_TEMPLATE),None)
    page=0
    for system,items in groups.items():
        for start in range(0,len(items),29):
            if page==0 and first is not None:sheet=first
            else:
                before=set(wb.sheetnames);add(wb,lookup[EXHAUST_TEMPLATE])
                sheet=wb[next(n for n in wb.sheetnames if n not in before)];reset(sheet)
            sheet['A6']=safe(system)
            for number,item in enumerate(items[start:start+29],start+1):
                row=7+(number-start-1)
                for col,value in [('A',item['location']),('B',number),('C',item['type']),('D',item.get('size','')),('F',float(item['design_cfm']))]:
                    if sheet[f'{col}{row}'].data_type=='f':raise ValueError('Exhaust grille design inputs overlap an original formula')
                    sheet[f'{col}{row}']=safe(value) if isinstance(value,str) else value
            page+=1
    return page
