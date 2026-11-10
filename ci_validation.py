"""Synthetic regressions inside the production image and aggregate cgroup limit.

No customer documents, credentials or network access are used by this runner.
The cgroup measurement includes this supervisor, test process and OCR children.
"""
import json
from pathlib import Path
import subprocess
import sys


def cgroup_value(name):
    path = Path('/sys/fs/cgroup') / name
    return path.read_text().strip() if path.exists() else 'unavailable'


if __name__ == '__main__':
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v'])
    print('ABP_CGROUP_RESULT ' + json.dumps({
        'exit_code': result.returncode,
        'memory_max': cgroup_value('memory.max'),
        'memory_peak': cgroup_value('memory.peak'),
        'memory_events': cgroup_value('memory.events'),
        'scope': 'synthetic regression suite; not a hosted Teriyaki measurement',
    }), flush=True)
    sys.exit(result.returncode)
