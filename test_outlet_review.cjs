const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.attributes={}}
 append(...items){this.children.push(...items)}
 replaceChildren(){this.children=[]}
 setAttribute(k,v){this.attributes[k]=v}
}
const box=new Element('div');
const outlets=[{include:false,type:'A',size:'8"',system:'',location:'',design_cfm:225,evidence:'Review duct connection'}];
const context=vm.createContext({document:{createElement:tag=>new Element(tag)},$:()=>box,diffusers:outlets});
const source=fs.readFileSync(__dirname+'/abp_server.py','utf8');
vm.runInContext(source.slice(source.indexOf('function renderOutlets(){'),source.indexOf('async function init(){')),context);
context.renderOutlets();
let row=box.children[2].children[0].children[1];
assert.equal(row.children[0].children[0].checked,false);
const checkbox=row.children[0].children[0];checkbox.checked=true;checkbox.onchange();
assert.equal(outlets[0].include,true);
const room=row.children[4].children[0];room.value='Room 101';room.oninput();
assert.equal(outlets[0].location,'Room 101');
context.renderOutlets();row=box.children[2].children[0].children[1];
assert.equal(row.children[0].children[0].checked,true);
row.children[0].children[0].checked=false;row.children[0].children[0].onchange();
assert.equal(outlets[0].include,false);
console.log('Outlet review: unchecked candidates, inclusion, exclusion and edited rooms persist.');
