#!/usr/bin/env python3
"""Execute the shipped native4k coalescing gate/matcher/blob-add with pthread mocks."""
from pathlib import Path
import argparse,ast,subprocess,tempfile,tomllib
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu-source',type=Path,default=R/'refer/xnu');a=p.parse_args();feed=a.xnu_source.resolve()
rev=next(x['commit'] for x in tomllib.loads((R/'feeds.toml').read_text())['source'] if x.get('kind')=='refer' and x.get('name')=='xnu')
try:actual=subprocess.check_output(['git','-C',str(feed),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
except subprocess.CalledProcessError:p.error('Prepare pinned refer/xnu or pass --xnu-source PATH')
if actual!=rev:p.error('XNU revision mismatch')
# Reuse API mocks, not implementation, from the blob-phase fixture.
syntax=ast.parse((R/'scripts/tests/check_root_blob_timing.py').read_text())
pre=next(ast.literal_eval(n.value) for n in ast.walk(syntax) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='pre' for t in n.targets))
pre=pre.replace('#include <pthread.h>','#include <pthread.h>\n#include <arpa/inet.h>')
pre=pre.replace('typedef int CS_CodeDirectory;', 'typedef struct {uint32_t codeLimit,version;uint64_t codeLimit64;} CS_CodeDirectory;\nstatic _Thread_local CS_CodeDirectory fixture_cd;')
pre=pre.replace('struct cs_blob{size_t csb_mem_size;', 'struct cs_blob{const CS_CodeDirectory*csb_cd;unsigned csb_hash_pageshift;size_t csb_mem_size;')
# The typedef must precede cs_blob in these host mocks.
a=pre.index('typedef struct {uint32_t codeLimit,version;uint64_t codeLimit64;} CS_CodeDirectory;');b=pre.index('struct image_params',a)
cd=pre[a:b];pre=pre[:a]+pre[b:];pre=pre.replace('struct cs_blob{',cd+'\nstruct cs_blob{',1)
pre=pre.replace('struct vnode{uint32_t vid;struct ubc_info*v_ubcinfo;}', 'struct vnode{uint32_t vid;struct ubc_info*v_ubcinfo;pthread_mutex_t mutex;int readonly;}')
a=pre.index('static struct proc process=');b=pre.index('static int proc_getpid',a)
pre=pre[:a]+'''static _Thread_local struct proc process={2,102,"probe"};
static unsigned flag;static int present=1;
static _Thread_local int phase,locked,cleanups,original_logs,summary_logs,init_calls,mac_calls,clocks,vid_reads,cs_debug;
static unsigned allocations,prepares,prepare_failures,max_active,active_prepares;
static int cs_blob_generation_count=17;static _Thread_local uint64_t ticks;static _Thread_local char output[8192];
static unsigned coalesce_flag=1;static int coalesce_present=1;
static pthread_mutex_t rendezvous_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t rendezvous_cond=PTHREAD_COND_INITIALIZER;
static unsigned entrants,required_entrants,producer_hold;
static _Thread_local int registry_held;
''' +pre[b:]
old='static int PE_parse_boot_argn(const char*n,void*v,size_t z){assert(!strcmp(n,"native-root-timing")&&z==sizeof(flag));*(unsigned*)v=flag;return present;}'
new='static int PE_parse_boot_argn(const char*n,void*v,size_t z){assert(!registry_held&&z==sizeof(flag));if(!strcmp(n,"native-cs-coalesce")){*(unsigned*)v=coalesce_flag;return coalesce_present;}assert(!strcmp(n,"native-root-timing"));*(unsigned*)v=flag;return present;}'
assert old in pre;pre=pre.replace(old,new)
pre=pre.replace('b->csb_platform_binary=1;return phase==1?', '''b->csb_platform_binary=1;fixture_cd.codeLimit=htonl(8192);b->csb_cd=&fixture_cd;b->csb_hash_pageshift=14;
if(phase==20)b->csb_flags^=1;if(phase==21)b->csb_signer_type=1;if(phase==22)b->csb_cdhash[0]=1;
if(phase==23){b->csb_flags=0;b->csb_platform_binary=0;}if(phase==24){b->csb_flags=0;b->csb_platform_binary=0;b->csb_teamid="team";}if(phase==25)b->csb_mem_size=1;
return phase==1?''')
pre=pre.replace('allocations++;return calloc', '__atomic_fetch_add(&allocations,1,__ATOMIC_RELAXED);return calloc').replace('allocations--;free(b);','__atomic_fetch_sub(&allocations,1,__ATOMIC_RELAXED);free(b);')
pre=pre.replace('static void vnode_lock(struct vnode*v){(void)v;assert(!locked);locked=1;}', 'static void vnode_lock(struct vnode*v){assert(!locked&&!registry_held);pthread_mutex_lock(&v->mutex);locked=1;}')
pre=pre.replace('static void vnode_unlock(struct vnode*v){(void)v;assert(locked);locked=0;}', 'static void vnode_unlock(struct vnode*v){assert(locked&&!registry_held);locked=0;pthread_mutex_unlock(&v->mutex);}')
# XNU static lock declarations and sleep release/reacquire behavior.
pre+='''
#define PAGE_SHIFT 12
#define CS_SUPPORTSCODELIMIT64 0x20300
#define ntohll(x) __builtin_bswap64(x)
#define PRIBIO 0
#define LCK_GRP_DECLARE(name,label) int name
#define LCK_MTX_DECLARE(name,group) pthread_mutex_t name=PTHREAD_MUTEX_INITIALIZER
static pthread_cond_t sleep_cond=PTHREAD_COND_INITIALIZER;
static unsigned sleepers;
static void lck_mtx_lock(pthread_mutex_t*l){assert(!locked&&!registry_held);pthread_mutex_lock(l);registry_held=1;}
static void lck_mtx_unlock(pthread_mutex_t*l){assert(registry_held&&!locked);registry_held=0;pthread_mutex_unlock(l);}
static int msleep(void*channel,pthread_mutex_t*l,int pri,const char*name,void*timeout){(void)channel;(void)pri;(void)name;(void)timeout;assert(registry_held&&!locked);__atomic_fetch_add(&sleepers,1,__ATOMIC_RELAXED);pthread_mutex_lock(&rendezvous_mutex);pthread_cond_broadcast(&rendezvous_cond);pthread_mutex_unlock(&rendezvous_mutex);registry_held=0;pthread_cond_wait(&sleep_cond,l);registry_held=1;return 0;}
static void wakeup(void*channel){(void)channel;assert(registry_held&&!locked);pthread_cond_broadcast(&sleep_cond);}
static int vnode_vfsisrdonly(struct vnode*v){assert(!registry_held);return v->readonly;}
static int cs_native4k_prepare(struct vnode*v,struct cs_blob*b){
 (void)v;assert(!locked&&!registry_held);__atomic_fetch_add(&prepares,1,__ATOMIC_RELAXED);
 unsigned current=__atomic_add_fetch(&active_prepares,1,__ATOMIC_RELAXED),old=__atomic_load_n(&max_active,__ATOMIC_RELAXED);
 while(current>old&&!__atomic_compare_exchange_n(&max_active,&old,current,0,__ATOMIC_RELAXED,__ATOMIC_RELAXED)){}
 pthread_mutex_lock(&rendezvous_mutex);entrants++;pthread_cond_broadcast(&rendezvous_cond);
 while(producer_hold||(required_entrants&&entrants<required_entrants))pthread_cond_wait(&rendezvous_cond,&rendezvous_mutex);
 pthread_mutex_unlock(&rendezvous_mutex);
 int fail=__atomic_exchange_n(&prepare_failures,0,__ATOMIC_RELAXED);
 if(!fail)b->csb_native4k_hashes=(void*)0xabc;
 __atomic_fetch_sub(&active_prepares,1,__ATOMIC_RELAXED);return fail?EIO:0;
}
'''
main=r'''
struct request{struct vnode*v;int result,test_phase,cpu;unsigned validates,macs;};
static void*call(void*opaque){struct request*r=opaque;phase=r->test_phase;init_calls=mac_calls=0;struct cs_blob*out=NULL;vm_address_t addr=0x1234;
 r->result=ubc_cs_blob_add(r->v,0,r->cpu,0,0,&addr,4096,NULL,0,&out);assert(!locked&&!registry_held);r->validates=init_calls;r->macs=mac_calls;return NULL;}
static void initialize(struct vnode*v,struct ubc_info*info){memset(info,0,sizeof(*info));*v=(struct vnode){.vid=7,.v_ubcinfo=info,.readonly=1};pthread_mutex_init(&v->mutex,NULL);}
static void finish(struct vnode*v){struct cs_blob*b=v->v_ubcinfo->cs_blobs;while(b){struct cs_blob*next=b->csb_next;zfree_ro(0,b);b=next;}pthread_mutex_destroy(&v->mutex);}
static void reset(void){assert(!allocations);prepares=prepare_failures=max_active=active_prepares=entrants=required_entrants=sleepers=producer_hold=0;coalesce_flag=1;coalesce_present=1;
#if XNU_ROOT_TIMING
 memset(native_sig_slots,0,sizeof(native_sig_slots));memset(native_sig_vnodes,0,sizeof(native_sig_vnodes));native_sig_reports=native_sig_vnodes_busy=0;
#endif
}
int main(void){
/* Strict independent flag/default behavior; validation and MACF always per call. */
for(coalesce_present=0;coalesce_present<2;coalesce_present++)for(coalesce_flag=0;coalesce_flag<4;coalesce_flag++){
 struct ubc_info info;struct vnode v;initialize(&v,&info);struct request a={.v=&v,.cpu=CPU_TYPE_ANY},b=a;
 unsigned before=prepares;call(&a);call(&b);assert(!a.result&&!b.result&&a.validates==1&&b.validates==1&&a.macs==1&&b.macs==1);
 unsigned expected=(XNU_NATIVE_CS_HASH_CACHE&&coalesce_present&&coalesce_flag==1)?1:2;
#if !XNU_NATIVE_CS_HASH_CACHE
 expected=0;
#endif
 assert(prepares-before==expected);assert(info.cs_add_gen==cs_blob_generation_count);finish(&v);
}
reset();struct ubc_info info;struct vnode v;initialize(&v,&info);
/* Four concurrent same-vnode calls, one complete preparation, each MACF intact. */
struct request request[4];pthread_t thread[4];
#if XNU_NATIVE_CS_HASH_CACHE
producer_hold=1;
#endif
request[0]=(struct request){.v=&v,.cpu=CPU_TYPE_ANY};pthread_create(&thread[0],NULL,call,&request[0]);
#if XNU_NATIVE_CS_HASH_CACHE
pthread_mutex_lock(&rendezvous_mutex);while(!entrants)pthread_cond_wait(&rendezvous_cond,&rendezvous_mutex);pthread_mutex_unlock(&rendezvous_mutex);
#endif
for(int i=1;i<4;i++){request[i]=(struct request){.v=&v,.cpu=CPU_TYPE_ANY};pthread_create(&thread[i],NULL,call,&request[i]);}
#if XNU_NATIVE_CS_HASH_CACHE
pthread_mutex_lock(&rendezvous_mutex);while(__atomic_load_n(&sleepers,__ATOMIC_RELAXED)<3)pthread_cond_wait(&rendezvous_cond,&rendezvous_mutex);producer_hold=0;pthread_cond_broadcast(&rendezvous_cond);pthread_mutex_unlock(&rendezvous_mutex);
#endif
for(int i=0;i<4;i++){pthread_join(thread[i],NULL);assert(!request[i].result&&request[i].validates==1&&request[i].macs==1);}
assert(prepares==(XNU_NATIVE_CS_HASH_CACHE?1u:0u));assert(info.cs_add_gen==cs_blob_generation_count);finish(&v);
#if XNU_NATIVE_CS_HASH_CACHE
/* A failed producer publishes nothing; a subsequent/waiting caller retries. */
reset();initialize(&v,&info);prepare_failures=1;struct request a={.v=&v,.cpu=CPU_TYPE_ANY};call(&a);assert(a.result==EIO&&!info.cs_blobs&&prepares==1);call(&a);assert(!a.result&&info.cs_blobs&&prepares==2);finish(&v);
/* A waiting caller retries after the first producer fails; no failure cache. */
reset();initialize(&v,&info);producer_hold=1;prepare_failures=1;
request[0]=(struct request){.v=&v,.cpu=7};request[1]=request[0];pthread_create(&thread[0],NULL,call,&request[0]);
pthread_mutex_lock(&rendezvous_mutex);while(!entrants)pthread_cond_wait(&rendezvous_cond,&rendezvous_mutex);pthread_mutex_unlock(&rendezvous_mutex);
pthread_create(&thread[1],NULL,call,&request[1]);pthread_mutex_lock(&rendezvous_mutex);while(!__atomic_load_n(&sleepers,__ATOMIC_RELAXED))pthread_cond_wait(&rendezvous_cond,&rendezvous_mutex);producer_hold=0;pthread_cond_broadcast(&rendezvous_cond);pthread_mutex_unlock(&rendezvous_mutex);
pthread_join(thread[0],NULL);pthread_join(thread[1],NULL);assert(request[0].result==EIO&&!request[1].result&&prepares==2);finish(&v);
/* Mismatches must still prepare and preserve the final original EALREADY. */
for(int mismatch=20;mismatch<=25;mismatch++){
 reset();initialize(&v,&info);a=(struct request){.v=&v,.cpu=7};call(&a);assert(!a.result);
 struct request b={.v=&v,.test_phase=mismatch,.cpu=7};call(&b);assert(b.result==EALREADY&&prepares==2&&b.validates==1&&b.macs==1);finish(&v);
}
reset();initialize(&v,&info);a=(struct request){.v=&v,.cpu=7};call(&a);a.cpu=8;call(&a);assert(a.result==EALREADY&&prepares==2);finish(&v);
/* Mismatch plus failed prepare keeps the original prepare-error precedence. */
reset();initialize(&v,&info);a=(struct request){.v=&v,.cpu=7};call(&a);prepare_failures=1;a.cpu=8;call(&a);assert(a.result==EIO&&prepares==2);finish(&v);
/* ANY CPU is updated on reuse; generation is refreshed just as in original. */
reset();initialize(&v,&info);a=(struct request){.v=&v,.cpu=CPU_TYPE_ANY};call(&a);info.cs_add_gen=0;a.cpu=7;call(&a);assert(!a.result&&prepares==1&&info.cs_blobs->csb_cpu_type==7&&info.cs_add_gen==cs_blob_generation_count);finish(&v);
/* Missing/incomplete native array is never an early reuse hit. */
reset();initialize(&v,&info);a=(struct request){.v=&v,.cpu=7};call(&a);info.cs_blobs->csb_native4k_hashes=NULL;call(&a);assert(!a.result&&prepares==2);finish(&v);
/* Writable vnode remains the old path. */
reset();initialize(&v,&info);v.readonly=0;a=(struct request){.v=&v,.cpu=7};call(&a);call(&a);assert(!a.result&&prepares==2);finish(&v);
/* Different vnodes actually execute preparation concurrently. */
reset();struct ubc_info infos[2];struct vnode nodes[2];required_entrants=2;
for(int i=0;i<2;i++){initialize(&nodes[i],&infos[i]);request[i]=(struct request){.v=&nodes[i],.cpu=7};pthread_create(&thread[i],NULL,call,&request[i]);}
for(int i=0;i<2;i++){pthread_join(thread[i],NULL);assert(!request[i].result);finish(&nodes[i]);}assert(prepares==2&&max_active==2);
/* Registry full is a safe original-path fallback, without orphan tokens. */
reset();struct vnode many[65];struct ubc_info manyinfo[65];struct cs_native4k_gate*token[65];
for(int i=0;i<65;i++){initialize(&many[i],&manyinfo[i]);token[i]=cs_native4k_gate_enter(&many[i],14);assert((token[i]!=NULL)==(i<64));}
for(int i=0;i<65;i++){cs_native4k_gate_leave(token[i]);finish(&many[i]);}
for(int i=0;i<64;i++)assert(!cs_native4k_gates[i].vp&&!cs_native4k_gates[i].vid);
/* Effective codeLimit64 telemetry must not silently truncate high bits. */
CS_CodeDirectory cd={.version=htonl(CS_SUPPORTSCODELIMIT64),.codeLimit=htonl(123),.codeLimit64=__builtin_bswap64(0x100000123ULL)};
assert(cs_native4k_requested_limit(&cd)==0x100000123ULL);cd.codeLimit64=0;assert(cs_native4k_requested_limit(&cd)==123);cd.version=0;cd.codeLimit64=__builtin_bswap64(999);assert(cs_native4k_requested_limit(&cd)==123);
/* Exact prepare telemetry is separately gated, and uses requested codeLimit bytes. */
#if XNU_ROOT_TIMING
reset();flag=1;present=1;initialize(&v,&info);a=(struct request){.v=&v,.cpu=7};call(&a);call(&a);
assert(native_sig_slots[0].prep_count==1&&native_sig_slots[0].prep_bytes==8192&&native_sig_slots[0].prep_ns==10&&native_sig_slots[0].prep_reuse==1);finish(&v);flag=0;
#endif
#endif
assert(!allocations);puts("PASS actual coalescing: strict default-off flag/cache gate, per-call validation+MACF, same-vnode 4 callers prepare once, failure retry, mismatches/error precedence/CPU update/generation, writable exclusion, distinct-vnode parallelism, bounded fallback and prepare telemetry");}
'''
with tempfile.TemporaryDirectory(prefix='root-coalesce-') as directory:
 t=Path(directory)
 for f in ('bsd/kern/ubc_subr.c','bsd/kern/kern_descrip.c'):
  out=t/f;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(subprocess.check_output(['git','-C',str(feed),'show',rev+':'+f]))
 for patch in [*sorted((R/'patches/xnu').glob('*.patch')),*sorted((R/'kits/NativePrelink/patches').glob('*.patch'))]:
  subprocess.run(['git','apply','--include=bsd/kern/ubc_subr.c','--include=bsd/kern/kern_descrip.c',str(patch)],cwd=t,check=True)
 s=(t/'bsd/kern/ubc_subr.c').read_text();a=s.index('/* Optional disjoint blob-add');b=s.index('\n#if CONFIG_SUPPLEMENTAL_SIGNATURES\nint\nubc_cs_blob_add_supplement(',a);body=s[a:b]
 for include in ('#include <kern/clock.h>','#include <pexpert/pexpert.h>','#include <kern/locks.h>'):body=body.replace(include,'')
 s=(t/'bsd/kern/kern_descrip.c').read_text();a=s.index('/* Optional signature-case');b=s.index('int\nsys_fcntl_nocancel(',a);collector=s[a:b].replace('#include <kern/clock.h>','').replace('#include <pexpert/pexpert.h>','')
 for cache,timing in ((0,0),(1,0),(1,1)):
  (t/'test.c').write_text(pre+collector+body+main)
  subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-unused-parameter','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-pie','-no-pie','-pthread','-DCONFIG_MACF=1','-DXNU_NATIVE_CS_HASH_CACHE='+str(cache),'-DXNU_ROOT_TIMING='+str(timing),str(t/'test.c'),'-o',str(t/'test')],check=True)
  subprocess.run([str(t/'test')],check=True,timeout=30)
