#!/usr/bin/env python3
"""Compile actual patched ubc_cs_blob_add and collectors, including concurrent samples."""
from pathlib import Path
import argparse, subprocess, tempfile, tomllib
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu-source',type=Path,default=R/'refer/xnu');args=p.parse_args()
feed=args.xnu_source.resolve();rev=next(x['commit'] for x in tomllib.loads((R/'feeds.toml').read_text())['source'] if x.get('kind')=='refer' and x.get('name')=='xnu')
try:actual=subprocess.check_output(['git','-C',str(feed),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
except subprocess.CalledProcessError:p.error('Prepare pinned refer/xnu or pass --xnu-source PATH')
if actual!=rev:p.error('XNU revision mismatch')
with tempfile.TemporaryDirectory(prefix='root-blob-') as directory:
 t=Path(directory)
 for f in ('bsd/kern/ubc_subr.c','bsd/kern/kern_descrip.c'):
  out=t/f;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(subprocess.check_output(['git','-C',str(feed),'show',rev+':'+f]))
 for patch in [*sorted((R/'patches/xnu').glob('*.patch')),*sorted((R/'kits/NativePrelink/patches').glob('*.patch'))]:
  subprocess.run(['git','apply','--include=bsd/kern/ubc_subr.c','--include=bsd/kern/kern_descrip.c',str(patch)],cwd=t,check=True)
 s=(t/'bsd/kern/ubc_subr.c').read_text();a=s.index('/* Optional disjoint blob-add');b=s.index('\n#if CONFIG_SUPPLEMENTAL_SIGNATURES\nint\nubc_cs_blob_add_supplement(',a);body=s[a:b].replace('#include <kern/clock.h>','').replace('#include <pexpert/pexpert.h>','')
 k=(t/'bsd/kern/kern_descrip.c').read_text();a=k.index('/* Optional signature-case');b=k.index('int\nsys_fcntl_nocancel(',a);collector=k[a:b].replace('#include <kern/clock.h>','').replace('#include <pexpert/pexpert.h>','')
 pre=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#define F_ADDSIGS 1
#define TRUE 1
#define false 0
#define EAUTH 80
#define HAS_APPLE_PAC 0
#define CODE_SIGNING_MONITOR 0
#define CONFIG_SUPPLEMENTAL_SIGNATURES 0
#define CS_PLATFORM_BINARY 0x400
#define CS_PLATFORM_PATH 0x800
#define MAC_VNODE_CHECK_DYLD_SIM 2
#define CPU_TYPE_ANY (-1)
#define CPU_SUBTYPE_MASK 0xff000000
#define KERN_DENIED 1
#define KERN_SUCCESS 0
#define ZONE_ID_CS_BLOB 0
#define Z_WAITOK 1
#define Z_NOFAIL 2
#define CS_CDHASH_LEN 20
#define PTRAUTH_ADDR_DIVERSIFY 0
#define OS_PTRAUTH_DISCRIMINATOR(x) 0
#define __unused __attribute__((unused))
#define UBCINFOEXISTS(v) (phase!=8)
#define os_atomic_thread_fence(x) ((void)0)
typedef int boolean_t,kern_return_t,errno_t,cpu_type_t,cpu_subtype_t,ptrauth_generic_signature_t;
typedef uintptr_t vm_address_t;typedef size_t vm_size_t;
struct proc{int pid;uint64_t uid;char p_comm[8];};typedef struct proc*proc_t;
struct cs_blob{size_t csb_mem_size;int csb_cpu_type,csb_cpu_subtype,csb_signer_type,csb_platform_binary,csb_platform_path;unsigned csb_flags;off_t csb_base_offset,csb_start_offset,csb_end_offset;char*csb_teamid;char csb_cdhash[20];struct cs_blob*csb_ro_addr,*csb_next;struct vnode*csb_vnode;};
struct ubc_info{struct cs_blob*cs_blobs;int cs_add_gen,ui_control,cs_mtime;};
struct vnode{uint32_t vid;struct ubc_info*v_ubcinfo;};
typedef int CS_CodeDirectory;struct image_params{int x;};
static struct proc process={2,102,"probe"};static unsigned flag;static int present=1,phase,locked,cleanups,allocations,original_logs,summary_logs,init_calls,mac_calls,clocks,vid_reads,cs_debug;
static int cs_blob_generation_count;static uint64_t ticks;static char output[8192];static struct cs_blob existing;
static int proc_getpid(proc_t p){return p->pid;}static uint64_t proc_uniqueid(proc_t p){return p->uid;}
static proc_t current_proc(void){return &process;}
static uint32_t vnode_vid(struct vnode*v){vid_reads++;return v->vid;}
static uint64_t mach_absolute_time(void){clocks++;return ticks+=10;}
static void absolutetime_to_nanoseconds(uint64_t n,uint64_t*out){*out=n;}
static int PE_parse_boot_argn(const char*n,void*v,size_t z){assert(!strcmp(n,"native-root-timing")&&z==sizeof(flag));*(unsigned*)v=flag;return present;}
static int mock_printf(const char*f,...){
 if(!strncmp(f,"RST ",4)){assert(!locked&&!allocations);va_list ap;va_start(ap,f);size_t n=strlen(output);vsnprintf(output+n,sizeof(output)-n,f,ap);va_end(ap);summary_logs++;}
 else original_logs++;
 return 0;
}
#define printf mock_printf
static int cs_blob_init_validated(vm_address_t*a,size_t n,struct cs_blob*b,const CS_CodeDirectory**cd){(void)n;(void)cd;init_calls++;*a=0;memset(b,0,sizeof(*b));b->csb_end_offset=phase==12?0:8192;b->csb_flags=CS_PLATFORM_BINARY;b->csb_platform_binary=1;return phase==1?EIO:0;}
static int reconstitute_code_signature(struct cs_blob*b){(void)b;return phase==2?EAUTH:0;}
static struct cs_blob*zalloc_ro(int z,int f){(void)z;(void)f;allocations++;return calloc(1,sizeof(struct cs_blob));}
static void zalloc_ro_update_elem(int z,struct cs_blob*b,const struct cs_blob*t){(void)z;*b=*t;}
static int mac_vnode_check_signature(struct vnode*v,struct cs_blob*b,struct image_params*i,unsigned*f,unsigned*s,int flags,unsigned platform){(void)v;(void)b;(void)i;(void)f;(void)s;(void)flags;(void)platform;mac_calls++;return phase==3?EAUTH:0;}
static int reconstitute_code_signature_2nd_stage(struct cs_blob*b){(void)b;return phase==4?EAUTH:0;}
static int setup_multilevel_hashing(struct cs_blob*b){(void)b;return phase==5?EAUTH:0;}
static int validate_auxiliary_signed_blobs(struct cs_blob*b){(void)b;return phase==6?EAUTH:0;}
static int accelerate_entitlement_queries(struct cs_blob*b){(void)b;return phase==7?EAUTH:0;}
static char*csblob_parse_teamid(struct cs_blob*b){(void)b;return NULL;}
static int ptrauth_utils_sign_blob_generic(void*b,size_t n,int d,int a){(void)b;(void)n;(void)d;(void)a;return 0;}
static void ptrauth_utils_auth_blob_generic(void*b,size_t n,int d,int a,int sig){(void)b;(void)n;(void)d;(void)a;(void)sig;}
static void vnode_lock(struct vnode*v){(void)v;assert(!locked);locked=1;}
static void vnode_unlock(struct vnode*v){(void)v;assert(locked);locked=0;}
static struct cs_blob*ubc_get_cs_blobs(struct vnode*v){return v->v_ubcinfo->cs_blobs;}
static void cs_blob_set_cpu_type(struct cs_blob*b,int cpu){b->csb_cpu_type=cpu;}
static int memory_object_signed(int c,int b){(void)c;(void)b;return phase==9?1:0;}
static void ubc_cs_blob_adjust_statistics(struct cs_blob*b){(void)b;}
static void zone_require_ro(int z,size_t n,struct cs_blob*b){(void)z;(void)n;(void)b;}
static const char*vnode_getname_printable(struct vnode*v){(void)v;return "fixture";}
static void vnode_putname_printable(const char*n){(void)n;}
static int vfs_context_current(void){return 0;}
static void vnode_mtime(struct vnode*v,int*m,int c){(void)v;(void)m;(void)c;}
static void cs_blob_cleanup(struct cs_blob*b){(void)b;assert(!locked);cleanups++;}
static void zfree_ro(int z,struct cs_blob*b){(void)z;allocations--;free(b);}
'''
 main=r'''
static void reset(void){
#if XNU_ROOT_TIMING
 memset(native_sig_slots,0,sizeof(native_sig_slots));memset(native_sig_vnodes,0,sizeof(native_sig_vnodes));native_sig_reports=native_sig_vnodes_busy=0;
#endif
 clocks=vid_reads=locked=cleanups=allocations=original_logs=summary_logs=init_calls=mac_calls=0;ticks=0;output[0]=0;
}
#if XNU_ROOT_TIMING
static pthread_mutex_t gate_mutex=PTHREAD_MUTEX_INITIALIZER;static pthread_cond_t gate_cond=PTHREAD_COND_INITIALIZER;static int ready,go;
static void*worker(void*arg){uint64_t uid=(uintptr_t)arg;uint64_t ns[4]={1,2,3,4};pthread_mutex_lock(&gate_mutex);ready++;pthread_cond_broadcast(&gate_cond);while(!go)pthread_cond_wait(&gate_cond,&gate_mutex);pthread_mutex_unlock(&gate_mutex);for(int i=0;i<1000;i++)native_root_blob_timing_record(2,uid,0x1234,7,0,ns,1,0);return NULL;}
#endif
int main(void){
for(flag=0;flag<4;flag++)for(present=0;present<2;present++)for(phase=0;phase<=12;phase++){
 reset();struct ubc_info info={0};struct vnode vnode={7,&info};struct cs_blob*out=(void*)1;vm_address_t addr=0x1234;
 existing=(struct cs_blob){.csb_cpu_type=CPU_TYPE_ANY,.csb_platform_binary=1,.csb_flags=CS_PLATFORM_BINARY,.csb_end_offset=8192};
 if(phase==10||phase==11){info.cs_blobs=&existing;if(phase==11)existing.csb_end_offset=16384;}
 int error=ubc_cs_blob_add(&vnode,0,CPU_TYPE_ANY,0,0,&addr,4096,NULL,0,&out);
 int expected=phase==1?EIO:phase==2?EAUTH:phase==3&&CONFIG_MACF?EAUTH:phase>=4&&phase<=7?EAUTH:phase==8||phase==9?ENOENT:phase==11?EALREADY:phase==12?EINVAL:0;
 assert(error==expected&&!locked&&init_calls==1&&!addr&&!summary_logs);
 assert(mac_calls==(CONFIG_MACF&&phase!=1&&phase!=2));
 if(error){assert(!out);assert(cleanups==(phase==1?0:1));}
 else if(phase==10){assert(out==&existing&&cleanups==1);}
 else {assert(out==info.cs_blobs&&out!=NULL&&cleanups==0);zfree_ro(0,out);}
 assert(!allocations);int active=0;
#if XNU_ROOT_TIMING
 active=present&&flag==1;
 if(active){struct native_sig_slot*s=&native_sig_slots[0];assert(s->uniqueid==102&&s->blob_count==1&&s->init_count==1&&s->blob_errors==(uint64_t)(error!=0));assert(s->mac_count==(uint64_t)mac_calls);assert(s->init_ns==10);assert(s->mac_ns==10*(uint64_t)mac_calls);assert(s->init_ns+s->pre_ns+s->mac_ns+s->post_ns==ticks-10);assert(vid_reads==1);native_root_signature_timing_report();assert(summary_logs==4&&strstr(output,"bc=1"));}
#endif
 if(!active)assert(!clocks&&!vid_reads);
}
#if XNU_ROOT_TIMING
reset();uint64_t ns[4]={1,2,3,4};
/* Same address with a different vid/offset is not the same signature identity. */
native_root_blob_timing_record(2,102,0x1234,7,0,ns,1,0);
native_root_blob_timing_record(2,202,0x1234,8,0,ns,1,0);
native_root_blob_timing_record(2,202,0x1234,7,4096,ns,1,0);
assert(!native_sig_slots[1].vnode_cross);
native_root_blob_timing_record(2,202,0x1234,7,0,ns,1,0);
assert(native_sig_slots[1].vnode_cross==1&&native_sig_slots[1].duplicate_vnode==0x1234&&native_sig_slots[1].duplicate_vid==7&&native_sig_slots[1].duplicate_peer==102);
native_root_signature_timing_report();assert(strstr(output,"a=1234 v=7 o=0 peer=102"));summary_logs=0;
/* Deterministic busy path drops only metadata, never intervals. */
native_sig_vnodes_busy=1;native_root_blob_timing_record(2,202,0x1234,7,0,ns,1,EIO);native_sig_vnodes_busy=0;
assert(native_sig_slots[1].blob_count==4&&native_sig_slots[1].vnode_dropped==1&&native_sig_slots[1].blob_errors==1);
reset();for(unsigned i=0;i<65;i++)native_root_blob_timing_record(2,102,0x1000+i,7,0,ns,1,0);
assert(native_sig_slots[0].blob_count==65&&native_sig_slots[0].vnode_dropped==1);
/* Race pre-existing identities; totals remain exact, observation may drop. */
reset();native_root_blob_timing_record(2,102,0x1234,7,0,ns,1,0);native_root_blob_timing_record(2,202,0x1234,7,0,ns,1,0);
pthread_t a,b;pthread_create(&a,NULL,worker,(void*)(uintptr_t)102);pthread_create(&b,NULL,worker,(void*)(uintptr_t)202);pthread_mutex_lock(&gate_mutex);while(ready<2)pthread_cond_wait(&gate_cond,&gate_mutex);go=1;pthread_cond_broadcast(&gate_cond);pthread_mutex_unlock(&gate_mutex);pthread_join(a,NULL);pthread_join(b,NULL);
assert(native_sig_slots[0].blob_count==1001&&native_sig_slots[1].blob_count==1001);
assert(native_sig_slots[0].init_ns==1001&&native_sig_slots[1].post_ns==4004);
assert(native_sig_slots[0].vnode_cross+native_sig_slots[0].vnode_dropped==1000);
assert(native_sig_slots[1].vnode_cross+native_sig_slots[1].vnode_dropped==1001);
assert(!summary_logs&&!original_logs);
/* Metadata is copied: destroying the vnode does not cause a later dereference. */
reset();flag=1;present=1;phase=0;struct ubc_info info={0};struct vnode*v=malloc(sizeof(*v));*v=(struct vnode){9,&info};vm_address_t addr=0;struct cs_blob*out=NULL;
assert(!ubc_cs_blob_add(v,0,CPU_TYPE_ANY,0,0,&addr,4096,NULL,0,&out));zfree_ro(0,out);free(v);native_root_signature_timing_report();assert(summary_logs==4);
#endif
puts("PASS shipped blob-add: strict compile/runtime gates, disjoint phases, MACF on/off, errors/cleanup/EAGAIN, vid+offset identity, bounded metadata/drop, concurrent counters and freed-vnode summary");}
'''
 for feature in (0,1):
  for mac in (0,1):
   (t/'test.c').write_text(pre+collector+body+main)
   subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-unused-parameter','-fsanitize=address,undefined','-fno-pie','-no-pie','-pthread','-DXNU_ROOT_TIMING='+str(feature),'-DCONFIG_MACF='+str(mac),str(t/'test.c'),'-o',str(t/'test')],check=True)
   subprocess.run([str(t/'test')],check=True)
