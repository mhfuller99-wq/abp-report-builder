const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ctx=vm.createContext({Blob});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
const candidate={kind:'kitchen_hood',tag:'KH-1',source:'drawing.pdf',page:1,review_values:{exhaust_cfm:2400,makeup_air_cfm:1800},evidence_text:'Hood source evidence',review_reasons:['Check source and duplicates.'],evidence_boxes:Array.from({length:100},()=>[123.456,234.567,345.678,456.789])};
const ordinary={tag:'AHU-1',status:'UNVERIFIED',template:'Air Moving Equipment.xlsx',design_cfm:1000,candidates:[{values:{design_cfm:1000},source:'schedule.pdf',reference:'page 2',evidence:'AHU-1 1000 CFM'}]};
const project={format:'ABP-PREFIELD-REVIEW',version:1,project:'Near limit',location:'Test',standard:'Commercial',templates:['Air Moving Equipment.xlsx'],records:[ordinary],diffusers:[],image_review:Array.from({length:480},(_,i)=>({...candidate,tag:'KH-'+(i+1)}))};
const validate=data=>ctx.validateSavedReview(data,project.templates,{'Air Moving Equipment.xlsx':{}},/^(?:AHU|KH)-\d+$/);
(async()=>{
 const compact=ctx.serializeSavedReview(project),pretty=JSON.stringify(project,null,2);
 assert(new Blob([compact]).size>1700000);assert(new Blob([compact]).size<2000000);assert(new Blob([pretty]).size>2000000);
 const restored=validate(await ctx.parseSavedReviewFile(new Blob([compact])));
 assert.equal(restored.records[0].design_cfm,1000);assert.equal(restored.image_review.length,480);assert.equal(restored.image_review[479].tag,'KH-480');
 // Exact total-project byte boundary, including ordinary equipment and multibyte evidence.
 const exact=structuredClone(project);exact.padding='';const base=new Blob([ctx.serializeSavedReview(exact)]).size;exact.padding='x'.repeat(2000000-base);
 const exactText=ctx.serializeSavedReview(exact);assert.equal(new Blob([exactText]).size,2000000);validate(await ctx.parseSavedReviewFile(new Blob([exactText])));
 exact.padding+='x';assert.throws(()=>ctx.serializeSavedReview(exact),/exceeds 2 MB/);await assert.rejects(()=>ctx.parseSavedReviewFile(new Blob([JSON.stringify(exact)])),/exceeds 2 MB/);
 exact.padding=exact.padding.slice(0,-1)+'é';assert.throws(()=>ctx.serializeSavedReview(exact),/exceeds 2 MB/);
 // Actual Save handler must not create a URL/download after rejecting an oversized total.
 const source=fs.readFileSync(__dirname+'/abp_server.py','utf8');const nodes={saveproject:{},status:{}};let downloads=0;
 Object.assign(ctx,{$:id=>nodes[id],projectPayload:()=>exact,URL:{createObjectURL(){downloads++;throw Error('Unexpected download')}},document:{},setTimeout});
 vm.runInContext(source.slice(source.indexOf("$('saveproject').onclick="),source.indexOf("$('loadproject').onchange=")),ctx);
 ctx.$('saveproject').onclick();assert.equal(downloads,0);assert.match(nodes.status.textContent,/exceeds 2 MB/);
 console.log(`Review size: ${new Blob([compact]).size}-byte compact project (${new Blob([pretty]).size} pretty) round-trips with ordinary records; exact-limit, Unicode bytes and guarded Save pass.`);
})().catch(error=>{console.error(error);process.exitCode=1});
