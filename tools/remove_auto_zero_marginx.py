#!/usr/bin/env python3
"""MarginX migration: remove automatic zero motion, preserve persisted position.

Run: python3 remove_auto_zero_marginx.py --dry-run
     python3 remove_auto_zero_marginx.py

Does not change motorlib.py, hardware, or calibration JSON.
Refuses to write if the installed controller/UI differ from expected structure.
"""
import argparse
import ast
import datetime
import difflib
from pathlib import Path
import re
import shutil
import sys

ROOT = Path.home() / "marginx" / "tools"


def method_region(src, name):
    pattern = re.compile(r"(?m)^    def " + re.escape(name) + r"\(")
    matches = list(pattern.finditer(src))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one method {name}(), found {len(matches)}")
    start = matches[0].start()
    nxt = re.search(r"(?m)^    def [A-Za-z_]\w*\(", src[matches[0].end():])
    end = matches[0].end() + nxt.start() if nxt else len(src)
    return start, end


def edit_method(src, name, change):
    a,b = method_region(src, name)
    old = src[a:b]
    new = change(old)
    if new == old:
        raise RuntimeError(f"No expected changes found in {name}()")
    return src[:a] + new + src[b:]


def one_replace(s, old, new, what):
    n=s.count(old)
    if n!=1:
        raise RuntimeError(f"Expected one {what}; found {n}. No files changed.")
    return s.replace(old,new,1)


def patch_controller(src):
    # Assert structure before patching.
    if "def start_scan(" not in src or "def _scan_worker(" not in src:
        raise RuntimeError("Controller scan methods not found")
    if "def valid_position(" not in src or "def save_new_zero(" not in src:
        raise RuntimeError("Position/calibration support not found")
    stages = re.compile(r"(?ms)^STAGES = \{\n.*?^\}")
    m = stages.search(src)
    if not m or "\"home\"" not in m.group():
        raise RuntimeError("Unexpected STAGES structure; no files changed")
    replacement = '''STAGES = {
    "move1": (0, 12, "Moving to 1/3 of range"),
    "rotate1": (12, 33, "Scanning at 1/3"),
    "move2": (33, 45, "Moving to 1/2 of range"),
    "rotate2": (45, 66, "Scanning at 1/2"),
    "move3": (66, 78, "Moving to 2/3 of range"),
    "rotate3": (78, 100, "Scanning at 2/3"),
}'''
    src=src[:m.start()]+replacement+src[m.end():]

    def change_start(s):
        s, a = re.subn(r"\bor not self\.zero_ready\b", "", s)
        s, b = re.subn(r"\bor self\.state\(\)\.get\(['\"]position['\"]\) != 0\b", "", s)
        if a!=1 or b!=1:
            raise RuntimeError("Unexpected start_scan gating: expected zero_ready + position==0")
        # A saved coordinate must also be internally consistent with calibration state.
        s=s.replace("self.running  or not self.sensors_ready()",
                    "self.running or self.calibration_active or self.calibration_uncertain or not self.sensors_ready()")
        s=s.replace('or not self.valid_position() ', 'or not self.valid_position()')
        return s
    src=edit_method(src,"start_scan",change_start)

    def change_worker(s):
        m=re.search(r'(?m)^\s+self\._move\(shift,\s*["\']home["\'],\s*0\)\s*$', s)
        if not m:
            raise RuntimeError("Expected scan-end home motion not found")
        line_start=s.rfind('\n',0,m.start())+1
        line_end=s.find('\n',m.end())
        if line_end<0: line_end=len(s)
        return s[:line_start]+s[line_end+1:]
    src=edit_method(src,"_scan_worker",change_worker)

    # Manual calibration is available ONLY when saved coordinate is already 0.
    if "def prepare_zero_verification(" in src:
        raise RuntimeError("Already patched controller; refusing second application")
    insert='''    def prepare_zero_verification(self):
        """Allow manual zero check without commanding any motor motion."""
        if self.running or not self.valid_position():
            raise RuntimeError("Stage position is invalid or motion is active.")
        st = self.state()
        if st.get("position") != 0:
            raise RuntimeError(
                "Manual zero calibration requires a verified zero position. "
                "Automatic homing has been removed; do not reset coordinates "
                "while the stage is away from zero."
            )
        self.zero_ready = True
        self.cal_offset = 0
        self.cal_original_range = st["range"]
        self.calibration_active = False
        self.calibration_uncertain = False

'''
    pos=src.index('    def start_home(')
    src=src[:pos]+insert+src[pos:]
    # Existing homing methods stay defined for compatibility but are not called from UI.
    return src


def patch_ui(src):
    if 'def login(' not in src or 'def show_preparation(' not in src:
        raise RuntimeError('Expected UI navigation methods not found')
    def change_login(s):
        pattern=re.compile(r"(?ms)^        self\.show_zero\(\)\n        try:\n            self\.scanner\.start_home\(\)\n        except Exception as exc:\n            self\.show_error\(str\(exc\)\)")
        s,n=pattern.subn('        self.show_preparation()',s)
        if n!=1: raise RuntimeError('Expected login start_home block not found')
        return s
    src=edit_method(src,'login',change_login)

    def change_back(s):
        # Replace method, but do not touch other code.
        return '''    def back_to_calibration(self):
        if self.scanner.running:
            return
        try:
            self.scanner.prepare_zero_verification()
        except Exception as exc:
            self.show_error(str(exc))
            return
        self.zero_error = ""
        self.show_zero()

'''
    src=edit_method(src,'back_to_calibration',change_back)

    def change_refresh(s):
        s,a=re.subn(r"\s+and s\.state\(\)\.get\(['\"]position['\"]\) == 0",'',s)
        s,b=re.subn(r"\s+and s\.zero_ready\b",'',s)
        if a!=1 or b!=1:
            raise RuntimeError('Unexpected preparation scan gating; aborting')
        # Ensure the prepared state remains valid and not in calibration.
        s=s.replace('and not s.running','and not s.running and not s.calibration_active and not s.calibration_uncertain',1)
        if 'not s.calibration_active' not in s:
            raise RuntimeError('Calibration block unavailable')
        return s
    src=edit_method(src,'refresh_preparation',change_refresh)

    def change_done(s):
        old='stage returned to zero'
        if s.count(old)!=1:
            raise RuntimeError('Finished-screen zero message not found')
        return s.replace(old,'stage remains at its final scan position',1)
    src=edit_method(src,'show_finished',change_done)
    src=one_replace(src,'1/3  →  1/2  →  2/3  →  ZERO  →  FINISHED',
                    '1/3  →  1/2  →  2/3  →  FINISHED','scan timeline')
    src=one_replace(src,"('move1', 'move2', 'move3', 'home')",
                    "('move1', 'move2', 'move3')",'animated scan phases')
    return src


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dry-run',action='store_true',help='Preview changes; write nothing')
    ap.add_argument('--dir',type=Path,default=ROOT,help='Tools folder (for testing)')
    args=ap.parse_args()
    base=args.dir.expanduser().resolve()
    ctrl=base/'marginx_control.py'; ui=base/'marginx_ui.py'
    if not ctrl.exists() or not ui.exists():
        raise RuntimeError(f'Files missing in {base}')
    old_c=ctrl.read_text(encoding='utf-8'); old_u=ui.read_text(encoding='utf-8')
    new_c=patch_controller(old_c); new_u=patch_ui(old_u)
    ast.parse(new_c, filename=str(ctrl)); ast.parse(new_u,filename=str(ui))
    if args.dry_run:
        for label,old,new in [(str(ctrl),old_c,new_c),(str(ui),old_u,new_u)]:
            print(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                          fromfile=label+' (before)',tofile=label+' (after)')))
        print('\nDRY RUN ONLY. No files changed.')
        return
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    for path in (ctrl,ui):
        backup=path.with_name(path.name+f'.before_no_auto_zero_{stamp}')
        shutil.copy2(path,backup)
        print('Backup:',backup)
    ctrl.write_text(new_c,encoding='utf-8')
    ui.write_text(new_u,encoding='utf-8')
    print('Updated:',ctrl,ui)
    print('No motorlib.py or shift_state.json changes. Check with py_compile before starting.')

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('ABORT:',exc,file=sys.stderr)
        sys.exit(1)
