const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
const form='Unit Heater ELE.xlsx';
const base={format:'ABP-PREFIELD-REVIEW',version:1,project:'Synthetic',location:'Test',standard:'Commercial',templates:[form],records:[{tag:'EUH-1',status:'UNVERIFIED',template:form,heating_type:'ELECTRIC',heater_volts:240,heater_phase:1,heater_amps:8.3,candidates:[{values:{heater_kw:2,selected_cfm:250},source:'synthetic.pdf',reference:'page 1'}]}]};
const validate=data=>ctx.validateSavedReview(data,[form],{[form]:{}},/^EUH-\d+$/i);
assert.equal(validate(structuredClone(base)).records[0].candidates[0].values.heater_kw,2);
for(const change of [{heater_phase:2},{heater_phase:0},{heater_stages:1.5},{heating_type:'STEAM'},{heater_amps:'not a number'}]){
 const data=structuredClone(base);Object.assign(data.records[0],change);assert.throws(()=>validate(data),/Invalid saved review/);
}
const server=fs.readFileSync(__dirname+'/abp_server.py','utf8');
const start=server.indexOf('function defaultUnitForm('),end=server.indexOf('function applyProposed(',start);
vm.runInContext(server.slice(start,end),ctx);
assert.equal(ctx.defaultUnitForm('EUH-1',{}),'Unit Heater ELE.xlsx');
assert.equal(ctx.defaultUnitForm('GUH-1',{}),'Unit Heater GAS.xlsx');
assert.equal(ctx.defaultUnitForm('UH-1',{heating_type:'HOT WATER'}),'Unit Heater WTR.xlsx');
assert.equal(ctx.defaultUnitForm('UH-1',{}),'');
console.log('Heater UI: typed defaults, saved review/evidence round-trip and invalid electrical values pass.');
