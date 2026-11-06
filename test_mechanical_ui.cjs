const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context=vm.createContext({});
vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),context);
assert.equal(context.reviewCoverage([
  {status:'VERIFIED',template:'Air Moving Equipment.xlsx'},
  {status:'UNVERIFIED',template:''},{status:'EXCLUDED',template:''}
],[{include:false},{include:true}]),
'1 equipment entries ready; 1 unresolved. 1 of 2 outlet candidates included. Check source revisions and unresolved entries before field use.');
// Compile all browser code, including nested companion-form markup.
const server=fs.readFileSync(__dirname+'/abp_server.py','utf8');
const begin=server.indexOf('<script>')+8,end=server.indexOf('</script>',begin);
let script=server.slice(begin,end).replace('__UNIT_FORMS_JSON__','{}').replace('__UI_HELPERS__','')
 .replace('__TAG_PATTERN__','".*"').replace('__DEFAULT_PACK_JSON__','[]');
new vm.Script(script);
console.log('Mechanical UI: partial coverage and browser script syntax pass.');
