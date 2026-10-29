#!/usr/bin/env python3
"""Exercise configuration precedence of the workflow's XNU flag guard."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

script = Path(__file__).resolve().parents[1] / 'check-xnu-effective-flags.py'
with tempfile.TemporaryDirectory(prefix='xnu-effective-') as tmp:
    config = Path(tmp) / '.config'
    env = dict(os.environ, XNU_IRQ_PC_STATS='1')
    command = [sys.executable, str(script), str(config), '--require', 'XNU_IRQ_PC_STATS=1']
    for contents, expected in [('', 0), ('CONFIG_XNU_IRQ_PC_STATS=y\n', 0),
                               ('CONFIG_XNU_IRQ_PC_STATS=n\n', 1),
                               ('# CONFIG_XNU_IRQ_PC_STATS is not set\n', 1)]:
        config.write_text(contents)
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        assert (result.returncode == 0) == (expected == 0), (contents, result.stdout, result.stderr)
print('PASS effective XNU flag checks: environment and defconfig precedence')
