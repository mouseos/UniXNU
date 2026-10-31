#!/usr/bin/env python3
"""Compile the shipped XNU overlap collector with bounded concurrent host mocks."""
import argparse, pathlib, subprocess, tempfile, tomllib
R=pathlib.Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--xnu-source',type=pathlib.Path,default=R/'refer/xnu');a=p.parse_args()
rev=next(e['commit'] for e in tomllib.loads((R/'feeds.toml').read_text())['source'] if e.get('name')=='xnu')
assert subprocess.check_output(['git','-C',str(a.xnu_source),'rev-parse','HEAD'],text=True).strip()==rev
pre=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <pthread.h>
#include <stdatomic.h>
struct vnode {uint32_t vid; int writable;};typedef struct vnode *vnode_t;
static unsigned flag=0;static _Atomic uint64_t clocks=0;
static int PE_parse_boot_argn(const char*n,void*v,size_t z){assert(!strcmp(n,"native-io-trace")&&z==sizeof(flag));*(unsigned*)v=flag;return 1;}
static uint32_t vnode_vid(vnode_t v){return v->vid;}
static int vnode_vfsisrdonly(vnode_t v){return !v->writable;}
static int proc_selfpid(void){return 42;}
static void *current_thread(void){return 0;}
static uint64_t thread_tid(void*t){(void)t;return 100;}
static uint64_t native_blob_now(void){return atomic_fetch_add(&clocks,1)+1;}
static char output[16384];
static int fake_printf(const char*f,...){va_list a;va_start(a,f);size_t n=strlen(output);int r=vsnprintf(output+n,sizeof(output)-n,f,a);va_end(a);return r;}
#define printf fake_printf
'''
main=r'''
#if XNU_IO_OVERLAP_TRACE
static void*work(void*x){struct vnode*v=x;for(int i=0;i<1000;i++){struct native_cs_trace_event e=native_cs_trace_begin(v,0);e.bytes=16;e.reads=1;native_cs_trace_end(&e,0);}return 0;}
#endif
int main(void){struct vnode a={7,0},b={8,0};
#if XNU_IO_OVERLAP_TRACE
 flag=0;struct native_cs_trace_event e=native_cs_trace_begin(&a,10);assert(!e.id&&!clocks);
 flag=1;a.writable=1;e=native_cs_trace_begin(&a,0);assert(!e.id);a.writable=0;e=native_cs_trace_begin(&a,10);struct native_cs_trace_event f=native_cs_trace_begin(&a,20),g=native_cs_trace_begin(&b,30);
 assert(e.id&&e.id==f.id&&g.id!=e.id&&f.op!=e.op&&e.base==10&&e.pid==42&&e.tid==100);
 e.bytes=16384;e.reads=1;native_cs_trace_end(&e,0);native_cs_trace_end(&f,5);native_cs_trace_end(&g,0);
 native_cs_trace_report();assert(strstr(output,"seq=1 count=6 full=0 busy=0 keys_full=0"));assert(strstr(output,"base=10 bytes=16384 reads=1 error=0"));assert(strstr(output,"CS overlap end seq=1 count=6"));
 output[0]=0;for(int i=0;i<40;i++){e=native_cs_trace_begin(&a,0);native_cs_trace_end(&e,0);}native_cs_trace_report();assert(strstr(output,"count=32 full=48"));
 __atomic_store_n(&native_cs_trace.lock,1,__ATOMIC_RELEASE);e=native_cs_trace_begin(&a,0);assert(!e.id);__atomic_store_n(&native_cs_trace.lock,0,__ATOMIC_RELEASE);output[0]=0;native_cs_trace_report();assert(strstr(output,"busy=1"));
 struct vnode vs[70];for(int i=0;i<70;i++){vs[i].vid=i+100;vs[i].writable=0;e=native_cs_trace_begin(&vs[i],0);native_cs_trace_end(&e,0);}output[0]=0;native_cs_trace_report();assert(strstr(output,"keys_full=8"));
 pthread_t threads[4];for(int i=0;i<4;i++)assert(!pthread_create(&threads[i],0,work,&a));for(int i=0;i<4;i++)pthread_join(threads[i],0);
 assert(native_cs_trace.n<=32);output[0]=0;native_cs_trace_report();assert(strstr(output,"CS overlap end"));
#else
 (void)b;struct native_cs_trace_event e=native_cs_trace_begin(&a,0);native_cs_trace_end(&e,0);assert(!clocks);
#endif
 return 0;}
'''
with tempfile.TemporaryDirectory() as d:
 t=pathlib.Path(d);f='bsd/kern/ubc_subr.c';out=t/f;out.parent.mkdir(parents=True);out.write_bytes(subprocess.check_output(['git','-C',str(a.xnu_source),'show',rev+':'+f]))
 for patch in [*sorted((R/'patches/xnu').glob('*.patch')),*sorted((R/'kits/NativePrelink/patches').glob('*.patch'))]:subprocess.run(['git','apply','--include='+f,str(patch)],cwd=t,check=True)
 s=out.read_text();begin=s.index('/* Optional bounded correlation trace.');end=s.index('\n__attribute__((noinline))\nstatic int\ncs_native4k_prepare',begin)
 body=s[begin:end];assert 'cs_trace.reads++; cs_trace.bytes += length;' in s and 'native_cs_trace_end(&cs_trace, error);' in s
 (t/'test.c').write_text(pre+body+main)
 for mode in (0,1):
  subprocess.run(['cc','-std=gnu11','-pthread','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=address,undefined','-fno-pie','-no-pie','-DXNU_ROOT_TIMING=1','-DXNU_IO_OVERLAP_TRACE='+str(mode),str(t/'test.c'),'-o',str(t/'test')],check=True)
  subprocess.run([str(t/'test')],check=True)
print('PASS actual XNU trace default off, vnode/vid ID, bounds, errors, drops, complete reports and concurrent producers; ASan/UBSan')
