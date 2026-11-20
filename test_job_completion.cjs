const fs=require('fs'),vm=require('vm'),assert=require('assert');
const workflow=fs.readFileSync(__dirname+'/abp_workflow.js','utf8');
const nodes={};
for(const id of ['reconnect-job','job-status','template-recommendations','scanstatus','status','scan-export-status'])nodes[id]={};
nodes.project={value:'Example project'};
let downloads=0;
nodes['download-scan']={click(){downloads++;},removeAttribute(key){delete this[key];}};
let applied=0,saved=0;const requests=[];
const context=vm.createContext({$:id=>nodes[id],workflowJob:{id:'finished',kind:'scan',source_revision:1,download_scan:true},workflowSourceRevision:1,
 URL,Blob,scanJobId:null,sourceManifest:[],scanState:{source_checkpoints:[]},records:[],diffusers:[],exhaustOutlets:[],workflowControls:()=>{},
 fetch:async path=>{requests.push(path);return Response.json(path.endsWith('/result')?{scan_status:'incomplete',records:[{tag:'AHU-1'}]}:{id:'finished',kind:'scan',status:'done'});},
 applyScanResult:data=>{applied++;data.records[0].tag='edited';},workflowRecommendations:async()=>{throw Error('Temporary suggestion service failure');},
 workflowSave:()=>saved++,updateWorkspace:()=>{},renderComparison:()=>{},confirm:()=>{throw Error('Unexpected replacement confirmation');}});
const ui=fs.readFileSync(__dirname+'/abp_ui.js','utf8');
vm.runInContext(ui.slice(ui.indexOf('async function readApiJson('),ui.indexOf('function validateSavedReview(')),context);
vm.runInContext(workflow.slice(workflow.indexOf('function isExpiredJob('),workflow.indexOf('function renderComparison(')),context);
(async()=>{
 await context.followWorkflowJob();assert.equal(applied,1);assert.equal(context.workflowJob,null);assert.equal(saved,2);
 assert.equal(downloads,1);
 assert.equal(nodes['download-scan'].download,'Example-project-scan.json');
 const raw=await (await fetch(nodes['download-scan'].href)).json();
 assert.deepEqual(raw,{scan_status:'incomplete',records:[{tag:'AHU-1'}]});
 assert.equal(nodes['reconnect-job'].hidden,true);assert.match(nodes['job-status'].textContent,/Scan finished/);assert.match(nodes['job-status'].textContent,/scan results are retained/);
 assert.match(nodes['template-recommendations'].textContent,/choose the applicable worksheets/);
 await context.followWorkflowJob();assert.equal(applied,1);assert.equal(requests.length,2);
 const expired=()=>Response.json({error:'The temporary job expired.',reason:'job_expired'},{status:404});
 const verified=[{tag:'AHU-1',status:'VERIFIED'}];
 context.records=verified;context.scanState.source_checkpoints=[{name:'plan.pdf'}];
 context.scanJobId='earlier';context.sourceManifest=[{name:'plan.pdf'}];
 context.completedBuild={id:'last-build'};context.workflowJob={id:'retry',kind:'scan'};context.fetch=async()=>expired();
 await context.followWorkflowJob();
 assert.equal(context.workflowJob,null);assert.equal(nodes['reconnect-job'].hidden,true);
 assert.equal(context.scanJobId,'earlier');assert.equal(context.sourceManifest.length,1);
 assert.strictEqual(context.records,verified);assert.equal(context.completedBuild.id,'last-build');
 assert.match(nodes.scanstatus.textContent,/Recover sources and keep reviewed values/);
 assert.equal(nodes.scanstatus.textContent,nodes['job-status'].textContent);
 // A result can disappear between status and download.
 context.workflowJob={id:'earlier',kind:'scan'};
 context.fetch=async path=>path.endsWith('/result')?expired():Response.json({id:'earlier',kind:'scan',status:'done'});
 await context.followWorkflowJob();
 assert.equal(context.scanJobId,null);assert.equal(context.sourceManifest.length,0);assert.equal(applied,1);
 // A generic proxy 404, interrupted connection or sign-in prompt may resolve on reconnect.
 for(const reply of [()=>new Response('Proxy',{status:404}),()=>Response.json({reason:'upstream'},{status:404}),
                     ()=>Response.json({reason:'job_expired'},{status:503}),()=>new Response('',{status:401}),()=>{throw Error('Network unavailable');}]){
  const job={kind:'scan',id:'transient'};context.workflowJob=job;context.fetch=reply;
  await context.followWorkflowJob();
  assert.strictEqual(context.workflowJob,job);assert.equal(nodes['reconnect-job'].hidden,false);
 }
 for(const kind of ['build','reference','scan']){
  context.workflowJob={id:'failed',kind};
  context.fetch=async()=>Response.json({id:'failed',kind,status:'failed',progress:{message:'Source could not be read.'}});
  await context.followWorkflowJob();
  assert.equal(context.workflowJob,null);assert.equal(nodes['reconnect-job'].hidden,true);
  assert.match(nodes[kind==='scan'?'scanstatus':'status'].textContent,/Source could not be read/);
 }
 const next={id:'replacement',kind:'scan'};
 context.workflowJob={id:'old',kind:'scan'};context.fetch=async()=>{context.workflowJob=next;return expired();};
 await context.followWorkflowJob();assert.strictEqual(context.workflowJob,next);
 context.clearScanDownload();assert.equal(nodes['download-scan'].hidden,true);assert.ok(!nodes['download-scan'].href);
 console.log('Job completion, original scan export, expiration, transient reconnects and review preservation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
