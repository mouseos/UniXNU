#!/usr/bin/env python3
"""Compile actual patched shared-region wrapper/helpers with host API mocks."""
from pathlib import Path
import argparse, re, subprocess, tempfile, tomllib
R=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--xnu-source', type=Path, default=R/'refer/xnu',
                    help='pinned XNU Git checkout (default: official refer/xnu)')
args=parser.parse_args()
feed=args.xnu_source.expanduser().resolve()
pins=[entry for entry in tomllib.loads((R/'feeds.toml').read_text())['source']
      if entry.get('kind')=='refer' and entry.get('name')=='xnu']
if len(pins)!=1 or not re.fullmatch(r'[0-9a-f]{40}', pins[0].get('commit','')):
 parser.error('feeds.toml must contain one full pinned XNU commit')
revision=pins[0]['commit']
try:
 actual_revision=subprocess.check_output(['git','-C',str(feed),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
except (OSError,subprocess.CalledProcessError):
 parser.error('XNU Git checkout unavailable: '+str(feed)+'; prepare official refer/xnu or pass --xnu-source PATH')
if actual_revision!=revision:
 parser.error('XNU revision mismatch: expected '+revision+', got '+actual_revision)

f='bsd/vm/vm_unix.c'
def extract(s,sig):
 a=s.index(sig);e=s.index('{',a)+1;d=1
 while d:d+=(s[e]=='{')-(s[e]=='}');e+=1
 return s[a:e]
with tempfile.TemporaryDirectory(prefix='root-timing-') as t:
 p=Path(t);src=p/f;src.parent.mkdir(parents=True)
 # Read the verified committed blob, never an implicitly patched working file.
 try:
  original=subprocess.check_output(['git','-C',str(feed),'show',revision+':'+f],stderr=subprocess.DEVNULL)
 except subprocess.CalledProcessError:
  parser.error('Pinned XNU checkout lacks '+f)
 src.write_bytes(original)
 for patch in sorted((R/'patches/xnu').glob('*.patch')):
  if patch.name>'zz-root-startup-timing.patch':break
  if ('a/'+f) in patch.read_text():subprocess.run(['git','apply','--unsafe-paths','--include='+f,str(patch)],cwd=p,check=True)
 s=src.read_text();a=s.index('/* Optional cold-start timing.');b=s.index('static int\n_shared_region_map_and_slide(',a)
 helpers=s[a:b].replace('weak_import','weak')
 actual=extract(s,'static int\n_shared_region_map_and_slide(')
 pre=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#include <stdarg.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
typedef int boolean_t,kern_return_t;
#define TRUE 1
#define KERN_SUCCESS 0
#define KERN_INVALID_ADDRESS 1
#define KERN_PROTECTION_FAILURE 2
#define KERN_NO_SPACE 3
#define KERN_FAILURE 5
#define KERN_INVALID_ARGUMENT 4
#define P_NOSHLIB 1
#define SHARED_REGION_TRACE_ERROR(x) ((void)0)
#define SHARED_REGION_TRACE_DEBUG(x) ((void)0)
struct vnode{int refs;};static struct vnode root={0};static struct vnode*rootvnode=&root;
struct proc{struct{struct vnode*fd_rdir;}p_fd;uint32_t p_flag;char p_comm[20];};
struct shared_file_np{int x;};struct shared_file_mapping_slide_np{int x;};struct _sr_file_mappings{int x;};struct vm_shared_region{int x;};
static unsigned flag;static int present,clocks,snapshots,logs,fdlock,setupError,mapError,maps,cleanups;
static uint64_t ticks=1000,metrics[6]={10,100,200,20,200,300};static char output[4096];
static uint64_t mach_absolute_time(void){clocks++;ticks+=10;return ticks;}
static void absolutetime_to_nanoseconds(uint64_t t,uint64_t*n){*n=t;}
static int PE_parse_boot_argn(const char*n,void*v,size_t z){assert(!strcmp(n,"native-root-timing")&&z==sizeof(flag));*(unsigned*)v=flag;return present;}
static int proc_getpid(struct proc*p){(void)p;return 2;}
static void test_printf(const char*f,...){va_list a;va_start(a,f);size_t len=strlen(output);vsnprintf(output+len,sizeof(output)-len,f,a);va_end(a);logs++;}
#define printf test_printf
#ifdef HAVE_PROVIDER
void native_root_timing_snapshot(uint64_t out[6]){snapshots++;memcpy(out,metrics,sizeof(metrics));}
#endif
static void proc_fdlock(struct proc*p){(void)p;assert(!fdlock);fdlock=1;}
static void proc_fdunlock(struct proc*p){(void)p;assert(fdlock);fdlock=0;}
static void vnode_get(struct vnode*v){v->refs++;}
static void vnode_put(struct vnode*v){v->refs--;}
static int shared_region_map_and_slide_setup(struct proc*p,uint32_t n,struct shared_file_np*f,uint32_t m,struct shared_file_mapping_slide_np*x,struct _sr_file_mappings**out,struct vm_shared_region**sr,struct vnode*v){(void)p;(void)n;(void)f;(void)m;(void)x;(void)out;(void)sr;(void)v;assert(!fdlock);return setupError;}
static int vm_shared_region_map_file(struct vm_shared_region*sr,uint32_t n,struct _sr_file_mappings*m){(void)sr;(void)n;(void)m;maps++;metrics[0]+=2;metrics[1]+=8192;metrics[2]+=70;metrics[3]+=2;metrics[4]+=8192;metrics[5]+=30;return mapError;}
static void shared_region_map_and_slide_cleanup(struct proc*p,uint32_t n,struct _sr_file_mappings*m,struct vm_shared_region*sr){(void)p;(void)n;(void)m;(void)sr;cleanups++;}
static void OSBitAndAtomic(uint32_t mask,uint32_t*v){*v&=mask;}
'''
 main=r'''
int main(void){struct proc p={{NULL},P_NOSHLIB,"powervrprobed"};
for(unsigned value=0;value<4;value++)for(int has=0;has<2;has++)for(int phase=0;phase<3;phase++){
flag=value;present=has;clocks=snapshots=logs=maps=cleanups=0;output[0]=0;setupError=phase==1?EACCES:0;mapError=phase==2?KERN_FAILURE:KERN_SUCCESS;
int error=_shared_region_map_and_slide(&p,2,NULL,3,NULL);assert(error==(phase==1?EACCES:phase==2?EINVAL:0));assert(!root.refs&&!fdlock);assert(maps==(phase==1?0:1)&&cleanups==(phase==1?0:1));
int active=0;
#if XNU_ROOT_TIMING
active=has&&value==1;
#endif
assert(clocks==(active?2:0)&&logs==(active?2:0));
#ifdef HAVE_PROVIDER
assert(snapshots==(active?2:0));
#else
assert(!snapshots);
#endif
if(active){assert(strstr(output,"root timing begin pid=2 comm=powervrprobed")&&strstr(output,"root timing end pid=2 comm=powervrprobed elapsed_ns=10"));
#ifdef HAVE_PROVIDER
if(!setupError)assert(strstr(output,"read_calls=2 read_requested_bytes=8192 read_ns=70 verify_calls=2 verify_bytes=8192 verify_ns=30"));
#endif
}}
puts("PASS actual shared-region timing: compile/runtime off no clock/log, strict flags, PID begin/end, setup failure and map failure/success preserve results, optional provider deltas");}
'''
 for feature in (0,1):
  for provider in (False,True):
   (p/'test.c').write_text(pre+helpers+actual+main)
   subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-address','-fsanitize=address,undefined','-fno-pie','-no-pie','-DXNU_ROOT_TIMING='+str(feature),*(['-DHAVE_PROVIDER'] if provider else []),str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)

# Exercise the actual incremental mode stamp in a temporary build tree.
script=(R/'scripts/build-xnu-4k-baseline.sh').read_text()
a=script.index("<<'PYROOT'")
a=script.index('\n',a)+1;b=script.index('\nPYROOT',a);stamp_code=script[a:b]
with tempfile.TemporaryDirectory(prefix='root-timing-stamp-') as t:
 p=Path(t);out=p/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
 sigobj=out/'bsd/DEVELOPMENT/kern_descrip.o';blobobj=out/'bsd/DEVELOPMENT/ubc_subr.o'
 obj=out/'bsd/DEVELOPMENT/vm_unix.o';linked=out/'mach.development.bcm2837.unstripped.noctf';unrelated=out/'bsd/DEVELOPMENT/kern_exec.o'
 def seed():
  obj.parent.mkdir(parents=True,exist_ok=True)
  for f in (obj,sigobj,blobobj,linked,unrelated):f.write_text('sentinel')
 seed();subprocess.run(['python3','-c',stamp_code,'0'],cwd=p,check=True);assert not obj.exists() and not sigobj.exists() and not blobobj.exists() and not linked.exists() and unrelated.exists()
 seed();subprocess.run(['python3','-c',stamp_code,'0'],cwd=p,check=True);assert obj.exists() and sigobj.exists() and blobobj.exists() and linked.exists()
 subprocess.run(['python3','-c',stamp_code,'1'],cwd=p,check=True);assert not obj.exists() and not sigobj.exists() and not blobobj.exists() and not linked.exists() and unrelated.exists()
print('PASS actual root timing build-mode stamp: toggles invalidate vm_unix/kern_descrip/ubc_subr/link only, stable mode preserves objects')
