#!/usr/bin/env python3
"""Check diagnostic define routing with the pinned real EDK II DSC parser."""
import argparse
import subprocess
import sys
import tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--edk2-source',type=Path,required=True,help='official pinned mu_basecore checkout')
edk2=parser.parse_args().edk2_source.resolve()
expected=next(s['commit'] for s in tomllib.loads((ROOT/'feeds.toml').read_text())['source'] if s['kind']=='refer' and s['name']=='edk2')
assert subprocess.check_output(['git','-C',str(edk2),'rev-parse','HEAD'],text=True).strip()==expected, 'EDK II source pin mismatch'
sys.path.insert(0,str(edk2/'BaseTools/Source/Python'))
from tempfile import TemporaryDirectory
from Common import GlobalData,EdkLogger
from Common.Misc import PathClass
from Common.MultipleWorkspace import MultipleWorkspace
from Workspace.WorkspaceDatabase import WorkspaceDatabase
root=ROOT;EdkLogger.Initialize();GlobalData.gWorkspace=str(root);GlobalData.gGlobalDefines['WORKSPACE']=str(root)
MultipleWorkspace.setWs(str(root),str(root/'drivers/DarwinBoot')+':'+str(root/'package'))
for value in (None,'0','1','2'):
 with TemporaryDirectory(prefix='dbmm-dsc-') as d:
  path=Path(d)/'check.dsc';path.write_text('[Defines]\n PLATFORM_NAME=Check\n PLATFORM_GUID=00000000-0000-0000-0000-000000000001\n PLATFORM_VERSION=1\n DSC_SPECIFICATION=0x0001001C\n SUPPORTED_ARCHITECTURES=AARCH64\n BUILD_TARGETS=DEBUG\n SKUID_IDENTIFIER=DEFAULT\n[Components]\n!include DarwinBootPkg/Driver/DarwinBoot.dsc.inc\n')
  GlobalData.gCommandLineDefines={} if value is None else {'DARWINBOOT_MEMORY_MAP_DIAG':value}
  obj=WorkspaceDatabase().BuildObject[PathClass(str(path)), 'AARCH64','DEBUG','CLANGPDB']
  mods=list(obj.Modules.values());assert len(mods)==1
  want={} if value is None else {('GCC','*_*_AARCH64_CC_FLAGS'):f'-DDARWINBOOT_MEMORY_MAP_DIAG={value}'}
  assert mods[0].BuildOptions==want, (value,mods[0].BuildOptions)
print('PASS pinned EDK II parser: component-scoped default/0/1/2 define routing; no firmware build')
