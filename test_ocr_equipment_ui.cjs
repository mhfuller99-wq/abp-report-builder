const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{constructor(){this.children=[];this.attributes={}}append(...x){this.children.push(...x)}replaceChildren(){this.children=[]}setAttribute(k,v){this.attributes[k]=v}}
const box=new Element(),candidate={kind:'equipment',tag:'RTU-1',source:'raster.pdf',page:3,review_values:{design_cfm:3000,esp:.8,motor_watts:999}};
const record={tag:'RTU-1',design_cfm:2625,esp:null,status:'VERIFIED',candidates:[],template:'Air Moving Equipment.xlsx'};
const ctx=vm.createContext({document:{createElement:()=>new Element(),createTextNode:x=>x,querySelectorAll:()=>[]},$:()=>box,imageReview:[candidate],records:[record],diffusers:[],tags:[],savedTagPattern:/^RTU-\d+$/,reviewNumericFields:['design_cfm','esp'],fieldLabel:x=>x,renderReview(){},renderOutlets(){},updateWorkspace(){}});
const source=fs.readFileSync(__dirname+'/abp_server.py','utf8');vm.runInContext(source.slice(source.indexOf('function renderImageReview(){'),source.indexOf('function projectPayload(){')),ctx);
ctx.renderImageReview();let panel=box.children[2];panel.children[4].onclick();assert.equal(record.status,'VERIFIED');
panel.children[3].children[0].checked=true;panel.children[4].onclick();
assert.equal(record.status,'UNVERIFIED');assert.equal(record.design_cfm,2625);assert.equal(record.esp,.8);assert.equal(record.motor_watts,undefined);assert.equal(record.candidates[0].values.design_cfm,3000);
const helper=vm.createContext({});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),helper);
const review={format:'ABP-PREFIELD-REVIEW',version:1,project:'Test',location:'Test',standard:'Commercial',records:[],templates:[],image_review:[{...candidate,review_values:{design_cfm:3000,esp:.8}}]};
assert.equal(helper.validateSavedReview(review,[],{},/^RTU-\d+$/).image_review[0].kind,'equipment');
assert.throws(()=>helper.validateSavedReview({...review,image_review:[candidate]},[],{},/^RTU-\d+$/));
console.log('Raster equipment needs source confirmation, preserves existing inputs, resets verification, and excludes evidence-only motor watts.');
