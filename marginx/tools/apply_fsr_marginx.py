"""Safely patch installed MarginX controller, preserving all other logic.
Run from ~/marginx with: .venv/bin/python3 tools/apply_fsr_marginx.py
"""
from pathlib import Path
from datetime import datetime
import ast


def main():
    path = Path(__file__).resolve().parent / 'marginx_control.py'
    if not path.exists():
        raise SystemExit(f"Not found: {path}")
    source = path.read_text(encoding='utf-8')
    import_line = 'from fsr_sensor import CupFSR'
    old = 'self.cup = Button(CUP_PIN, pull_up=True, bounce_time=0.05)'
    new = 'self.cup = CupFSR(channel=0, press_threshold=0.25, release_threshold=0.15)'
    if import_line in source and new in source:
        print('FSR patch already installed; no changes made.')
        return
    if source.count(old) != 1 or source.count('from gpiozero import Button') != 1:
        raise SystemExit('Could not identify exact old cup-switch code. File unchanged.')
    if import_line in source or new in source:
        raise SystemExit('Partial previous modification detected. File unchanged.')
    updated = source.replace('from gpiozero import Button', 'from gpiozero import Button\n' + import_line, 1)
    updated = updated.replace(old, new, 1)
    ast.parse(updated, filename=str(path))
    backup = path.with_name(f'marginx_control_before_fsr_{datetime.now():%Y%m%d_%H%M%S}.py')
    backup.write_text(source, encoding='utf-8')
    path.write_text(updated, encoding='utf-8')
    print(f'Updated: {path}\nBackup: {backup}')
    print('Leave motors OFF until FSR detection is calibrated and verified.')


if __name__ == '__main__':
    main()
