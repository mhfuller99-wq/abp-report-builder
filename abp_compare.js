// The office workbook stays on this device. No fetch, upload, or actual-value import.
const compareNormalize=x=>String(x??'').toUpperCase().replace(/[^A-Z0-9]+/g,' ').trim();
const compareTag=x=>String(x??'').trim().toUpperCase().replace(/\s*-\s*|\s+/g,'-');
const compareIsTag=x=>/^[A-Z]{1,10}-\d+[A-Z0-9.-]*$/.test(compareTag(x));
const compareNumber=x=>typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=1000000?x:null;
function compareField(label){
 const key=compareNormalize(label);
 if(/\b(ACTUAL|MEASURED|INITIAL|FINAL|TEST)\b/.test(key))return null;
 return ({'TOTAL AIRFLOW CFM':'design_cfm','TOTAL CFM':'design_cfm','DESIGN CFM':'design_cfm','CFM':'design_cfm','SUPPLY CFM':'design_cfm','HEATING CFM':'heating_cfm',
 'OSA AIRFLOW CFM':'osa_cfm','OSA CFM':'osa_cfm','OUTSIDE AIR CFM':'osa_cfm','OSA AIRFLOW MIN CFM':'osa_min_cfm','OSA AIRFLOW MAX CFM':'osa_cfm',
 'EXTERNAL S P IN W C':'esp','EXTERNAL S P':'esp','ESP':'esp','TOTAL S P IN W C':'total_sp','DESIGN GPM':'design_gpm','GPM':'design_gpm'})[key]||null;
}
function officeDesignFromSheets(sheets){
 const units=new Map(),outlets=[],warnings=[];
 for(const sheet of sheets){
  const rows=sheet.rows,at=(r,c)=>rows[r]?.[c]??null;
  const unitRows=rows.flatMap((row,i)=>row.some(v=>['UNIT DESIGNATION','COIL DESIGNATION','UNIT ID'].includes(compareNormalize(v)))?[i]:[]);
  unitRows.forEach((start,index)=>{
   const end=unitRows[index+1]??Math.min(rows.length,start+45);
   rows[start].forEach((value,col)=>{
    if(!compareIsTag(value))return;
    const tag=compareTag(value);if(!units.has(tag))units.set(tag,{tag,values:{},references:{}});
    const unit=units.get(tag);const header=Array.from({length:Math.min(end,start+19)-start-1},(_,j)=>start+j+1).find(r=>compareNormalize(at(r,col))==='DESIGN');
    for(let r=header===undefined?start+1:header+1;r<(header===undefined?Math.min(end,start+6):end);r++){
     const label=(rows[r]||[]).slice(0,col).find(x=>x!=null&&String(x).trim());
     let field=compareField(label);const number=compareNumber(at(r,col));
     if(compareNormalize(label)==='CFM'&&/^UNIT HEATER\b/.test(compareNormalize(sheet.name)))field='heating_cfm';
     if(!field||number===null||header===undefined&&compareNormalize(label)!=='DESIGN CFM')continue;
     if(unit.values[field]!==undefined&&unit.values[field]!==number){delete unit.values[field];unit.conflict=true;warnings.push(tag+' has conflicting office design values for '+field);continue;}
     if(unit.conflict)continue;
     unit.values[field]=number;unit.references[field]=sheet.name+' · row '+(r+1)+' · column '+(col+1);
    }
   });
  });
  if(!compareNormalize(sheet.name).startsWith('SUPPLY DIFFUSERS'))continue;
  let system='';
  for(let r=0;r<rows.length;r++){
   const row=rows[r]||[];
   // Room labels (LOBBY 101) can look like unit tags. A numbered outlet row
   // takes precedence; only a standalone header can change the system.
   const outletRow=compareNumber(row[2])!==null&&typeof row[3]==='string'&&compareNumber(row[6])!==null;
   if(!outletRow&&compareIsTag(row[0])&&row.slice(1).every(v=>v==null||String(v).trim()==='')){system=compareTag(row[0]);continue;}
   // Original ABP supply form: outlet number C, type D, neck E, DESIGN G.
   // F/H are never inspected: those are initial/actual readings.
   if(compareNumber(row[2])===null||typeof row[3]!=='string'||compareNumber(row[6])===null)continue;
   outlets.push({system,type:row[3].trim().toUpperCase(),size:String(row[4]??''),location:String(row[0]??''),design_cfm:row[6],reference:sheet.name+' · row '+(r+1)});
  }
 }
 if(!units.size&&!outlets.length)throw Error('No supported ABP design panels found. This layout needs manual comparison; no values were imported.');
 for(const unit of units.values())if(!Object.keys(unit.values).length)warnings.push(unit.tag+': office design cells could not be read; manual comparison is required.');
 return {units:[...units.values()],outlets,warnings};
}
function compareSize(value){return String(value??'').toUpperCase().replace(/["Øø\s]/g,'');}
function compareOfficeDesign(office,records,outlets){
 const rows=[],current=new Map(records.map(r=>[compareTag(r.tag),r]));
 for(const unit of office.units){
  const record=current.get(unit.tag);
  if(!record){rows.push({item:unit.tag,field:'Equipment ID',office:'Present',builder:'Missing',status:'missing',reference:Object.values(unit.references)[0]||''});continue;}
  if(!Object.keys(unit.values).length)rows.push({item:unit.tag,field:'Office design coverage',office:'No supported design values read',builder:record.status,status:'unresolved',reference:'Manual office comparison required'});
  for(const [field,value] of Object.entries(unit.values)){
   const raw=record[field],actual=raw===undefined||raw===null||raw===''?null:Number(raw);
   rows.push({item:unit.tag,field:fieldLabel(field),office:value,builder:actual??'Blank',status:actual===null?'missing':actual!==value?'different':record.status!=='VERIFIED'?'unverified':'match',reference:unit.references[field]});
  }
 }
 for(const r of records)if(!office.units.some(u=>u.tag===compareTag(r.tag)))rows.push({item:r.tag,field:'Equipment ID',office:'Missing',builder:r.status,status:'different',reference:'IDs are compared exactly; MAU and MUA are not assumed identical.'});
 const unused=new Set(outlets.map((_,i)=>i));
 for(const [n,expected] of office.outlets.entries()){
  const candidates=[...unused].filter(i=>compareTag(outlets[i].system)===expected.system&&String(outlets[i].type).toUpperCase()===expected.type);
  candidates.sort((a,b)=>{
   const score=i=>(Number(outlets[i].design_cfm)===expected.design_cfm?0:4)+(compareSize(outlets[i].size)===compareSize(expected.size)?0:1);
   return score(a)-score(b);
  });
  const index=candidates[0],actual=outlets[index];if(actual)unused.delete(index);
  const label=expected.system+' outlet '+(n+1)+' ('+expected.type+')';
  if(!actual){rows.push({item:label,field:'Supply outlet',office:expected.design_cfm+' CFM',builder:'Missing/unassigned',status:'missing',reference:expected.reference});continue;}
  for(const [field,oldValue,newValue] of [['Design CFM',expected.design_cfm,actual.design_cfm],['Neck size',expected.size,actual.size]]){
   const same=field==='Neck size'?compareSize(oldValue)===compareSize(newValue):Number(oldValue)===Number(newValue);
   rows.push({item:label,field,office:oldValue,builder:newValue??'Blank',status:actual.include===false?'excluded':same?'match':'different',reference:expected.reference});
  }
 }
 for(const i of unused)rows.push({item:'Builder outlet '+(i+1),field:'Supply outlet',office:'Missing/unmatched',builder:(outlets[i].system||'Unassigned')+' · '+(outlets[i].design_cfm??'Blank')+' CFM',status:'different',reference:outlets[i].source||''});
 return {rows,warnings:office.warnings,office_total:office.outlets.reduce((n,o)=>n+o.design_cfm,0),builder_total:outlets.filter(o=>o.include!==false).reduce((n,o)=>n+Number(o.design_cfm||0),0)};
}
async function readLocalOfficeWorkbook(file){
 if(!file||file.size>8000000||!/\.xlsx$/i.test(file.name))throw Error('Choose a macro-free .xlsx office report smaller than 8 MB. It stays on this device.');
 const bytes=new Uint8Array(await file.arrayBuffer()),view=new DataView(bytes.buffer);let eocd=-1;
 for(let i=bytes.length-22;i>=Math.max(0,bytes.length-65557);i--)if(view.getUint32(i,true)===0x06054b50){eocd=i;break;}
 if(eocd<0)throw Error('Invalid XLSX archive');
 const count=view.getUint16(eocd+10,true),start=view.getUint32(eocd+16,true);
 if(count>2048||view.getUint16(eocd+4,true)!==0||view.getUint16(eocd+6,true)!==0)throw Error('Workbook archive is unsupported');
 let offset=start,total=0;const entries=new Map(),decode=new TextDecoder();
 for(let i=0;i<count;i++){
  if(offset+46>bytes.length||view.getUint32(offset,true)!==0x02014b50)throw Error('Invalid XLSX directory');
  const flags=view.getUint16(offset+8,true),method=view.getUint16(offset+10,true),compressed=view.getUint32(offset+20,true),size=view.getUint32(offset+24,true),nameLen=view.getUint16(offset+28,true),extra=view.getUint16(offset+30,true),comment=view.getUint16(offset+32,true),local=view.getUint32(offset+42,true);
  const name=decode.decode(bytes.slice(offset+46,offset+46+nameLen));offset+=46+nameLen+extra+comment;
  total+=size;if(total>50000000||size>25000000||flags&1||compressed===0xffffffff||size===0xffffffff)throw Error('Workbook exceeds local comparison limits');
  if(name.includes('vbaProject'))throw Error('Use a macro-free XLSX workbook');
  if(!/^(xl\/(workbook\.xml|_rels\/workbook\.xml\.rels|sharedStrings\.xml|worksheets\/sheet\d+\.xml))$/.test(name))continue;
  if(entries.has(name))throw Error('Duplicate workbook part');
  entries.set(name,{method,compressed,size,local});
 }
 const xml=async name=>{
  const e=entries.get(name);if(!e)return null;
  if(e.local+30>bytes.length||view.getUint32(e.local,true)!==0x04034b50)throw Error('Invalid worksheet part');
  const begin=e.local+30+view.getUint16(e.local+26,true)+view.getUint16(e.local+28,true);
  if(begin+e.compressed>bytes.length)throw Error('Truncated worksheet');
  let output=bytes.slice(begin,begin+e.compressed);
  if(e.method===8){
   let stream;try{stream=new Blob([output]).stream().pipeThrough(new DecompressionStream('deflate-raw'));}catch{throw Error('This browser cannot read XLSX locally. Use an updated Chrome or Edge browser.');}
   const reader=stream.getReader(),chunks=[];let length=0;
   while(true){const part=await reader.read();if(part.done)break;length+=part.value.length;if(length>e.size||length>25000000){await reader.cancel();throw Error('Expanded worksheet exceeds its declared size');}chunks.push(part.value);}
   output=new Uint8Array(length);let cursor=0;for(const chunk of chunks){output.set(chunk,cursor);cursor+=chunk.length;}
  }else if(e.method!==0)throw Error('Unsupported workbook compression');
  if(output.length!==e.size)throw Error('Invalid expanded worksheet size');
  const text=decode.decode(output);if(/<!DOCTYPE|<!ENTITY/i.test(text))throw Error('Unsupported XML declarations');
  const doc=new DOMParser().parseFromString(text,'application/xml');if(doc.querySelector('parsererror'))throw Error('Invalid workbook XML');return doc;
 };
 const nodes=(root,name)=>[...root.getElementsByTagNameNS('*',name)];
 const strings=await xml('xl/sharedStrings.xml'),shared=strings?nodes(strings,'si').map(si=>nodes(si,'t').map(t=>t.textContent).join('')):[];
 const book=await xml('xl/workbook.xml'),rels=await xml('xl/_rels/workbook.xml.rels');if(!book||!rels)throw Error('Workbook definition missing');
 const targets=new Map(nodes(rels,'Relationship').filter(r=>r.getAttribute('TargetMode')!=='External').map(r=>[r.getAttribute('Id'),r.getAttribute('Target').replace(/^\/xl\//,'').replace(/^xl\//,'')]));
 const sheets=[];let cells=0;
 for(const sheet of nodes(book,'sheet')){
  const target=targets.get(sheet.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships','id')||sheet.getAttribute('r:id'));if(!target||target.includes('..'))continue;
  const doc=await xml('xl/'+target);if(!doc)continue;const rows=[];
  for(const cell of nodes(doc,'c')){
   if(++cells>200000)throw Error('Workbook has too many cells for local comparison');
   const match=/^([A-Z]{1,3})(\d+)$/.exec(cell.getAttribute('r')||'');if(!match||nodes(cell,'f').length)continue;
   let col=0;for(const char of match[1])col=col*26+char.charCodeAt(0)-64;
   const row=Number(match[2]);if(row>20000||col>200)throw Error('Workbook layout exceeds comparison limits');
   const raw=nodes(cell,'v')[0]?.textContent,type=cell.getAttribute('t');let value=null;
   if(type==='s')value=shared[Number(raw)]??'';
   else if(type==='inlineStr')value=nodes(cell,'t').map(t=>t.textContent).join('');
   else if(raw!==undefined&&type!=='e')value=type==='str'?raw:Number(raw);
   if(value!==null){rows[row-1]??=[];rows[row-1][col-1]=value;}
  }
  sheets.push({name:sheet.getAttribute('name'),rows:Array.from({length:rows.length},(_,i)=>rows[i]||[])});
 }
 return officeDesignFromSheets(sheets);
}
