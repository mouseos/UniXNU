#!/usr/bin/env python3
"""Execute the actual preparer and page validator with real SHA-256 on the host."""
import argparse,ast,pathlib,subprocess,tempfile,tomllib
R=pathlib.Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--xnu-source',type=pathlib.Path,default=R/'refer/xnu');a=p.parse_args()
rev=next(e['commit'] for e in tomllib.loads((R/'feeds.toml').read_text())['source'] if e.get('name')=='xnu')
assert subprocess.check_output(['git','-C',str(a.xnu_source),'rev-parse','HEAD'],text=True).strip()==rev
syntax=ast.parse((R/'scripts/tests/check_root_read_batch.py').read_text())
def literal(name):return next(ast.literal_eval(n.value) for n in ast.walk(syntax) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
pre=literal('pre');helpers=literal('main').split('int main(void)')[0]
pre=pre.replace('struct cs_blob {const CS_CodeDirectory*csb_cd;', 'struct cs_blob {struct cs_blob *csb_next;off_t csb_start_offset,csb_end_offset;size_t csb_mem_offset;const CS_CodeDirectory*csb_cd;')
pre+='''\ntypedef int boolean_t;typedef void *memory_object_t;typedef unsigned long long memory_object_offset_t;\n#define FALSE 0\n#define CS_VALIDATE_TAINTED 1\n#define CS_VALIDATE_NX 2\n#define CAST_DOWN(type,value) ((type)(value))\nstatic unsigned long cs_native4k_page_checks,cs_validate_page_no_hash;static int cs_debug;\n#define panic(...) abort()\n'''
main=r'''
int main(void){
 CS_CodeDirectory cd;struct cs_blob blob;struct vnode vnode={1};
 unsigned char baseline[32*72];
 for(int batch=0;batch<2;batch++){
  reset();batch_present=1;batch_flag=batch;setup(17*16384+123,&cd,&blob);
  blob.csb_start_offset=0;blob.csb_end_offset=input_size;
  assert(!cs_native4k_prepare(&vnode,&blob));
  assert(blob.csb_native4k_hashes&&cs_native4k_full_blocks==18);
  assert(reads==(batch?2:18)&&read_bytes==input_size);
  size_t hashbytes=blob.csb_native4k_hash_count*md.cs_size;
  assert(hashbytes<=sizeof(baseline));
  if(!batch)memcpy(baseline,blob.csb_native4k_hashes,hashbytes);
  else assert(!memcmp(baseline,blob.csb_native4k_hashes,hashbytes));
  size_t fullpages=input_size/4096;
  for(size_t page=0;page<fullpages;page++){
   vm_size_t bytes=0;unsigned taint=0;
   assert(cs_validate_hash(&blob,NULL,(memory_object_offset_t)page*4096,input+page*4096,&bytes,&taint));
   assert(bytes==4096&&taint==0);
   input[page*4096+100]^=1;taint=0;bytes=0;
   assert(cs_validate_hash(&blob,NULL,(memory_object_offset_t)page*4096,input+page*4096,&bytes,&taint));
   assert(bytes==4096&&(taint&CS_VALIDATE_TAINTED));input[page*4096+100]^=1;
  }
  assert(cs_validate_page_bad_hash==fullpages);dispose(&blob);
  for(int variant=0;variant<2;variant++)for(int bad=0;bad<18;bad++){
   reset();batch_present=1;batch_flag=batch;setup(17*16384+123,&cd,&blob);
   if(variant)input[bad*16384]^=1;else expected_hashes[bad*md.cs_size]^=1;
   assert(cs_native4k_prepare(&vnode,&blob)==EBADEXEC);
   assert(cs_native4k_full_blocks==(unsigned)bad&&!blob.csb_native4k_hashes&&!cs_native4k_ready_blobs);
   dispose(&blob);
  }
 }
 puts("PASS actual 16KiB and 256KiB preparers: equal derived hashes, every modified 4KiB page tainted, every bad 16KiB block rejected before publication");
}
'''
with tempfile.TemporaryDirectory() as d:
 t=pathlib.Path(d);f='bsd/kern/ubc_subr.c';out=t/f;out.parent.mkdir(parents=True);out.write_bytes(subprocess.check_output(['git','-C',str(a.xnu_source),'show',rev+':'+f]))
 for patch in [*sorted((R/'patches/xnu').glob('*.patch')),*sorted((R/'kits/NativePrelink/patches').glob('*.patch'))]:subprocess.run(['git','apply','--include='+f,str(patch)],cwd=t,check=True)
 source=out.read_text();start=source.index('/* Optional profiling of the eager');fn=source.index('static int\ncs_native4k_prepare(',start);end=source.index('\n}\n',fn)+2
 body=source[start:end].replace('#include <pexpert/pexpert.h>','')
 start=source.index('static boolean_t\ncs_validate_hash(',end);end=source.index('\n}\n',start)+2;validator=source[start:end]
 (t/'test.c').write_text(pre+body+'\n'+validator+'\n'+helpers+main)
 libs=subprocess.check_output(['pkg-config','--cflags','--libs','openssl'],text=True).split()
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-misleading-indentation','-Wno-deprecated-declarations','-fsanitize=address,undefined','-fno-pie','-no-pie','-DXNU_ROOT_TIMING=0','-DXNU_IO_OVERLAP_TRACE=0',str(t/'test.c'),'-o',str(t/'test'),*libs],check=True)
 subprocess.run([str(t/'test')],check=True,timeout=30)
