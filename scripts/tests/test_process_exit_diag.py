#!/usr/bin/env python3
"""Exercise the actual added exit-site code with both flag settings."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
patch=(root/'patches/xnu/zzzz-process-exit-diag.patch').read_text()
code='\n'.join(x[1:] for x in patch.splitlines() if x.startswith('+') and not x.startswith('+++'))
assert 'unixnu-exit-process' in code
src=r'''#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdarg.h>
#include <assert.h>
struct reason { unsigned osr_namespace; uint64_t osr_code; };
struct process { char p_name[16]; struct reason *p_exit_reason; };
static const char *bootarg; static int prints;
static int PE_parse_boot_argn(const char *key, void *out, int len) { (void)key; if (!bootarg) return 0; snprintf(out,len,"%s",bootarg); return 1; }
static const char *exit_reason_get_string_desc(struct reason *r) { return r ? "test description" : 0; }
static int proc_getpid(struct process *p) { (void)p; return 56; }
static int output(const char *format,...) { (void)format; ++prints; return 0; }
#define printf output
static void check(struct process *p, int rv) { (void)p; (void)rv;
''' + code + r'''
}
int main(void) { struct reason r={7,0x1234};struct process p={"backboardd",&r};
 bootarg="other";check(&p,9);assert(!prints);
 bootarg="backboardd";check(&p,9);
#if XNU_PROCESS_EXIT_DIAG
 assert(prints==1);p.p_exit_reason=0;check(&p,0);assert(prints==2);bootarg=0;check(&p,0);assert(prints==3);
#else
 assert(!prints);
#endif
 return 0; }
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'t.c';p.write_text(src)
 for flag in ('0','1'):
  exe=Path(d)/flag
  subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Wno-unused-function','-Werror','-DXNU_PROCESS_EXIT_DIAG='+flag,str(p),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True)
script=(root/'scripts/build-xnu-4k-baseline.sh').read_text()
assert 'XNU_PROCESS_EXIT_DIAG:-0' in script and 'bsd/DEVELOPMENT/kern_exit.o' in script
print('PASS: opt-in flag, process filter, missing reason and object invalidation')
