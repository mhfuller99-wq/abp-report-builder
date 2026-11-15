const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ctx=vm.createContext({Blob});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
const state={status:'incomplete',complete_takeoff:false,warnings:[],source_checkpoints:[{name:'plan.pdf',pages:2,sha256:'a'.repeat(64),native_status:'completed_native_stage',image_status:'incomplete'}]};
const forms={'Air Moving Equipment.xlsx':{}},parent={tag:'RTU-6',template:'Air Moving Equipment.xlsx',status:'VERIFIED',design_cfm:2700,osa_cfm:550};
const input={kind:'supply_fans',component_of:'RTU-6',supply_fan_count:'2',source:'plan.pdf',page:2,confirmed:true,note:'Original schedule specifies two supply fans with individual motor horsepower.'};
const make=(i=input,rs=[parent])=>ctx.manualSourceEntry(i,state,rs,[],forms,/^RTU-\d+$/);
const before=JSON.stringify([parent,input,state]),entry=make();assert.equal(JSON.stringify([parent,input,state]),before);
assert.equal(entry.kind,'equipment_group');assert.equal(entry.records.length,3);assert.equal(entry.records[0].supply_fan_count,2);assert.equal(entry.records[0].design_cfm,2700);
assert(entry.records.every(r=>r.status==='UNVERIFIED'));
for(const [n,r] of entry.records.slice(1).entries()){
 assert.equal(r.tag,'RTU-6 SUPPLY FAN '+(n+1));assert.equal(r.component_index,n+1);assert.equal(r.component_count,2);assert.equal(r.coil_template,'');
 assert.equal(r.design_cfm,undefined);assert.equal(r.osa_cfm,undefined);assert.equal(r.motor_hp,undefined);assert.equal(r.component_source_sha256,'a'.repeat(64));
}
for(const changes of [{supply_fan_count:true},{supply_fan_count:'2.5'},{supply_fan_count:1},{supply_fan_count:21},{component_of:'RTU-8'},{note:'ok'},{confirmed:false}])assert.throws(()=>make({...input,...changes}));
assert.throws(()=>make(input,[{...parent,motor_hp:2}]));assert.throws(()=>make(input,entry.records));
const saved={format:'ABP-PREFIELD-REVIEW',version:1,project:'SYNTHETIC',location:'TEST',standard:'Commercial',records:entry.records,diffusers:[],templates:Object.keys(forms),scan_state:state};
const restored=ctx.validateSavedReview(JSON.parse(ctx.serializeSavedReview(saved)),Object.keys(forms),forms,/^RTU-\d+$/);
assert.equal(restored.records[0].supply_fan_count,2);assert.equal(restored.records[2].component_index,2);
for(const r of restored.records){r.status='VERIFIED';if(r.component_kind==='integral_supply')r.motor_hp=2;}
const pages=[1,2].map(page=>({source:'plan.pdf',sha256:'a'.repeat(64),page,disposition:'reviewed',note:'Reviewed source fan count and individual motor data.'}));
restored.source_review=ctx.makeSourceReview(restored,pages,'Reviewed complete equipment and all physical fan motor forms.');
assert(ctx.sourceReviewApproved(restored));assert.match(ctx.reviewCoverage(restored.records,[]),/^1 equipment entries ready; 2 linked component forms/);
for(const mutate of [p=>p.records.splice(1,1),p=>p.records.splice(1,2),p=>p.records[0].supply_fan_count=3,p=>p.records[1].component_index=2,p=>p.records[1].component_source_sha256='b'.repeat(64),p=>p.records[1].reference='page 1',p=>p.records[1].design_cfm=1350,p=>p.records[1].coil_template='Coil DX GAS HT.xlsx',p=>p.records[1].status='EXCLUDED',p=>p.records[0].motor_hp=2]){
 const changed=structuredClone(restored);mutate(changed);assert(ctx.equipmentComponentErrors(changed).length);assert(!ctx.sourceReviewApproved(changed));
}
const retry=ctx.reconcileReviewedEquipment(restored.records,[{...parent,status:'UNVERIFIED',candidates:[]}],'plan.pdf');
assert.equal(retry.length,3);assert.equal(retry[0].supply_fan_count,2);assert.equal(retry[1].component_count,2);assert.equal(retry[2].component_index,2);assert(retry.every(r=>r.status==='UNVERIFIED'));
const fanOutlet={kind:'outlet',source:'plan.pdf',page:1,confirmed:true,note:'Original supply duct traced',type:'A',design_cfm:100,system:'RTU-6 SUPPLY FAN 1',location:'ROOM A',size:'6',locator:'NORTH'};
assert.throws(()=>ctx.manualSourceEntry(fanOutlet,state,restored.records,[],forms,/^RTU-\d+$/));
console.log('Multiple supply motors preserve one parent, count witness, complete indexed membership, blank unassigned values, drafts and retry provenance; coils/flows cannot attach to motor forms.');
