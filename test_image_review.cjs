const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.checked=false}append(...x){this.children.push(...x)}replaceChildren(){this.children=[]}setAttribute(k,v){this.attributes[k]=v}}
const box=new Element('div');const candidates=[{kind:'kitchen_hood',tag:'KH-1',source:'synthetic.pdf',page:1,review_values:{exhaust_cfm:2400,makeup_air_cfm:1800},evidence_text:'KH-1 2400 1800'}];
const ctx=vm.createContext({document:{createElement:x=>new Element(x),createTextNode:x=>x,querySelectorAll:()=>[]},$:()=>box,imageReview:candidates,records:[],diffusers:[],tags:[],savedTagPattern:/^KH-\d+$/,fieldLabel:x=>x,renderReview(){},renderOutlets(){},updateWorkspace(){}});
const source=fs.readFileSync(__dirname+'/abp_server.py','utf8');
vm.runInContext(source.slice(source.indexOf('function renderImageReview(){'),source.indexOf('function projectPayload(){')),ctx);
ctx.renderImageReview();let panel=box.children[2];let button=panel.children[4];button.onclick();assert.equal(ctx.records.length,0);assert.match(panel.children[5].textContent,/confirm/);
panel.children[3].children[0].checked=true;button.onclick();assert.equal(ctx.records.length,1);assert.equal(ctx.records[0].design_cfm,2400);assert.equal(ctx.records[0].osa_cfm,undefined);assert.equal(ctx.records[0].status,'UNVERIFIED');assert.equal(ctx.records[0].candidates.length,0);
// A second source does not overwrite a previously reviewed record.
candidates.push({...candidates[0],accepted:false});ctx.renderImageReview();panel=box.children[3];panel.children[3].children[0].checked=true;panel.children[4].onclick();assert.equal(ctx.records.length,1);assert.match(panel.children[5].textContent,/already exists/);
candidates.push({kind:'diffuser',tag:'',source:'test',page:2,type:'A',size:'8"',review_values:{design_cfm:225}});ctx.renderImageReview();panel=box.children[4];panel.children[3].children[0].checked=true;panel.children[4].onclick();assert.equal(ctx.diffusers[0].include,false);assert.equal(ctx.diffusers[0].system,'');assert.equal(ctx.diffusers[0].location,'');
console.log('Image review: explicit source confirmation, no auto-verification, distinct makeup air, duplicate protection, unchecked outlets.');
const helper=vm.createContext({});vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),helper);
const saved={format:'ABP-PREFIELD-REVIEW',version:1,project:'Test',location:'Test',standard:'Commercial',records:[],templates:[],image_review:candidates};
assert.equal(helper.validateSavedReview(saved,[],{},/^KH-\d+$/).image_review.length,3);
assert.throws(()=>helper.validateSavedReview({...saved,image_review:[{...candidates[0],review_values:{exhaust_cfm:Infinity}}]},[],{},/^KH-\d+$/));
assert.throws(()=>helper.validateSavedReview({...saved,image_review:[{...candidates[0],review_reasons:'not an array'}]},[],{},/^KH-\d+$/));
console.log('Image queue saved-review round trip and malformed queue rejection pass.');
