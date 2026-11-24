const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync(__dirname+'/abp_workflow.js','utf8');
const nodes={};for(const id of ['source-preview','source-preview-status','source-preview-retry','source-preview-large','source-view-title','source-viewer','source-review-layout'])nodes[id]={hidden:false,removeAttribute(k){delete this[k];},classList:{add(){},remove(){}},scrollIntoView(){}};
let fetcher,created=0;const revoked=[];
const context=vm.createContext({$:id=>nodes[id],sourceIndex:()=>0,scanJobId:'scan-job',AbortController,
 fetch:(...args)=>fetcher(...args),URL:{createObjectURL:()=>`blob:preview-${++created}`,revokeObjectURL:url=>revoked.push(url)}});
vm.runInContext(script.slice(script.indexOf('let sourcePreviewRevision='),script.indexOf('function renderOutletTotals(')),context);
const response=(status,detail={},type='application/json')=>({status,ok:status===200,headers:{get:()=>type},json:async()=>detail,blob:async()=>({})});
(async()=>{
 fetcher=async()=>response(503,{reason:'processing_busy'});await context.viewSource('plan.pdf');
 assert.match(nodes['source-preview-status'].textContent,/processing is running/);assert.doesNotMatch(nodes['source-preview-status'].textContent,/Recover|expired/);
 assert.equal(nodes['source-preview-retry'].hidden,false);assert.equal(nodes['source-preview-large'].hidden,true);
 fetcher=async()=>response(200,{},'image/png');await nodes['source-preview-retry'].onclick();nodes['source-preview'].onload();
 assert.match(nodes['source-preview-status'].textContent,/full drawing/);assert.equal(nodes['source-preview-large'].href,'blob:preview-1');
 let resolveOld;fetcher=()=>new Promise(resolve=>resolveOld=resolve);const stale=context.viewSource('old.pdf');
 fetcher=async()=>response(404);await context.viewSource('new.pdf');assert.deepEqual(revoked,['blob:preview-1']);
 resolveOld(response(200,{},'image/png'));await stale;
 assert.match(nodes['source-preview-status'].textContent,/Recover sources/);assert.equal(nodes['source-preview'].src,undefined);assert.equal(created,1);
 fetcher=async()=>response(401);await context.viewSource('plan.pdf');assert.match(nodes['source-preview-status'].textContent,/Sign in again/);
 fetcher=async()=>response(200,{},'text/html');await context.viewSource('plan.pdf');assert.equal(nodes['source-preview'].src,undefined);
 fetcher=async()=>{throw Error('Connection interrupted');};await context.viewSource('plan.pdf');assert.equal(nodes['source-preview-retry'].hidden,false);
 fetcher=async()=>response(200,{},'image/png');await context.viewSource('plan.pdf');nodes['source-preview'].onerror();assert.match(nodes['source-preview-status'].textContent,/could not be displayed/);
 context.clearSourcePreview();assert.equal(nodes['source-preview'].src,undefined);assert.equal(nodes['source-preview-large'].href,undefined);assert.equal(nodes['source-preview-retry'].hidden,true);assert.equal(revoked.length,2);
 console.log('Source preview: busy versus expired, retry, authentication, stale response, image failure and object URL cleanup passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
