#!/usr/bin/env python3
"""Run actual native4k preparer with real SHA-256 and bounded I/O/VM API mocks."""
from pathlib import Path
import argparse,subprocess,tempfile,tomllib
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu-source',type=Path,default=R/'refer/xnu');args=p.parse_args();feed=args.xnu_source.resolve()
rev=next(x['commit'] for x in tomllib.loads((R/'feeds.toml').read_text())['source'] if x.get('kind')=='refer' and x.get('name')=='xnu')
try:head=subprocess.check_output(['git','-C',str(feed),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
except subprocess.CalledProcessError:p.error('Prepare pinned refer/xnu or pass --xnu-source PATH')
if head!=rev:p.error('XNU revision mismatch')
pre=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
#include <strings.h>
#include <errno.h>
#include <limits.h>
#include <arpa/inet.h>
#include <openssl/sha.h>
#define XNU_NATIVE_CS_HASH_CACHE 1
#define PAGE_SHIFT 12
#define PAGE_SIZE 4096
#define PAGE_MASK 4095
#define CS_HASH_MAX_SIZE 64
#define CS_SUPPORTSSCATTER 0x20100
#define CS_SUPPORTSCODELIMIT64 0x20300
#define ntohll(x) __builtin_bswap64(x)
#define EBADEXEC 85
#define KERN_SUCCESS 0
#define KMA_KOBJECT 1
#define KMA_DATA 2
#define KMA_ZERO 4
#define VM_KERN_MEMORY_SECURITY 0
#define VM_PROT_READ 1
#define TRUE 1
#define Z_WAITOK 1
#define UIO_READ 0
#define UIO_SYSSPACE 0
#define MIN(a,b) ((a)<(b)?(a):(b))
#define os_mul_overflow(a,b,out) __builtin_mul_overflow((a),(b),(out))
#define os_add_overflow(a,b,out) __builtin_add_overflow((a),(b),(out))
#define os_atomic_inc(p,order) (++*(p))
typedef uintptr_t vm_offset_t;typedef size_t vm_size_t;typedef int kern_return_t;
union cs_hash_union {SHA256_CTX sha;};
struct cs_hash {size_t cs_size,cs_digest_size;void(*cs_init)(union cs_hash_union*);void(*cs_update)(union cs_hash_union*,const void*,size_t);void(*cs_final)(void*,union cs_hash_union*);};
typedef struct {uint32_t version,scatterOffset,codeLimit,nCodeSlots;uint64_t codeLimit64;}CS_CodeDirectory;
struct cs_blob {const CS_CodeDirectory*csb_cd;const struct cs_hash*csb_hashtype;unsigned csb_hash_pageshift,csb_hash_firstlevel_pageshift;off_t csb_base_offset;const void*csb_mem_kaddr;size_t csb_mem_size;const uint8_t*csb_native4k_hashes;size_t csb_native4k_hashes_size,csb_native4k_hash_count;};
struct vnode{int readonly;};typedef struct vnode*vnode_t;
struct proc{int pid;uint64_t uid;};typedef struct proc*proc_t;
static unsigned batch_flag,root_flag=1;static int batch_present,root_present=1;
static unsigned clocks,identity_reads,timing_records;static uint64_t ticks,reported[5];static int reported_batched;
static uint8_t *input,*snapshot,*expected_hashes;static size_t input_size,read_size,scratch_size;
static size_t reads,read_bytes,max_read,original_hashes,derived_hashes;
static int scratch_live,storage_live,protects,fail_storage,fail_scratch,fail_protect,fail_round;
static int read_error_call,resid_call,null_hash_index=-1,corrupt_hash_index=-1,mutate_after_read;
static off_t file_base;static struct cs_blob*observed_blob;static void*storage_pointer;
static unsigned long cs_native4k_full_blocks,cs_native4k_ready_blobs,cs_validate_page_bad_hash;
static int kernel_map;
static void sha_init(union cs_hash_union*c){SHA256_Init(&c->sha);}
static void sha_update(union cs_hash_union*c,const void*b,size_t n){SHA256_Update(&c->sha,b,n);}
static void sha_final(void*out,union cs_hash_union*c){SHA256_Final(out,&c->sha);}
static struct cs_hash md={32,32,sha_init,sha_update,sha_final};
static int PE_parse_boot_argn(const char*n,void*out,size_t z){assert(z==sizeof(unsigned));if(!strcmp(n,"native-cs-read-batch")){*(unsigned*)out=batch_flag;return batch_present;}assert(!strcmp(n,"native-root-timing"));*(unsigned*)out=root_flag;return root_present;}
static proc_t current_proc(void){static struct proc p={2,102};return &p;}
static int proc_getpid(proc_t p){identity_reads++;return p->pid;}
static uint64_t proc_uniqueid(proc_t p){identity_reads++;return p->uid;}
static uint64_t native_blob_now(void){clocks++;return ticks+=10;}
static void native_root_hash_timing_record(int pid,uint64_t uid,const uint64_t m[5],int batched){assert(pid==2&&uid==102);memcpy(reported,m,sizeof(reported));reported_batched=batched;timing_records++;}
static int vnode_vfsisrdonly(vnode_t v){return v->readonly;}
static int round_page_overflow(size_t n,size_t*out){if(fail_round)return 1;return __builtin_add_overflow(n,(size_t)4095,out)?1:(*out&=~(size_t)4095,0);}
static int kmem_alloc(int map,uintptr_t*out,size_t n,int flags,int tag){(void)map;(void)flags;(void)tag;if(fail_storage)return 1;assert(!storage_live);*out=(uintptr_t)calloc(1,n);assert(*out);storage_pointer=(void*)*out;storage_live=1;return 0;}
static void kmem_free(int map,uintptr_t addr,size_t n){(void)map;(void)n;assert(storage_live&&(void*)addr==storage_pointer);free((void*)addr);storage_pointer=NULL;storage_live=0;}
static void*kalloc_data(size_t n,int f){(void)f;if(fail_scratch)return NULL;assert(!scratch_live);scratch_size=n;scratch_live=1;uint8_t*p=malloc(n);assert(p);memset(p,0xa5,n);return p;}
static void kfree_data(void*p,size_t n){assert(p&&scratch_live&&n==scratch_size);scratch_live=0;free(p);}
static int vfs_context_current(void){return 0;}
static int vfs_context_ucred(int c){return c;}
static int vn_rdwr(int op,vnode_t v,char*buffer,int length,off_t position,int space,int flags,int cred,int*resid,proc_t p){
 (void)op;(void)v;(void)space;(void)flags;(void)cred;(void)p;
 assert(!observed_blob->csb_native4k_hashes&&length>0&&(unsigned)length<=262144);
 assert(position>=file_base);uint64_t offset=(uint64_t)(position-file_base);assert(offset<=input_size&&(uint64_t)length<=input_size-offset);
 reads++;read_bytes+=length;if((size_t)length>max_read)max_read=length;
 if(read_error_call==(int)reads)return EACCES;
 memcpy(buffer,input+offset,length);*resid=resid_call==(int)reads?1:0;
 if(mutate_after_read)input[offset]^=0x80;
 return 0;
}
static const uint8_t*hashes(const CS_CodeDirectory*cd,uint32_t index,size_t stride,const char*lower,const char*upper){
 assert(index<ntohl(cd->nCodeSlots)&&stride==md.cs_size&&lower==(const char*)cd&&upper==lower+observed_blob->csb_mem_size);
 if((int)index==null_hash_index)return NULL;
 return expected_hashes+(size_t)index*stride;
}
static int vm_map_protect(int map,uintptr_t start,uintptr_t end,int perm,int maximum){
 (void)map;assert((void*)start==storage_pointer&&end>start&&perm==VM_PROT_READ&&maximum==TRUE);
 assert(!observed_blob->csb_native4k_hashes&&!observed_blob->csb_native4k_hashes_size&&!observed_blob->csb_native4k_hash_count);
 assert(cs_native4k_full_blocks==(input_size+16383)/16384);
 for(size_t offset=0;offset<input_size;offset+=4096){uint8_t digest[32];SHA256(snapshot+offset,MIN((size_t)4096,input_size-offset),digest);assert(!memcmp((void*)(start+(offset/4096)*md.cs_size),digest,md.cs_size));}
 for(size_t i=((input_size+4095)/4096)*md.cs_size;i<end-start;i++)assert(((uint8_t*)start)[i]==0);
 protects++;return fail_protect?1:0;
}
'''
main=r'''
static void reset(void){assert(!scratch_live&&!storage_live);reads=read_bytes=max_read=clocks=identity_reads=timing_records=protects=0;ticks=0;memset(reported,0,sizeof(reported));reported_batched=0;cs_native4k_full_blocks=cs_native4k_ready_blobs=cs_validate_page_bad_hash=0;fail_storage=fail_scratch=fail_protect=fail_round=read_error_call=resid_call=mutate_after_read=0;null_hash_index=corrupt_hash_index=-1;file_base=0;}
static void setup(size_t length,CS_CodeDirectory*cd,struct cs_blob*blob){
 input_size=length;input=malloc(length);snapshot=malloc(length);assert(input&&snapshot);
 for(size_t i=0;i<length;i++)input[i]=(uint8_t)(i*17+(i>>12));memcpy(snapshot,input,length);
 size_t blocks=(length+16383)/16384;expected_hashes=malloc(blocks*md.cs_size);assert(expected_hashes);
 for(size_t i=0;i<blocks;i++){uint8_t digest[32];SHA256(input+i*16384,MIN((size_t)16384,length-i*16384),digest);memcpy(expected_hashes+i*md.cs_size,digest,md.cs_size);}
 *cd=(CS_CodeDirectory){.codeLimit=htonl(length),.nCodeSlots=htonl(blocks)};
 *blob=(struct cs_blob){.csb_cd=cd,.csb_hashtype=&md,.csb_hash_pageshift=14,.csb_mem_kaddr=cd,.csb_mem_size=sizeof(*cd)};observed_blob=blob;
}
static void dispose(struct cs_blob*b){if(b->csb_native4k_hashes)kmem_free(0,(uintptr_t)b->csb_native4k_hashes,b->csb_native4k_hashes_size);assert(!scratch_live&&!storage_live);free(input);free(snapshot);free(expected_hashes);}
static void check_telemetry(int batched){int active=0;
#if XNU_ROOT_TIMING
 active=root_present&&root_flag==1;
#endif
 assert(timing_records==(unsigned)active);
 if(active){assert(reported[3]==reads&&reported[4]==read_bytes&&reported[0]==reads*10&&reported_batched==batched);}
 else assert(!clocks&&!identity_reads);
}
int main(void){
const size_t limits[]={1,4095,4096,4097,16383,16384,16385,262143,262144,262145,524288+4099};
for(int exists=0;exists<2;exists++)for(unsigned value=0;value<4;value++)for(int ro=0;ro<2;ro++)for(size_t i=0;i<sizeof(limits)/sizeof(limits[0]);i++){
 reset();batch_present=exists;batch_flag=value;CS_CodeDirectory cd;struct cs_blob blob;setup(limits[i],&cd,&blob);struct vnode v={ro};
 int batched=exists&&value==1&&ro;size_t chunk=batched?262144:16384;
 assert(!cs_native4k_prepare(&v,&blob));assert(reads==(input_size+chunk-1)/chunk&&read_bytes==input_size&&max_read<=chunk);
 assert(scratch_size==chunk&&protects==1&&cs_native4k_ready_blobs==1&&blob.csb_native4k_hash_count==(input_size+4095)/4096);
 check_telemetry(batched);
#if XNU_ROOT_TIMING
 if(root_flag==1){assert(reported[1]==((input_size+16383)/16384)*10&&reported[2]==((input_size+4095)/4096)*10);}
#endif
 dispose(&blob);
}
/* Real truncated SHA-256 strides, tail and same-buffer derivation after backing mutation. */
reset();batch_flag=batch_present=1;md.cs_size=20;CS_CodeDirectory cd;struct cs_blob blob;setup(262144+123,&cd,&blob);struct vnode v={1};mutate_after_read=1;assert(!cs_native4k_prepare(&v,&blob));assert(memcmp(input,snapshot,input_size));check_telemetry(1);dispose(&blob);md.cs_size=32;
/* Corruption anywhere, including later original blocks in one batch, never publishes. */
for(int batch=0;batch<2;batch++)for(int index=0;index<19;index++){
 reset();batch_flag=batch;setup(18*16384+123,&cd,&blob);expected_hashes[index*md.cs_size]^=1;
 assert(cs_native4k_prepare(&v,&blob)==EBADEXEC);assert(cs_native4k_full_blocks==(unsigned)index&&cs_validate_page_bad_hash==1&&!protects&&!cs_native4k_ready_blobs);
 assert(!blob.csb_native4k_hashes&&!blob.csb_native4k_hashes_size&&!blob.csb_native4k_hash_count);check_telemetry(batch);dispose(&blob);
}
for(int fault=0;fault<8;fault++){
 reset();batch_flag=1;setup(524288+123,&cd,&blob);
 int expected=0;
 if(fault==0){read_error_call=2;expected=EACCES;}if(fault==1){resid_call=2;expected=EIO;}
 if(fault==2){null_hash_index=17;expected=EBADEXEC;}if(fault==3){fail_protect=1;expected=EPERM;}
 if(fault==4){fail_scratch=1;expected=ENOMEM;}if(fault==5){fail_storage=1;expected=ENOMEM;}
 if(fault==6){fail_round=1;expected=EOVERFLOW;}if(fault==7){blob.csb_base_offset=file_base=INT64_MAX-4095;expected=EOVERFLOW;}
 assert(cs_native4k_prepare(&v,&blob)==expected);assert(!blob.csb_native4k_hashes&&!blob.csb_native4k_hashes_size&&!blob.csb_native4k_hash_count&&!cs_native4k_ready_blobs);check_telemetry(fault<5||fault==7);dispose(&blob);
}
/* Read failures/short reads at first, middle and last request in both modes. */
for(int batch=0;batch<2;batch++)for(int short_read=0;short_read<2;short_read++)for(int location=0;location<3;location++){
 reset();batch_flag=batch;setup(524288+123,&cd,&blob);size_t chunk=batch?262144:16384;int total=(input_size+chunk-1)/chunk;
 int request=location==0?1:location==1?(total+1)/2:total;
 if(short_read)resid_call=request;else read_error_call=request;
 assert(cs_native4k_prepare(&v,&blob)==(short_read?EIO:EACCES));assert(reads==(size_t)request&&!protects&&!blob.csb_native4k_hashes&&!cs_native4k_ready_blobs);check_telemetry(batch);dispose(&blob);
}
/* Original compatibility rejections and page-size no-op remain intact. */
for(int fault=0;fault<7;fault++){
 reset();setup(16384,&cd,&blob);int expected=ENOTSUP;
 if(fault==0)blob.csb_hash_pageshift=13;
 if(fault==1)blob.csb_base_offset=-4096;
 if(fault==2)blob.csb_hash_firstlevel_pageshift=1;
 if(fault==3){cd.version=htonl(CS_SUPPORTSSCATTER);cd.scatterOffset=htonl(1);}
 if(fault==4){cd.version=htonl(CS_SUPPORTSCODELIMIT64);cd.codeLimit64=__builtin_bswap64(0x100004000ULL);}
 if(fault==5)cd.nCodeSlots=htonl(2);
 if(fault==6){blob.csb_hash_pageshift=12;expected=0;}
 assert(cs_native4k_prepare(&v,&blob)==expected&&!reads&&!protects&&!blob.csb_native4k_hashes);check_telemetry(0);dispose(&blob);
}
/* Strict root gate must not perform identity reads or clocks when disabled. */
for(root_present=0;root_present<2;root_present++)for(root_flag=0;root_flag<4;root_flag++){
 reset();setup(32769,&cd,&blob);assert(!cs_native4k_prepare(&v,&blob));check_telemetry(1);dispose(&blob);
}
puts("PASS actual preparer + real SHA256: strict/default/readonly gates, 4K/16K/256K boundaries, partial tails, digest strides, same-buffer derivation, every corrupt block, read/resid/nullhash/alloc/protect/overflow failures without publication, compatibility and gated read/original/derived timing");}
'''
with tempfile.TemporaryDirectory(prefix='native4k-batch-') as directory:
 t=Path(directory);f='bsd/kern/ubc_subr.c';out=t/f;out.parent.mkdir(parents=True);out.write_bytes(subprocess.check_output(['git','-C',str(feed),'show',rev+':'+f]))
 for patch in [*sorted((R/'patches/xnu').glob('*.patch')),*sorted((R/'kits/NativePrelink/patches').glob('*.patch'))]:
  subprocess.run(['git','apply','--include='+f,str(patch)],cwd=t,check=True)
 s=out.read_text();a=s.index('/* Optional profiling of the eager');b=s.index('static int\ncs_native4k_prepare(',a);end=s.index('\n}\n',b)+2
 body=s[a:end].replace('#include <pexpert/pexpert.h>','')
 assert 'printf(' not in body, 'preparer must not emit UART on the read/hash path'
 libs=subprocess.check_output(['pkg-config','--cflags','--libs','openssl'],text=True).split()
 for timing in (0,1):
  (t/'test.c').write_text(pre+body+main)
  subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-Wno-misleading-indentation','-Wno-deprecated-declarations','-fsanitize=address,undefined','-fno-pie','-no-pie','-DXNU_ROOT_TIMING='+str(timing),str(t/'test.c'),'-o',str(t/'test'),*libs],check=True)
  subprocess.run([str(t/'test')],check=True,timeout=30)
