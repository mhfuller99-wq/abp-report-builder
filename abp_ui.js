const reviewNumericFields=['design_cfm','osa_cfm','osa_min_cfm','esp','total_sp','motor_hp','motor_volts','motor_fla','design_gpm','cooling_edb','cooling_ewb','cooling_ldb','cooling_lwb','heating_cfm','heating_edb','heating_ldb','heating_input_btu','heating_output_btu','cooling_total_btu','cooling_sensible_btu'];
const reviewTextFields=['manufacturer','model','unit_type','service','equipment_location','area_served'];
function fieldLabel(key){return ({cooling_edb:'Cooling entering dry bulb °F',cooling_ewb:'Cooling entering wet bulb °F',cooling_ldb:'Cooling leaving dry bulb °F',cooling_lwb:'Cooling leaving wet bulb °F',heating_edb:'Heating entering dry bulb °F',heating_ldb:'Heating leaving dry bulb °F',heating_cfm:'Heating CFM',heating_input_btu:'Heating input BTU/h',heating_output_btu:'Heating output BTU/h'})[key]||key.replaceAll('_',' ');}
// Shared browser helpers. Keep saved reviews validated before replacing UI state.
function worksheetLabel(name) {
  return name.replace(/(?:\.xlsx)+$/i,'').replaceAll('_',' ').replace(/\s+/g,' ').trim();
}
async function readApiJson(response) {
  if(response.status===401) throw Error('Your session has expired. Save your review, then sign in again.');
  let data;
  try { data=await response.json(); }
  catch { throw Error('The server did not return a valid response. Please try again.'); }
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
    for(const field of fields) if(r[field]!==undefined&&r[field]!==null&&r[field]!==''&&!numeric(r[field])) invalid();
    if(r.design_cfm!=null&&r.design_cfm!==''&&r.osa_cfm!=null&&r.osa_cfm!==''&&Number(r.osa_cfm)>Number(r.design_cfm)) invalid();
    for(const key of reviewTextFields) if(r[key]!==undefined&&(typeof r[key]!=='string'||r[key].length>120)) invalid();
    if(r.osa_min_cfm!=null&&r.osa_min_cfm!==''&&(r.osa_cfm==null||r.osa_cfm===''||Number(r.osa_min_cfm)>Number(r.osa_cfm))) invalid();
    for(const key of ['source','reference','evidence']) if(r[key]!==undefined&&typeof r[key]!=='string') invalid();
    if(r.occurrences!==undefined&&(!Array.isArray(r.occurrences)||r.occurrences.length>30||r.occurrences.some(o=>!object(o)||['source','reference','evidence'].some(k=>o[k]!==undefined&&typeof o[k]!=='string')))) invalid();
    if(r.candidates!==undefined&&(!Array.isArray(r.candidates)||r.candidates.length>30||r.candidates.some(c=>!object(c)||!object(c.values)||Object.entries(c.values).some(([k,v])=>reviewTextFields.includes(k)?typeof v!=='string'||v.length>120:!fields.includes(k)||!numeric(v))||['source','reference','evidence'].some(k=>c[k]!==undefined&&typeof c[k]!=='string')))) invalid();
  }
  if(data.diffusers!==undefined&&(!Array.isArray(data.diffusers)||data.diffusers.length>500||data.diffusers.some(d=>!object(d)||(d.design_cfm!==undefined&&d.design_cfm!==null&&d.design_cfm!==''&&!numeric(d.design_cfm))))) invalid();
  return {...data,records:data.records.map(r=>({...r,tag:r.tag.toUpperCase()}))};
}
