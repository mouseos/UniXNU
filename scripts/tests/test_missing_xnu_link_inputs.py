#!/usr/bin/env python3
"""An interrupted incremental build must not send missing objects to nm."""
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unixnu.kernel import missing_link_inputs
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp); d=root/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837';d.mkdir(parents=True)
 assert missing_link_inputs(root)==[]
 a=root/'present.o';a.write_bytes(b'object');b=root/'KernelConfigTables.cpo'
 (d/'link.filelist').write_text(str(a)+'\n'+str(b)+'\nrelative.o\n\n')
 assert missing_link_inputs(root)==[str(b),str(root/'relative.o')]
 b.write_bytes(b'object');(root/'relative.o').write_bytes(b'object')
 assert missing_link_inputs(root)==[]
print('PASS missing XNU link input detection and recovery precondition')
