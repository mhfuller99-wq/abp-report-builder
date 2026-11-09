const fs=require('fs'), vm=require('vm'), assert=require('assert');
const elements=new Map();const element=id=>{if(!elements.has(id))elements.set(id,{disabled:false,textContent:'',innerHTML:''});return elements.get(id)};
const records=[{tag:'EF-1',status:'VERIFIED',design_cfm:400}],diffusers=[{include:true,design_cfm:100}],imageReview=[{tag:'KH-1'}];
const ctx=vm.createContext({$:element,templatesReady:true,sourceFiles:[{name:'test.pdf'}],records,diffusers,imageReview,tags:['EF-1'],FormData:class {append(){}},
  fetch:async()=>({ok:false,status:400,headers:{get:()=> 'application/json'},json:async()=>({error:'Native scan incomplete: wall time limit',scan_status:'incomplete',complete_takeoff:false})}),
  updateWorkspace(){},renderReview(){throw Error('Review must not be replaced')},renderOutlets(){throw Error('Outlets must not be replaced')},renderImageReview(){throw Error('Image review must not be replaced')}});
vm.runInContext(fs.readFileSync(__dirname+'/abp_ui.js','utf8'),ctx);
const line=fs.readFileSync(__dirname+'/abp_server.py','utf8').split('\n').find(x=>x.startsWith("$('scan').onclick="));vm.runInContext(line,ctx);
(async()=>{await element('scan').onclick();assert.strictEqual(ctx.records,records);assert.strictEqual(ctx.diffusers,diffusers);assert.strictEqual(ctx.imageReview,imageReview);assert.match(element('scanstatus').textContent,/incomplete/);assert.equal(element('scan').disabled,false);assert.equal(element('files').disabled,false);console.log('Failed scan preserves reviewed records, outlets and OCR queue; controls recover.');})().catch(e=>{console.error(e);process.exit(1)});
