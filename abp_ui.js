const reviewNumericFields=['design_cfm','osa_cfm','osa_min_cfm','esp','total_sp','motor_hp','motor_volts','motor_fla','design_gpm','cooling_edb','cooling_ewb','cooling_ldb','cooling_lwb','heating_cfm','heating_edb','heating_ldb','heating_input_btu','heating_output_btu','cooling_total_btu','cooling_sensible_btu','electric_heating_edb','electric_heating_ldb','heater_volts','heater_phase','heater_amps','heater_stages','heating_ewt','heating_lwt','water_dp_ft'];
const reviewEvidenceFields=['selected_cfm','heater_kw'];
const reviewTextFields=['manufacturer','model','unit_type','service','equipment_location','area_served','heating_type'];
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
function fieldLabel(key){return ({exhaust_cfm:'Hood exhaust CFM',supply_cfm:'Hood supply CFM (evidence only)',makeup_air_cfm:'Hood makeup CFM (evidence only)',heater_volts:'Heater design volts',heater_phase:'Heater phases (1 or 3)',heater_amps:'Heater design amps',heater_stages:'Heater stages',heating_type:'Heating type: ELECTRIC, GAS, or HOT WATER',heating_ewt:'Heating entering water temperature',heating_lwt:'Heating leaving water temperature',water_dp_ft:'Water pressure drop (ft)',cooling_edb:'Cooling entering dry bulb °F',cooling_ewb:'Cooling entering wet bulb °F',cooling_ldb:'Cooling leaving dry bulb °F',cooling_lwb:'Cooling leaving wet bulb °F',heating_edb:'Heating entering dry bulb °F',heating_ldb:'Heating leaving dry bulb °F',heating_cfm:'Heating CFM',heating_input_btu:'Heating input BTU/h',heating_output_btu:'Heating output BTU/h'})[key]||key.replaceAll('_',' ');}
function reviewCoverage(records, outlets) {
  const populated=records.filter(r=>r.status==='VERIFIED'&&r.template).length;
  const unresolved=records.filter(r=>r.status!=='VERIFIED'&&r.status!=='EXCLUDED').length;
  const included=outlets.filter(d=>d.include!==false).length;
  return `${populated} equipment entries ready; ${unresolved} unresolved. ${included} of ${outlets.length} outlet candidates included. Check source revisions and unresolved entries before field use.`;
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
  if(!object(data)||data.format!=='ABP-PREFIELD-REVIEW'||data.version!==1||typeof data.project!=='string'||data.project.length>180||typeof data.location!=='string'||data.location.length>180||!['Commercial','USACE'].includes(data.standard)||!Array.isArray(data.records)||data.records.length>500||!Array.isArray(data.templates)||data.templates.some(t=>typeof t!=='string'||!templates.includes(t))||new Set(data.templates).size!==data.templates.length) invalid();
  const tags=new Set();
  for(const r of data.records) {
    if(!object(r)||typeof r.tag!=='string'||!tagPattern.test(r.tag)||tags.has(r.tag.toUpperCase())||!['UNVERIFIED','VERIFIED','EXCLUDED'].includes(r.status)) invalid();
    tags.add(r.tag.toUpperCase());
    if(r.template!==undefined&&(typeof r.template!=='string'||r.template!==''&&!Object.hasOwn(forms,r.template))) invalid();
    if(r.coil_template!==undefined&&!['','Coil DX GAS HT.xlsx','COIL DX HP ELE.xlsx','Coil WTR CLG WTR HT.xlsx'].includes(r.coil_template)) invalid();
    for(const field of fields) if(r[field]!==undefined&&r[field]!==null&&r[field]!==''&&!numeric(r[field])) invalid();
    if(r.design_cfm!=null&&r.design_cfm!==''&&r.osa_cfm!=null&&r.osa_cfm!==''&&Number(r.osa_cfm)>Number(r.design_cfm)) invalid();
    for(const key of reviewTextFields) if(r[key]!==undefined&&(typeof r[key]!=='string'||r[key].length>120)) invalid();
    if(r.heater_phase!=null&&r.heater_phase!==''&&![1,3].includes(Number(r.heater_phase))) invalid();
    if(r.heater_stages!=null&&r.heater_stages!==''&&(!Number.isInteger(Number(r.heater_stages))||Number(r.heater_stages)<1)) invalid();
    if(r.heating_type!=null&&r.heating_type!==''&&!['ELECTRIC','GAS','HOT WATER'].includes(r.heating_type.trim().toUpperCase())) invalid();
    if(r.osa_min_cfm!=null&&r.osa_min_cfm!==''&&(r.osa_cfm==null||r.osa_cfm===''||Number(r.osa_min_cfm)>Number(r.osa_cfm))) invalid();
    for(const key of ['source','reference','evidence']) if(r[key]!==undefined&&typeof r[key]!=='string') invalid();
    if(r.occurrences!==undefined&&(!Array.isArray(r.occurrences)||r.occurrences.length>30||r.occurrences.some(o=>!object(o)||['source','reference','evidence'].some(k=>o[k]!==undefined&&typeof o[k]!=='string')))) invalid();
    if(r.candidates!==undefined&&(!Array.isArray(r.candidates)||r.candidates.length>30||r.candidates.some(c=>!object(c)||!object(c.values)||Object.entries(c.values).some(([k,v])=>reviewTextFields.includes(k)?typeof v!=='string'||v.length>120:(!fields.includes(k)&&!reviewEvidenceFields.includes(k))||!numeric(v))||['source','reference','evidence'].some(k=>c[k]!==undefined&&typeof c[k]!=='string')))) invalid();
  }
  if(data.diffusers!==undefined&&(!Array.isArray(data.diffusers)||data.diffusers.length>500||data.diffusers.some(d=>!object(d)||(d.design_cfm!==undefined&&d.design_cfm!==null&&d.design_cfm!==''&&!numeric(d.design_cfm))))) invalid();
  if(data.image_coverage_truncated!==undefined&&typeof data.image_coverage_truncated!=='boolean')invalid();
  if(data.image_coverage!==undefined&&(!Array.isArray(data.image_coverage)||data.image_coverage.length>1000||data.image_coverage.some(p=>!object(p)||typeof p.source!=='string'||p.source.length>160||!Number.isInteger(p.page)||p.page<1||p.page>300||typeof (p.status||p.ocr_status)!=='string'||(p.status||p.ocr_status).length>100||p.regions_omitted!==undefined&&(!Number.isInteger(p.regions_omitted)||p.regions_omitted<0||p.regions_omitted>100000)||['image_regions_truncated','selection_truncated'].some(k=>p[k]!==undefined&&typeof p[k]!=='boolean')||p.selection_failed!==undefined&&(typeof p.selection_failed!=='string'||p.selection_failed.length>100)||p.unexamined_content!==undefined&&(typeof p.unexamined_content!=='string'||p.unexamined_content.length>1000)||p.regions!==undefined&&(!Array.isArray(p.regions)||p.regions.length>100||p.regions.some(r=>!object(r)||typeof r.status!=='string'||r.status.length>100||r.box!==undefined&&(!Array.isArray(r.box)||r.box.length!==4||r.box.some(x=>typeof x!=='number'||!Number.isFinite(x)||Math.abs(x)>100000))||r.reason!==undefined&&(typeof r.reason!=='string'||r.reason.length>1000)||r.method!==undefined&&(typeof r.method!=='string'||r.method.length>100)||r.pixels!==undefined&&(!Number.isInteger(r.pixels)||r.pixels<0||r.pixels>100000000))))))invalid();
  if(data.image_review!==undefined&&(!Array.isArray(data.image_review)||data.image_review.length>500||data.image_review.some(c=>!object(c)||!['kitchen_hood','diffuser'].includes(c.kind)||typeof c.tag!=='string'||c.tag.length>80||typeof c.source!=='string'||c.source.length>160||!Number.isInteger(c.page)||c.page<1||c.page>300||!object(c.review_values)||Object.entries(c.review_values).some(([k,v])=>!['exhaust_cfm','supply_cfm','makeup_air_cfm','design_cfm'].includes(k)||!numeric(v))||c.evidence_text!==undefined&&(typeof c.evidence_text!=='string'||c.evidence_text.length>4000)||c.review_reasons!==undefined&&(!Array.isArray(c.review_reasons)||c.review_reasons.length>20||c.review_reasons.some(x=>typeof x!=='string'||x.length>1000))||['type','size'].some(k=>c[k]!==undefined&&(typeof c[k]!=='string'||c[k].length>120))||c.accepted!==undefined&&typeof c.accepted!=='boolean')))invalid();
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
