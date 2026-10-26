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
pin = 'b77365072a2447f688d37de5b08e941f801b1298'
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
    git.write_text('#!/bin/sh\n[ "$*" = "-C device rev-parse HEAD" ] || exit 91\nprintf "%s\\n" ' + pin + '\n')
    git.chmod(0o755)
    for probe, metal, roa, mode in itertools.product((False, True), (False, True), (False, True), ('selftest', 'publish')):
        generated = root / 'a04br3.env'
        generated.unlink(missing_ok=True)
        substitutions = {'inputs.powervr_probe': str(probe).lower(), 'inputs.powervr_metal': str(metal).lower(),
                         'inputs.skip_setup': 'true', 'github.run_id': '123'}
        rendered = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda match: substitutions[match[1]], body)
        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                   RUNNER_TEMP=str(root), GITHUB_WORKSPACE=str(root), GITHUB_REPOSITORY='fixture/repository',
                   UNIQUE_CHIP_ID='fixture', GH_TOKEN='fixture', A04BR3_POWERVR_METAL_MODE=mode,
                   A04BR3_POWERVR_METAL_ROA_COLOR=str(int(roa)))
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
# Execute both actual artifact-copy blocks with namespaced CLI output, not the old fixed layout.
copy_blocks = re.findall(r'^          WORK=.+\n          cp .+\n', source, re.M)
assert len(copy_blocks) == 2
with tempfile.TemporaryDirectory(prefix='a04br3-copy-') as tmp:
    root = Path(tmp)
    output = root/'custom output/a04br3/ipados-17.7.11-21H461/a04br3'
    (output/'payload').mkdir(parents=True)
    (output/'payload/payload.img').write_bytes(b'actual source controller payload fixture')
    cli = root/'unixnu'
    cli.write_text("#!/bin/sh\ncat <<'JSON'\n" + __import__('json').dumps({'output':str(output)}) + '\nJSON\n')
    cli.chmod(0o755)
    env={**os.environ,'GITHUB_WORKSPACE':str(root),'RUNNER_TEMP':str(root),'tag':'fixture'}
    for block in copy_blocks:
        subprocess.run(['bash','-euc', '\n'.join(line[10:] for line in block.splitlines())],cwd=root,env=env,check=True)
        assert (root/'payload-fixture.img').read_bytes()==(output/'payload/payload.img').read_bytes()
        (root/'payload-fixture.img').unlink()
assert '-- sleep 21600' in source and 'timeout-minutes: 360' in source
assert 'out/a04br3/**/tree/build/m2v-target' in source
# Parse every embedded shell body with bash without executing it.
for run in re.findall(r'^        run: \|\n((?:          .*\n|\n)+)', source, re.M):
    script = '\n'.join(line[10:] for line in run.splitlines())
    script = re.sub(r'\$\{\{.*?\}\}', 'fixture', script)
    subprocess.run(['/bin/bash', '-n'], input=script, text=True, check=True)
print('PASS actual SSH environment generator: 16 profiles, ROA dependencies/default off, publish args, fixed initial/incremental ref, two actual namespaced payload copy blocks, shell syntax')
