#!/usr/bin/env python3
"""Compile shipped F_ADDFILESIGS case and timing helpers with host API mocks."""
from pathlib import Path
import argparse, subprocess, tempfile, tomllib
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--xnu-source',type=Path,default=R/'refer/xnu')
a=p.parse_args();feed=a.xnu_source.resolve()
rev=next(x['commit'] for x in tomllib.loads((R/'feeds.toml').read_text())['source'] if x.get('kind')=='refer' and x.get('name')=='xnu')
try: head=subprocess.check_output(['git','-C',str(feed),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
except subprocess.CalledProcessError:p.error('Prepare pinned refer/xnu or pass --xnu-source PATH')
if head!=rev:p.error('XNU revision mismatch: expected '+rev+', got '+head)
f='bsd/kern/kern_descrip.c'
with tempfile.TemporaryDirectory(prefix='signature-timing-') as d:
 t=Path(d);src=t/f;src.parent.mkdir(parents=True)
 src.write_bytes(subprocess.check_output(['git','-C',str(feed),'show',rev+':'+f]))
 subprocess.run(['git','apply','--include='+f,str(R/'patches/xnu/zz-root-startup-timing.patch')],cwd=t,check=True)
 s=src.read_text();helpers=s[s.index('/* Optional signature-case'):s.index('int\nsys_fcntl_nocancel(')]
 helpers=helpers.replace('#include <kern/clock.h>','').replace('#include <pexpert/pexpert.h>','')
 case=s[s.index('\tcase F_ADDSIGS:',s.index('int\nsys_fcntl_nocancel(')):s.index('#if CONFIG_SUPPLEMENTAL_SIGNATURES',s.index('\tcase F_ADDSIGS:',s.index('int\nsys_fcntl_nocancel(')))]
 # Use the shipped cleanup return expressions, not hand-written timing ordering.
 tail=s[s.index('outdrop:\n',s.index('int\nsys_fcntl_nocancel(')):s.index('\n\n/*\n * sys_close')]
 pre=r'''
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <stdarg.h>
#define F_ADDSIGS 1
#define F_ADDFILESIGS 2
#define F_ADDFILESIGS_FOR_DYLD_SIM 3
#define F_ADDFILESIGS_RETURN 4
#define F_ADDFILESIGS_INFO 5
#define DTYPE_VNODE 1
#define MAC_VNODE_CHECK_DYLD_SIM 0
#define CS_KILL 1
#define KERN_SUCCESS 0
#define EAUTH 80
#define UIO_READ 0
#define UIO_SYSSPACE 0
#define CPU_TYPE_ANY 0
#define CPU_SUBTYPE_ANY 0
#define USER_FSIGNATURES_CDHASH_LEN 20
#define IS_64BIT_PROCESS(p) 1
#define CAST_DOWN(t,v) ((t)(v))
#define CAST_USER_ADDR_T(v) ((uintptr_t)(v))
typedef int kern_return_t;typedef uintptr_t vm_offset_t,vm_address_t,user_addr_t;typedef size_t vm_size_t;
struct proc{int pid;uint64_t uniqueid;};typedef struct proc* proc_t;
struct vnode{int x;};struct fileproc{int f_type;};
struct cs_blob{long csb_end_offset;char csb_cdhash[20];int csb_hashtype;};
struct user_fsignatures{long fs_file_start;uintptr_t fs_blob_start;size_t fs_blob_size,fs_fsignatures_size;char fs_cdhash[20];int fs_hash_type;};
struct user32_fsignatures{long fs_file_start;uintptr_t fs_blob_start;size_t fs_blob_size;};
static unsigned flag;static int present=1,clocks,logs,locked,refs,allocated,phase,cached,reads,adds,padding;
static uint64_t ticks;
static struct cs_blob blob_value;static struct user_fsignatures input={0,0,100,0,{0},0};static unsigned char buffer[4096];
static uint64_t mach_absolute_time(void){clocks++;return ticks+=10;}
static void absolutetime_to_nanoseconds(uint64_t v,uint64_t*out){*out=v;}
static int PE_parse_boot_argn(const char*n,void*v,size_t z){assert(!strcmp(n,"native-root-timing")&&z==sizeof(flag));*(unsigned*)v=flag;return present;}
static int proc_getpid(proc_t p){return p->pid;}
static uint64_t proc_uniqueid(proc_t p){return p->uniqueid;}
static char output[8192];
static int mock_printf(const char*f,...){assert(!locked&&!refs&&!allocated);va_list ap;va_start(ap,f);size_t n=strlen(output);vsnprintf(output+n,sizeof(output)-n,f,ap);va_end(ap);logs++;return 0;}
#define printf mock_printf
static void*fp_get_data(struct fileproc*f){return f;}
static void proc_fdunlock(proc_t p){(void)p;assert(locked);locked=0;}
static int proc_getcsflags(proc_t p){(void)p;return CS_KILL;}
static void proc_lock(proc_t p){(void)p;}
static void proc_unlock(proc_t p){(void)p;}
static void proc_csflags_set(proc_t p,int f){(void)p;(void)f;}
static int proc_platform(proc_t p){(void)p;return 0;}
static int vnode_getwithref(struct vnode*v){(void)v;if(phase==1)return EIO;refs++;return 0;}
static int vnode_put(struct vnode*v){(void)v;assert(refs==1);refs--;return 0;}
static int copyin(uintptr_t a,void*b,size_t n){(void)a;if(phase==2)return EFAULT;if(b==buffer){memset(b,0,n);return 0;}memcpy(b,&input,n);return 0;}
static int copyout(const void*a,uintptr_t b,size_t n){(void)a;(void)b;(void)n;return phase==6?EFAULT:0;}
static struct cs_blob*ubc_cs_blob_get(struct vnode*v,int a,int b,long c){(void)v;(void)a;(void)b;(void)c;return cached?&blob_value:NULL;}
static int ubc_cs_blob_revalidate(struct vnode*v,struct cs_blob*b,void*x,int f,int platform){(void)v;(void)b;(void)x;(void)f;(void)platform;return 0;}
static int ubc_cs_blob_allocate(uintptr_t*a,size_t*n){if(phase==3)return 1;allocated=1;*a=(uintptr_t)buffer;*n=4096;return 0;}
static void ubc_cs_blob_deallocate(uintptr_t a,size_t n){assert(a==(uintptr_t)buffer&&n==4096&&allocated);allocated=0;}
static int kauth_cred_get(void){return 0;}
static int vn_rdwr(int op,struct vnode*v,char*b,int n,long off,int space,int flags,int cred,int*resid,proc_t p){(void)op;(void)v;(void)off;(void)space;(void)flags;(void)cred;(void)p;assert(!locked&&refs&&allocated&&n==4096);reads++;memset(b,0x55,n);*resid=padding?16:0;return phase==4?EIO:0;}
static int ubc_cs_blob_add(struct vnode*v,int platform,int cpu,int sub,long off,uintptr_t*a,size_t n,void*x,int flags,struct cs_blob**out){(void)v;(void)platform;(void)cpu;(void)sub;(void)off;(void)n;(void)x;(void)flags;assert(!locked&&refs&&allocated);adds++;if(phase==5)return EAUTH;if(padding)for(int i=4080;i<4096;i++)assert(buffer[i]==0);*a=0;allocated=0;*out=&blob_value;return 0;}
static int cs_hash_type(int n){return n;}
static int sys_fcntl_outdrop(proc_t p,int fd,struct fileproc*f,struct vnode*v,int e){(void)p;(void)fd;(void)f;(void)v;assert(!locked&&!refs&&!allocated);return e;}
static int sys_fcntl_out(proc_t p,int fd,struct fileproc*f,int e){(void)p;(void)fd;(void)f;assert(locked&&!refs&&!allocated);locked=0;return e;}
'''
 wrapper='''static int run(proc_t p,int cmd,int badtype) {
struct native_sig_timing sig_timing={0};uint64_t sig_stage=0;
int fd=3,error=0;struct fileproc file={badtype?0:DTYPE_VNODE},*fp=&file;struct vnode*vp=NULL;uintptr_t argp=0;
locked=1;switch(cmd){\n'''+case+'\n}\n'+tail
 main=r'''
int main(void){struct proc p={2,102};
for(flag=0;flag<4;flag++)for(present=0;present<2;present++)for(int cmd=1;cmd<=5;cmd++)for(phase=0;phase<=6;phase++)for(cached=0;cached<2;cached++)for(padding=0;padding<2;padding++)for(int bad=0;bad<2;bad++){
#if XNU_ROOT_TIMING
memset(native_sig_slots,0,sizeof(native_sig_slots));native_sig_reports=0;
#endif
clocks=logs=reads=adds=0;output[0]=0;int e=run(&p,cmd,bad);assert(!locked&&!refs&&!allocated&&!logs);
int expected=bad?EBADF:phase==1?EIO:phase==2?EFAULT:!cached&&phase==3?ENOMEM:!cached&&phase==4&&cmd!=F_ADDSIGS?EIO:!cached&&phase==5?EAUTH:phase==6&&cmd>=3?EFAULT:0;
assert(e==expected);int active=0;
#if XNU_ROOT_TIMING
active=present&&flag==1&&cmd!=F_ADDSIGS;
if(active){struct native_sig_slot*s=&native_sig_slots[0];assert(s->pid==2&&s->uniqueid==102&&s->count==1&&s->errors==(uint64_t)(e!=0));assert(s->read_count==(uint64_t)reads&&s->add_count==(uint64_t)adds);assert(s->read_ns==10*(uint64_t)reads&&s->add_ns==10*(uint64_t)adds);assert(s->read_bytes==4096*(uint64_t)reads&&s->add_bytes==4096*(uint64_t)adds);assert(s->whole_ns==10+20*(uint64_t)(reads+adds));
for(int i=0;i<10;i++){native_root_signature_timing_report();}assert(logs==8);
}
#endif
if(!active)assert(!clocks);
}
#if XNU_ROOT_TIMING
memset(native_sig_slots,0,sizeof(native_sig_slots));native_sig_reports=0;flag=1;present=1;phase=0;cached=0;padding=0;
for(int pid=1;pid<=5;pid++){p.pid=pid;p.uniqueid=100+pid;assert(!run(&p,F_ADDFILESIGS,0));}
logs=0;output[0]=0;for(int i=0;i<10;i++){native_root_signature_timing_report();}assert(logs==32);
/* PID reuse must occupy a separate process slot; same identity aggregates. */
memset(native_sig_slots,0,sizeof(native_sig_slots));native_sig_reports=0;
p.pid=2;p.uniqueid=0x100000001ULL;assert(!run(&p,F_ADDFILESIGS,0));assert(!run(&p,F_ADDFILESIGS,0));
p.uniqueid=0x200000001ULL;phase=4;assert(run(&p,F_ADDFILESIGS,0)==EIO);
assert(native_sig_slots[0].pid==2&&native_sig_slots[1].pid==2);
assert(native_sig_slots[0].uniqueid==0x100000001ULL&&native_sig_slots[0].count==2&&native_sig_slots[0].errors==0);
assert(native_sig_slots[1].uniqueid==0x200000001ULL&&native_sig_slots[1].count==1&&native_sig_slots[1].errors==1);
assert(native_sig_slots[0].read_count==2&&native_sig_slots[0].add_count==2);
assert(native_sig_slots[1].read_count==1&&native_sig_slots[1].add_count==0);
logs=0;output[0]=0;native_root_signature_timing_report();assert(logs==8);
assert(strstr(output,"p=2 u=4294967297 c=2")&&strstr(output,"p=2 u=8589934593 c=1"));
/* Zero identity is reserved for an empty slot, and cannot start a clock. */
p.uniqueid=0;clocks=0;phase=0;assert(!run(&p,F_ADDFILESIGS,0));assert(!clocks);

#endif
puts("PASS shipped signature case: strict gates, all variants, read/add errors, existing blob, residual zeroing, cleanup-before-finish, bounded unique-ID summaries and PID reuse separation");}
'''
 for mode in (0,1):
  (t/'test.c').write_text(pre+helpers+wrapper+main)
  subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-unused-parameter','-fsanitize=address,undefined','-fno-pie','-no-pie','-DXNU_ROOT_TIMING='+str(mode),str(t/'test.c'),'-o',str(t/'test')],check=True)
  subprocess.run([str(t/'test')],check=True)
