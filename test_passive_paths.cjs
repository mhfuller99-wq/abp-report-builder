const fs=require('fs'),vm=require('vm'),assert=require('assert');
const c=vm.createContext({Blob});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),c);
const state={status:'incomplete',complete_takeoff:false,warnings:[],source_checkpoints:[{name:'synthetic.pdf',sha256:'a'.repeat(64),pages:2,native_status:'completed_native_stage',image_status:'incomplete'}]};
const input={tag:'l-7',source:'synthetic.pdf',page:1,location:'STORAGE',note:'Keynote identifies passive supply inlet; separate exhaust drives makeup.',confirmed:true};
const path=c.makePassivePath(input,state,[],[]);assert.equal(path.status,'UNVERIFIED');assert.equal(path.tag,'L-7');
const p={project:'TEST',location:'TEST',templates:['Supply Diffusers.xlsx'],records:[],air_paths:[path],diffusers:[{type:'SAG-9',system:'L-7',location:'STORAGE',design_cfm:640,source:'synthetic.pdf',reference:'page 1',include:true}],image_review:[],scan_state:state};
const pages=[1,2].map(page=>({source:'synthetic.pdf',sha256:'a'.repeat(64),page,disposition:'reviewed',note:'Checked original source design and physical inventory.'}));
const note='Reviewed original sources; passive path stays separate from motorized equipment.';
assert.throws(()=>c.makeSourceReview(p,pages,note),/Verify every passive/);
path.status='VERIFIED';p.source_review=c.makeSourceReview(p,pages,note);assert(c.sourceReviewApproved(p));
for(const key of ['location','note']){const original=path[key];path[key]='A different source-reviewed value';assert(!c.sourceReviewApproved(p));path[key]=original;}
const recovered=c.reconcileAirPaths([path],['synthetic.pdf']);assert.equal(recovered[0].status,'UNVERIFIED');assert.equal(path.status,'VERIFIED');
assert.equal(recovered[0].source_sha256,path.source_sha256);assert.equal(recovered[0].note,path.note);
assert.equal(c.reconcileAirPaths([path],'other.pdf')[0].status,'VERIFIED');
for(const tag of ['EF-7','RTU-7','AC-7','L-7 ']){const bad={...path,tag};assert(c.airPathErrors({...p,air_paths:[bad]}).length);}
assert.throws(()=>c.makePassivePath(input,state,[],[path]),/unique/);
assert.throws(()=>c.makePassivePath({...input,confirmed:false},state,[],[]),/Confirm/);
assert.throws(()=>c.makePassivePath({...input,page:3},state,[],[]),/source changed/);
assert(c.airPathErrors({...p,air_paths:[{...path,motor_hp:1}]}).length);
assert(c.airPathErrors({...p,air_paths:[{...path,source_sha256:'b'.repeat(64)}]}).length);
assert(!c.sourceReviewApproved({...p,air_paths:null}));
const manual={kind:'outlet',source:'synthetic.pdf',page:2,confirmed:true,note:'Original drawing shows a separate supply opening.',type:'SAG-8',system:'L-7',location:'ROOM B',size:'10X8',locator:'WEST SUPPLY',design_cfm:120};
const added=c.manualSourceEntry(manual,state,[],[],{},/^EF-\d+$/,p.air_paths);assert.equal(added.item.system,'L-7');assert.equal(added.item.include,false);
assert.throws(()=>c.manualSourceEntry(manual,state,[],[],{},/^EF-\d+$/,recovered),/verified passive/);
const saved={format:'ABP-PREFIELD-REVIEW',version:1,standard:'Commercial',...p};
const restored=c.validateSavedReview(JSON.parse(c.serializeSavedReview(saved)),['Supply Diffusers.xlsx'],{},/^EF-\d+$/);
assert.equal(restored.air_paths[0].source_sha256,path.source_sha256);assert.equal(restored.air_paths[0].note,path.note);
assert(c.sourceReviewApproved(restored));
const stale=JSON.parse(JSON.stringify(saved));stale.scan_state.source_checkpoints[0].sha256='b'.repeat(64);
assert.equal(c.validateSavedReview(stale,['Supply Diffusers.xlsx'],{},/^EF-\d+$/).air_paths[0].note,path.note);
assert(!c.sourceReviewApproved(stale));
for(const air_paths of [null,{},[null],[{...path,template:'Air Moving Equipment.xlsx'}]])assert.throws(()=>c.validateSavedReview({...saved,air_paths},['Supply Diffusers.xlsx'],{},/^EF-\d+$/));
// Delayed autosave must retain an unfinished path form while source and path
// inventory are unchanged. Source/review changes intentionally replace it.
const workflow=fs.readFileSync(__dirname+'/abp_workflow.js','utf8');
const code=workflow.slice(workflow.indexOf('function renderPassivePaths('),workflow.indexOf('function renderReadiness('));
const controls=[{value:'L-8',disabled:false},{value:'Draft evidence still being written',disabled:false}];
const panel={dataset:{sourceKey:JSON.stringify([state.source_checkpoints,[path]])},querySelectorAll:()=>controls};let appended;
const ui=vm.createContext({scanState:state,airPaths:[path],workflowBusy:false,workflowElement:()=>{throw Error('draft replaced');}});
vm.runInContext(code,ui);ui.renderPassivePaths({append:p=>{appended=p;}},panel);assert.strictEqual(appended,panel);assert.equal(controls[1].value,'Draft evidence still being written');
ui.workflowBusy=true;ui.renderPassivePaths({append:()=>{}},panel);assert(controls.every(x=>x.disabled));
console.log('Passive paths require source evidence, stay separate from powered units, bind approval, and need re-verification after recovery.');
