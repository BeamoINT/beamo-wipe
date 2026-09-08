"""Exercise the QEMU keyboard driver with inert commands, without a VM."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_qemu_explicitly_focuses_erase_after_final_countdown():
    source = (ROOT / 'scripts/qemu-verify.sh').read_text()
    function = 'drive_report_export() {' + source.split('drive_report_export() {', 1)[1].split('\n}', 1)[0] + '\n}\n'
    stubs = '''
set -eu
QEMU_TARGET_SERIAL=123456
REPORT_RAW=unused
send_key_for_marker() { printf 'marker %s %s\\n' "$3" "$4"; }
send_key() { printf 'key %s\\n' "$2"; }
wait_for_marker() { :; }
type_token_for_marker() { :; }
qmp_request() { :; }
wait_for_report_saved() { :; }
sleep() { printf 'wait %s\\n' "$1"; }
'''
    result = subprocess.run(  # noqa: S603
        ['/bin/bash', '-c', stubs + function + '\ndrive_report_export fake unused\n'],
        capture_output=True, text=True, check=True,
    )
    actions = result.stdout.splitlines()
    final = actions.index('marker ret BEAMO_WIPE_SCREEN_LAST_CHANCE')
    assert actions[final + 1:final + 4] == [
        'wait 6', 'key tab', 'marker ret BEAMO_WIPE_SCREEN_WORKING',
    ]
    report = actions.index('wait 5')
    assert actions[report + 1:report + 4] == [
        'key tab', 'key tab', 'marker spc BEAMO_WIPE_REPORT_SAVING',
    ]
