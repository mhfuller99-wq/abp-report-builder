const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/abp_server.py','utf8');
const elements=new Map();const $=id=>{if(!elements.has(id))elements.set(id,{value:'Project',disabled:false,textContent:'',innerHTML:'',setAttribute(){},removeAttribute(){}});return elements.get(id)};
let requests=0;
const ctx=vm.createContext({$,Blob,templatesReady:true,records:[{tag:'EF-1',status:'VERIFIED'}],tags:['EF-1'],diffusers:[],imageReview:[],imageCoverage:[],imageCoverageTruncated:false,sourceFiles:[{name:'broken.pdf'}],FormData:class{append(){}},document:{querySelectorAll(){return []}},renderImageCoverage(){},renderImageReview(){},renderReview(){},renderOutlets(){},renderSourceFiles(){},updateWorkspace(){},applyProposed(){},confirm(){return true},fetch:async()=>{requests++;if(requests===1)return {ok:true,json:async()=>({scan_status:'incomplete',complete_takeoff:false,records:[{tag:'EF-2'}],tags:['EF-2'],warnings:['broken.pdf failed'],source_checkpoints:[{name:'broken.pdf',native_status:'incomplete',image_status:'not_started'}]})};throw Error('suggest failed')}});
vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
for(const prefix of ['function sourcesChanged()','function projectPayload()',"$('scan').onclick=","$('generate').onclick="])vm.runInContext(source.split('\n').find(s=>s.startsWith(prefix)),ctx);
(async()=>{
 const before=ctx.records;ctx.sourcesChanged();assert.strictEqual(ctx.records,before);assert.equal(vm.runInContext('scanState.status',ctx),'stale');
 await $('scan').onclick();assert.equal(ctx.records[0].tag,'EF-2');assert.match($('scanstatus').textContent,/SOURCE SCAN INCOMPLETE/);assert.match($('scanstatus').textContent,/suggest failed/);
 const payload=ctx.projectPayload();assert.equal(payload.scan_state.status,'incomplete');assert.equal(payload.scan_state.source_checkpoints[0].name,'broken.pdf');const restored=JSON.parse(ctx.serializeSavedReview(payload));assert.equal(ctx.validateScanState(restored.scan_state).status,'incomplete');
 $('buildmethod').value='sources';await $('generate').onclick();assert.equal(requests,2);assert.match($('status').textContent,/rescan/);
 assert(ctx.scanStateBlocked(ctx.validateScanState(undefined)));assert.throws(()=>ctx.validateScanState({status:'review_required',complete_takeoff:true}));
 assert(ctx.scanStateBlocked({status:'review_required',source_checkpoints:[{native_status:'incomplete',image_status:'not_started'}]}));
 console.log('Persistent scan state, source-change preservation, recommendation failure, save round trip, legacy state and build block passed.');
})().catch(e=>{console.error(e);process.exit(1)});
