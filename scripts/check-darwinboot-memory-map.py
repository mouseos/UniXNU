#!/usr/bin/env python3
"""Run the shipped map walker with checked bounds/serial mocks, off/on/invalid flag."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / 'drivers/DarwinBoot/DarwinBootPkg/Driver'
source = (DRIVER / 'DarwinBoot.c').read_text()
# Actual call sites: diagnostics inspect the successful map before search/EBS.
pre = source[source.index('AllocateWindow ('):source.index('  return Status;', source.index('DarwinDumpMemoryMap (0,'))+16]
assert pre.index('GetMap (&Map, &Capacity, &Size, &Key, &Stride)') < pre.index('DarwinDumpMemoryMap (0, Map, Size, Stride);') < pre.index('for (Offset = 0;')
last = source[source.rindex('  for (Attempt = 0; Attempt < 3; Attempt++) {'):]
assert last.index('gBS->GetMemoryMap') < last.index('if (EFI_ERROR (Status))') < last.index('DarwinDumpMemoryMap (1, Map, MapSize, Stride);') < last.index('gBS->ExitBootServices')
between = last[last.index('DarwinDumpMemoryMap (1,'):last.index('gBS->ExitBootServices')]
assert 'Print (' not in between and 'Allocate' not in between
header=(DRIVER/'MemoryMapDiag.h').read_text()
assert '#define DARWINBOOT_MEMORY_MAP_DIAG 0' in header
assert '#if DARWINBOOT_MEMORY_MAP_DIAG == 1' in header
assert not any(token in header for token in ('gBS->','AllocatePool','AllocatePages','FreePool','DEBUG (','gST->'))
inc=(DRIVER/'DarwinBoot.dsc.inc').read_text()
assert '!ifdef DARWINBOOT_MEMORY_MAP_DIAG' in inc
assert 'GCC:*_*_AARCH64_CC_FLAGS = -DDARWINBOOT_MEMORY_MAP_DIAG=$(DARWINBOOT_MEMORY_MAP_DIAG)' in inc
assert 'DarwinBootPkg/Driver/DarwinBoot.dsc.inc' in (DRIVER.parent/'DarwinBoot.dsc').read_text()

common=r'''
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#define MAX_UINTN ((size_t)-1)
#define STATIC static
#define CONST const
#define VOID void
typedef unsigned long long UINT64;
typedef uint32_t UINT32;
typedef size_t UINTN;
typedef uint8_t UINT8;
typedef char CHAR8;
typedef struct {UINT32 Type,Pad;UINT64 PhysicalStart,VirtualStart,NumberOfPages,Attribute;} EFI_MEMORY_DESCRIPTOR;
'''
on=r'''
static const UINT8 *begin,*end;
static UINTN reads,lines,formatted;
static char output[256*1024];
static void *CopyMem(void*dst,const void*src,UINTN n){
 assert(n==sizeof(EFI_MEMORY_DESCRIPTOR));assert((const UINT8*)src>=begin&&(const UINT8*)src<=end-n);reads++;
 return memcpy(dst,src,n);
}
static UINTN AsciiSPrint(char*out,UINTN size,const char*format,...){
 // EDK PrintLib's %a / %L... spelling, translated only for host libc formatting.
 char fmt[256];size_t j=0;
 for(size_t i=0;format[i];i++){
  if(format[i]=='%'&&format[i+1]=='a'){fmt[j++]='%';fmt[j++]='s';i++;}
  else if(format[i]=='L'){fmt[j++]='l';fmt[j++]='l';}
  else fmt[j++]=format[i];
 }fmt[j]=0;
 va_list a;va_start(a,format);int n=vsnprintf(out,size,fmt,a);va_end(a);
 assert(n>0&&(UINTN)n<size&&n<200);formatted++;return n;
}
static UINTN SerialPortWrite(UINT8*line,UINTN length){
 assert(length&&length<192&&line[length-1]=='\n'&&line[length-2]=='\r');
 assert(strlen(output)+length<sizeof output);strncat(output,(char*)line,length);lines++;return length;
}
'''
main=r'''
#if DARWINBOOT_MEMORY_MAP_DIAG == 1
static void reset(const void*map,UINTN size){begin=map;end=begin?begin+size:begin;reads=lines=formatted=0;output[0]=0;}
#endif
int main(void){
#if DARWINBOOT_MEMORY_MAP_DIAG == 1
 // Unaligned map and larger descriptor stride; all standard fields preserved.
 UINT8 storage[1+3*56];memset(storage,0xa5,sizeof storage);
 for(UINTN i=0;i<3;i++){
  EFI_MEMORY_DESCRIPTOR d={(UINT32)(i==0?7:i==1?0:6),0,0x52000000+i*0x1000,~0ULL,0xffffffffffffffffULL,~0ULL};
  memcpy(storage+1+i*56,&d,sizeof d);
 }
 UINT8 original[sizeof storage];memcpy(original,storage,sizeof storage);
 reset(storage+1,168);DarwinDumpMemoryMap(0,storage+1,168,56);
 assert(reads==3&&lines==4&&formatted==4&&!memcmp(original,storage,sizeof storage));
 assert(strstr(output,"DBMM pre count=3 bytes=168 stride=56 emitted=3\r\n"));
 assert(strstr(output,"i=0 type=7 pa=0000000052000000 va=ffffffffffffffff pages=ffffffffffffffff attr=ffffffffffffffff\r\n"));
 assert(strstr(output,"i=1 type=0")&&strstr(output,"i=2 type=6")); // reserved/runtime not filtered
 reset(storage+1,168);DarwinDumpMemoryMap(1,storage+1,168,56);assert(reads==3&&strstr(output,"DBMM final"));
 for(unsigned bad=0;bad<4;bad++){
  reset(storage+1,168);
  DarwinDumpMemoryMap(0,bad==0?NULL:storage+1,bad==1?167:168,bad==2?0:bad==3?39:56);
  assert(!reads&&lines==1&&strstr(output,"invalid"));
 }
 reset(NULL,0);DarwinDumpMemoryMap(0,NULL,0,sizeof(EFI_MEMORY_DESCRIPTOR));assert(!reads&&lines==1&&strstr(output,"count=0"));
 // A full bound plus one descriptor explicitly reports incompleteness.
 UINTN n=1025*sizeof(EFI_MEMORY_DESCRIPTOR);UINT8*large=calloc(1,n);assert(large);
 reset(large,n);DarwinDumpMemoryMap(1,large,n,sizeof(EFI_MEMORY_DESCRIPTOR));
 assert(reads==1024&&lines==1026&&strstr(output,"TRUNCATED remaining=1\r\n"));free(large);
 reset(NULL,0);DarwinDumpMemoryMap(1,(const void*)(~(UINTN)0-7),40,40);assert(!reads&&lines==1&&strstr(output,"invalid"));
 // Invalid maximal size/stride is rejected before touching a byte of the pointer.
 reset(NULL,0);DarwinDumpMemoryMap(1,NULL,~(UINTN)0,~(UINTN)0);assert(!reads&&lines==1);
#else
 // No formatting/serial/copy declarations exist in this configuration.
 DarwinDumpMemoryMap(0,(const void*)1,~(UINTN)0,0);
 DarwinDumpMemoryMap(1,NULL,~(UINTN)0,~(UINTN)0);
#endif
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='darwinboot-map-') as directory:
    for flag in (None,0,1,2):
        c=Path(directory)/f'map-{flag}.c'
        c.write_text(common+(on if flag==1 else '')+'\n#include "MemoryMapDiag.h"\n'+main)
        cmd=[os.environ.get('CC','cc'),'-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie','-I',str(DRIVER)]
        if flag is not None:cmd += [f'-DDARWINBOOT_MEMORY_MAP_DIAG={flag}']
        binary=c.with_suffix('');subprocess.run(cmd+[str(c),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
print('PASS shipped map walker: default/0/1/2, actual call order, stride/unaligned/invalid/overflow bounds, raw reserved/runtime rows, cap/truncation, no map mutation, <200-byte serial records (ASan/UBSan)')
