const fs=require('fs'),vm=require('vm'),assert=require('assert');
const workflow=fs.readFileSync(__dirname+'/abp_workflow.js','utf8');
const nodes={};for(const id of ['reconnect-job','job-status','template-recommendations'])nodes[id]={};
let applied=0,saved=0;const requests=[];
const context=vm.createContext({$:id=>nodes[id],workflowJob:{id:'finished',source_revision:1},workflowSourceRevision:1,
 records:[],diffusers:[],workflowControls:()=>{},readApiJson:async value=>value,
 fetch:async path=>{requests.push(path);return path.endsWith('/result')?{records:[{tag:'AHU-1'}]}:{id:'finished',kind:'scan',status:'done'};},
 applyScanResult:()=>applied++,workflowRecommendations:async()=>{throw Error('Temporary suggestion service failure');},
 workflowSave:()=>saved++,updateWorkspace:()=>{},renderComparison:()=>{},confirm:()=>{throw Error('Unexpected replacement confirmation');}});
vm.runInContext(workflow.slice(workflow.indexOf('async function followWorkflowJob('),workflow.indexOf('function renderComparison(')),context);
(async()=>{
 await context.followWorkflowJob();assert.equal(applied,1);assert.equal(context.workflowJob,null);assert.equal(saved,1);
 assert.equal(nodes['reconnect-job'].hidden,true);assert.match(nodes['job-status'].textContent,/Scan finished/);assert.match(nodes['job-status'].textContent,/scan results are retained/);
 assert.match(nodes['template-recommendations'].textContent,/choose the applicable worksheets/);
 await context.followWorkflowJob();assert.equal(applied,1);assert.equal(requests.length,2);
 console.log('A suggestion failure retains the completed scan and does not replay or replace its review.');
})().catch(error=>{console.error(error);process.exitCode=1;});
