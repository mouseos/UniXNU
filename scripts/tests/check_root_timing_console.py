#!/usr/bin/env python3
"""Run shipped summary formats through pinned XNU formatter + 255-byte console."""
from pathlib import Path
import argparse,re,subprocess,tempfile,tomllib
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu-source',type=Path,default=R/'refer/xnu');args=p.parse_args();feed=args.xnu_source.resolve()
rev=next(x['commit'] for x in tomllib.loads((R/'feeds.toml').read_text())['source'] if x.get('kind')=='refer' and x.get('name')=='xnu')
try:head=subprocess.check_output(['git','-C',str(feed),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
except subprocess.CalledProcessError:p.error('Prepare pinned refer/xnu or pass --xnu-source PATH')
if head!=rev:p.error('XNU revision mismatch')
def source(name):return subprocess.check_output(['git','-C',str(feed),'show',rev+':'+name],text=True)
def function(text,signature):
 a=text.index(signature);b=text.index('\n}',a)+2;return text[a:b]+'\n'
formatter=source('osfmk/kern/printf.c');serial=source('osfmk/console/serial_general.c');header=source('osfmk/console/serial_protos.h')
console_struct=header[header.index('struct console_printbuf_state {'):header.index('\n};',header.index('struct console_printbuf_state {'))+3]
size=re.search(r'^#define SERIAL_CONS_BUF_SIZE\s+\d+',header,re.M)[0]
console_write=source('osfmk/console/serial_console.c')
assert int(re.search(r'^#define CPU_CONS_BUF_SIZE\s+(\d+)',console_write,re.M)[1])>=200
assert 'console_ring_reserve_space(chunk_size)' in function(console_write,'void\nconsole_write(')
actual_formatter=function(formatter,'static int\nprintnum(')+function(formatter,'int\n__doprnt(')
actual_console=''.join(function(serial,sig) for sig in ('void\nconsole_printbuf_state_init(', 'void\nconsole_printbuf_putc(', 'void\nconsole_printbuf_clear('))
with tempfile.TemporaryDirectory(prefix='root-console-') as directory:
 t=Path(directory);f='bsd/kern/kern_descrip.c';out=t/f;out.parent.mkdir(parents=True);out.write_text(source(f))
 subprocess.run(['git','apply','--include='+f,str(R/'patches/xnu/zz-root-startup-timing.patch')],cwd=t,check=True)
 s=out.read_text();a=s.index('/* Optional signature-case');b=s.index('int\nsys_fcntl_nocancel(',a);collector=s[a:b].replace('#include <kern/clock.h>','').replace('#include <pexpert/pexpert.h>','')
 pre=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdbool.h>
#include <string.h>
#include <strings.h>
#include <assert.h>
#include <limits.h>
#include <pthread.h>
#define XNU_ROOT_TIMING 1
#define F_ADDSIGS 1
#define TRUE 1
#define FALSE 0
#define OS_FALLTHROUGH __attribute__((fallthrough))
#define VM_MIN_KERNEL_AND_KEXT_ADDRESS 0xffff000000000000ULL
#define VM_MAX_KERNEL_ADDRESS UINT64_MAX
#define MAXBUF (sizeof(long long int)*8)
#define Ctod(c) ((c)-'0')
#define isdigit(d) ((d)>='0'&&(d)<='9')
typedef int boolean_t;
static char digs[]="0123456789abcdef";
static boolean_t _doprnt_truncates=FALSE,doprnt_hide_pointers=FALSE;
static unsigned serialmode;
#define SERIALMODE_SYNCDRAIN 1
static _Thread_local char expected[4096];
static pthread_mutex_t wire_lock=PTHREAD_MUTEX_INITIALIZER;
static unsigned writes,seen[2][4][5],reproduce;
static void console_write(const char*text,int size){
 pthread_mutex_lock(&wire_lock);
 if(reproduce){assert(size==255&&!memchr(text,'\n',size));writes++;pthread_mutex_unlock(&wire_lock);return;}
 assert(size>0&&size<=200&&text[size-1]=='\n');
 assert((int)strlen(expected)==size&&!memcmp(expected,text,size));
 unsigned q=0;int pid;unsigned long long uid;char tag[20];
 assert(sscanf(text,"RST %19s q=%u p=%d u=%llu",tag,&q,&pid,&uid)==4);
 assert(q>=1&&q<=2&&pid==INT_MAX&&uid>=UINT64_MAX-3);
 unsigned kind=!strcmp(tag,"sig")?0:!strcmp(tag,"add")?1:!strcmp(tag,"phase")?2:!strcmp(tag,"vnode")?3:!strcmp(tag,"prep")?4:99;
 assert(kind<5);assert(!seen[q-1][UINT64_MAX-uid][kind]++);writes++;
 pthread_mutex_unlock(&wire_lock);
}
struct proc{int pid;uint64_t uid;};typedef struct proc*proc_t;
static int proc_getpid(proc_t p){return p->pid;}
static uint64_t proc_uniqueid(proc_t p){return p->uid;}
static uint64_t mach_absolute_time(void){return 0;}
static void absolutetime_to_nanoseconds(uint64_t n,uint64_t*out){*out=n;}
static int PE_parse_boot_argn(const char*n,void*v,size_t z){(void)n;(void)v;(void)z;return 0;}
'''
 bridge=r'''
static int fixture_printf(const char*fmt,...){
 assert(!__atomic_load_n(&native_sig_vnodes_busy,__ATOMIC_RELAXED));
 struct console_printbuf_state state;console_printbuf_state_init(&state,TRUE,TRUE);
 va_list a,b;va_start(a,fmt);va_copy(b,a);vsnprintf(expected,sizeof(expected),fmt,b);va_end(b);
 int result=__doprnt(fmt,a,console_printbuf_putc,&state,16,TRUE);va_end(a);
 console_printbuf_clear(&state);return result;
}
'''
 # Reporter references fixture_printf; its body needs the collector's try-lock symbol.
 decl='static int fixture_printf(const char*,...) __attribute__((format(printf,1,2)));\n#define printf fixture_printf\n'
 main=r'''
static void*report(void*unused){(void)unused;native_root_signature_timing_report();return NULL;}
int main(void){
 /* Reproduce the original failure using the actual console buffer. */
 struct console_printbuf_state state;reproduce=1;console_printbuf_state_init(&state,TRUE,TRUE);
 for(int i=0;i<400;i++)console_printbuf_putc('x',&state);
 console_printbuf_putc('\n',&state);console_printbuf_clear(&state);assert(writes==1);reproduce=0;writes=0;
 /* All numeric fields at maximum width, including full-width vnode metadata. */
 memset(native_sig_slots,0xff,sizeof(native_sig_slots));
 for(int i=0;i<4;i++){native_sig_slots[i].pid=INT_MAX;native_sig_slots[i].uniqueid=UINT64_MAX-i;}
 pthread_t a,b;pthread_create(&a,NULL,report,NULL);pthread_create(&b,NULL,report,NULL);pthread_join(a,NULL);pthread_join(b,NULL);
 for(int i=0;i<10;i++)native_root_signature_timing_report();assert(writes==40);
 for(int q=0;q<2;q++)for(int uid=0;uid<4;uid++)for(int kind=0;kind<5;kind++)assert(seen[q][uid][kind]==1);
 puts("PASS actual XNU formatter/console: reproduces 255-byte newline loss; all five full-width records <=200, exact libc vararg parity, concurrent report IDs, each record one complete console write, bounded 40 records");
}
'''
 c=pre+size+'\n'+console_struct+'\n'+actual_formatter+actual_console+decl+collector+'\n#undef printf\n'+bridge+main
 (t/'test.c').write_text(c)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-pie','-no-pie','-pthread',str(t/'test.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
