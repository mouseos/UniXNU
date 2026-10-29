#!/usr/bin/env python3
"""Execute the workflow's environment generator without Actions or build/device operations."""
import itertools
import os
from pathlib import Path
import re
import subprocess
import tempfile

workflow = Path(__file__).resolve().parents[2] / '.github/workflows/a04br3-ssh.yml'
source = workflow.read_text()
step = source.split('      - name: Environment and rebuild script for the SSH session\n', 1)[1]
body = step.split('        run: |\n', 1)[1].split("          cat > /tmp/a04br3-rebuild.sh <<'SCRIPT'", 1)[0]
body = '\n'.join(line[10:] for line in body.splitlines())
pin = 'dde2dab72621c02696857abc12b29977cdc447a2'
assert re.search(r'device_ref:\n.*\n        required: true\n        default: ' + pin, source)
assert re.search(r'powervr_metal_roa_color:\n.*\n        type: boolean\n        default: false', source)
assert "inputs.powervr_metal_roa_color && '1' || '0'" in step
assert '"${1:-$A04BR3_DEVICE_REF}"' in source
# Both build paths must consume the generated configuration.
assert 'source "$RUNNER_TEMP/a04br3.env"' in source.split("<<'SCRIPT'", 1)[1].split('\n          SCRIPT', 1)[0]
assert 'source "$RUNNER_TEMP/a04br3.env"' in source.split('      - name: First build', 1)[1]
with tempfile.TemporaryDirectory(prefix='a04br3-profile-') as tmp:
    root = Path(tmp)
    tools = root / 'tools'
    tools.mkdir()
    git = tools / 'git'
    git.write_text('''#!/bin/sh
case "$*" in
  '-C device rev-parse HEAD') printf '%s\\n' "$DEVICE_HEAD" ;;
  'rev-parse HEAD:drivers/ArmCpu') printf '%s\\n' "$ARMCPU_HEAD" ;;
  '-C device cat-file -e '* | '-C device merge-base --is-ancestor '*) [ "$AUTO_PROFILE" = 1 ] ;;
  *) exit 91 ;;
esac
''')
    git.chmod(0o755)
    fake_python = tools/'python3'
    fake_python.write_text('''#!/bin/sh
[ "$XNU_IRQ_PC_STATS" = 1 ] && [ "$XNU_MSDC_IRQ_WAIT" = 1 ] &&
[ "$XNU_MSDC_IRQ_WORKER" = 1 ] && [ "$XNU_MSDC_GIC_NS" = 1 ] &&
[ "$XNU_PROCESS_EXIT_DIAG" = 1 ] && [ "$XNU_ROOT_TIMING" = 1 ] &&
[ "$XNU_IO_OVERLAP_TRACE" = 1 ] && [ "$XNU_NATIVE_CS_HASH_CACHE" = 1 ]
''')
    fake_python.chmod(0o755)
    for probe, metal, roa, mode in itertools.product((False, True), (False, True), (False, True), ('selftest', 'publish')):
        generated = root / 'a04br3.env'
        generated.unlink(missing_ok=True)
        substitutions = {'inputs.powervr_probe': str(probe).lower(), 'inputs.powervr_metal': str(metal).lower(),
                         'inputs.skip_setup': 'true', 'github.run_id': '123'}
        rendered = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda match: substitutions[match[1]], body)
        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                   RUNNER_TEMP=str(root), GITHUB_WORKSPACE=str(root), GITHUB_REPOSITORY='fixture/repository',
                   UNIQUE_CHIP_ID='fixture', GH_TOKEN='fixture', A04BR3_POWERVR_METAL_MODE=mode,
                   A04BR3_POWERVR_METAL_ROA_COLOR=str(int(roa)), IOSTAT_STACK_PROFILE='0',
                   DEVICE_HEAD=pin, ARMCPU_HEAD='85d06a5248a4516c777763d195866a2362e5d7b0', AUTO_PROFILE='0')
        result = subprocess.run(['/bin/bash', '-c', rendered], env=env, capture_output=True, text=True)
        if roa and not (probe and metal):
            assert result.returncode != 0 and not generated.exists()
            assert 'requires powervr_probe=true and powervr_metal=true' in result.stderr
            continue
        assert result.returncode == 0, result.stderr
        inspect = 'source "$RUNNER_TEMP/a04br3.env"\nprintf "%s\\0" "$A04BR3_DEVICE_REF" "$A04BR3_POWERVR_METAL_MODE" "$A04BR3_POWERVR_METAL_ROA_COLOR" "${METAL_KERNEL_ARGS[*]}"'
        fields = subprocess.check_output(['/bin/bash', '-c', inspect], env=env).decode().split('\0')
        assert fields[:3] == [pin, mode, str(int(roa))]
        assert fields[3] == ('--kernel-arg sheng-fb-gpu=1' if mode == 'publish' else '')
    substitutions = {'inputs.powervr_probe':'true', 'inputs.powervr_metal':'true', 'inputs.skip_setup':'false', 'github.run_id':'123'}
    rendered = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda match: substitutions[match[1]], body)
    flags = ['XNU_IRQ_PC_STATS','XNU_MSDC_IRQ_WAIT','XNU_MSDC_IRQ_WORKER','XNU_MSDC_GIC_NS',
             'XNU_PROCESS_EXIT_DIAG','XNU_ROOT_TIMING','XNU_IO_OVERLAP_TRACE','XNU_NATIVE_CS_HASH_CACHE']
    for explicit, auto, armcpu, expected in [('0','0','85d06a5248a4516c777763d195866a2362e5d7b0','off'),
                                             ('1','0','85d06a5248a4516c777763d195866a2362e5d7b0','on'),
                                             ('0','1','85d06a5248a4516c777763d195866a2362e5d7b0','on'),
                                             ('0','1','1951cc8444b340d7d8879e9418220cf29eb711d7','reject')]:
        env = dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'], RUNNER_TEMP=str(root),
                   GITHUB_WORKSPACE=str(root), GITHUB_REPOSITORY='fixture/repository', UNIQUE_CHIP_ID='fixture', GH_TOKEN='fixture',
                   A04BR3_POWERVR_METAL_MODE='publish', A04BR3_POWERVR_METAL_ROA_COLOR='1',
                   IOSTAT_STACK_PROFILE=explicit, AUTO_PROFILE=auto, DEVICE_HEAD=pin, ARMCPU_HEAD=armcpu)
        generated = root/'a04br3.env'; generated.unlink(missing_ok=True)
        result = subprocess.run(['/bin/bash','-c',rendered],env=env,capture_output=True,text=True)
        if expected == 'reject':
            assert result.returncode != 0 and 'requires ArmCpu' in result.stderr
            continue
        assert result.returncode == 0, result.stderr
        inspect = 'source "$RUNNER_TEMP/a04br3.env"; printf "%s\\0" ' + ' '.join('"${'+name+'-unset}"' for name in flags)
        values = subprocess.check_output(['/bin/bash','-c',inspect],env=env).decode().split('\0')[:-1]
        assert values == (['1']*len(flags) if expected == 'on' else ['unset']*len(flags)), values
    # Execute the real post-checkout rebuild gate: it must auto-enable when the
    # requested device changes to the diagnostic revision, and reject an
    # incompatible ArmCpu before the rebuild starts.
    rebuild = source.split("<<'SCRIPT'", 1)[1].split('\n          SCRIPT', 1)[0]
    gate = rebuild.split('          diagnostic_device=', 1)[1].split('          ./unixnu tree', 1)[0]
    gate = 'diagnostic_device=' + '\n'.join(line[10:] if line.startswith('          ') else line for line in gate.splitlines())
    for explicit, auto, armcpu, expected in [('0','0','85d06a5248a4516c777763d195866a2362e5d7b0','off'),
                                             ('1','0','85d06a5248a4516c777763d195866a2362e5d7b0','on'),
                                             ('0','1','85d06a5248a4516c777763d195866a2362e5d7b0','on'),
                                             ('0','1','1951cc8444b340d7d8879e9418220cf29eb711d7','reject')]:
        env = dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'], IOSTAT_STACK_PROFILE=explicit,
                   AUTO_PROFILE=auto, DEVICE_HEAD=pin, ARMCPU_HEAD=armcpu)
        for name in flags: env.pop(name, None)
        inspect = 'printf "%s\\0" ' + ' '.join('"${'+name+'-unset}"' for name in flags)
        result=subprocess.run(['/bin/bash','-c','set -e\n'+gate+'\n'+inspect],env=env,capture_output=True)
        if expected == 'reject': assert result.returncode != 0 and b'requires the pinned ArmCpu' in result.stderr
        else:
            assert result.returncode == 0, result.stderr
            values=result.stdout.decode().split('\0')[:-1]
            assert values == (['1']*len(flags) if expected == 'on' else ['unset']*len(flags)), values
# Parse every embedded shell body with bash without executing it.
for run in re.findall(r'^        run: \|\n((?:          .*\n|\n)+)', source, re.M):
    script = '\n'.join(line[10:] for line in run.splitlines())
    script = re.sub(r'\$\{\{.*?\}\}', 'fixture', script)
    subprocess.run(['/bin/bash', '-n'], input=script, text=True, check=True)
print('PASS actual SSH environment generator: 16 profiles, ROA dependencies/default off, publish args, fixed initial/incremental ref, shell syntax')
