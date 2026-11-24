const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ctx=vm.createContext({Blob});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
const state={status:'incomplete',complete_takeoff:false,warnings:[],source_checkpoints:[{name:'plan.pdf',pages:2,sha256:'a'.repeat(64),native_status:'completed_native_stage',image_status:'incomplete'}]};
const forms={'Air Moving Equipment.xlsx':{},'Exhaust Fans _Std._.xlsx':{}},pattern=/^(RTU|EF)-\d+$/i;
const parent={tag:'RTU-9',status:'VERIFIED',template:'Air Moving Equipment.xlsx',design_cfm:2400,motor_hp:3,motor_volts:460};
const input={kind:'component',component_of:'rtu-9',source:'plan.pdf',page:2,confirmed:true,note:'Schedule separately identifies the integral exhaust fan and its design.'};
const make=(arg=input,records=[parent])=>ctx.manualSourceEntry(arg,state,records,[],forms,pattern);
const row=make().item;assert.equal(row.tag,'RTU-9 EXHAUST');assert.equal(row.status,'UNVERIFIED');
assert.equal(row.template,'Exhaust Fans _Std._.xlsx');assert.equal(row.component_kind,'integral_exhaust');
assert.equal(row.design_cfm,undefined);assert.equal(row.motor_hp,undefined);assert.equal(row.motor_volts,undefined);
assert.equal(row.component_source_sha256,'a'.repeat(64));assert.equal(row.reference,'page 2');
assert.equal(row.review_history[0].kind,'manual_source_entry');
assert.throws(()=>make(input,[parent,row]));
for(const bad of [{...input,confirmed:false},{...input,component_of:'EF-3'},{...input,page:3},{...input,note:'too short'},{...input,component_of:'RTU-10'},{...input,source:'wrong.pdf'}])assert.throws(()=>make(bad));
assert.throws(()=>make(input,[{...parent,quantity:2}]));assert.throws(()=>make(input,[{...parent,quantity:true}]));
const saved={format:'ABP-PREFIELD-REVIEW',version:1,project:'SYNTHETIC',location:'TEST',standard:'Commercial',records:[parent,row],diffusers:[],templates:Object.keys(forms),scan_state:state};
const restored=ctx.validateSavedReview(JSON.parse(ctx.serializeSavedReview(saved)),Object.keys(forms),forms,pattern);
assert.equal(restored.records[1].component_of,'RTU-9');assert.equal(restored.records[1].status,'UNVERIFIED');
for(const field of ['component_of','component_kind','component_source_sha256','component_note']){
 const changed=structuredClone(saved);delete changed.records[1][field];assert.throws(()=>ctx.validateSavedReview(changed,Object.keys(forms),forms,pattern));
}
const reviewed=structuredClone(saved);reviewed.records[1].status='VERIFIED';reviewed.records[1].design_cfm=630;
const pages=[1,2].map(page=>({source:'plan.pdf',sha256:'a'.repeat(64),page,disposition:'reviewed',note:'Checked all source content and separate fan data.'}));
reviewed.source_review=ctx.makeSourceReview(reviewed,pages,'All relevant source pages checked; unspecified component motor ratings remain blank.');
assert(ctx.sourceReviewApproved(reviewed));
assert.match(ctx.reviewCoverage(reviewed.records,[]),/^1 equipment entries ready; 1 linked component forms ready/);
assert.match(ctx.sourceReadiness(reviewed.records,[],[],null).title,/^1 equipment verified · 1 linked component forms verified/);
for(const key of ['component_of','component_kind','component_source_sha256','component_note']){
 const changed=structuredClone(reviewed);changed.records[1][key]+=' changed';assert(!ctx.sourceReviewApproved(changed));
}
const retried=ctx.reconcileReviewedEquipment(reviewed.records,[{...parent,status:'UNVERIFIED',candidates:[]}],'plan.pdf');
assert.equal(retried[1].status,'UNVERIFIED');assert.equal(retried[1].component_of,'RTU-9');assert.equal(retried[1].design_cfm,630);
assert(!ctx.sourceReviewApproved({...reviewed,records:retried}));
assert(ctx.equipmentComponentErrors({...reviewed,scan_state:{...state,source_checkpoints:[{...state.source_checkpoints[0],sha256:'b'.repeat(64)}]}}).length);
console.log('Linked components: derived labels, independent blank values, strict parent/source binding, save/restore, retry invalidation and approval checks passed.');
