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
function viewSource(name,page=1,position){
 const index=sourceIndex(name),panel=$('source-viewer');panel.hidden=false;
 $('source-view-title').textContent=name+' · page '+page+(position?' · callout near ['+position.map(n=>Math.round(n)).join(', ')+'] PDF points':'');
 $('source-preview').alt='Source drawing preview for '+name+', page '+page;
 $('source-preview-status').textContent='Loading source page…';
 if(!scanJobId||index<0){$('source-preview').removeAttribute('src');$('source-preview-status').textContent='Reattach this source and scan to enable its preview. The saved design review is still available.';return;}
 $('source-preview').onload=()=>{$('source-preview-status').textContent='Check the full drawing, revision, duct connection and room. Coordinates identify the extracted callout; they do not prove supply service.';};
 $('source-preview').onerror=()=>{$('source-preview-status').textContent='Preview unavailable or source expired. Open the original locally, or reattach it and scan again.';};
 $('source-preview').src='/api/jobs/'+scanJobId+'/preview?source='+index+'&page='+page;
 $('source-preview-large').href=$('source-preview').src;$('source-review-layout').classList.add('viewing');
 panel.scrollIntoView({block:'nearest'});
}
function renderOutletTotals(){
 const box=$('outlet-totals');if(!box)return;box.replaceChildren();
 const systems=new Map(),positions=new Map();let duplicates=0;
 for(const [i,o] of diffusers.entries()){
  if(o.include===false)continue;
  const system=String(o.system||'Unassigned').trim().toUpperCase();
  const item=systems.get(system)||{count:0,total:0};item.count++;item.total+=Number(o.design_cfm||0);systems.set(system,item);
  if(o.position?.length===2){const k=JSON.stringify([o.source,o.reference,o.position.map(n=>Math.round(n*10)/10)]);if(positions.has(k))duplicates++;positions.set(k,i);}
 }
 for(const [system,s] of [...systems].sort((a,b)=>a[0].localeCompare(b[0]))){
  const record=records.find(r=>r.tag===system),target=record?.design_cfm;
  box.append(workflowElement('p',system+': '+s.count+' included outlets · '+s.total.toLocaleString()+' design CFM'+(target!=null&&target!==''?' · unit target '+target+' CFM · difference '+(s.total-Number(target))+' CFM':' · unit target unverified/not supplied')));
 }
 if(duplicates)box.append(workflowElement('p','Review '+duplicates+' repeated source positions before building. Repeated flow values alone are not treated as duplicates.'));
 if(new Set(diffusers.map(o=>o.source).filter(Boolean)).size>1)box.append(workflowElement('p','Multiple source documents contain outlet candidates. Review revisions and duplicates; no drawing is silently superseded.'));
}
renderOutlets=function(){
 workflowOriginalOutlets();const box=$('outlets');if(!diffusers.length)return;
 const totals=workflowElement('div');totals.id='outlet-totals';box.insertBefore(totals,box.children[2]);
 const table=box.querySelector('table'),rows=[...table.querySelectorAll('tr')].slice(1);
 rows.forEach((row,index)=>{const o=diffusers[index];row.lastElementChild.append(document.createElement('br'),workflowButton('View outlet '+(index+1)+' source',()=>viewSource(o.source,sourcePage(o.reference),o.position)));});
 // Display by serving system without changing original candidate indices.
 // Stable dataset mapping avoids interpreting identical CFM values as one outlet.
 const originalRows=[...table.querySelectorAll('tr')].slice(1);originalRows.forEach((row,i)=>row.dataset.outletIndex=i);
 originalRows.sort((a,b)=>String(diffusers[+a.dataset.outletIndex].system||'').localeCompare(String(diffusers[+b.dataset.outletIndex].system||''))||Number(a.dataset.outletIndex)-Number(b.dataset.outletIndex));
 for(const row of originalRows)table.append(row);renderOutletTotals();
};
renderReview=function(){workflowOriginalReview();renderReadiness();};
renderImageReview=function(){workflowOriginalImageReview();$('image-review').querySelectorAll('fieldset').forEach((panel,index)=>{const c=imageReview[index];if(c)panel.append(workflowButton('View image candidate '+(index+1)+' source',()=>viewSource(c.source,c.page)));});};
function renderReadiness(){
 const box=$('readiness');if(!box)return;box.replaceChildren();
 const verified=records.filter(r=>r.status==='VERIFIED').length,unresolved=records.filter(r=>!['VERIFIED','EXCLUDED'].includes(r.status));
 const title=workflowElement('h3',verified+' equipment verified · '+unresolved.length+' unresolved');box.append(title);
 box.append(workflowElement('p',scanStateBlocked(scanState)?'Source coverage is incomplete or outdated. Review the omissions and acknowledge a partial report before building.':'Source extraction still requires manual review; it is never certified as a complete takeoff.'));
 for(const record of unresolved){
  const row=workflowElement('div');row.className='readiness-row';
  const missing=['design_cfm','esp'].filter(k=>record[k]===undefined||record[k]===null||record[k]==='');
  row.append(workflowElement('span',record.tag+' · '+(missing.length?'Missing '+missing.map(fieldLabel).join(', '):'Values entered; verification pending')+' · '+(record.source||'No source linked')));
   if(record.source&&/\.pdf$/i.test(record.source))row.append(workflowButton('View '+record.tag+' source',()=>viewSource(record.source,sourcePage(record.reference))));box.append(row);
 }
 if(scanState.source_checkpoints.length){
  const heading=workflowElement('h4','Source coverage and page retries');box.append(heading);
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
function applyScanResult(data,retrySourceName){
 scanState=validateScanState({status:data.scan_status||'unknown',complete_takeoff:false,source_checkpoints:data.source_checkpoints||[],warnings:data.warnings||[]});renderScanReview();
 const fresh=(data.records||[]).map(r=>{const next={...r};applyProposed(next);return next;});
 if(retrySourceName){
  const prior=new Map(records.map(r=>[r.tag,r]));
  records=fresh.map(r=>{const old=prior.get(r.tag);if(!old)return r;prior.delete(r.tag);
   const affected=old.source===retrySourceName||(old.occurrences||[]).some(c=>c.source===retrySourceName)||(r.candidates||[]).some(c=>c.source===retrySourceName);
   return affected?{...r,...old,candidates:r.candidates,occurrences:r.occurrences,proposed:r.proposed,text_proposed:r.text_proposed,flags:r.flags,status:'UNVERIFIED'}:old;
  });
  for(const old of prior.values())records.push({...old,status:'UNVERIFIED'});
  const key=o=>JSON.stringify([o.source,o.reference,o.position||[],o.type,o.size,o.design_cfm]);const old=new Map(diffusers.map(o=>[key(o),o]));
  diffusers=(data.diffusers||[]).map(o=>old.has(key(o))?old.get(key(o)):o);
 }else{records=fresh;diffusers=data.diffusers||[];}
 tags=records.map(r=>r.tag);imageReview=data.image_review||[];imageCoverage=data.image_coverage||[];imageCoverageTruncated=data.image_coverage_truncated===true;
 scanJobId=data.job_id;sourceManifest=data.source_manifest||[];
 renderReview();renderOutlets();renderImageReview();renderImageCoverage();
 $('scanstatus').textContent=(data.scan_status==='incomplete'?'SCAN INCOMPLETE. Completed results retained. ':'Source results ready for review. ')+records.length+' equipment entries and '+diffusers.length+' outlet candidates. '+(retrySourceName?'Retried '+retrySourceName+'; affected equipment requires fresh verification. ':'')+(data.warnings||[]).join(' | ');
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
     if(!finished.retry_source&&(records.length||diffusers.length)&&!confirm('Replace the current review with these scan results? Cancel preserves your current review.')){
      $('job-status').textContent='Scan finished. Current review kept. Use Reconnect completed job to review its results.';$('reconnect-job').hidden=false;return;
     }
     applyScanResult(data,finished.retry_source);if(!finished.retry_source)await workflowRecommendations(data);
     $('job-status').textContent='Scan finished. Check source coverage, unresolved equipment and outlet totals below.';
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
 const box=$('office-comparison');if(!box||!officeComparison)return;box.replaceChildren();
 const result=compareOfficeDesign(officeComparison,records,diffusers),counts={};for(const row of result.rows)counts[row.status]=(counts[row.status]||0)+1;
 box.append(workflowElement('p',Object.entries(counts).map(([k,v])=>v+' '+k).join(' · ')+'. Office supply total '+result.office_total+' CFM; included builder total '+result.builder_total+' CFM.'));
 box.append(workflowElement('p','Comparison only: office values never populate this report. Actuals and formulas are ignored. Outlet rows are paired by system, type, flow and size; this does not establish physical outlet identity.'));
 for(const warning of result.warnings)box.append(workflowElement('p',warning));
 const wrap=workflowElement('div');wrap.className='review-scroll';const table=workflowElement('table'),head=workflowElement('tr');
 for(const title of ['Item','Design field','Office','Builder','Result','Office cell location'])head.append(workflowElement('th',title));table.append(head);
 for(const row of result.rows){const tr=workflowElement('tr');tr.className='comparison-'+row.status;for(const key of ['item','field','office','builder','status','reference'])tr.append(workflowElement('td',String(row[key]??'')));table.append(tr);}
 wrap.append(table);box.append(wrap);
}
function restoreWorkflow(saved){
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
 viewer.append(workflowButton('Close source preview',()=>{viewer.hidden=true;$('source-review-layout').classList.remove('viewing');}),caption,large,previewStatus,image);source.insertBefore(viewer,$('review'));
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
   if(scanBuildBlocked(scanState,payload.scan_acknowledgement))throw Error(scanStateNotice()+'Review source omissions and enter a fresh partial-report acknowledgment.');
   if(!payload.project.trim())throw Error('Enter a project name.');if(!payload.templates.length)throw Error('Select at least one worksheet.');
   workflowJob={...(await readApiJson(await fetch('/api/jobs/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}))),project:payload.project,partial:!!payload.scan_acknowledgement};
   workflowSave();await followWorkflowJob();
  }catch(e){$('status').textContent=e.message;workflowControls(false);}
 };
 document.addEventListener('input',workflowChanged);document.addEventListener('change',workflowChanged);
 const oldSourcesChanged=sourcesChanged;sourcesChanged=function(){workflowSourceRevision++;scanJobId=null;sourceManifest=[];oldSourcesChanged();workflowSave();};
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
