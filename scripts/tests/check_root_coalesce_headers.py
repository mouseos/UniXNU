#!/usr/bin/env python3
"""Cross-compile actual coalescer against pinned real XNU headers, without API mocks."""
from pathlib import Path
import argparse,os,subprocess,tempfile,tomllib
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu-source',type=Path,default=R/'refer/xnu');args=p.parse_args();feed=args.xnu_source.resolve()
rev=next(x['commit'] for x in tomllib.loads((R/'feeds.toml').read_text())['source'] if x.get('kind')=='refer' and x.get('name')=='xnu')
try:head=subprocess.check_output(['git','-C',str(feed),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
except subprocess.CalledProcessError:p.error('Prepare pinned refer/xnu or pass --xnu-source PATH')
if head!=rev:p.error('XNU revision mismatch')
clang=os.environ.get('CLANG','clang');resource=Path(subprocess.check_output([clang,'-print-resource-dir'],text=True).strip())/'include'
with tempfile.TemporaryDirectory(prefix='cs4k-headers-') as directory:
 t=Path(directory);f='bsd/kern/ubc_subr.c';out=t/f;out.parent.mkdir(parents=True);out.write_bytes(subprocess.check_output(['git','-C',str(feed),'show',rev+':'+f]))
 for patch in sorted((R/'patches/xnu').glob('*.patch')):
  subprocess.run(['git','apply','--include='+f,str(patch)],cwd=t,check=True)
 s=out.read_text();a=s.index('#if defined(XNU_NATIVE_CS_HASH_CACHE)',s.index('cs_native4k_existing_locked('));b=s.index('\n#else\nstruct cs_native4k_gate;',a)
 gate=s[a:b]+'\n#endif\n'
 pre='''#include <sys/param.h>
#include <sys/systm.h>
#include <sys/namei.h>
#include <sys/vnode.h>
#include <sys/codedir_internal.h>
#include <libkern/libkern.h>
/* Headers are deliberately included after an existing file-scope function,
 * matching their location in the patched translation unit. */
static void before_headers(void) {}
'''
 (t/'check.c').write_text(pre+gate+'''\nvoid check_gate(vnode_t vp) {
 struct cs_native4k_gate *g=cs_native4k_gate_enter(vp,14);
 cs_native4k_gate_leave(g);
}
''')
 command=[clang,'-target','arm64-apple-ios17.0','-ffreestanding','-nostdinc','-isystem',str(resource),'-DKERNEL','-DPRIVATE','-DXNU_KERNEL_PRIVATE','-DBSD_KERNEL_PRIVATE','-DKERNEL_PRIVATE','-DMACH_KERNEL','-D__arm64__','-DARM64_BOARD_CONFIG_BCM2837','-DXNU_NATIVE_CS_HASH_CACHE=1','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable']
 for relative in ('osfmk','bsd','EXTERNAL_HEADERS','libkern','osfmk/libsa','pexpert','iokit'):command+=['-I',str(feed/relative)]
 subprocess.run(command+['-c',str(t/'check.c'),'-o',str(t/'check.o')],check=True)
 print('PASS actual gate arm64 Mach-O compilation using real pinned XNU headers: static LCK declarations, mid-TU includes, msleep/wakeup, vnode/vid/readonly APIs, codeLimit64 helper; full kernel link remains owner validation')
