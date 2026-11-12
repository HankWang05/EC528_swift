#!/usr/bin/env python3
"""exp11 -- composite-builder saves keep the composite file's permission bits.

Claim
-----
Replacing the composite file must not change who can read it. Upstream
truncated and rewrote the existing file, so an update kept the file's mode and
a first save got the ordinary umask-derived mode. A temporary-file save
installs a different inode; tempfile.NamedTemporaryFile creates files with
mode 0600, so unless the fix restores the mode, an update narrows a 0644
composite file to owner-only. This checks a side effect of the fix: upstream is
expected to pass, and a patched tree fails it until the mode is preserved.
Ownership changes and ACLs are out of scope.

Usage (from EC528_swift)
-----------------------
    python3 experiments/exp11_composite_save_file_mode.py
    python3 experiments/exp11_composite_save_file_mode.py --swift-src /path/to/Swift
    python3 experiments/exp11_composite_save_file_mode.py --results-json exp11.json

On the EC528 Lightsail box (SwiftBugFix):

    # Connect using SSH in the AWS Lightsail dashboard, then:
    cd /home/ubuntu/EC528_swift
    source .venv/bin/activate
    python3 experiments/exp11_composite_save_file_mode.py
    echo "exit=$?"

If the checkout is at /opt/ec528-swift, use that location in the cd command
instead. Run from the checkout containing the fix; the script does not switch
branches or modify the implementation.

To keep a result file and set an explicit runtime bound on Lightsail:

    python3 experiments/exp11_composite_save_file_mode.py \
        --results-json exp11-results.json \
        --timeout 90
    echo "exit=$?"

Setup is provided by experiments/setup.sh on a clean Linux machine. The
prepared instance should already have .venv; keep composite_save_support.py
beside this script. The selected composite builder source path and revision are
printed before the checks, so verify they identify the intended checkout.

Exit codes: 0 = checks passed; 1 = check failed; 77 = could not run or timed out.
Linux, upstream dependencies, and a writable temporary filesystem are required.
The worker has a 90-second default deadline.
"""

import os
import stat

from composite_save_support import CompositeCase, make_composite, run


def mode_of(path):
    return stat.S_IMODE(os.stat(str(path)).st_mode)


class TestCompositeSaveFileMode(CompositeCase):
    def test_update_keeps_existing_file_mode(self):
        os.chmod(str(self.path), 0o644)
        self.composite.version += 1
        self.composite.save(str(self.path))
        print('  mode after update  %04o (was 0644)' % mode_of(self.path),
              flush=True)
        self.assertEqual(0o644, mode_of(self.path),
                         'saving changed the composite file permissions')

    def test_first_save_uses_umask_mode(self):
        directory = self.path.parent / 'first-save'
        directory.mkdir()
        probe = directory / 'probe.json'
        with open(str(probe), 'wt') as handle:
            handle.write('{}')
        expected = mode_of(probe)
        path = directory / 'first-save.json'
        make_composite(self.module, directory).save(str(path))
        print('  mode after first save %04o (plain create gives %04o)' % (
            mode_of(path), expected), flush=True)
        self.assertEqual(expected, mode_of(path),
                         'a first save did not get the ordinary file mode')


if __name__ == '__main__':
    raise SystemExit(run('Composite-builder saves keep the composite file '
                         'permission bits.', TestCompositeSaveFileMode, __file__))
