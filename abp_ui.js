const reviewNumericFields=['quantity','design_cfm','osa_cfm','osa_min_cfm','esp','total_sp','motor_hp','motor_volts','motor_phase','motor_fla','motor_rpm','design_gpm','cooling_edb','cooling_ewb','cooling_ldb','cooling_lwb','heating_cfm','heating_edb','heating_ldb','heating_input_btu','heating_output_btu','cooling_total_btu','cooling_sensible_btu','electric_heating_edb','electric_heating_ldb','heater_volts','heater_phase','heater_amps','heater_stages','heating_ewt','heating_lwt','water_dp_ft'];
const reviewEvidenceFields=['selected_cfm','heater_kw'];
const reviewTextFields=['manufacturer','model','unit_type','service','equipment_location','area_served','heating_type'];
const exhaustFields=['include','type','size','system','location','design_cfm','source','reference','source_sha256','evidence','position','position_coordinate_space','manual_locator','quantity','quantity_unresolved','exclusion_note'];
const exhaustTemplate='Exhaust Grills.xlsx';
function exhaustOutletErrors(payload,requireReview=true,checkSources=true){
 if(!payload||typeof payload!=='object'||Array.isArray(payload))return ['Invalid exhaust grille inventory'];
 const outlets=payload.exhaust_outlets===undefined?[]:payload.exhaust_outlets;
 if(!Array.isArray(outlets)||outlets.length>500)return ['Invalid exhaust grille inventory'];
 const records=payload.records===undefined?[]:payload.records,errors=[],seen=new Set(),sources=payload.scan_state?.source_checkpoints||[];
 const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
 if(!Array.isArray(records)||records.some(r=>!object(r)))return ['Invalid equipment inventory for exhaust grilles'];
 const supply=payload.diffusers===undefined?[]:payload.diffusers,templates=payload.templates===undefined?[]:payload.templates;
 if(!Array.isArray(supply)||supply.some(r=>!object(r)))return ['Invalid supply inventory for exhaust grille comparison'];
 if(!Array.isArray(templates))return ['Invalid exhaust grille worksheet selection'];
 for(const o of outlets){
  if(!o||typeof o!=='object'||Array.isArray(o)||Object.keys(o).some(k=>![...exhaustFields,'review_history','review_notice','latest_observation'].includes(k))){errors.push('Invalid exhaust grille fields; measurements are not design inputs');continue;}
  if(typeof o.include!=='boolean')errors.push('Choose whether to include each exhaust grille');
  for(const [key,limit] of [['type',120],['size',120],['system',120],['location',120],['source',160],['reference',80],['manual_locator',120]])if(typeof (o[key]??'')!=='string'||(o[key]||'').length>limit)errors.push('Invalid exhaust grille text');
  if(o.quantity!==1||o.quantity_unresolved!==false)errors.push('Each exhaust grille row must identify one physical inlet');
  if(!['number','string'].includes(typeof o.design_cfm)||typeof o.design_cfm==='string'&&!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(o.design_cfm.trim())||!Number.isFinite(Number(o.design_cfm))||Number(o.design_cfm)<=0||Number(o.design_cfm)>100000)errors.push('Exhaust grille design CFM must be positive and no more than 100000');
  const match=typeof o.reference==='string'&&/^page ([1-9]\d{0,2})$/.exec(o.reference);
  if(typeof o.source_sha256!=='string'||!/^[a-f0-9]{64}$/.test(o.source_sha256)||!match)errors.push('Exhaust grilles need their original source hash and page');
  else if(checkSources){const found=(Array.isArray(sources)?sources:[]).filter(s=>s&&s.name===o.source&&s.sha256===o.source_sha256);
   if(found.length!==1||!Number.isInteger(found[0].pages)||Number(match[1])>found[0].pages)errors.push('Exhaust grille source changed or is missing; review the original source again');}
  if(typeof o.evidence!=='string'||o.evidence.trim().length<20||o.evidence.trim().length>500)errors.push('Record 20–500 characters of exhaust inlet source evidence');
  if(['type','system','location','manual_locator'].some(k=>typeof o[k]!=='string'||!o[k].trim()))errors.push('Exhaust grilles need a type, exhaust fan, room and distinct physical locator');
  if(typeof o.type==='string'&&/^(SAG|SAD|SAR|RAG|SUPPLY|RETURN)(\W|\d|$)/i.test(o.type))errors.push('Supply and return devices do not belong on the exhaust grille sheet');
  if(o.position!=null&&(!Array.isArray(o.position)||o.position.length!==2||o.position.some(v=>typeof v!=='number'||!Number.isFinite(v)||v<0||v>100000)||o.position_coordinate_space!=='displayed_pdf_points'))errors.push('Invalid exhaust grille source position');
  const key=JSON.stringify([o.source,o.reference,o.manual_locator]);if(seen.has(key))errors.push('Duplicate physical exhaust grille locator');seen.add(key);
  if(o.include===true){const fans=records.filter(r=>r.tag===o.system&&['Exhaust Fans _Std._.xlsx','Exhaust Fans _Sm._.xlsx'].includes(r.template)&&r.status!=='EXCLUDED');
   if(fans.length!==1||requireReview&&fans[0].status!=='VERIFIED')errors.push('Every included exhaust grille must belong to one verified exhaust fan');}
  else if(requireReview&&(typeof o.exclusion_note!=='string'||o.exclusion_note.trim().length<10||o.exclusion_note.trim().length>500))errors.push('Every unchecked exhaust grille needs a source-based exclusion reason');
 }
 const included=outlets.filter(o=>o&&o.include===true),physical=[...included,...supply.filter(o=>o.include===true)];
 if(included.length&&!templates.includes(exhaustTemplate))errors.push('Include the original Exhaust Grills worksheet for the exhaust inlets');
 for(const [i,a] of included.entries())for(const b of physical.slice(i+1))if(a.source===b.source&&a.reference===b.reference&&Array.isArray(a.position)&&Array.isArray(b.position)&&a.position.length===2&&b.position.length===2&&[...a.position,...b.position].every(n=>typeof n==='number'&&Number.isFinite(n))&&Math.hypot(a.position[0]-b.position[0],a.position[1]-b.position[1])<1)errors.push('One physical inlet cannot be included twice or as both supply and exhaust');
 return [...new Set(errors)];
}
function makeExhaustOutlet(input,state,records,supply,exhaust){
 if(!['incomplete','review_required'].includes(state.status)||state.complete_takeoff!==false)throw Error('Scan the current sources before adding an exhaust grille.');
 if(input.confirmed!==true)throw Error('Confirm the original physical exhaust inlet, its fan connection and duplicates.');
 const source=(state.source_checkpoints||[]).find(s=>s.name===input.source);if(!source)throw Error('Choose the original source document.');
 const text=value=>String(value??'').trim().toUpperCase(),note=text(input.note);
 const item={include:false,type:text(input.type),size:text(input.size),system:text(input.system),location:text(input.location),manual_locator:text(input.locator),design_cfm:Number(input.design_cfm),
  source:source.name,reference:'page '+Number(input.page),source_sha256:source.sha256,evidence:note,quantity:1,quantity_unresolved:false,
  review_history:[{kind:'manual_source_entry',source:source.name,sha256:source.sha256,page:Number(input.page),note}]};
 if(String(input.x??'').trim()||String(input.y??'').trim()){
  if(!String(input.x??'').trim()||!String(input.y??'').trim())throw Error('Enter both source coordinates or leave both blank.');
  item.position=[Number(input.x),Number(input.y)];item.position_coordinate_space='displayed_pdf_points';
 }
 if(!records.some(r=>r.tag===item.system&&r.status!=='EXCLUDED'&&['Exhaust Fans _Std._.xlsx','Exhaust Fans _Sm._.xlsx'].includes(r.template)))throw Error('Assign the grille to its source-confirmed exhaust fan.');
 if(item.position&&exhaust.some(o=>o.source===item.source&&o.reference===item.reference&&Array.isArray(o.position)&&o.position.length===2&&o.position.every(Number.isFinite)&&Math.hypot(o.position[0]-item.position[0],o.position[1]-item.position[1])<1))throw Error('This physical exhaust inlet already has a review row.');
 const errors=exhaustOutletErrors({records,diffusers:supply,exhaust_outlets:[...exhaust,item],scan_state:state,templates:[exhaustTemplate]},false);
 if(errors.length)throw Error(errors.join('. '));return item;
}
const componentFields=['component_of','component_kind','component_source_sha256','component_note'];
function isEquipmentComponent(record){return componentFields.some(key=>Object.hasOwn(record,key));}
function equipmentComponentErrors(payload,requireVerified=true,checkSources=true){
 const records=payload.records===undefined?[]:payload.records;if(!Array.isArray(records)||records.some(r=>!r||typeof r!=='object'||Array.isArray(r)))return ['Invalid equipment component inventory'];
 const errors=[],seen=new Set(),one=value=>[undefined,null,'',1,'1'].includes(value);
 for(const r of records){
  if(!isEquipmentComponent(r))continue;
  const parent=r.component_of;
  if(typeof parent!=='string'||parent.length>70||!/^(RTU|AHU|MAU|MUA|DOAS|PKU|HP|AC|FCU|BCU)-[A-Z0-9]+(?:[.-][A-Z0-9]+)*$/.test(parent)){errors.push('Choose the printed ID of the parent air unit');continue;}
  if(r.component_kind!=='integral_exhaust'||r.tag!==parent+' EXHAUST')errors.push('Integral exhaust labels must be derived from their parent unit');
  if(seen.has(parent))errors.push('Only one integral exhaust review is allowed per parent unit');seen.add(parent);
  const parents=records.filter(p=>p.tag===parent);
  if(parents.length!==1||isEquipmentComponent(parents[0])||parents[0].template!=='Air Moving Equipment.xlsx'||!one(parents[0].quantity))errors.push('An integral exhaust component needs one unambiguous parent air unit');
  else if(requireVerified&&r.status!=='EXCLUDED'&&parents[0].status!=='VERIFIED')errors.push('Verify the parent air unit before its integral exhaust component');
  if(r.template!=='Exhaust Fans _Std._.xlsx'||![undefined,null,''].includes(r.coil_template)||!one(r.quantity)||(r.instance_locations!=null&&(!Array.isArray(r.instance_locations)||r.instance_locations.length)))errors.push('Use one original standard exhaust form for the linked component');
  if(!['UNVERIFIED','VERIFIED','EXCLUDED'].includes(r.status))errors.push('Invalid equipment component review status');
  if(requireVerified&&!['VERIFIED','EXCLUDED'].includes(r.status))errors.push('Verify or exclude every integral exhaust component');
  if(typeof r.component_note!=='string'||r.component_note.trim().length<20||r.component_note.trim().length>500)errors.push('Record 20–500 characters of source evidence for the integral exhaust component');
  const page=typeof r.reference==='string'&&/^page ([1-9]\d{0,2})$/.exec(r.reference);
  if(typeof r.source!=='string'||r.source.length<1||r.source.length>160||!page||typeof r.component_source_sha256!=='string'||!/^[a-f0-9]{64}$/.test(r.component_source_sha256)){errors.push('Integral exhaust components need their original source hash and page');continue;}
  if(checkSources){const checkpoints=payload.scan_state?.source_checkpoints;
   const sources=(Array.isArray(checkpoints)?checkpoints:[]).filter(s=>s&&s.name===r.source&&s.sha256===r.component_source_sha256);
   if(sources.length!==1||!Number.isInteger(sources[0].pages)||Number(page[1])>sources[0].pages)errors.push('Integral exhaust source changed or is missing; review it against the current source');}
 }
 return [...new Set(errors)];
}
function mergeSourceFiles(current,incoming){
  const files=[...current],keys=new Set(files.map(f=>JSON.stringify([f.name,f.size,f.lastModified])));
  for(const file of incoming){
    if(!/\.(pdf|xlsx|csv)$/i.test(file.name))throw Error('Choose PDF, Excel (.xlsx), or CSV source documents.');
    const key=JSON.stringify([file.name,file.size,file.lastModified]);
    if(!keys.has(key)){keys.add(key);files.push(file);}
  }
  if(files.reduce((n,f)=>n+f.size,0)>200000000)throw Error('Combined source documents exceed 200 MB. Remove a file before adding more.');
  return files;
}
function fieldLabel(key){return ({quantity:'Physical quantity under this printed tag',exhaust_cfm:'Hood exhaust CFM',supply_cfm:'Hood supply CFM (evidence only)',makeup_air_cfm:'Hood makeup CFM (evidence only)',heater_volts:'Heater design volts',heater_phase:'Heater phases (1 or 3)',heater_amps:'Heater design amps',heater_stages:'Heater stages',heating_type:'Heating type: ELECTRIC, GAS, or HOT WATER',heating_ewt:'Heating entering water temperature',heating_lwt:'Heating leaving water temperature',water_dp_ft:'Water pressure drop (ft)',cooling_edb:'Cooling entering dry bulb °F',cooling_ewb:'Cooling entering wet bulb °F',cooling_ldb:'Cooling leaving dry bulb °F',cooling_lwb:'Cooling leaving wet bulb °F',heating_edb:'Heating entering dry bulb °F',heating_ldb:'Heating leaving dry bulb °F',heating_cfm:'Heating CFM',heating_input_btu:'Heating input BTU/h',heating_output_btu:'Heating output BTU/h'})[key]||key.replaceAll('_',' ');}
function reviewCoverage(records, outlets) {
  if(!records.length&&!outlets.length)return 'No equipment or outlets extracted. This is an empty takeoff; review the source documents before building a job report.';
  const populated=records.filter(r=>r.status==='VERIFIED'&&r.template&&!isEquipmentComponent(r)).length;
  const components=records.filter(r=>r.status==='VERIFIED'&&r.template&&isEquipmentComponent(r)).length;
  const unresolved=records.filter(r=>r.status!=='VERIFIED'&&r.status!=='EXCLUDED').length;
  const included=outlets.filter(d=>d.include!==false).length;
  return `${populated} equipment entries ready${components?'; '+components+' linked component forms ready':''}; ${unresolved} unresolved. ${included} of ${outlets.length} outlet candidates included. Check source revisions and unresolved entries before field use.`;
}
function sourceReadiness(records,outlets,images,comparison){
  const verified=records.filter(r=>r.status==='VERIFIED'&&!isEquipmentComponent(r)).length;
  const components=records.filter(r=>r.status==='VERIFIED'&&isEquipmentComponent(r)).length;
  const unresolved=records.filter(r=>!['VERIFIED','EXCLUDED'].includes(r.status)).length;
  const pendingImages=images.filter(c=>!c.accepted&&!c.excluded).length;
  const problems=comparison?comparison.rows.filter(r=>r.status!=='match').length:0;
  const imageOutlets=images.filter(c=>!c.accepted&&!c.excluded&&c.kind==='diffuser').length;
  const imageEquipment=images.filter(c=>!c.accepted&&!c.excluded&&['equipment','kitchen_hood'].includes(c.kind)).length;
  const empty=!records.length&&!outlets.length&&!images.length;
  const title=empty?'No equipment or outlets extracted — source review required':
    !records.length&&!outlets.length?'Image candidates found — source confirmation required':verified+' equipment verified'+(components?' · '+components+' linked component forms verified':'')+' · '+unresolved+' equipment unresolved';
  return {title,empty,pendingImages,imageOutlets,imageEquipment,problems};
}
function scanCandidateSummary(records,outlets,images){
  const counts=sourceReadiness(records,outlets,images,null);
  return records.length+' equipment review rows; '+outlets.length+' outlet review rows. '+
    counts.imageOutlets+' image outlet candidates and '+counts.imageEquipment+' image equipment/hood candidates awaiting source confirmation. '+
    'Image candidates may overlap existing rows; they are not report-ready entries. ';
}
function emptySourceReport(records,outlets,state){
  return !!state?.source_checkpoints?.length&&!records.some(r=>r.status==='VERIFIED'&&r.template)&&!outlets.some(d=>d.include!==false);
}
// Shared browser helpers. Keep saved reviews validated before replacing UI state.
function worksheetLabel(name) {
  return name.replace(/(?:\.xlsx)+$/i,'').replaceAll('_',' ').replace(/\s+/g,' ').trim();
}
function applyCompanionChoices(chosen, records) {
  const assigned=new Set(records.map(r=>r.coil_template).filter(Boolean));
  for(const name of ['Coil DX GAS HT.xlsx','COIL DX HP ELE.xlsx','Coil WTR CLG WTR HT.xlsx']) {
    if(assigned.has(name)) chosen.add(name); else chosen.delete(name);
  }
  return chosen;
}

async function readApiJson(response) {
  if(response.status===401) throw Error('Your session has expired. Save your review, then sign in again.');
  let data;
  try { data=await response.json(); }
  catch { throw Error(`The server did not return a valid response (HTTP ${response.status}). Your current review has been preserved. Please try again.`); }
  if(!response.ok) throw Error(data?.error||'The request could not be completed. Please try again.');
  return data;
}
function validateSavedReview(data, templates, forms, tagPattern) {
  const invalid=()=>{throw Error('Invalid saved review. Your current report has not been changed.');};
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const numeric=x=>(typeof x==='number'||typeof x==='string'&&x.trim()!=='')&&Number.isFinite(Number(x))&&Number(x)>=0&&Number(x)<=1000000;
  const fields=reviewNumericFields;
  if(Array.isArray(data?.templates)&&data.templates.includes('Exhaust Grilles.xlsx.xlsx'))data={...data,
   templates:[...new Set(data.templates.map(t=>t==='Exhaust Grilles.xlsx.xlsx'?exhaustTemplate:t))],source_review:null,
   template_migration_notice:'The old grille-named fan form was replaced with the genuine original Exhaust Grills worksheet. Review the worksheet selection and source inventory again.'};
  if(!object(data)||data.format!=='ABP-PREFIELD-REVIEW'||data.version!==1||typeof data.project!=='string'||data.project.length>180||typeof data.location!=='string'||data.location.length>180||!['Commercial','USACE'].includes(data.standard)||!Array.isArray(data.records)||data.records.length>500||!Array.isArray(data.templates)||data.templates.some(t=>typeof t!=='string'||!templates.includes(t))||new Set(data.templates).size!==data.templates.length) invalid();
  if(data.human_page_reviews!==undefined&&(!Array.isArray(data.human_page_reviews)||data.human_page_reviews.length>30000||data.human_page_reviews.some(p=>!object(p)||typeof p.source!=='string'||p.source.length>160||! /^[a-f0-9]{64}$/.test(p.sha256||'')||!Number.isInteger(p.page)||p.page<1||p.page>300||!['reviewed','not_applicable'].includes(p.disposition)||typeof p.note!=='string'||p.note.trim().length<10||p.note.length>500)))invalid();
  if(data.human_review_note!==undefined&&(typeof data.human_review_note!=='string'||data.human_review_note.length>1000))invalid();
  const tags=new Set();
  for(const r of data.records) {
    if(!object(r)||typeof r.tag!=='string'||!isEquipmentComponent(r)&&!tagPattern.test(r.tag)||tags.has(r.tag.toUpperCase())||!['UNVERIFIED','VERIFIED','EXCLUDED'].includes(r.status)) invalid();
    tags.add(r.tag.toUpperCase());
    if(r.template!==undefined&&(typeof r.template!=='string'||r.template!==''&&!Object.hasOwn(forms,r.template))) invalid();
    if(r.coil_template!==undefined&&!['','Coil DX GAS HT.xlsx','COIL DX HP ELE.xlsx','Coil WTR CLG WTR HT.xlsx'].includes(r.coil_template)) invalid();
    for(const field of fields) if(r[field]!==undefined&&r[field]!==null&&r[field]!==''&&!numeric(r[field])) invalid();
    if(r.quantity!=null&&r.quantity!==''&&(!Number.isInteger(Number(r.quantity))||Number(r.quantity)<1||Number(r.quantity)>100)) invalid();
    if(r.instance_locations!==undefined&&(!Array.isArray(r.instance_locations)||r.instance_locations.length>100||r.instance_locations.some(x=>typeof x!=='string'||x.length>120))) invalid();
    if(r.design_cfm!=null&&r.design_cfm!==''&&r.osa_cfm!=null&&r.osa_cfm!==''&&Number(r.osa_cfm)>Number(r.design_cfm)) invalid();
    for(const key of reviewTextFields) if(r[key]!==undefined&&(typeof r[key]!=='string'||r[key].length>120)) invalid();
    if(r.heater_phase!=null&&r.heater_phase!==''&&![1,3].includes(Number(r.heater_phase))) invalid();
    if(r.motor_phase!=null&&r.motor_phase!==''&&![1,3].includes(Number(r.motor_phase))) invalid();
    if(r.heater_stages!=null&&r.heater_stages!==''&&(!Number.isInteger(Number(r.heater_stages))||Number(r.heater_stages)<1)) invalid();
    if(r.heating_type!=null&&r.heating_type!==''&&!['ELECTRIC','GAS','HOT WATER'].includes(r.heating_type.trim().toUpperCase())) invalid();
    if(r.osa_min_cfm!=null&&r.osa_min_cfm!==''&&(r.osa_cfm==null||r.osa_cfm===''||Number(r.osa_min_cfm)>Number(r.osa_cfm))) invalid();
    for(const key of ['source','reference','evidence']) if(r[key]!==undefined&&typeof r[key]!=='string') invalid();
    if(r.occurrences!==undefined&&(!Array.isArray(r.occurrences)||r.occurrences.length>30||r.occurrences.some(o=>!object(o)||['source','reference','evidence'].some(k=>o[k]!==undefined&&typeof o[k]!=='string')))) invalid();
    if(r.candidates!==undefined&&(!Array.isArray(r.candidates)||r.candidates.length>30||r.candidates.some(c=>!object(c)||!object(c.values)||Object.entries(c.values).some(([k,v])=>reviewTextFields.includes(k)?typeof v!=='string'||v.length>120:(!fields.includes(k)&&!reviewEvidenceFields.includes(k))||!numeric(v))||['source','reference','evidence'].some(k=>c[k]!==undefined&&typeof c[k]!=='string')))) invalid();
  }
  if(data.diffusers!==undefined&&(!Array.isArray(data.diffusers)||data.diffusers.length>500||data.diffusers.some(d=>!object(d)||(d.design_cfm!==undefined&&d.design_cfm!==null&&d.design_cfm!==''&&!numeric(d.design_cfm))||(d.exclusion_note!==undefined&&(typeof d.exclusion_note!=='string'||d.exclusion_note.length>500))))) invalid();
  if(outletInstanceErrors((data.diffusers||[]).filter(d=>d.repeat_resolution!==undefined||d.repeat_instance!==undefined)).length)invalid();
  if(data.image_coverage_truncated!==undefined&&typeof data.image_coverage_truncated!=='boolean')invalid();
  if(data.image_coverage!==undefined&&(!Array.isArray(data.image_coverage)||data.image_coverage.length>1000||data.image_coverage.some(p=>!object(p)||typeof p.source!=='string'||p.source.length>160||!Number.isInteger(p.page)||p.page<1||p.page>300||typeof (p.status||p.ocr_status)!=='string'||(p.status||p.ocr_status).length>100||p.regions_omitted!==undefined&&(!Number.isInteger(p.regions_omitted)||p.regions_omitted<0||p.regions_omitted>100000)||['image_regions_truncated','selection_truncated'].some(k=>p[k]!==undefined&&typeof p[k]!=='boolean')||p.selection_failed!==undefined&&(typeof p.selection_failed!=='string'||p.selection_failed.length>100)||p.unexamined_content!==undefined&&(typeof p.unexamined_content!=='string'||p.unexamined_content.length>1000)||p.regions!==undefined&&(!Array.isArray(p.regions)||p.regions.length>100||p.regions.some(r=>!object(r)||typeof r.status!=='string'||r.status.length>100||r.box!==undefined&&(!Array.isArray(r.box)||r.box.length!==4||r.box.some(x=>typeof x!=='number'||!Number.isFinite(x)||Math.abs(x)>100000))||r.reason!==undefined&&(typeof r.reason!=='string'||r.reason.length>1000)||r.method!==undefined&&(typeof r.method!=='string'||r.method.length>100)||r.pixels!==undefined&&(!Number.isInteger(r.pixels)||r.pixels<0||r.pixels>100000000))))))invalid();
  if(data.image_review!==undefined&&(!Array.isArray(data.image_review)||data.image_review.length>500||data.image_review.some(c=>!object(c)||!['kitchen_hood','diffuser','equipment'].includes(c.kind)||typeof c.tag!=='string'||c.tag.length>80||typeof c.source!=='string'||c.source.length>160||!Number.isInteger(c.page)||c.page<1||c.page>300||!object(c.review_values)||Object.entries(c.review_values).some(([k,v])=>!(c.kind==='equipment'?fields:['exhaust_cfm','supply_cfm','makeup_air_cfm','design_cfm']).includes(k)||!numeric(v))||c.evidence_text!==undefined&&(typeof c.evidence_text!=='string'||c.evidence_text.length>4000)||c.review_reasons!==undefined&&(!Array.isArray(c.review_reasons)||c.review_reasons.length>20||c.review_reasons.some(x=>typeof x!=='string'||x.length>1000))||['type','size'].some(k=>c[k]!==undefined&&(typeof c[k]!=='string'||c[k].length>120))||c.accepted!==undefined&&typeof c.accepted!=='boolean')))invalid();
  for(const c of data.image_review||[])for(const key of ['native_outlet_match','native_outlet_ambiguous'])if(c[key]!==undefined&&typeof c[key]!=='boolean')invalid();
  validateScanState(data.scan_state);
  if(airPathErrors(data,false,false).length)invalid();
  if(equipmentComponentErrors(data,false,false).length)invalid();
  if(exhaustOutletErrors(data,false,false).length)invalid();
  return {...data,records:data.records.map(r=>({...r,tag:r.tag.toUpperCase()}))};
}

// Save and restore share the same UTF-8 byte budget. Never download an unreadable review.
const savedReviewByteLimit=2000000;
function assertSavedReviewSize(bytes){
  if(!Number.isFinite(bytes)||bytes<0||bytes>savedReviewByteLimit)throw Error('Project review exceeds 2 MB. Split the source set into smaller project reviews; your current review has not been changed.');
}
function serializeSavedReview(data){
  const text=JSON.stringify(data);
  assertSavedReviewSize(new Blob([text]).size);
  return text;
}
async function parseSavedReviewFile(file){
  assertSavedReviewSize(file.size);
  const text=await file.text();
  assertSavedReviewSize(new Blob([text]).size);
  return JSON.parse(text);
}

function coverageStatusLabel(status){
 const labels={image_reading_unavailable:'Image reading unavailable or incomplete; review manually',not_needed:'No OCR needed',native_text_preserved_small_images_skipped:'Native text preserved; small marginal images skipped',native_text_present:'Native text present',budget_skipped:'Not examined: budget reached',failed:'OCR failed; review manually',ocr_failed:'OCR failed; review manually',no_text:'No readable OCR text',review_required:'OCR requires source review',partial_review_required:'Partial image review only',review_candidate:'Unverified candidate found',no_supported_table_recognized:'No supported table recognized; review manually',no_ruled_regions_detected_manual_review:'No ruled table detected; review images manually',outside_raster:'Outside detected raster content'};
 return labels[status]||String(status||'Coverage unknown').replaceAll('_',' ');
}

// Scan completeness is review state, not a transient status message.
let scanState={status:'not_scanned',complete_takeoff:false,source_checkpoints:[],warnings:[]};
function validateScanState(state){
 if(state===undefined)return {status:'unknown',complete_takeoff:false,source_checkpoints:[],warnings:['This older saved review has no source scan history. Rescan before building.']};
 const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
 const invalid=()=>{throw Error('Invalid source scan history. Current review was not changed.');};
 if(!obj(state)||!['not_scanned','review_required','incomplete','stale','unknown'].includes(state.status)||state.complete_takeoff!==false||!Array.isArray(state.source_checkpoints)||state.source_checkpoints.length>100||!Array.isArray(state.warnings)||state.warnings.length>1000||state.warnings.some(w=>typeof w!=='string'||w.length>2000))invalid();
 for(const c of state.source_checkpoints){
  if(c.pages!==undefined&&(!Number.isInteger(c.pages)||c.pages<1||c.pages>300))invalid();
  if(c.completed_pages!==undefined&&(!Array.isArray(c.completed_pages)||c.completed_pages.length>300||c.completed_pages.some(p=>!Number.isInteger(p)||p<1||p>300)))invalid();
  if(!obj(c)||typeof c.name!=='string'||c.name.length>160||!['completed_native_stage','incomplete'].includes(c.native_status)||!['not_applicable','not_started','incomplete','review_required'].includes(c.image_status)||c.sha256!=null&&(typeof c.sha256!=='string'||! /^[a-f0-9]{64}$/.test(c.sha256))||c.reason!==undefined&&(typeof c.reason!=='string'||c.reason.length>1000))invalid();
 }
 return state;
}
function scanStateBlocked(state){return ['incomplete','stale','unknown'].includes(state.status)||state.source_checkpoints.some(c=>c.native_status!=='completed_native_stage'||['incomplete','not_started'].includes(c.image_status));}
function scanStateNotice(){return scanStateBlocked(scanState)?'SOURCE SCAN INCOMPLETE OR OUTDATED. Review is required before building. '+scanState.warnings.join(' | ')+' ':'';}

function scanBuildBlocked(state,ack){
 if(!scanStateBlocked(state))return false;
 return !(state.status==='incomplete'&&state.source_checkpoints.some(c=>c.native_status==='completed_native_stage')&&ack&&ack.acknowledged===true&&typeof ack.note==='string'&&ack.note.trim().length>=20&&ack.note.trim().length<=1000&&JSON.stringify(ack.scan_state)===JSON.stringify(state));
}
function currentScanAcknowledgement(){
 const checked=$('partial-review-ack');const note=$('partial-review-note');
 return checked&&checked.checked?{acknowledged:true,note:String(note?.value||'').trim(),scan_state:JSON.parse(JSON.stringify(scanState))}:null;
}
function renderScanReview(){
 const box=$('partial-review-panel');if(!box)return;
 box.hidden=!scanStateBlocked(scanState);
 $('partial-coverage').textContent=scanState.source_checkpoints.map(c=>c.name+': native '+c.native_status+'; image '+c.image_status+(c.reason?' — '+c.reason:'')).concat(scanState.warnings).join('\n');
 $('partial-review-ack').checked=false;$('partial-review-note').value='';
}


// Stable source observations survive review edits; CFM/room are not identity.
function outletFromImage(candidate){
 const outlet={include:false,type:candidate.type||'',size:candidate.size||'',design_cfm:candidate.review_values?.design_cfm??null,system:'',location:'',source:candidate.source,reference:'page '+candidate.page,evidence:candidate.evidence_text||''};
 for(const key of ['position','position_coordinate_space','region','region_coordinate_space','coordinate_space','method','shape','quantity','quantity_unresolved','quantity_candidates'])if(candidate[key]!==undefined)outlet[key]=JSON.parse(JSON.stringify(candidate[key]));
 outlet.observation={type:outlet.type,size:outlet.size,design_cfm:outlet.design_cfm};
 return outlet;
}
function samePhysicalOutlet(a,b){
 if(a.source!==b.source||a.reference!==b.reference)return false;
 if(a.repeat_instance||b.repeat_instance)return Boolean(a.repeat_instance&&b.repeat_instance&&a.repeat_instance.group===b.repeat_instance.group&&a.repeat_instance.index===b.repeat_instance.index);
 if(!Array.isArray(a.position)||!Array.isArray(b.position)||a.position.length!==2||b.position.length!==2)return false;
 return a.position.every(Number.isFinite)&&b.position.every(Number.isFinite)&&Math.hypot(a.position[0]-b.position[0],a.position[1]-b.position[1])<=2;
}
function recoverySourceIdentities(expected,actual){
 if(!Array.isArray(expected)||!expected.length||expected.length>100)throw Error('The saved review has no complete source identity list. Use a new scan and review its results.');
 const names=new Set(),identities=expected.map(s=>{
  if(!s||typeof s.name!=='string'||!s.name.length||s.name.length>160||/[\\/]/.test(s.name)||names.has(s.name)||typeof s.sha256!=='string'||!/^[a-f0-9]{64}$/.test(s.sha256))throw Error('The saved review has invalid source identities. Use a new scan and review its results.');
  names.add(s.name);return {name:s.name,sha256:s.sha256};
 });
 if(actual!==undefined){
  const uploaded=recoverySourceIdentities(actual),byName=new Map(uploaded.map(s=>[s.name,s.sha256]));
  if(uploaded.length!==identities.length||identities.some(s=>byName.get(s.name)!==s.sha256))throw Error('Source files differ from the saved review. Reattach every original file with the same name and contents. Your reviewed values were not replaced.');
 }
 return identities;
}
function reconcileReviewedOutlets(previous,native,images,retried){
 const observations=native.map(o=>({...o}));
 for(const candidate of images.filter(c=>c.kind==='diffuser')){
  const o=outletFromImage(candidate);
  // Only materialize an image observation already represented by a review row.
  if(previous.some(old=>samePhysicalOutlet(old,o))&&!observations.some(old=>samePhysicalOutlet(old,o)))observations.push(o);
 }
 const consumed=new Set(),result=[];
 for(const old of previous){
  const matches=observations.map((o,i)=>samePhysicalOutlet(old,o)?i:-1).filter(i=>i>=0);
  // An array denotes recovery of the complete source set. Even a legacy row
  // without source metadata must be rechecked, never silently retained as included.
  const affected=Array.isArray(retried)||old.source===retried;
  if(matches.length===1&&!consumed.has(matches[0])){
   const index=matches[0],incoming=observations[index];consumed.add(index);
   result.push(affected?{...old,include:false,prior_inclusion:old.include!==false,
    latest_observation:{type:incoming.type,size:incoming.size,design_cfm:incoming.design_cfm,...(incoming.quantity!==undefined?{quantity:incoming.quantity}:{}),...(incoming.quantity_candidates?{quantity_candidates:incoming.quantity_candidates}:{})},
    review_notice:'This source was retried. Your reviewed values and associations were retained. Compare the new source observation, then check Include again.'}:old);
  }else{
   for(const index of matches)consumed.add(index);
   result.push(affected?{...old,include:false,prior_inclusion:old.include!==false,
    review_notice:matches.length?'Ambiguous repeated source observations: resolve this physical outlet before including.':'This outlet was not recovered on retry. Your prior row is retained; check the source before including it.'}:old);
  }
 }
 for(let i=0;i<native.length;i++)if(!consumed.has(i))result.push(observations[i]);
 if(result.length>500)throw Error('Outlet review limit exceeded; previous review was preserved.');
 return result;
}
function reconcileReviewedEquipment(previous,fresh,retried,recovering=false){
 const prior=new Map(previous.map(r=>[r.tag,r]));
 const result=fresh.map(r=>{
  const old=prior.get(r.tag);if(!old)return r;prior.delete(r.tag);
  const affected=recovering||old.source===retried||(old.occurrences||[]).some(c=>c.source===retried)||(r.candidates||[]).some(c=>c.source===retried);
  return affected?{...r,...old,candidates:r.candidates,occurrences:r.occurrences,proposed:r.proposed,text_proposed:r.text_proposed,flags:r.flags,status:'UNVERIFIED'}:old;
 });
 for(const old of prior.values())result.push({...old,status:'UNVERIFIED',flags:[...(old.flags||[]),'Prior equipment was not recovered. Check its original source before verification.']});
 if(result.length>500)throw Error('Equipment review limit exceeded; previous review was preserved.');
 return result;
}
function assignOutletBatch(outlets,indices,values,note){
 if(!Array.isArray(indices)||!indices.length||new Set(indices).size!==indices.length||indices.some(i=>!Number.isInteger(i)||i<0||i>=outlets.length))throw Error('Select the specific outlets to update.');
 const changes={};for(const key of ['system','location','size'])if(String(values[key]||'').trim())changes[key]=String(values[key]).trim().toUpperCase();
 if(!Object.keys(changes).length)throw Error('Enter a system, room or neck size to assign.');
 if(Object.values(changes).some(x=>x.length>120))throw Error('Assignment text is too long.');
 if(typeof note!=='string'||note.trim().length<10||note.length>500)throw Error('Describe the source evidence for this assignment (10–500 characters).');
 if(indices.some(i=>(outlets[i].review_history||[]).length>=30))throw Error('Review history limit reached; save this review before starting another batch.');
 const action={note:note.trim(),at:new Date().toISOString(),rows:indices.map(i=>({index:i,before:Object.fromEntries(Object.keys(changes).map(k=>[k,outlets[i][k]??''])),after:changes}))};
 const result=outlets.map((o,i)=>indices.includes(i)?{...o,...changes,review_history:[...(o.review_history||[]),{kind:'batch_assignment',note:action.note,at:action.at,source:o.source,reference:o.reference,before:action.rows.find(r=>r.index===i).before,after:changes}]}:o);
 return {outlets:result,action};
}
function undoOutletBatch(outlets,action){
 if(!action||action.rows.some(r=>!outlets[r.index]||Object.entries(r.after).some(([k,v])=>outlets[r.index][k]!==v)))throw Error('These fields changed after the batch. Review them individually; newer edits were preserved.');
 return outlets.map((o,i)=>{const row=action.rows.find(r=>r.index===i);return row?{...o,...row.before,review_history:[...(o.review_history||[]),{kind:'undo_batch',at:new Date().toISOString(),batch_at:action.at}]}:o;});
}

function resolveRepeatedOutlet(outlets,index,locations,note,confirmed=false,reviewedCount){
 if(confirmed!==true)throw Error('Confirm the physical count and whether the printed airflow applies to each outlet.');
 const original=outlets[index];
 if(!original||original.repeat_resolution||original.repeat_instance)throw Error('This callout was already resolved; review its physical rows.');
 const count=reviewedCount===undefined?original.quantity:reviewedCount;
 const manualCount=!original.quantity_unresolved&&!(original.quantity>1);
 if(manualCount&&reviewedCount===undefined)throw Error('Enter the repeated count you checked on the original source.');
 if(!Number.isInteger(count)||count<2||count>100)throw Error('A source-supported repeated count between 2 and 100 is required.');
 if(!Array.isArray(original.position)||original.position.length!==2||original.position.some(x=>!Number.isFinite(x))||!original.source||!original.reference)throw Error('The repeated callout needs an original source page and position.');
 if(!Array.isArray(locations)||locations.some(x=>typeof x!=='string'))throw Error('Enter one physical locator per line.');
 const locators=locations.map(x=>x.trim().toUpperCase()).filter(Boolean);
 if(locators.length!==count||locators.some(x=>x.length>120)||new Set(locators).size!==count)throw Error('Enter exactly '+count+' distinct physical locators, one per line (room and position, such as OFFICE 101 / NORTH).');
 if(typeof note!=='string'||note.trim().length<10||note.trim().length>500)throw Error('Describe the source evidence establishing every physical outlet (10–500 characters).');
 if(outlets.length+count>500)throw Error('Resolving this count exceeds the 500-row review limit. Split the source set.');
 const group=JSON.stringify([original.source,original.reference,original.position]);
 if(outlets.some(o=>o.repeat_resolution?.group===group))throw Error('This source callout already has a physical resolution.');
 const parent={...original,quantity:count,include:false,exclusion_note:'AGGREGATE CALLOUT REPLACED BY '+count+' SOURCE-REVIEWED PHYSICAL ROWS.',repeat_resolution:{group,locators,note:note.trim(),source_quantity:manualCount?null:original.quantity??null,source_quantity_candidates:original.quantity_candidates||[],...(manualCount?{manual_count:true,scanned_quantity:original.quantity??null}:{})}};
 const children=locators.map((locator,i)=>{const item={...original,include:false,quantity:1,quantity_unresolved:false,repeat_instance:{group,index:i+1,locator},location:locator,exclusion_note:'',review_notice:'Manually resolved from a repeated source callout. Check this physical location and Include after source review.'};delete item.repeat_resolution;return item;});
 const result=outlets.map((o,i)=>i===index?parent:o).concat(children);
 return {outlets:result,action:{index,before:JSON.parse(JSON.stringify(original)),after:JSON.parse(JSON.stringify(parent)),children:JSON.parse(JSON.stringify(children)),start:outlets.length}};
}
function undoRepeatedOutlet(outlets,action){
 if(!action||outlets.length!==action.start+action.children.length||JSON.stringify(outlets[action.index])!==JSON.stringify(action.after)||JSON.stringify(outlets.slice(action.start))!==JSON.stringify(action.children))throw Error('Physical rows changed after resolution. Keep the newer edits and review them individually.');
 return outlets.slice(0,action.start).map((o,i)=>i===action.index?action.before:o);
}
function outletInstanceErrors(outlets){
 const errors=[],parents=new Map(),children=new Map(),text=(v,min=1,max=120)=>typeof v==='string'&&v.trim().length>=min&&v.trim().length<=max;
 for(const o of outlets){
  if(o.include!==false&&(o.quantity_unresolved||o.quantity!==undefined&&o.quantity!==1))errors.push('Resolve the repeated outlet count into reviewed physical rows before including it');
  if(o.repeat_resolution!==undefined){
   const p=o.repeat_resolution;let identity;
   try{identity=typeof p?.group==='string'&&p.group.length<=600?JSON.parse(p.group):null;}catch(e){identity=null;}
   const validSource=text(o.source,1,160)&&text(o.reference,1,120)&&Array.isArray(o.position)&&o.position.length===2&&o.position.every(Number.isFinite);
   const validWitness=p&&(p.source_quantity===null||Number.isInteger(p.source_quantity)&&p.source_quantity>1)&&Array.isArray(p.source_quantity_candidates)&&p.source_quantity_candidates.length<=100&&p.source_quantity_candidates.every(x=>Number.isInteger(x)&&x>1);
   if(!p||!validSource||!validWitness||JSON.stringify(identity)!==JSON.stringify([o.source,o.reference,o.position])||!Array.isArray(p.locators)||p.locators.length<2||p.locators.length>100||p.locators.some(x=>!text(x))||new Set(p.locators.map(x=>x.trim().toUpperCase())).size!==p.locators.length||o.quantity!==p.locators.length||o.include!==false||!text(p.note,10,500)){errors.push('Repeated callout needs its reviewed count, original source and distinct physical locators');continue;}
   if(parents.has(p.group))errors.push('Duplicate repeated callout review');parents.set(p.group,[o,p]);
  }
  if(o.repeat_instance!==undefined){
   const c=o.repeat_instance;if(!c||!text(c.group,1,600)||!Number.isInteger(c.index)){errors.push('Invalid repeated outlet identity');continue;}
   const list=children.get(c.group)||[];list.push(o);children.set(c.group,list);
  }
 }
 for(const group of new Set([...parents.keys(),...children.keys()])){
  if(!parents.has(group)){errors.push('Repeated outlets lost their original callout review');continue;}
  const [original,parent]=parents.get(group),rows=children.get(group)||[],indices=rows.map(o=>o.repeat_instance.index).sort((a,b)=>a-b);
  if(JSON.stringify(indices)!==JSON.stringify(parent.locators.map((_,i)=>i+1))){errors.push('Repeated callout physical rows are missing or duplicated');continue;}
  for(const o of rows){const c=o.repeat_instance;if(c.locator!==parent.locators[c.index-1]||['source','reference','position'].some(k=>JSON.stringify(o[k])!==JSON.stringify(original[k]))||o.quantity!==1||o.quantity_unresolved!==false||o.repeat_resolution!==undefined)errors.push('Repeated outlet source identity changed; review the callout again');}
 }
 return [...new Set(errors)];
}


let humanSourceReview=null,humanPageReviews=[],humanReviewNote='';
function manualSourceEntry(input,state,records,outlets,forms,tagPattern,paths=[]){
 if(!['incomplete','review_required'].includes(state.status)||state.complete_takeoff!==false)throw Error('Scan the current source files before adding a source-reviewed item.');
 const source=(state.source_checkpoints||[]).find(s=>s.name===input.source),page=Number(input.page);
 if(!source||! /^[a-f0-9]{64}$/.test(source.sha256||'')||!Number.isInteger(page)||page<1||!Number.isInteger(source.pages)||page>source.pages)throw Error('Choose an original source and a page within that document.');
 if(input.confirmed!==true)throw Error('Check the physical item, source page and duplicates before adding it.');
 const text=(value,limit=120)=>{const s=String(value??'').trim().toUpperCase();if(s.length>limit)throw Error('A manual entry exceeds its text limit.');return s;};
 const note=text(input.note,500);if(note.length<10)throw Error('Describe the source evidence in at least 10 characters.');
 const provenance={source:source.name,reference:'page '+page,evidence:'MANUAL SOURCE ENTRY: '+note,
  review_history:[{kind:'manual_source_entry',source:source.name,sha256:source.sha256,page,note}]};
 if(input.kind==='component'){
  if(records.length>=500)throw Error('Equipment review is limited to 500 rows.');
  const parent=text(input.component_of),item={...provenance,tag:parent+' EXHAUST',component_of:parent,component_kind:'integral_exhaust',component_source_sha256:source.sha256,component_note:note,
   template:'Exhaust Fans _Std._.xlsx',status:'UNVERIFIED',candidates:[],proposed:{},flags:['INTEGRAL EXHAUST: linked test form; review its own design values. Parent values are not copied.']};
  const errors=equipmentComponentErrors({records:[...records,item],scan_state:state},false);
  if(records.some(r=>r.tag===item.tag))errors.push('That integral exhaust component already has a review row.');
  if(errors.length)throw Error(errors.join('. '));return {kind:'equipment',item};
 }
 if(input.kind==='equipment'){
  if(records.length>=500)throw Error('Equipment review is limited to 500 rows.');
  const tag=text(input.tag);if(!tagPattern.test(tag))throw Error('Enter a supported equipment ID exactly as shown on the source.');
  if(records.some(r=>String(r.tag).toUpperCase()===tag))throw Error('That equipment ID already has a review row. Edit it or record its physical quantity there.');
  if(!Object.hasOwn(forms,input.template))throw Error('Choose the applicable original equipment form.');
  return {kind:'equipment',item:{...provenance,tag,template:input.template,status:'UNVERIFIED',candidates:[],proposed:{},flags:['MANUAL SOURCE ENTRY: design inputs still need review.']}};
 }
 if(input.kind!=='outlet')throw Error('Choose equipment, an integral exhaust component, or a supply outlet.');
 if(outlets.length>=500)throw Error('Outlet review is limited to 500 rows.');
 const type=text(input.type),system=text(input.system),location=text(input.location),size=text(input.size),locator=text(input.locator);
 const cfm=Number(input.design_cfm);
 if(!type||!location||!locator||String(input.design_cfm??'').trim()===''||!Number.isFinite(cfm)||cfm<=0||cfm>1000000)throw Error('Enter the physical outlet type, room, locator and positive design CFM.');
 const unit=records.find(r=>String(r.tag).toUpperCase()===system&&r.status!=='EXCLUDED');
 const passive=paths.find(p=>p.tag===system&&p.status==='VERIFIED');
 if(!(unit&&!['Exhaust Fans _Sm._.xlsx','Exhaust Fans _Std._.xlsx','Kitchen Hood.xlsx','Chiller - Air Cooled.xlsx','Chiller - Water Cooled.xlsx'].includes(unit.template))&&(!passive||airPathErrors({air_paths:[passive],records,scan_state:state}).length))throw Error('Assign this outlet to supply equipment or a verified passive supply path.');
 let position;
 if(String(input.x??'').trim()!==''||String(input.y??'').trim()!==''){
  position=[input.x,input.y].map(v=>String(v??'').trim()===''?NaN:Number(v));
  if(position.some(v=>!Number.isFinite(v)||v<0||v>100000))throw Error('Enter both valid PDF point coordinates, or leave both blank.');
 }
 if(outlets.some(o=>o.source===source.name&&sourcePageNumber(o.reference)===page&&(
    position&&Array.isArray(o.position)&&Math.hypot(position[0]-o.position[0],position[1]-o.position[1])<1||o.manual_locator===locator)))throw Error('This source position or physical locator already has an outlet row. Review the existing row.');
 return {kind:'outlet',item:{...provenance,type,system,location,size,design_cfm:cfm,include:false,quantity:1,manual_locator:locator,...(position?{position,position_coordinate_space:'displayed_pdf_points'}:{})}};
}
const airPathFields=['tag','kind','status','source','source_sha256','reference','location','note'];
const passivePathTag=/^(?:L|LOUVER|LOUVRE|OA|INTAKE|TRANSFER|PASSIVE)-[A-Z0-9]+(?:[.-][A-Z0-9]+)*$/;
function airPathErrors(payload,requireVerified=true,checkSources=true){
 const paths=payload.air_paths===undefined?[]:payload.air_paths;
 if(!Array.isArray(paths)||paths.length>100)return ['Invalid passive supply paths'];
 const errors=[],seen=new Set(),equipment=new Set((payload.records||[]).map(r=>String(r.tag||'').trim().toUpperCase()));
 for(const path of paths){
  if(!path||typeof path!=='object'||Array.isArray(path)||Object.keys(path).some(k=>!airPathFields.includes(k))){errors.push('Invalid passive supply path fields');continue;}
  if(typeof path.tag!=='string'||path.tag.length>80||!passivePathTag.test(path.tag)){errors.push('Use a passive inlet or transfer ID, such as L-1 or PASSIVE-1');continue;}
  if(seen.has(path.tag)||equipment.has(path.tag))errors.push('Passive path IDs must be unique and separate from equipment IDs');seen.add(path.tag);
  if(path.kind!=='passive_supply'||!['UNVERIFIED','VERIFIED'].includes(path.status))errors.push('Invalid passive supply path kind or status');
  if(requireVerified&&path.status!=='VERIFIED')errors.push('Verify every passive supply path from its source');
  for(const [field,min,max] of [['source',1,160],['reference',1,80],['location',1,120],['note',20,500]])if(typeof path[field]!=='string'||path[field].trim().length<min||path[field].trim().length>max)errors.push('Passive paths need a source page, room / area and 20–500 character supply-path evidence');
  const match=typeof path.reference==='string'&&/^page ([1-9]\d{0,2})$/.exec(path.reference);
  if(typeof path.source_sha256!=='string'||! /^[a-f0-9]{64}$/.test(path.source_sha256)||!match){errors.push('Invalid passive path source identity');continue;}
  if(checkSources){const sources=(payload.scan_state?.source_checkpoints||[]).filter(s=>s.name===path.source&&s.sha256===path.source_sha256);
   if(sources.length!==1||!Number.isInteger(sources[0].pages)||Number(match[1])>sources[0].pages)errors.push('Passive path source changed or is missing; check and add it again from the current source');}
 }
 return [...new Set(errors)];
}
function makePassivePath(input,state,records,paths){
 const source=(state.source_checkpoints||[]).find(s=>s.name===input.source);
 if(!['incomplete','review_required'].includes(state.status)||state.complete_takeoff!==false||!source)throw Error('Scan the current source files before adding a passive path.');
 if(input.confirmed!==true)throw Error('Confirm this is a passive supply connection, not powered equipment or a return/exhaust outlet.');
 const path={tag:String(input.tag||'').trim().toUpperCase(),kind:'passive_supply',status:'UNVERIFIED',source:source.name,source_sha256:source.sha256,
  reference:'page '+Number(input.page),location:String(input.location||'').trim().toUpperCase(),note:String(input.note||'').trim().toUpperCase()};
 const errors=airPathErrors({air_paths:[...paths,path],records,scan_state:state},false);
 if(errors.length)throw Error(errors.join('. '));return path;
}
function reconcileAirPaths(paths,affectedSources){
 const affected=new Set(Array.isArray(affectedSources)?affectedSources:[affectedSources]);
 return paths.map(p=>affected.has(p.source)?{...p,status:'UNVERIFIED'}:{...p});
}
function sourcePageNumber(reference){return Number(/\bpage (\d+)\b/i.exec(reference||'')?.[1]||0);}
function sourceInventorySnapshot(payload){
 const recordKeys=['tag','status','template','coil_template','source','reference','instance_locations',...reviewNumericFields,'heater_kw',...reviewTextFields,...componentFields];
 const outletKeys=['include','type','size','system','location','design_cfm','source','reference','position','quantity','quantity_unresolved','quantity_candidates','exclusion_note','repeat_resolution','repeat_instance','manual_locator'];
 const project=(rows,keys)=>rows.map(r=>Object.fromEntries(keys.filter(k=>Object.hasOwn(r,k)).map(k=>[k,r[k]])));
 const snapshot={project:payload.project||'',location:payload.location||'',templates:payload.templates||[],standard:payload.standard||'Commercial',records:project(payload.records||[],recordKeys),diffusers:project(payload.diffusers||[],outletKeys),image_decisions:(payload.image_review||[]).map(r=>({accepted:r.accepted??false,excluded:r.excluded??false,exclusion_note:r.exclusion_note||'',tag:r.tag||'',source:r.source||'',page:r.page??null,position:r.position??null}))};
 if(payload.air_paths?.length)snapshot.air_paths=project(payload.air_paths,airPathFields);
 if(payload.exhaust_outlets?.length)snapshot.exhaust_outlets=project(payload.exhaust_outlets,exhaustFields);
 return snapshot;
}
function sourceReviewErrors(payload){
 const state=payload.scan_state||{},review=payload.source_review;
 if(!review||typeof review!=='object')return ['Human source review has not been approved'];
 for(const key of ['records','diffusers','image_review','exhaust_outlets'])if(payload[key]!==undefined&&(!Array.isArray(payload[key])||payload[key].some(r=>!r||typeof r!=='object'||Array.isArray(r))))return ['Invalid source inventory'];
 if(payload.air_paths!==undefined&&(!Array.isArray(payload.air_paths)||payload.air_paths.some(p=>!p||typeof p!=='object'||Array.isArray(p))))return ['Invalid passive supply paths'];
 const errors=[...airPathErrors(payload),...equipmentComponentErrors(payload),...exhaustOutletErrors(payload)];
 if(review.version!==1||review.approved!==true)errors.push('Human source review has not been approved');
 if(!['incomplete','review_required'].includes(state.status)||state.complete_takeoff!==false)errors.push('Sources are unscanned, outdated or unknown');
 if(JSON.stringify(review.scan_state)!==JSON.stringify(state))errors.push('Source scan changed after human review');
 if(JSON.stringify(review.inventory)!==JSON.stringify(sourceInventorySnapshot(payload)))errors.push('Design inventory changed after human review');
 if(typeof review.note!=='string'||review.note.trim().length<20||review.note.trim().length>1000)errors.push('Record the review basis and deliberate blanks (20–1000 characters)');
 const checkpoints=state.source_checkpoints||[],pages=review.pages;
 if(!checkpoints.length||!Array.isArray(pages)||pages.length>30000)return [...errors,'Source pages have not been accounted for'];
 const expected=new Set(),actual=new Set();
 for(const source of checkpoints){
  if(!Number.isInteger(source.pages)||source.pages<1||source.pages>300||! /^[a-f0-9]{64}$/.test(source.sha256||'')){errors.push('Re-upload sources with page counts and content identities');continue;}
  for(let page=1;page<=source.pages;page++)expected.add(JSON.stringify([source.name,source.sha256,page]));
 }
 for(const page of pages){
  if(!page||typeof page.source!=='string'||typeof page.sha256!=='string'||!Number.isInteger(page.page)){errors.push('Invalid human page review');continue;}
  const key=JSON.stringify([page.source,page.sha256,page.page]);if(actual.has(key))errors.push('Duplicate human page review');actual.add(key);
  if(!['reviewed','not_applicable'].includes(page.disposition)||typeof page.note!=='string'||page.note.trim().length<10||page.note.trim().length>500)errors.push('Every page needs a reviewed / not applicable disposition and source note');
 }
 if(actual.size!==expected.size||[...actual].some(k=>!expected.has(k)))errors.push('Every uploaded page must be accounted for against its source hash');
 if((payload.records||[]).some(r=>!['VERIFIED','EXCLUDED'].includes(r.status)))errors.push('Resolve every equipment review row');
 errors.push(...outletInstanceErrors(payload.diffusers||[]));
 if((payload.image_review||[]).some(c=>c.accepted!==true&&!(c.excluded===true&&typeof c.exclusion_note==='string'&&c.exclusion_note.trim().length>=10&&c.exclusion_note.trim().length<=500)))errors.push('Resolve every image candidate: add it or exclude it with a reason');
 if(!(payload.records||[]).some(r=>r.status==='VERIFIED')&&!(payload.diffusers||[]).some(o=>o.include===true))errors.push('The reviewed inventory is empty');
 if((payload.diffusers||[]).some(o=>o.include===true)&&!(payload.templates||[]).includes('Supply Diffusers.xlsx'))errors.push('Include the Supply Diffusers worksheet for the included outlets');
 const supplyUnits=new Set((payload.records||[]).filter(r=>r.status==='VERIFIED'&&!['Exhaust Fans _Sm._.xlsx','Exhaust Fans _Std._.xlsx','Kitchen Hood.xlsx','Chiller - Air Cooled.xlsx','Chiller - Water Cooled.xlsx'].includes(r.template)).map(r=>String(r.tag||'').trim().toUpperCase()));
 for(const path of payload.air_paths||[])if(path.status==='VERIFIED'&&path.kind==='passive_supply')supplyUnits.add(path.tag);
 for(const outlet of payload.diffusers||[]){if(outlet.include!==true){if(typeof outlet.exclusion_note!=='string'||outlet.exclusion_note.trim().length<10||outlet.exclusion_note.trim().length>500)errors.push('Every unchecked outlet needs a source-based exclusion reason; unchecked is not reviewed');continue;}
  if(!supplyUnits.has(String(outlet.system||'').trim().toUpperCase()))errors.push('Every included supply outlet must belong to verified supply equipment or a source-reviewed passive supply path');
  if(outlet.quantity_unresolved||outlet.quantity!==undefined&&outlet.quantity!==1)errors.push('Resolve repeated outlet quantities into physical rows before approval');
  if(['source','reference','type','system','location','design_cfm'].some(k=>outlet[k]===undefined||outlet[k]===null||outlet[k]===''))errors.push('Included outlets need source, type, system, location and design CFM; document deliberate neck-size blanks in the review basis');
 }
 return [...new Set(errors)];
}
function sourceReviewApproved(payload){return sourceReviewErrors(payload).length===0;}
function makeSourceReview(payload,pages,note){
 const review=JSON.parse(JSON.stringify({version:1,approved:true,scan_state:payload.scan_state,inventory:sourceInventorySnapshot(payload),pages,note}));
 const errors=sourceReviewErrors({...payload,source_review:review});if(errors.length)throw Error(errors.join('. '));return review;
}
