"""Bounded private jobs for a single-instance deployment.

Authenticated, unguessable job URLs reconnect after browser refresh. Temporary
source files expire after two hours and do not survive an ephemeral-host restart.
The browser separately saves the review; no public bucket or new service needed.
"""
import copy, gc, hashlib, json, os, re, secrets, shutil, tempfile, threading, time
from contextlib import ExitStack
from pathlib import Path
from abp_limits import mark_staging

TTL=2*60*60
MAX_RETAINED_BYTES=350_000_000
MAX_JOBS=24

def write_json(path,value):
    data=json.dumps(value,allow_nan=False).encode('utf-8')
    if len(data)>8_000_000:raise ValueError('Job result is too large; use fewer source documents')
    tmp=path.with_suffix('.tmp');tmp.write_bytes(data);os.replace(tmp,path)

def page_of(item):
    if type(item.get('page')) is int:return item['page']
    found=re.search(r'\bpage (\d+)\b',str(item.get('reference','')))
    return int(found[1]) if found else None

def merge_pages(old,new,pages,kind):
    if not old or pages is None:return new
    result=dict(old)
    if kind=='native':
        for field in ('candidates','outlets'):
            result[field]=[r for r in old.get(field,[]) if page_of(r) not in pages]+new.get(field,[])
        contexts=set(old.get('context_pages',[]))
        if old.get('status')=='completed_native_stage':contexts.update(range(1,old.get('pages',0)+1))
        if new.get('status')=='completed_native_stage':contexts.update(pages)
        result['context_pages']=sorted(contexts)
        result['completed_pages']=sorted(set(old.get('completed_pages',[]))|set(new.get('completed_pages',[])))
        result['status']='completed_native_stage' if len(contexts)==old.get('pages') else 'incomplete'
        result['partial_native']=result['status']=='incomplete'
        result['warnings']=list(dict.fromkeys([w for w in old.get('warnings',[]) if not any(f'page {p} ' in w for p in pages)]+new.get('warnings',[])))
        if result['status']=='completed_native_stage':
            result.pop('reason',None)
            result['warnings']=[w for w in result['warnings'] if not w.startswith(('Native scan incomplete:','Native page results preserved;'))]
    else:
        result['review_candidates']=[r for r in old.get('review_candidates',[]) if page_of(r) not in pages]+new.get('review_candidates',[])
        coverage={c['page']:c for c in old.get('coverage',[])}
        coverage.update({c['page']:c for c in new.get('coverage',[])})
        result['coverage']=[coverage[p] for p in sorted(coverage)]
        result['warnings']=list(dict.fromkeys([w for w in old.get('warnings',[]) if not any(f'Page {p}:' in w for p in pages)]+new.get('warnings',[])))
        result['interrupted']=bool(new.get('interrupted'))
    return result

class SourceRunner:
    def __init__(self,job,update):self.job=job;self.update=update;self.deadline=time.monotonic()+900
    def index(self,name):return next(i for i,s in enumerate(self.job['sources']) if s['name']==name)
    def cache(self,index,kind):return self.job['root']/f'{index}-{kind}.json'
    def load(self,index,kind):
        path=self.cache(index,kind)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    def selection(self,index,kind):
        selection=self.job.get('retry')
        if selection is None:return True,None
        if index!=selection['source_index'] or selection['stage'] not in (kind,'both'):return False,None
        return True,selection.get('page_numbers')
    def native(self,name,stream,**kwargs):
        from abp_scan import scan
        index=self.index(name);old=self.load(index,'native');run,pages=self.selection(index,'native')
        if old and not run:return old
        if not run:raise ValueError('Missing native checkpoint; rescan this source')
        remaining=self.deadline-time.monotonic()
        if remaining<=0:
            from abp_scan import incomplete
            source=self.job['sources'][index]
            return old or incomplete('job time budget reached',{'name':name,'sha256':source['sha256'],'bytes':source['bytes']})
        self.update(source=name,stage='native',message='Reading native text and schedules',source_index=index)
        kwargs.update(timeout=min(90,remaining),ocr_timeout=0,page_numbers=pages,
                      progress=lambda p:self.update(source=name,source_index=index,**p))
        result=scan(name,stream,**kwargs)
        result=merge_pages(old,result,pages,'native');write_json(self.cache(index,'native'),result)
        return result
    def image(self,name,stream,identity,timeout):
        from abp_resilient import deferred_ocr
        index=self.index(name);old=self.load(index,'images');run,pages=self.selection(index,'images')
        if old and not run:return old
        if not run:return {'review_candidates':[],'warnings':['Image stage not examined'],'coverage':[]}
        if time.monotonic()>=self.deadline:return old or {'review_candidates':[],'warnings':['Job time budget reached; retry image pages'],'coverage':[]}
        native=self.load(index,'native') or {};count=native.get('pages') or 12
        allowance=min(120,max(35,(len(pages) if pages else count)*12),self.deadline-time.monotonic())
        self.update(source=name,stage='images',source_index=index,message='Reading bounded image regions')
        result=deferred_ocr(name,stream,identity,allowance,page_numbers=pages,
            progress=lambda p:self.update(source=name,source_index=index,**p))
        result=merge_pages(old,result,pages,'images')
        # An interrupted worker must never hide later, unexamined pages.
        coverage={c['page']:c for c in result.get('coverage',[])}
        for p in range(1,(native.get('pages') or 0)+1):
            coverage.setdefault(p,{'page':p,'status':'budget_skipped','unexamined_content':'Page not completed; retry this page or review manually.'})
        result['coverage']=[coverage[p] for p in sorted(coverage)]
        write_json(self.cache(index,'images'),result);return result

class Jobs:
    def __init__(self,work_lock,read_sources,build,reference_build=None,*,janitor=False):
        self.work_lock=work_lock;self.read_sources=read_sources;self.build=build;self.reference_build=reference_build
        self.lock=threading.RLock();self.jobs={};self.worker=None
        self.directory=None
        if janitor:threading.Thread(target=self.expire,daemon=True).start()
    def expire(self):
        while True:
            time.sleep(60)
            with self.lock:
                try:self.prune()
                except OSError:pass
    def root(self):
        if self.directory is None:
            self.directory=Path(tempfile.mkdtemp(prefix='native-jobs-',dir=os.environ.get('ABP_SCAN_TMPDIR')))
            os.chmod(self.directory,0o700);mark_staging(self.directory)
        return self.directory
    def prune(self):
        for token,job in list(self.jobs.items()):
            if job['status'] in ('done','failed') and time.time()-job['updated']>TTL:
                shutil.rmtree(job['root']);del self.jobs[token]
    def size(self):return sum(p.stat().st_size for p in self.root().rglob('*') if p.is_file())
    def create(self,kind,*,parts=None,payload=None,parent=None,retry=None):
        with self.lock:
            self.prune()
            if len(self.jobs)>=MAX_JOBS or sum(j['status'] in ('queued','running','uploading') for j in self.jobs.values())>=3:
                raise ValueError('Job capacity reached. Finish the current jobs and try again; your review is preserved.')
            token=secrets.token_hex(24);root=self.root()/token;root.mkdir(mode=0o700)
            job={'id':token,'kind':kind,'root':root,'status':'uploading','created':time.time(),'updated':time.time(),'sources':[],'progress':{'message':'Receiving documents'}}
            self.jobs[token]=job
            try:
                if parent:
                    previous=self.get(parent)
                    if previous['status']!='done' or previous['kind']!='scan':raise ValueError('Previous scan is not ready for retry')
                    job['sources']=copy.deepcopy(previous['sources'])
                    for path in previous['root'].iterdir():
                        if path.name=='result.json' or path.name=='status.json':continue
                        try:os.link(path,root/path.name)
                        except OSError:shutil.copyfile(path,root/path.name)
                    job['retry']=retry
                elif parts is not None:
                    names=set();total=0
                    for _,name,stream in parts:
                        if not name:continue
                        name=Path(name.replace('\\','/')).name[:160]
                        if not name or Path(name).suffix.lower() not in ('.pdf','.xlsx','.csv'):raise ValueError('Use PDF, XLSX, or CSV source files')
                        if name in names:raise ValueError('Source names must be unique; rename duplicate filenames before uploading')
                        names.add(name);index=len(job['sources']);path=root/f'source-{index}{Path(name).suffix.lower()}'
                        h=hashlib.sha256();size=0
                        with path.open('xb') as dest:
                            os.chmod(path,0o600)
                            for block in iter(lambda:stream.read(65536),b''):
                                size+=len(block);total+=len(block)
                                if total>200_000_000:raise ValueError('Source limit is 200 MB')
                                dest.write(block);h.update(block)
                        job['sources'].append({'name':name,'file':path.name,'bytes':size,'sha256':h.hexdigest()})
                    if not job['sources']:raise ValueError('Choose source documents first')
                if payload is not None:write_json(root/'payload.json',payload)
                if self.size()>MAX_RETAINED_BYTES:raise ValueError('Temporary document capacity reached; save your review and try a smaller source set')
                job.update(status='queued',progress={'message':'Queued for document processing'})
                self.persist(job)
                if not self.worker or not self.worker.is_alive():
                    self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
                return self.public(job)
            except Exception:
                shutil.rmtree(root);del self.jobs[token];raise
    def get(self,token):
        if not re.fullmatch(r'[a-f0-9]{48}',token):raise KeyError('Unknown job')
        with self.lock:
            self.prune()
            job=self.jobs[token];job['updated']=time.time();return job
    def public(self,job):
        return {k:job[k] for k in ('id','kind','status','created','updated','progress','sources')}|{'retention_seconds':TTL,'storage':'Temporary on this server; browser review is saved separately. Reattach sources after a server restart.'}
    def persist(self,job):write_json(job['root']/'status.json',self.public(job))
    def update(self,job,**progress):
        with self.lock:
            job['progress']=progress;job['updated']=time.time();self.persist(job)
    def run(self):
        while True:
            with self.lock:
                job=next((j for j in self.jobs.values() if j['status']=='queued'),None)
                if job is None:self.worker=None;return
                job['status']='running';self.persist(job)
            try:
                with self.work_lock:
                    if job['kind']=='scan':
                        with ExitStack() as stack:
                            sources=[(s['name'],stack.enter_context((job['root']/s['file']).open('rb'))) for s in job['sources']]
                            result=self.read_sources(sources,runner=SourceRunner(job,lambda **p:self.update(job,**p)))
                        result['job_id']=job['id'];result['source_manifest']=job['sources']
                        write_json(job['root']/'result.json',result)
                    else:
                        payload=json.loads((job['root']/'payload.json').read_text(encoding='utf-8'))
                        self.update(job,stage='build',message='Building original forms and checking template integrity')
                        if job['kind']=='reference':
                            source=job['root']/job['sources'][0]['file']
                            result=self.reference_build(source.read_bytes(),payload['project'],payload['location'])
                        else:result=self.build(payload)
                        (job['root']/'report.xlsx').write_bytes(result)
                    self.update(job,message='Finished; review coverage and unresolved design values',stage='finished')
                    job['status']='done';self.persist(job)
            except Exception as exc:
                job['status']='failed';self.update(job,message=str(exc)[:500],stage='failed')
            finally:gc.collect()
