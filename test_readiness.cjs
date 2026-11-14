const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
const server=fs.readFileSync(__dirname+'/abp_server.py','utf8');
vm.runInContext(server.split('\n').find(x=>x.startsWith('function defaultUnitForm(')),ctx);
assert.equal(ctx.defaultUnitForm('PU-7'),'Air Moving Equipment.xlsx');
const state={source_checkpoints:[{name:'synthetic.pdf'}]};
assert(ctx.emptySourceReport([],[],state));
assert(ctx.emptySourceReport([{status:'UNVERIFIED',template:'Air Moving Equipment.xlsx'}],[],state));
assert(!ctx.emptySourceReport([{status:'VERIFIED',template:'Air Moving Equipment.xlsx'}],[],state));
assert(!ctx.emptySourceReport([],[{include:true,design_cfm:100}],state));
assert(!ctx.emptySourceReport([],[],{source_checkpoints:[]}));
let r=ctx.sourceReadiness([],[],[{kind:'diffuser',accepted:false},{kind:'equipment',accepted:true}],{rows:[{status:'missing'},{status:'match'}]});
assert.match(r.title,/Image candidates found/);assert.equal(r.empty,false);assert.equal(r.pendingImages,1);assert.equal(r.problems,1);
assert.equal(r.imageOutlets,1);assert.equal(r.imageEquipment,0);
assert.match(ctx.sourceReadiness([],[],[],null).title,/No equipment or outlets extracted/);
// Image-only outlet extraction must not be advertised as zero candidates.
const imageOutlets=Array.from({length:7},()=>({kind:'diffuser',accepted:false}));
const summary=ctx.scanCandidateSummary([{status:'UNVERIFIED'}],[],[...imageOutlets,{kind:'equipment'},{kind:'kitchen_hood'},{kind:'diffuser',accepted:true}]);
assert.match(summary,/0 outlet review rows/);assert.match(summary,/7 image outlet candidates and 2 image equipment\/hood candidates/);
assert.match(summary,/may overlap existing rows/);assert.match(summary,/not report-ready/);
// Repeated readings do not become an invented unique outlet total or mutate input.
const duplicate={kind:'diffuser',native_outlet_match:true,accepted:false};
assert.match(ctx.scanCandidateSummary([],[{include:false}],[duplicate]),/1 outlet review rows.*1 image outlet candidates/);
assert.equal(duplicate.accepted,false);
assert.match(ctx.reviewCoverage([],[]),/empty takeoff/);
r=ctx.sourceReadiness([{status:'VERIFIED'},{status:'EXCLUDED'},{status:'UNVERIFIED'}],[],[],null);
assert.match(r.title,/1 equipment verified.*1 equipment unresolved/);
console.log('Readiness exposes empty scans, pending images and office mismatches; blank packs remain available.');
