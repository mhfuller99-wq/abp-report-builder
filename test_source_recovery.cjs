const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
const identities=[{name:'plan.pdf',sha256:'a'.repeat(64)},{name:'selection.pdf',sha256:'b'.repeat(64)}];
assert.equal(ctx.recoverySourceIdentities(identities,[...identities].reverse()).length,2);
for(const actual of [[],identities.slice(1),[identities[0],identities[0]],
 [{...identities[0],sha256:'c'.repeat(64)},identities[1]],
 [...identities,{name:'extra.pdf',sha256:'d'.repeat(64)}]]){
 assert.throws(()=>ctx.recoverySourceIdentities(identities,actual));
}
for(const bad of [null,[],[{name:'../plan.pdf',sha256:'a'.repeat(64)}],[{name:'plan.pdf',sha256:'not-a-hash'}]])assert.throws(()=>ctx.recoverySourceIdentities(bad));
const oldRecord={tag:'AHU-1',source:'plan.pdf',design_cfm:900,motor_hp:1,model:'REVIEWED MODEL',status:'VERIFIED',instance_locations:['ROOM A']};
const missingRecord={tag:'EF-2',source:'selection.pdf',design_cfm:50,status:'VERIFIED'};
const freshRecord={tag:'AHU-1',source:'plan.pdf',design_cfm:1000,motor_hp:2,model:'NEW OBSERVATION',status:'UNVERIFIED',proposed:{design_cfm:1000},candidates:[]};
let result=ctx.reconcileReviewedEquipment([oldRecord,missingRecord],[freshRecord],null,true);
assert.equal(result.length,2);assert.equal(result[0].design_cfm,900);assert.equal(result[0].model,'REVIEWED MODEL');
assert.equal(result[0].proposed.design_cfm,1000);assert.equal(result[0].status,'UNVERIFIED');assert.equal(result[1].status,'UNVERIFIED');
assert(result[1].flags[0].includes('not recovered'));assert.equal(oldRecord.status,'VERIFIED');
const untouched={tag:'EF-3',source:'other.pdf',design_cfm:75,status:'VERIFIED'};
assert.equal(ctx.reconcileReviewedEquipment([untouched],[{...untouched,design_cfm:100}],'plan.pdf')[0].design_cfm,75);
assert.throws(()=>ctx.reconcileReviewedEquipment(Array.from({length:500},(_,i)=>({tag:'OLD-'+i})),[{tag:'NEW-1'}],null,true));
const oldOutlet={source:'plan.pdf',reference:'page 1',position:[30,50],type:'A',design_cfm:150,size:'8',system:'AHU-1',location:'ROOM A',include:true,review_history:[{kind:'batch_assignment',note:'Reviewed original duct connection'}]};
const missingOutlet={...oldOutlet,source:'selection.pdf',position:[60,80]};
const legacyOutlet={...oldOutlet,source:''};
result=ctx.reconcileReviewedOutlets([oldOutlet,missingOutlet,legacyOutlet],[{...oldOutlet,design_cfm:125,size:'6'}],[],identities.map(s=>s.name));
assert.equal(result.length,3);assert(result.every(o=>o.include===false));assert.equal(result[0].design_cfm,150);assert.equal(result[0].size,'8');
assert.equal(result[0].latest_observation.design_cfm,125);assert.equal(result[0].system,'AHU-1');assert.equal(result[0].review_history.length,1);
assert(result[1].review_notice.includes('not recovered'));assert.equal(oldOutlet.include,true);
// Exercise the actual workflow application, including its fail-before-mutation boundary.
const workflow=fs.readFileSync(__dirname+'/abp_workflow.js','utf8');
vm.runInContext(workflow.slice(workflow.indexOf('function applyScanResult('),workflow.indexOf('async function workflowRecommendations(')),ctx);
const nodes={scanstatus:{}};Object.assign(ctx,{
 records:[oldRecord,missingRecord],diffusers:[oldOutlet,missingOutlet],airPaths:[{tag:'L-7',kind:'passive_supply',status:'VERIFIED',source:'plan.pdf',source_sha256:'a'.repeat(64),reference:'page 1',location:'STORAGE',note:'Original plan shows passive louver feeding supply outlets.'}],
 outletBatchUndo:{},outletRepeatUndo:{},$:id=>nodes[id],applyProposed:()=>{},renderScanReview:()=>{},renderReview:()=>{},renderOutlets:()=>{},renderImageReview:()=>{},renderImageCoverage:()=>{},workflowSave:()=>{}
});
vm.runInContext("humanSourceReview={approved:true};humanPageReviews=[{source:'plan.pdf',page:1}];humanReviewNote='SOURCE REVIEW RETAINED';",ctx);
const checkpoints=identities.map(s=>({...s,pages:1,native_status:'completed_native_stage',image_status:'incomplete'}));
const data={records:[freshRecord],diffusers:[{...oldOutlet,design_cfm:125}],scan_status:'incomplete',source_checkpoints:checkpoints,source_manifest:identities,job_id:'f'.repeat(48)};
const current=()=>vm.runInContext('JSON.stringify([records,diffusers,airPaths,humanSourceReview,scanState])',ctx),snapshot=current();
for(const altered of [{...data,source_manifest:undefined},{...data,source_manifest:[{...identities[0],sha256:'e'.repeat(64)},identities[1]]},{...data,source_checkpoints:[]}]){
 assert.throws(()=>ctx.applyScanResult(altered,null,identities));assert.equal(current(),snapshot);
}
ctx.applyScanResult(data,null,identities);
assert.equal(ctx.records[0].design_cfm,900);assert.equal(ctx.records[1].tag,'EF-2');assert.equal(ctx.diffusers[0].design_cfm,150);
assert.equal(vm.runInContext('humanSourceReview',ctx),null);assert.equal(vm.runInContext('humanPageReviews.length',ctx),1);assert.equal(vm.runInContext('humanReviewNote',ctx),'SOURCE REVIEW RETAINED');
assert.equal(ctx.scanJobId,'f'.repeat(48));assert.equal(vm.runInContext('scanState.complete_takeoff',ctx),false);
assert(ctx.records.every(r=>r.status==='UNVERIFIED'));assert(ctx.diffusers.every(o=>o.include===false));
assert.equal(ctx.airPaths[0].status,'UNVERIFIED');assert.equal(ctx.airPaths[0].source_sha256,'a'.repeat(64));
console.log('Hash-bound source recovery preserves reviewed and missing rows, rejects changed sources atomically, and requires fresh approval.');
