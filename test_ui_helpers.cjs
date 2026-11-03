const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ctx=vm.createContext({});
vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
const original={format:'ABP-PREFIELD-REVIEW',version:1,project:'Example',location:'Test',standard:'Commercial',templates:['Air Moving Equipment.xlsx'],records:[{tag:'AHU-1',status:'VERIFIED',design_cfm:1000,osa_cfm:0,candidates:[{values:{design_cfm:1000},source:'schedule.csv',reference:'B2'}]}]};
const validate=data=>ctx.validateSavedReview(data,['Air Moving Equipment.xlsx'],{'Air Moving Equipment.xlsx':{}},/^AHU-\d+$/i);
assert.equal(validate(structuredClone(original)).records[0].osa_cfm,0);
const lowercase=structuredClone(original);lowercase.records[0].tag='ahu-1';
assert.equal(validate(lowercase).records[0].tag,'AHU-1');
for(const mutate of [
 d=>d.records=[null], d=>d.records[0].candidates={},
 d=>d.records[0].candidates=[{values:null}],
 d=>d.records[0].candidates=[{values:{design_cfm:null}}],
 d=>d.records[0].design_cfm=true,
 d=>d.records[0].osa_cfm=2000,
 d=>d.records.push({...d.records[0],tag:'ahu-1'}),
 d=>d.templates=[{}], d=>d.records[0].template='Unknown.xlsx',
 d=>d.records[0].occurrences=[null],
]) {const data=structuredClone(original);mutate(data);assert.throws(()=>validate(data),/current report has not been changed/);}
assert.equal(ctx.worksheetLabel('Exhaust Fans _Std._.xlsx'),'Exhaust Fans Std.');
assert.equal(ctx.worksheetLabel('Exhaust Grilles.xlsx.xlsx'),'Exhaust Grilles');
(async()=>{
 await assert.rejects(()=>ctx.readApiJson({status:401}),/session has expired/);
 await assert.rejects(()=>ctx.readApiJson({status:502,ok:false,json:async()=>{throw Error('HTML')}}),/valid response/);
 await assert.rejects(()=>ctx.readApiJson({status:400,ok:false,json:async()=>({error:'Choose a unit form'})}),/Choose a unit form/);
 assert.equal((await ctx.readApiJson({status:200,ok:true,json:async()=>({ready:true})})).ready,true);
 console.log('UI helper checks passed: saved reviews, zero values, malformed data, worksheet labels, and API errors.');
})().catch(error=>{console.error(error);process.exitCode=1});
