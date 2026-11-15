// Job recovery, source review, and local-only office comparisons.
let workflowJob=null,scanJobId=null,sourceManifest=[],officeComparison=null,workflowBusy=false,workflowSourceRevision=0,completedBuild=null;
const workflowOriginalOutlets=renderOutlets,workflowOriginalReview=renderReview;
const workflowOriginalImageReview=renderImageReview;
const workflowOriginalPayload=projectPayload;
const workflowId=sessionStorage.getItem('abp-workspace-id')||crypto.randomUUID();
sessionStorage.setItem('abp-workspace-id',workflowId);
const workflowDraftKey='abp-review-v2:'+workflowId;
function workflowElement(tag,text){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;}
function workflowButton(text,action){const b=workflowElement('button',text);b.type='button';b.onclick=action;return b;}
function workflowSaved(){
 const review={format:'ABP-PREFIELD-REVIEW',version:1,...workflowOriginalPayload()};delete review.scan_acknowledgement;
 return {review,active_job:workflowJob,scan_job_id:scanJobId,source_manifest:sourceManifest,source_revision:workflowSourceRevision,completed_build:completedBuild,saved_at:Date.now()};
}
function workflowSave(){
 if(!templatesReady||$('buildmethod').value==='reference')return;
 try{
  const saved=workflowSaved(),text=serializeSavedReview(saved);
  localStorage.setItem(workflowDraftKey,text);sessionStorage.setItem('abp-active-workspace',workflowDraftKey);
  $('autosave-status').textContent='Review saved on this device · '+new Date(saved.saved_at).toLocaleTimeString()+'. Source files stay temporarily on the server for up to two hours.';
 }catch(e){$('autosave-status').textContent='Automatic save unavailable: '+e.message+' Use Save project review to keep a copy.';}
}
let workflowSaveTimer;
function workflowChanged(event){if(event?.target?.closest('#readiness,#office-comparison-panel'))return;clearTimeout(workflowSaveTimer);workflowSaveTimer=setTimeout(()=>{workflowSave();renderReadiness();renderOutletTotals();renderComparison();},450);}
function sourceIndex(name){return sourceManifest.findIndex(s=>s.name===name);}
function sourcePage(reference){return Number(/\bpage (\d+)\b/i.exec(reference||'')?.[1]||1);}
let sourcePreviewRevision=0,sourcePreviewController=null,sourcePreviewObjectUrl=null;
function clearSourcePreview(){
 sourcePreviewRevision++;sourcePreviewController?.abort();sourcePreviewController=null;
 const image=$('source-preview');image.onload=null;image.onerror=null;image.removeAttribute('src');
 if(sourcePreviewObjectUrl){URL.revokeObjectURL(sourcePreviewObjectUrl);sourcePreviewObjectUrl=null;}
 $('source-preview-large').removeAttribute('href');$('source-preview-large').hidden=true;
 $('source-preview-retry').hidden=true;
}
async function viewSource(name,page=1,position){
 clearSourcePreview();const revision=sourcePreviewRevision;
 const index=sourceIndex(name),panel=$('source-viewer');panel.hidden=false;
 $('source-view-title').textContent=name+' · page '+page+(position?' · callout near ['+position.map(n=>Math.round(n)).join(', ')+'] PDF points':'');
 $('source-preview').alt='Source drawing preview for '+name+', page '+page;
 $('source-preview-status').textContent='Loading source page…';
 $('source-review-layout').classList.add('viewing');
 panel.scrollIntoView({block:'nearest'});
 const recovery='Reattach the original files, then use Recover sources and keep reviewed values under Source coverage. The saved design review is still available.';
 if(!scanJobId||index<0){$('source-preview-status').textContent=recovery;return;}
 const controller=new AbortController();sourcePreviewController=controller;
 const retry=$('source-preview-retry');retry.onclick=()=>viewSource(name,page,position);
 try{
  const response=await fetch('/api/jobs/'+scanJobId+'/preview?source='+index+'&page='+page,{signal:controller.signal});
  if(revision!==sourcePreviewRevision)return;
  if(response.status===401||response.redirected)throw new Error('Sign in again to view this source page. Your saved design review is retained.');
  if(!response.ok){
   const detail=await response.json().catch(()=>({}));
   if(response.status===503&&detail.reason==='processing_busy')throw new Error('Document processing is running. Retry this preview when it finishes. Your source files and reviewed values are still available.');
   if(response.status===404)throw new Error('Source files expired or the server restarted. '+recovery);
   throw new Error(detail.error||'The source preview could not be loaded. Retry the preview or open the original locally.');
  }
  if(!(response.headers.get('content-type')||'').startsWith('image/png'))throw new Error('The source preview could not be loaded. Retry the preview or sign in again.');
  const blob=await response.blob();if(revision!==sourcePreviewRevision)return;
  sourcePreviewObjectUrl=URL.createObjectURL(blob);
  const image=$('source-preview');
  image.onload=()=>{if(revision===sourcePreviewRevision)$('source-preview-status').textContent='Check the full drawing, revision, duct connection and room. Coordinates identify the extracted callout; they do not prove supply service.';};
  image.onerror=()=>{if(revision===sourcePreviewRevision){$('source-preview-status').textContent='The preview image could not be displayed. Retry the preview or open the original locally.';retry.hidden=false;}};
  image.src=sourcePreviewObjectUrl;$('source-preview-large').href=sourcePreviewObjectUrl;$('source-preview-large').hidden=false;
 }catch(e){if(revision===sourcePreviewRevision&&e.name!=='AbortError'){$('source-preview-status').textContent=e.message||'Connection interrupted. Retry the source preview.';retry.hidden=false;}}
 finally{if(revision===sourcePreviewRevision)sourcePreviewController=null;}
}
function renderOutletTotals(){
 const box=$('outlet-totals');if(!box)return;box.replaceChildren();
 const systems=new Map(),positions=new Map();let duplicates=0;
 for(const [i,o] of diffusers.entries()){
  if(o.include===false)continue;
  const system=String(o.system||'Unassigned').trim().toUpperCase();
  const item=systems.get(system)||{count:0,total:0};item.count++;item.total+=Number(o.design_cfm||0);systems.set(system,item);
  if(o.position?.length===2){const k=JSON.stringify([o.source,o.reference,o.position.map(n=>Math.round(n*10)/10),o.repeat_instance?.index??null]);if(positions.has(k))duplicates++;positions.set(k,i);}
 }
 for(const [system,s] of [...systems].sort((a,b)=>a[0].localeCompare(b[0]))){
  const record=records.find(r=>r.tag===system),target=record?.design_cfm;
  box.append(workflowElement('p',system+': '+s.count+' included outlets · '+s.total.toLocaleString()+' design CFM'+(target!=null&&target!==''?' · unit target '+target+' CFM · difference '+(s.total-Number(target))+' CFM':' · unit target unverified/not supplied')));
 }
 if(duplicates)box.append(workflowElement('p','Review '+duplicates+' repeated source positions before building. Repeated flow values alone are not treated as duplicates.'));
 if(new Set(diffusers.map(o=>o.source).filter(Boolean)).size>1)box.append(workflowElement('p','Multiple source documents contain outlet candidates. Review revisions and duplicates; no drawing is silently superseded.'));
}
let outletBatchUndo=null,outletRepeatUndo=null;
renderOutlets=function(){
 workflowOriginalOutlets();const box=$('outlets');if(!diffusers.length)return;
 const totals=workflowElement('div');totals.id='outlet-totals';box.insertBefore(totals,box.children[2]);
 const table=box.querySelector('table'),rows=[...table.querySelectorAll('tr')].slice(1);
 const batch=workflowElement('fieldset'),legend=workflowElement('legend','Assign reviewed fields to selected outlets');batch.append(legend);
 batch.append(workflowElement('p','Select the individual physical outlets below. Assign only fields supported by the original source; blank batch fields leave existing values unchanged.'));
 const inputs={};for(const key of ['system','location','size']){const label=workflowElement('label',({system:'Serving equipment',location:'Room / area',size:'Neck size (not face or branch size)'})[key]),input=document.createElement('input');input.maxLength=120;input.setAttribute('aria-label','Batch '+key);label.append(input);inputs[key]=input;batch.append(label);}
 const evidenceLabel=workflowElement('label','Source evidence for this assignment'),evidenceInput=document.createElement('input');evidenceInput.maxLength=500;evidenceInput.setAttribute('aria-label','Batch source evidence');evidenceLabel.append(evidenceInput);batch.append(evidenceLabel);
 const message=workflowElement('p');message.setAttribute('role','status');
 batch.append(workflowButton('Apply to selected outlets',()=>{try{const indices=Array.from(table.querySelectorAll('[data-batch-outlet]')).filter(x=>x.checked).map(x=>Number(x.dataset.batchOutlet));const result=assignOutletBatch(diffusers,indices,Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value])),evidenceInput.value);diffusers=result.outlets;outletBatchUndo=result.action;renderOutlets();workflowChanged();}catch(e){message.textContent=e.message;}}));
 const undo=workflowButton('Undo last assignment',()=>{try{diffusers=undoOutletBatch(diffusers,outletBatchUndo);outletBatchUndo=null;renderOutlets();workflowChanged();}catch(e){message.textContent=e.message;}});undo.disabled=!outletBatchUndo;batch.append(undo,message);table.parentElement.insertBefore(batch,table);
 table.querySelector('tr').prepend(workflowElement('th','Batch'));
 rows.forEach((row,index)=>{
  const o=diffusers[index],cell=workflowElement('td'),check=document.createElement('input');check.type='checkbox';check.dataset.batchOutlet=index;check.setAttribute('aria-label','Select outlet '+(index+1)+' for batch assignment');cell.append(check);row.prepend(cell);
  const inclusion=row.querySelector('input[aria-label="Include outlet '+(index+1)+' in supply sheet"]');
  if(o.repeat_resolution||o.quantity_unresolved||o.quantity>1){inclusion.disabled=true;inclusion.title='Resolve the repeated annotation and include its individual physical rows.';}
  const exclusion=workflowElement('label','Reason this outlet is excluded'),reason=document.createElement('input');
  reason.maxLength=500;reason.value=o.exclusion_note||'';reason.setAttribute('aria-label','Outlet '+(index+1)+' exclusion reason');
  reason.oninput=()=>{o.exclusion_note=reason.value;workflowChanged();};exclusion.append(reason);exclusion.hidden=o.include!==false;row.lastElementChild.append(exclusion);
  inclusion.addEventListener('change',()=>{exclusion.hidden=inclusion.checked;if(inclusion.checked){const sheet=[...document.querySelectorAll('.template input')].find(x=>x.value==='Supply Diffusers.xlsx');if(sheet)sheet.checked=true;updateWorkspace();}});
  row.lastElementChild.append(document.createElement('br'),workflowButton('View outlet '+(index+1)+' source',()=>viewSource(o.source,sourcePage(o.reference),o.position)));
  if(o.repeat_instance)row.lastElementChild.append(workflowElement('p','Physical outlet '+o.repeat_instance.index+': '+o.repeat_instance.locator+' — human-reviewed repeated callout.'));
  if((o.quantity_unresolved||o.quantity>1)&&!o.repeat_resolution){
   const details=workflowElement('details'),summary=workflowElement('summary','Resolve repeated outlet '+(index+1)+' ('+(o.quantity||'unknown')+' physical locations)');details.append(summary);
   details.append(workflowElement('p','Identify every physical outlet from the original drawing. Enter one distinct room and position per line. The original annotation remains in the review log; new physical rows start unchecked.'));
   const countLabel=workflowElement('label','Reviewed physical count'),count=document.createElement('input');count.type='number';count.min=2;count.max=100;count.step=1;count.value=o.quantity||'';count.setAttribute('aria-label','Outlet '+(index+1)+' reviewed repeated count');countLabel.append(count);details.append(countLabel);
   if(o.quantity_candidates?.length)details.append(workflowElement('p','Conflicting source readings: '+o.quantity_candidates.join(', ')+'. Confirm the count from the original drawing.'));
   const locLabel=workflowElement('label','Physical locators'),locators=document.createElement('textarea');locators.maxLength=12100;locators.setAttribute('aria-label','Outlet '+(index+1)+' repeated physical locators');locLabel.append(locators);
   const evidenceLabel=workflowElement('label','Source basis for the count and airflow'),evidence=document.createElement('input');evidence.maxLength=500;evidence.setAttribute('aria-label','Outlet '+(index+1)+' repetition evidence');evidenceLabel.append(evidence);
   const confirmLabel=workflowElement('label',' I checked each physical location and confirmed this airflow applies to each outlet, not the combined group.'),confirm=document.createElement('input');confirm.type='checkbox';confirm.setAttribute('aria-label','Confirm outlet '+(index+1)+' repeated count and per-outlet airflow');confirmLabel.prepend(confirm);
   const status=workflowElement('p');status.setAttribute('role','status');
   details.append(locLabel,evidenceLabel,confirmLabel,workflowButton('Create physical rows for outlet '+(index+1),()=>{try{const result=resolveRepeatedOutlet(diffusers,index,locators.value.split('\n'),evidence.value,confirm.checked,Number(count.value));diffusers=result.outlets;outletRepeatUndo=result.action;outletBatchUndo=null;humanSourceReview=null;renderOutlets();workflowChanged();}catch(e){status.textContent=e.message;}}),status);row.lastElementChild.append(details);
  }
  if(o.repeat_resolution)row.lastElementChild.append(workflowElement('p','Aggregate annotation resolved into '+o.repeat_resolution.locators.length+' physical rows. Source basis: '+o.repeat_resolution.note));
  if(o.review_notice)row.lastElementChild.append(workflowElement('p',o.review_notice));
  if(o.latest_observation)row.lastElementChild.append(workflowElement('p','Latest source observation: '+Object.entries(o.latest_observation).map(([k,v])=>k+': '+(v??'UNREAD')).join(' · ')));
 });
 // Display by serving system without changing original candidate indices.
 // Stable dataset mapping avoids interpreting identical CFM values as one outlet.
 const originalRows=[...table.querySelectorAll('tr')].slice(1);originalRows.forEach((row,i)=>row.dataset.outletIndex=i);
 originalRows.sort((a,b)=>String(diffusers[+a.dataset.outletIndex].system||'').localeCompare(String(diffusers[+b.dataset.outletIndex].system||''))||Number(a.dataset.outletIndex)-Number(b.dataset.outletIndex));
 for(const row of originalRows)table.append(row);
 if(outletRepeatUndo){const status=workflowElement('p');status.setAttribute('role','status');box.append(workflowButton('Undo last repeated-callout resolution',()=>{try{diffusers=undoRepeatedOutlet(diffusers,outletRepeatUndo);outletRepeatUndo=null;humanSourceReview=null;renderOutlets();workflowChanged();}catch(e){status.textContent=e.message;}}),status);}
 renderOutletTotals();
};
renderReview=function(){
 const expanded=[...$('review').querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent);
 workflowOriginalReview();
 if(records.length){
  const details=workflowElement('details'),summary=workflowElement('summary','Physical unit locations for shared equipment tags');details.append(summary);
  details.append(workflowElement('p','Review Physical quantity in the submittal details above. If one printed tag represents multiple units, enter one distinct room or location per line. Each unit gets its own space on the applicable equipment tab; the printed tag stays unchanged.'));
  records.forEach((r,i)=>{
   const label=workflowElement('label',r.tag+' physical locations'),input=document.createElement('textarea');
   input.value=(r.instance_locations||[]).join('\n');input.maxLength=12100;input.setAttribute('aria-label',r.tag+' physical locations');
   input.oninput=()=>{r.instance_locations=input.value.split('\n').map(x=>x.trim()).filter(Boolean);r.status='UNVERIFIED';const status=document.querySelector('[data-status="'+i+'"]');if(status)status.value='UNVERIFIED';workflowChanged();};
   label.append(input);details.append(label);
  });$('review').append(details);
 }
 for(const detail of $('review').querySelectorAll('details'))if(expanded.includes(detail.querySelector('summary')?.textContent))detail.open=true;
 renderReadiness();
};
renderImageReview=function(){workflowOriginalImageReview();$('image-review').querySelectorAll('fieldset').forEach((panel,index)=>{
 const c=imageReview[index];if(!c)return;
 panel.append(workflowButton('View image candidate '+(index+1)+' source',()=>viewSource(c.source,c.page,c.position)));
 if(c.accepted)return;
 if(c.excluded){panel.append(workflowElement('p','Excluded after source review: '+c.exclusion_note),workflowButton('Reopen candidate',()=>{c.excluded=false;c.exclusion_note='';renderImageReview();workflowChanged();}));return;}
 const label=workflowElement('label','Reason to exclude this candidate'),input=document.createElement('input');input.maxLength=500;input.setAttribute('aria-label','Candidate '+(index+1)+' exclusion reason');label.append(input);panel.append(label);
 const status=workflowElement('p');status.setAttribute('role','status');panel.append(workflowButton('Exclude with source reason',()=>{if(input.value.trim().length<10){status.textContent='Enter a source-based reason of at least 10 characters.';return;}c.excluded=true;c.exclusion_note=input.value.trim();renderImageReview();workflowChanged();}),status);
 });};
function renderHumanReview(box,wasOpen){
 const panel=workflowElement('details');panel.id='human-source-review';panel.open=wasOpen;panel.append(workflowElement('summary','Complete human source review'));
 panel.append(workflowElement('p','Account for every source page, resolve equipment and image candidates, and review the final design inventory. This does not mark automatic scanning complete or certify field measurements.'));
 const message=workflowElement('p');message.setAttribute('role','status');
 for(const source of scanState.source_checkpoints){
  const row=workflowElement('fieldset');row.append(workflowElement('legend',source.name));
  const reviewed=humanPageReviews.filter(p=>p.source===source.name&&p.sha256===source.sha256);row.append(workflowElement('p',reviewed.length+' of '+(source.pages||'UNKNOWN')+' pages accounted for'));
  const range=workflowElement('input');range.placeholder='1, 3-5';range.setAttribute('aria-label',source.name+' reviewed pages');const label=workflowElement('label','Reviewed page numbers');label.append(range);row.append(label);
  const disposition=workflowElement('select');disposition.setAttribute('aria-label',source.name+' page disposition');for(const [value,text] of [['reviewed','Relevant design content reviewed'],['not_applicable','No applicable TAB design data']]){const option=workflowElement('option',text);option.value=value;disposition.append(option);}row.append(disposition);
  const note=workflowElement('input');note.maxLength=500;note.setAttribute('aria-label',source.name+' page review note');const nl=workflowElement('label','What was checked on these pages');nl.append(note);row.append(nl);
  row.append(workflowButton('Record page review',()=>{try{const pages=parseRetryPages(range.value);if(!pages||!source.pages||pages.some(p=>p>source.pages))throw Error('Enter explicit page numbers within this document.');if(note.value.trim().length<10)throw Error('Describe what was checked in at least 10 characters.');humanPageReviews=humanPageReviews.filter(p=>!(p.source===source.name&&p.sha256===source.sha256&&pages.includes(p.page)));for(const page of pages)humanPageReviews.push({source:source.name,sha256:source.sha256,page,disposition:disposition.value,note:note.value.trim()});humanSourceReview=null;workflowSave();renderReadiness(true);}catch(e){message.textContent=e.message;}}));
  if(reviewed.length){const list=workflowElement('details');list.append(workflowElement('summary','Recorded page decisions'));for(const p of reviewed.sort((a,b)=>a.page-b.page))list.append(workflowElement('p','Page '+p.page+' · '+p.disposition.replaceAll('_',' ')+' · '+p.note));row.append(list);}panel.append(row);
 }
 const label=workflowElement('label','Final review basis, differences and deliberate blanks'),input=workflowElement('textarea');input.maxLength=1000;input.value=humanReviewNote;input.setAttribute('aria-label','Final source review basis');input.oninput=()=>{humanReviewNote=input.value;workflowSave();};label.append(input);panel.append(label);
 const confirm=workflowElement('input');confirm.type='checkbox';const confirmLabel=workflowElement('label');confirmLabel.append(confirm,document.createTextNode(' I compared the final inventory with all applicable source pages, resolved differences, and accounted for missing design information.'));panel.append(confirmLabel);
 panel.append(workflowButton('Approve reviewed design inventory',()=>{try{if(workflowBusy)throw Error('Wait for the current document job.');if(!confirm.checked)throw Error('Confirm the completed source review first.');humanSourceReview=makeSourceReview(workflowOriginalPayload(),humanPageReviews,humanReviewNote);workflowSave();renderReadiness(true);}catch(e){message.textContent=e.message;}}),message);for(const control of panel.querySelectorAll('input,textarea,select,button'))control.disabled=workflowBusy;box.append(panel);
}
function renderManualSourceEntry(box,wasOpen,previousPanel){
 if(!['incomplete','review_required'].includes(scanState.status)||!scanState.source_checkpoints.length)return;
 const sourceKey=JSON.stringify(scanState.source_checkpoints.map(s=>[s.name,s.sha256,s.pages]));
 // Autosave can fire between two input events, when focus is temporarily on the
 // document. Keep the actual draft controls until submission or sources change.
 if(previousPanel?.dataset.sourceKey===sourceKey){for(const control of previousPanel.querySelectorAll('input,textarea,select,button'))control.disabled=workflowBusy;box.append(previousPanel);return;}
 const panel=workflowElement('details');panel.id='manual-source-entry';panel.open=wasOpen;
 panel.dataset.sourceKey=sourceKey;
 panel.append(workflowElement('summary','Add equipment or a supply outlet missed by the scan'),workflowElement('p','Use the original source page. Added equipment starts unverified and added outlets start unchecked. Automatic scan coverage stays incomplete; finish the source review before building.'));
 const fields={};
 function field(name,title,parent=panel,options){
  const label=workflowElement('label',title),el=workflowElement(options?'select':name==='note'?'textarea':'input');
  el.setAttribute('aria-label','Manual '+title);if(!options)el.maxLength=name==='note'?500:120;
  if(options)for(const [value,title] of options){const option=workflowElement('option',title);option.value=value;el.append(option);}
  fields[name]=el;label.append(el);parent.append(label);return el;
 }
 field('kind','Item kind',panel,[['equipment','Equipment'],['outlet','Supply outlet']]);
 field('source','Source document',panel,[['','Choose original source'],...scanState.source_checkpoints.filter(s=>s.pages&&s.sha256).map(s=>[s.name,s.name])]);
 field('page','Source page');
 const equipment=workflowElement('fieldset'),outlet=workflowElement('fieldset');equipment.append(workflowElement('legend','Equipment identification'));outlet.append(workflowElement('legend','One physical supply outlet'));outlet.hidden=true;panel.append(equipment,outlet);
 field('tag','Equipment ID',equipment);field('template','Original equipment form',equipment,[['','Choose form'],...Object.keys(unitForms).map(name=>[name,worksheetLabel(name)])]);
 for(const [name,title] of [['type','Outlet type'],['design_cfm','Design CFM'],['system','Serving equipment ID'],['location','Room / area'],['size','Neck size, if supported'],['locator','Distinct physical locator'],['x','PDF X coordinate (optional)'],['y','PDF Y coordinate (optional)']])field(name,title,outlet);
 fields.kind.onchange=()=>{equipment.hidden=fields.kind.value!=='equipment';outlet.hidden=fields.kind.value!=='outlet';};
 field('note','Source evidence');const confirmation=workflowElement('input');confirmation.type='checkbox';confirmation.setAttribute('aria-label','Manual item source and duplicates checked');const label=workflowElement('label');label.append(confirmation,document.createTextNode(' I checked this physical item on the original page and checked the existing review for duplicates.'));panel.append(label);
 const message=workflowElement('p');message.setAttribute('role','status');
 panel.append(workflowButton('Add source-reviewed item',()=>{
  try{
   if(workflowBusy)throw Error('Wait for the current document job.');
   const entry=manualSourceEntry({...Object.fromEntries(Object.entries(fields).map(([key,el])=>[key,el.value])),confirmed:confirmation.checked},scanState,records,diffusers,unitForms,savedTagPattern);
   if(entry.kind==='equipment'){records=[...records,entry.item];tags=records.map(r=>r.tag);const check=[...document.querySelectorAll('.template input')].find(x=>x.value===entry.item.template);if(check)check.checked=true;}
   else diffusers=[...diffusers,entry.item];
   humanSourceReview=null;outletBatchUndo=null;outletRepeatUndo=null;renderReview();renderOutlets();workflowSave();updateWorkspace();renderReadiness(true);
   $('job-status').textContent=entry.kind==='equipment'?'Equipment added from your source review. Enter supported design values and verify its review row.':'One physical outlet added from your source review. Check its fields, then include it in the supply sheet.';
  }catch(e){message.textContent=e.message;}
 }),message);
 for(const control of panel.querySelectorAll('input,textarea,select,button'))control.disabled=workflowBusy;
 box.append(panel);
}
function renderReadiness(force=false){
 const box=$('readiness');if(!box)return;
 // A delayed inventory autosave must not erase a page note or confirmation
 // while the reviewer is using it. Approval still checks the current payload.
 const humanPanel=$('human-source-review');
 const manualPanel=$('manual-source-entry');
 if(!force&&(humanPanel?.open&&humanPanel.contains(document.activeElement)||manualPanel?.open&&manualPanel.contains(document.activeElement)))return;
 const humanOpen=humanPanel?.open===true,manualOpen=manualPanel?.open===true;box.replaceChildren();
 if(humanSourceReview&&!workflowBusy)$('scanstatus').textContent=sourceReviewApproved(workflowOriginalPayload())?'AUTOMATED SCAN: '+scanState.status.toUpperCase()+'. HUMAN SOURCE REVIEW APPROVED FOR THIS INVENTORY.':'Source or inventory changed after human approval. Recheck the changes and approve the reviewed design inventory again.';
 const verified=records.filter(r=>r.status==='VERIFIED').length,unresolved=records.filter(r=>!['VERIFIED','EXCLUDED'].includes(r.status));
 const assessment=sourceReadiness(records,diffusers,imageReview,officeComparison?compareOfficeDesign(officeComparison,records,diffusers):null);
 const title=workflowElement('h3',assessment.title);box.append(title);
 if(assessment.empty)box.append(workflowElement('p','No job equipment was captured. A completed scan stage does not mean its schedules were recognized. Retry the schedule pages or add source-reviewed equipment before building.'));
 if(assessment.pendingImages){
  box.append(workflowElement('p',assessment.imageOutlets+' image outlet candidates and '+assessment.imageEquipment+' image equipment/hood candidates await source confirmation. They may overlap existing review rows and are not report-ready entries.'));
  const link=workflowElement('a','Review image candidates');link.href='#image-review';box.append(link);
 }
 if(assessment.problems)box.append(workflowElement('p',assessment.problems+' office comparison findings require review below. Missing IDs, differences and unsupported values remain unresolved.'));
 box.append(workflowElement('p',sourceReviewApproved(workflowOriginalPayload())?'DESIGN INVENTORY REVIEWED BY A PERSON. Automatic coverage stays separately recorded; this is not field certification.':scanStateBlocked(scanState)?'Source coverage is incomplete or outdated. Review the omissions and acknowledge a partial report before building.':'Source extraction still requires manual review; it is never certified as a complete takeoff.'));
 for(const record of unresolved){
  const row=workflowElement('div');row.className='readiness-row';
  const missing=['design_cfm','esp'].filter(k=>record[k]===undefined||record[k]===null||record[k]==='');
  row.append(workflowElement('span',record.tag+' · '+(missing.length?'Missing '+missing.map(fieldLabel).join(', '):'Values entered; verification pending')+' · '+(record.source||'No source linked')));
   if(record.source&&/\.pdf$/i.test(record.source))row.append(workflowButton('View '+record.tag+' source',()=>viewSource(record.source,sourcePage(record.reference))));box.append(row);
 }
 if(scanState.source_checkpoints.length){
  renderManualSourceEntry(box,manualOpen,force?null:manualPanel);renderHumanReview(box,humanOpen);
  const heading=workflowElement('h4','Source coverage and page retries');box.append(heading);
  if(records.length||diffusers.length){
   const recovery=workflowElement('div');recovery.id='source-recovery';
   recovery.append(workflowElement('p','Saved reviews keep your edited values, but temporary source files can expire or disappear after a server restart. Reattach every original file below its original filename. Recovery checks the file contents and rescans to restore previews and page retries, while keeping reviewed values and worksheet choices. You must verify the refreshed observations and approve the inventory again.'));
   const button=workflowButton('Recover sources and keep reviewed values',async()=>{try{await recoverSources();}catch(e){$('job-status').textContent=e.message+' Your current review is preserved.';}});
   button.disabled=workflowBusy||!sourceFiles.length;recovery.append(button);if(!sourceFiles.length)recovery.append(workflowElement('p','Choose the original files in Upload source documents to enable recovery.'));box.append(recovery);
  }
  scanState.source_checkpoints.forEach(c=>{
   const row=workflowElement('div');row.className='source-checkpoint';
   row.append(workflowElement('strong',c.name),workflowElement('p','Native: '+c.native_status.replaceAll('_',' ')+' · Images: '+c.image_status.replaceAll('_',' ')+(c.pages?' · '+c.pages+' pages':'')));
   if(!/\.pdf$/i.test(c.name)){box.append(row);return;}
   const label=workflowElement('label','Pages to retry (blank = whole source)'),input=workflowElement('input');input.type='text';input.placeholder='1, 3-5';input.setAttribute('aria-label',c.name+' retry pages');label.append(input);row.append(label);
   for(const [stage,text] of [['native','Retry native pages'],['images','Retry image pages']]){
    const button=workflowButton(text,async()=>{try{await retrySource(c.name,stage,input.value);}catch(e){$('job-status').textContent=e.message;}});button.disabled=!scanJobId||sourceIndex(c.name)<0||workflowBusy;row.append(button);
   }
   box.append(row);
  });
 }
}
function parseRetryPages(value){
 if(!value.trim())return null;const found=new Set();
 for(const part of value.split(',')){
  const m=/^\s*(\d{1,3})(?:\s*-\s*(\d{1,3}))?\s*$/.exec(part);if(!m)throw Error('Use page numbers such as 1, 3-5.');
  const begin=Number(m[1]),end=Number(m[2]||m[1]);if(begin<1||end<begin||end>300)throw Error('Pages must be between 1 and 300.');
  for(let i=begin;i<=end;i++)found.add(i);
 }
 return [...found].sort((a,b)=>a-b);
}
function workflowControls(busy){
 workflowBusy=busy;for(const id of ['scan','files','buildmethod','generate','loadproject'])$(id).disabled=busy;
 $('generate').textContent=busy&&workflowJob?.kind!=='scan'?'Building report…':'Build report';
 $('scan').textContent=busy&&workflowJob?.kind==='scan'?'Scanning documents…':'Scan uploaded files';
 for(const el of document.querySelectorAll('#review input,#review select,#review button,#outlets input,#outlets button,#image-review button,#image-review input,.template input,#project-card input,#project-card select,#partial-review-panel input,#partial-review-panel textarea')){
  if(busy){if(!el.hasAttribute('data-workflow-disabled'))el.dataset.workflowDisabled=el.disabled?'true':'false';el.disabled=true;}
  else if(el.hasAttribute('data-workflow-disabled')){el.disabled=el.dataset.workflowDisabled==='true';delete el.dataset.workflowDisabled;}
 }
 renderReadiness();
}
async function retrySource(name,stage,pages){
 if(workflowBusy)throw Error('Wait for the current document job.');
 const selection=parseRetryPages(pages),index=sourceIndex(name);if(index<0||!scanJobId)throw Error('Reattach sources before retrying.');
 workflowJob={...(await readApiJson(await fetch('/api/jobs/'+scanJobId+'/retry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_index:index,stage,page_numbers:selection})}))),retry_source:name,retry_pages:selection,retry_stage:stage,source_revision:workflowSourceRevision};
 workflowSave();await followWorkflowJob();
}
async function recoverSources(){
 if(workflowBusy)throw Error('Wait for the current document job.');
 const expected=recoverySourceIdentities(scanState.source_checkpoints);
 if(sourceFiles.length!==expected.length||expected.some(s=>!sourceFiles.some(f=>f.name===s.name)))throw Error('Choose every original source file with its original filename before recovery.');
 try{
  workflowControls(true);$('job-status').textContent='Checking original source files for recovery…';
  const form=new FormData();for(const file of sourceFiles)form.append('files',file);form.append('recovery_sources',JSON.stringify(expected));
  const job=await readApiJson(await fetch('/api/jobs/scan',{method:'POST',body:form}));
  recoverySourceIdentities(expected,job.sources||[]);
  workflowJob={...job,recovery_sources:expected,source_revision:workflowSourceRevision};workflowSave();await followWorkflowJob();
 }finally{workflowControls(false);}
}
function applyScanResult(data,retrySourceName,recoverySources){
 if(recoverySources){recoverySourceIdentities(recoverySources,data.source_manifest||[]);recoverySourceIdentities(recoverySources,data.source_checkpoints||[]);}
 const preserving=Boolean(retrySourceName||recoverySources),affectedSources=recoverySources?recoverySources.map(s=>s.name):retrySourceName;
 const nextOutlets=preserving?reconcileReviewedOutlets(diffusers,data.diffusers||[],data.image_review||[],affectedSources):(data.diffusers||[]);
 const fresh=(data.records||[]).map(r=>{const next={...r};applyProposed(next);return next;});
 const nextRecords=preserving?reconcileReviewedEquipment(records,fresh,retrySourceName,Boolean(recoverySources)):fresh;
 outletBatchUndo=null;
 outletRepeatUndo=null;humanSourceReview=null;
 scanState=validateScanState({status:data.scan_status||'unknown',complete_takeoff:false,source_checkpoints:data.source_checkpoints||[],warnings:data.warnings||[]});renderScanReview();
 records=nextRecords;diffusers=nextOutlets;
 tags=records.map(r=>r.tag);imageReview=data.image_review||[];
 if(preserving)for(const candidate of imageReview)if(candidate.kind==='diffuser'&&diffusers.some(o=>samePhysicalOutlet(o,outletFromImage(candidate))))candidate.accepted=true;
imageCoverage=data.image_coverage||[];imageCoverageTruncated=data.image_coverage_truncated===true;
 scanJobId=data.job_id;sourceManifest=data.source_manifest||[];
 renderReview();renderOutlets();renderImageReview();renderImageCoverage();
 $('scanstatus').textContent=(data.scan_status==='incomplete'?'SCAN INCOMPLETE. Completed results retained. ':'Source results ready for review. ')+scanCandidateSummary(records,diffusers,imageReview)+(recoverySources?'Original sources recovered. Reviewed values retained; equipment and outlet inclusion require fresh verification. ':retrySourceName?'Retried '+retrySourceName+'; affected equipment requires fresh verification. ':'')+(data.warnings||[]).join(' | ');
 workflowSave();
}
async function workflowRecommendations(data){
 const rec=await readApiJson(await fetch('/api/suggest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tags,signals:data.signals||[],sparse:data.sparse===true})}));
 const chosen=new Set((rec.recommended||[]).map(x=>x.name));const assigned=new Set(records.map(r=>r.template).filter(Boolean));
 if(assigned.size)for(const name of Object.keys(unitForms))if(!assigned.has(name))chosen.delete(name);
 for(const name of assigned)chosen.add(name);applyCompanionChoices(chosen,records);
 document.querySelectorAll('.template input').forEach(x=>x.checked=chosen.has(x.value));
 $('template-recommendations').textContent='Recommended '+chosen.size+' original ABP worksheets. Review equipment forms and selections before building. '+(rec.review_note||'');
}
async function followWorkflowJob(){
 if(!workflowJob)return;workflowControls(true);$('reconnect-job').hidden=true;
 try{
  while(workflowJob){
   const status=await readApiJson(await fetch('/api/jobs/'+workflowJob.id));const p=status.progress||{};
   $('job-status').textContent=(status.kind==='scan'?'Scanning documents':'Building report')+' · '+status.status+' · '+(p.source||'')+' · '+(p.stage||'')+' · '+(p.message||'')+(p.completed_pages?' · native pages retained: '+p.completed_pages.join(', '):'')+(p.pages_completed!==undefined?' · image pages retained: '+p.pages_completed:'');
   if(status.status==='failed')throw Error(p.message||'Document job failed. Your review was preserved.');
   if(status.status==='done'){
    const finished=workflowJob;
    if(status.kind==='scan'){
     if(finished.source_revision!==undefined&&finished.source_revision!==workflowSourceRevision){$('job-status').textContent='The source list changed after this scan started. Your review was preserved. Scan the new source list before building.';return;}
     const data=await readApiJson(await fetch('/api/jobs/'+status.id+'/result'));
     if(!finished.retry_source&&!finished.recovery_sources&&(records.length||diffusers.length)&&!confirm('Replace the current review with these scan results? Cancel preserves your current review.')){
      $('job-status').textContent='Scan finished. Current review kept. Use Reconnect completed job to review its results.';$('reconnect-job').hidden=false;return;
     }
     applyScanResult(data,finished.retry_source,finished.recovery_sources);
     let recommendationWarning='';
     if(!finished.retry_source&&!finished.recovery_sources){
      try{await workflowRecommendations(data);}
      catch(e){recommendationWarning=' Worksheet suggestions are unavailable. Your scan results are retained; choose the applicable worksheets before building.';$('template-recommendations').textContent=recommendationWarning;}
     }
     $('job-status').textContent=finished.recovery_sources?'Source recovery finished. Original files matched; edited values and worksheet choices were retained. Recheck equipment and outlet inclusion, then approve the inventory again.':'Scan finished. Check source coverage, unresolved equipment and outlet totals below.';
     $('job-status').textContent+=recommendationWarning;
    }else{
     completedBuild={id:status.id,project:finished.project,partial:finished.partial};const link=$('download-report');link.href='/api/jobs/'+status.id+'/result';link.download=String(finished.project||'ABP').replace(/[^a-z0-9_-]+/gi,'_')+'_PreField_TAB.xlsx';link.hidden=false;link.textContent='Download checked Excel report';link.click();
     $('status').textContent=status.kind==='reference'?'Report built from the approved reference. Original formula XML preserved; field readings and signoffs cleared.':(finished.partial?'Reviewed partial report built. SOURCE SCAN REMAINS INCOMPLETE. See Notes for omissions. ':'Report built. ')+'Template integrity checks passed. '+reviewCoverage(records,diffusers);
     $('job-status').textContent='Build finished. The checked report can be downloaded again below.';
    }
    workflowJob=null;workflowSave();break;
   }
   await new Promise(resolve=>setTimeout(resolve,1500));
  }
 }catch(e){$('job-status').textContent=e.message+' Your browser review is preserved.';$('reconnect-job').hidden=false;workflowSave();}
 finally{workflowControls(false);updateWorkspace();renderComparison();}
}
function renderComparison(){
 renderReadiness();
 const box=$('office-comparison');if(!box||!officeComparison)return;box.replaceChildren();
 const result=compareOfficeDesign(officeComparison,records,diffusers),counts={};for(const row of result.rows)counts[row.status]=(counts[row.status]||0)+1;
 const outletSummary=officeComparison.outlets.length?'Office supply-outlet total '+result.office_total+' CFM; included builder outlet total '+result.builder_total+' CFM.':'No office supply-outlet rows were read. Equipment airflows are compared individually below.';
 box.append(workflowElement('p',Object.entries(counts).map(([k,v])=>v+' '+k).join(' · ')+'. '+outletSummary));
 box.append(workflowElement('p','Comparison only: office values never populate this report. Actuals and formulas are ignored. Outlet rows are paired by system, type, flow and size; this does not establish physical outlet identity.'));
 for(const warning of result.warnings)box.append(workflowElement('p',warning));
 const wrap=workflowElement('div');wrap.className='review-scroll';const table=workflowElement('table'),head=workflowElement('tr');
 for(const title of ['Item','Design field','Office','Builder','Result','Office cell location'])head.append(workflowElement('th',title));table.append(head);
 for(const row of result.rows){const tr=workflowElement('tr');tr.className='comparison-'+row.status;for(const key of ['item','field','office','builder','status','reference'])tr.append(workflowElement('td',String(row[key]??'')));table.append(tr);}
 wrap.append(table);box.append(wrap);
}
function restoreWorkflow(saved){
 humanSourceReview=null;humanReviewNote=typeof saved.review?.human_review_note==='string'?saved.review.human_review_note:'';humanPageReviews=Array.isArray(saved.review?.human_page_reviews)?saved.review.human_page_reviews:[];
 const data=validateSavedReview(saved.review,[...document.querySelectorAll('.template input')].map(x=>x.value),unitForms,savedTagPattern);
 scanState=validateScanState(data.scan_state);renderScanReview();records=data.records;tags=records.map(r=>r.tag);diffusers=data.diffusers||[];imageReview=data.image_review||[];imageCoverage=data.image_coverage||[];imageCoverageTruncated=data.image_coverage_truncated===true;
 $('project').value=data.project;$('location').value=data.location;$('standard').value=data.standard;document.querySelectorAll('.template input').forEach(x=>x.checked=data.templates.includes(x.value));
 scanJobId=typeof saved.scan_job_id==='string'&&/^[a-f0-9]{48}$/.test(saved.scan_job_id)?saved.scan_job_id:null;
 sourceManifest=Array.isArray(saved.source_manifest)?saved.source_manifest.filter(s=>typeof s.name==='string'&&s.name.length<=160).slice(0,100):[];
 workflowSourceRevision=Number.isInteger(saved.source_revision)?saved.source_revision:0;
 completedBuild=saved.completed_build&&/^[a-f0-9]{48}$/.test(saved.completed_build.id)?saved.completed_build:null;
 if(completedBuild){const link=$('download-report');link.href='/api/jobs/'+completedBuild.id+'/result';link.download=String(completedBuild.project||'ABP').replace(/[^a-z0-9_-]+/gi,'_')+'_PreField_TAB.xlsx';link.hidden=false;link.textContent='Download previous checked report (temporary server copy)';}
 workflowJob=saved.active_job&&/^[a-f0-9]{48}$/.test(saved.active_job.id)&&['scan','build','reference'].includes(saved.active_job.kind)?saved.active_job:null;
 renderReview();renderOutlets();renderImageReview();renderImageCoverage();updateWorkspace();
 $('scanstatus').textContent=scanStateNotice()+'Saved browser review restored. Source files are not saved in browser storage. Check revisions before building.';
 $('partial-review-ack').checked=false;$('partial-review-note').value='';
}
function installWorkflow(){
 const style=workflowElement('style');style.textContent='.readiness-row{display:flex;gap:12px;align-items:center;justify-content:space-between;border-bottom:1px solid #40536c;padding:12px 0}.source-checkpoint{padding:14px;border:1px solid #40536c;border-radius:8px;margin:12px 0}.source-checkpoint input{max-width:260px}.source-checkpoint button{margin-right:10px}#source-viewer{position:sticky;top:65px;max-height:70vh;overflow:auto;border:1px solid #6c9cb8;background:#122337;padding:16px;z-index:4;border-radius:10px}#source-preview{width:100%;height:auto;background:white}#readiness{border-left:3px solid #efbc75;padding:18px;margin:18px 0;background:#1d2635}#office-comparison table,#outlets table{width:100%;border-collapse:collapse}#office-comparison td,#office-comparison th,#outlets td,#outlets th{padding:9px;border:1px solid #40536c;text-align:left}#office-comparison .comparison-different,#office-comparison .comparison-missing{background:#4a302d}#office-comparison .comparison-unverified,#office-comparison .comparison-excluded{background:#413b22}#autosave-status,#job-status{overflow-wrap:anywhere}#download-report{display:inline-block;padding:12px;background:#b1f0d5;color:#092e2c;border-radius:7px;margin-top:12px}#download-report[hidden]{display:none}#outlet-totals{padding:12px;background:#152f3e;border:1px solid #466276;margin:14px 0}';document.head.append(style);
 const source=$('source-panel'),viewer=workflowElement('section');viewer.id='source-viewer';viewer.hidden=true;viewer.append(workflowElement('h3','Source page review'));
 const caption=workflowElement('p');caption.id='source-view-title';const image=workflowElement('img');image.id='source-preview';const previewStatus=workflowElement('p');previewStatus.id='source-preview-status';
 const large=workflowElement('a','Open larger source preview');large.id='source-preview-large';large.target='_blank';large.rel='noopener';
 const previewRetry=workflowButton('Retry source preview',()=>{});previewRetry.id='source-preview-retry';previewRetry.hidden=true;
 viewer.append(workflowButton('Close source preview',()=>{clearSourcePreview();viewer.hidden=true;$('source-review-layout').classList.remove('viewing');}),caption,large,previewStatus,previewRetry,image);source.insertBefore(viewer,$('review'));
 const readiness=workflowElement('section');readiness.id='readiness';source.insertBefore(readiness,$('review'));
 const layout=workflowElement('div');layout.id='source-review-layout';const body=workflowElement('div');body.id='source-review-body';source.insertBefore(layout,readiness);
 for(const element of [readiness,$('review'),$('outlets'),$('image-coverage'),$('image-review')])body.append(element);
 layout.append(body,viewer);style.textContent+='@media(min-width:1100px){#source-review-layout.viewing{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,1fr);gap:16px;align-items:start}#source-review-layout.viewing #source-viewer{top:70px}}';
 const jobs=workflowElement('div');jobs.id='job-panel';const status=workflowElement('p');status.id='job-status';status.setAttribute('role','status');const reconnect=workflowButton('Reconnect completed job',()=>followWorkflowJob());reconnect.id='reconnect-job';reconnect.hidden=true;
 jobs.append(status,reconnect);$('build-card').prepend(jobs);
 new MutationObserver(()=>{if(workflowJob?.kind==='scan')$('scanstatus').textContent=status.textContent;}).observe(status,{childList:true});
 const autosave=workflowElement('p');autosave.id='autosave-status';$('build-card').append(autosave);
 const download=workflowElement('a');download.id='download-report';download.hidden=true;$('build-card').append(download);
 const compare=workflowElement('details');compare.id='office-comparison-panel';compare.append(workflowElement('summary','Compare with your completed office report'));
 compare.append(workflowElement('p','Choose the office XLSX for comparison. It is read only in this browser and is never uploaded or saved with the review. Its measurements are ignored.'));
 const label=workflowElement('label','Office report for local comparison'),input=workflowElement('input');input.type='file';input.accept='.xlsx';input.setAttribute('aria-label','Office report for local comparison');label.append(input);compare.append(label);
 const compareStatus=workflowElement('p');compareStatus.id='office-compare-status';const compareResults=workflowElement('div');compareResults.id='office-comparison';compare.append(compareStatus,compareResults);$('build-card').before(compare);compare.className='card';
 input.onchange=async()=>{try{compareStatus.textContent='Reading office design values locally…';officeComparison=await readLocalOfficeWorkbook(input.files[0]);compareStatus.textContent='Office workbook read locally. No values were imported into the report.';renderComparison();}catch(e){officeComparison=null;compareResults.replaceChildren();compareStatus.textContent=e.message;}};
 $('scan').onclick=async()=>{
  if(!templatesReady||workflowBusy)return;if(!sourceFiles.length){$('scanstatus').textContent='Choose source files first.';return;}
  try{workflowControls(true);$('job-status').textContent='Uploading source documents…';const form=new FormData();for(const file of sourceFiles)form.append('files',file);
   workflowJob={...(await readApiJson(await fetch('/api/jobs/scan',{method:'POST',body:form}))),source_revision:workflowSourceRevision};workflowSave();await followWorkflowJob();
  }catch(e){$('job-status').textContent=e.message;workflowControls(false);}
 };
 $('generate').onclick=async()=>{
  if($('buildmethod').value==='reference'){
   try{if(workflowBusy)return;if(!inspectedReference||inspectedReference!==$('reference-file').files[0])throw Error('Review the selected reference first.');if(!$('reference-approved').checked)throw Error('Confirm the reference equipment list and design values.');if(!$('project').value.trim())throw Error('Enter a project name.');
    const form=referenceForm();form.append('project',$('project').value);form.append('location',$('location').value);form.append('approved','true');
    workflowJob={...(await readApiJson(await fetch('/api/jobs/reference',{method:'POST',body:form}))),project:$('project').value};
    sessionStorage.setItem('abp-reference-job',JSON.stringify(workflowJob));await followWorkflowJob();if(!workflowJob)sessionStorage.removeItem('abp-reference-job');
   }catch(e){$('status').textContent=e.message;workflowControls(false);}return;
  }
  try{if(workflowBusy)return;if(!templatesReady)throw Error('Wait for report worksheets to load.');const payload=workflowOriginalPayload();
   if(emptySourceReport(payload.records,payload.diffusers,scanState))throw Error('No reviewed equipment or included outlets. The source takeoff is empty; retry the schedules or add source-reviewed equipment before building a job report.');
   if(!sourceReviewApproved(payload)&&scanBuildBlocked(scanState,payload.scan_acknowledgement))throw Error(scanStateNotice()+'Review source omissions and enter a fresh partial-report acknowledgment.');
   if(!payload.project.trim())throw Error('Enter a project name.');if(!payload.templates.length)throw Error('Select at least one worksheet.');
   $('status').textContent='Submitting report build…';
   workflowJob={...(await readApiJson(await fetch('/api/jobs/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}))),project:payload.project,partial:!!payload.scan_acknowledgement&&!sourceReviewApproved(payload)};
   workflowSave();await followWorkflowJob();
  }catch(e){$('status').textContent=e.message;workflowControls(false);}
 };
 document.addEventListener('input',workflowChanged);document.addEventListener('change',workflowChanged);
 const oldSourcesChanged=sourcesChanged;sourcesChanged=function(){workflowSourceRevision++;scanJobId=null;sourceManifest=[];oldSourcesChanged();renderReadiness();workflowSave();};
 const oldLoadProject=$('loadproject').onchange;
 $('loadproject').onchange=async event=>{
  if(workflowBusy)return;await oldLoadProject(event);
  if($('status').textContent.startsWith('Saved review restored.')){
   // A downloaded review has no authenticated link to this browser's old job.
   // Common filenames from a different project must never show the wrong PDF.
   workflowSourceRevision++;scanJobId=null;sourceManifest=[];completedBuild=null;
   $('download-report').hidden=true;renderReadiness();workflowSave();
  }
 };
 const saved=localStorage.getItem(workflowDraftKey);
 if(saved){try{restoreWorkflow(JSON.parse(saved));if(workflowJob)followWorkflowJob();}catch(e){autosave.textContent='Saved review could not be restored: '+e.message;}}
 if(!workflowJob&&sessionStorage.getItem('abp-reference-job')){
  try{const job=JSON.parse(sessionStorage.getItem('abp-reference-job'));if(job.kind==='reference'&&/^[a-f0-9]{48}$/.test(job.id)){workflowJob=job;followWorkflowJob().then(()=>{if(!workflowJob)sessionStorage.removeItem('abp-reference-job');});}}catch{}
 }
 const recent=workflowElement('details');recent.append(workflowElement('summary','Recover a saved browser review'));
 for(const key of Object.keys(localStorage).filter(k=>k.startsWith('abp-review-v2:')).slice(-10)){
  try{const saved=JSON.parse(localStorage.getItem(key));if(!saved.review?.project)continue;recent.append(workflowButton(saved.review.project+' · '+new Date(saved.saved_at).toLocaleString(),()=>{if(workflowBusy)return;try{restoreWorkflow(saved);workflowSave();if(workflowJob)followWorkflowJob();}catch(e){autosave.textContent=e.message;}}));}catch{}
 }
 $('review-tools').append(recent);renderReadiness();
}
let workflowInstallAttempts=0;
const workflowInstallTimer=setInterval(()=>{if(templatesReady){clearInterval(workflowInstallTimer);installWorkflow();}else if(++workflowInstallAttempts>120)clearInterval(workflowInstallTimer);},250);
