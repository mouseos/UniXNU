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
assert pre.count('struct cs_blob {const CS_CodeDirectory*csb_cd;') == 1
pre=pre.replace('struct cs_blob {const CS_CodeDirectory*csb_cd;', 'struct cs_blob {struct cs_blob *csb_next;off_t csb_start_offset,csb_end_offset;size_t csb_mem_offset;const CS_CodeDirectory*csb_cd;')
assert pre.count('reads++;read_bytes+=length;if((size_t)length>max_read)max_read=length;') == 1
pre=pre.replace('reads++;read_bytes+=length;if((size_t)length>max_read)max_read=length;',
                'reads++;read_bytes+=length;if((size_t)length>max_read)max_read=length; if (offset+(size_t)length>fail_from) return EACCES;')
pre=pre.replace('static unsigned batch_flag', 'static size_t fail_from=(size_t)-1;\nstatic unsigned batch_flag', 1)
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
  if(!batch){printf("COMPARE hash ");for(size_t i=0;i<hashbytes;i++)printf("%02x",blob.csb_native4k_hashes[i]);putchar('\n');}
  size_t fullpages=input_size/4096;
  for(size_t page=0;page<fullpages;page++){
   vm_size_t bytes=0;unsigned taint=0;
   assert(cs_validate_hash(&blob,NULL,(memory_object_offset_t)page*4096,input+page*4096,&bytes,&taint));
   assert(bytes==4096&&taint==0);
   input[page*4096+100]^=1;taint=0;bytes=0;
   assert(cs_validate_hash(&blob,NULL,(memory_object_offset_t)page*4096,input+page*4096,&bytes,&taint));
   assert(bytes==4096&&(taint&CS_VALIDATE_TAINTED));
   if(!batch)printf("COMPARE page %zu %zu %u\n",page,(size_t)bytes,taint);
   input[page*4096+100]^=1;
  }
  vm_size_t tailbytes=0;unsigned tailtaint=0;
  assert(cs_validate_hash(&blob,NULL,(memory_object_offset_t)fullpages*4096,input+fullpages*4096,&tailbytes,&tailtaint));
  assert(tailbytes==4096 && tailtaint==CS_VALIDATE_NX);
  input[fullpages*4096+100]^=1;tailtaint=0;tailbytes=0;
  assert(cs_validate_hash(&blob,NULL,(memory_object_offset_t)fullpages*4096,input+fullpages*4096,&tailbytes,&tailtaint));
  assert(tailbytes==4096 && (tailtaint&CS_VALIDATE_NX) && (tailtaint&CS_VALIDATE_TAINTED));
  if(!batch)printf("COMPARE tail %zu %u\n",(size_t)tailbytes,tailtaint);
  assert(cs_validate_page_bad_hash==fullpages+1);dispose(&blob);
  for(int variant=0;variant<2;variant++)for(int bad=0;bad<18;bad++){
   reset();batch_present=1;batch_flag=batch;setup(17*16384+123,&cd,&blob);
   if(variant)input[bad*16384]^=1;else expected_hashes[bad*md.cs_size]^=1;
   int result=cs_native4k_prepare(&vnode,&blob);assert(result==EBADEXEC);
   if(!batch)printf("COMPARE corrupt %d %d %d %zu\n",variant,bad,result,reads);
   assert(cs_native4k_full_blocks==(unsigned)bad&&!blob.csb_native4k_hashes&&!cs_native4k_ready_blobs);
   dispose(&blob);
  }
 }
 /* Absent selector and explicit non-one values retain the original read size. */
 for(int setting=0;setting<3;setting++){
  reset();batch_present=setting!=0;batch_flag=setting==2?2:0;setup(32768,&cd,&blob);
  assert(!cs_native4k_prepare(&vnode,&blob));
  assert(reads==2&&read_bytes==32768&&scratch_size==16384&&cs_native4k_full_blocks==2);
  dispose(&blob);
 }
 /* Faults at the first and second 16KiB reads: original and default-off must agree. */
 for(int fault=0;fault<4;fault++)for(int location=1;location<=2;location++){
  reset();batch_present=0;batch_flag=0;setup(32768,&cd,&blob);
  int want;
  if(fault==0){read_error_call=location;want=EACCES;}
  else if(fault==1){resid_call=location;want=EIO;}
  else if(fault==2){null_hash_index=location-1;want=EBADEXEC;}
  else {expected_hashes[(location-1)*md.cs_size]^=1;want=EBADEXEC;}
  int result=cs_native4k_prepare(&vnode,&blob);assert(result==want);
  printf("COMPARE fault %d %d %d %zu %lu\n",fault,location,result,reads,cs_native4k_full_blocks);
  assert(reads==(unsigned)location&&cs_native4k_full_blocks==(unsigned)(location-1));
  assert(!blob.csb_native4k_hashes&&!cs_native4k_ready_blobs&&!protects);
  dispose(&blob);
 }
 for(int batch=0;batch<2;batch++){
  reset();batch_present=1;batch_flag=batch;setup(32768,&cd,&blob);
  expected_hashes[0]^=1;fail_from=16384;
  assert(cs_native4k_prepare(&vnode,&blob)==(batch?EACCES:EBADEXEC));
  assert(!blob.csb_native4k_hashes&&!cs_native4k_ready_blobs);
  fail_from=(size_t)-1;dispose(&blob);
 }
 puts("PASS actual 16KiB and 256KiB preparers: equal derived hashes, every modified 4KiB page including tail tainted, every bad 16KiB block rejected before publication");
}
'''
with tempfile.TemporaryDirectory() as d:
 t=pathlib.Path(d);f='bsd/kern/ubc_subr.c';out=t/f;out.parent.mkdir(parents=True);out.write_bytes(subprocess.check_output(['git','-C',str(a.xnu_source),'show',rev+':'+f]))
 before_batch=None
 for patch in [*sorted((R/'patches/xnu').glob('*.patch')),*sorted((R/'kits/NativePrelink/patches').glob('*.patch'))]:
  if patch.name=='zzx-native4k-read-batch.patch':before_batch=out.read_text()
  subprocess.run(['git','apply','--include='+f,str(patch)],cwd=t,check=True)
 assert before_batch is not None
 source=out.read_text();start=source.index('/* Optional profiling of the eager');fn=source.index('static int\ncs_native4k_prepare(',start);end=source.index('\n}\n',fn)+2
 body=source[start:end].replace('#include <pexpert/pexpert.h>','')
 start=source.index('static boolean_t\ncs_validate_hash(',end);end=source.index('\n}\n',start)+2;validator=source[start:end]
 (t/'test.c').write_text(pre+body+'\n'+validator+'\n'+helpers+main)
 libs=subprocess.check_output(['pkg-config','--cflags','--libs','openssl'],text=True).split()
 comparisons=[]
 for timing in (0,1):
  subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-misleading-indentation','-Wno-deprecated-declarations','-fsanitize=address,undefined','-fno-pie','-no-pie',f'-DXNU_ROOT_TIMING={timing}','-DXNU_IO_OVERLAP_TRACE=0',str(t/'test.c'),'-o',str(t/'test'),*libs],check=True)
  result=subprocess.run([str(t/'test')],check=True,timeout=30,capture_output=True,text=True)
  comparisons.append([line for line in result.stdout.splitlines() if line.startswith('COMPARE ')])
  print(result.stdout.splitlines()[-1])

 # Compare to the actual preparer before the read-batch patch, not just its off mode.
 fn=before_batch.index('static int\ncs_native4k_prepare(',before_batch.index('cs_validate_page_bad_hash'))
 end=before_batch.index('\n}\n',fn)+2
 original=before_batch[fn:end]
 start=before_batch.index('static boolean_t\ncs_validate_hash(',end);end=before_batch.index('\n}\n',start)+2
 original_validator=before_batch[start:end]
 assert original_validator==validator, 'later patches changed actual page validator'
 original_main=main.replace('batch<2','batch<1').replace('actual 16KiB and 256KiB preparers','pre-batch 16KiB preparer')
 (t/'original.c').write_text(pre+original+'\n'+original_validator+'\n'+helpers+original_main)
 for timing in (0,1):
  subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-misleading-indentation','-Wno-deprecated-declarations','-fsanitize=address,undefined','-fno-pie','-no-pie',f'-DXNU_ROOT_TIMING={timing}','-DXNU_IO_OVERLAP_TRACE=0',str(t/'original.c'),'-o',str(t/'original'),*libs],check=True)
  result=subprocess.run([str(t/'original')],check=True,timeout=30,capture_output=True,text=True)
  original_values=[line for line in result.stdout.splitlines() if line.startswith('COMPARE ')]
  assert len(original_values)>100 and original_values==comparisons[timing], 'original/default-off values differ'
  print('PASS original/default-off hash, page taints and fault results directly equal; timing='+str(timing))
