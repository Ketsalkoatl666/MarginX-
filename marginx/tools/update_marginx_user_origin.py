#!/usr/bin/env python3
"""MarginX: user-set scan origin, relative targets, return to that origin.

For the post-remove_auto_zero_marginx.py controller/UI family. Refuses unknown
source structures. No change to motorlib.py or persisted calibration JSON.
"""
from pathlib import Path
import ast, argparse, datetime, difflib, re, shutil, sys

DEFAULT = Path.home() / 'marginx' / 'tools'

def region(src, method):
    pattern = re.compile(r'(?m)^    def ' + re.escape(method) + r'\(')
    matches = list(pattern.finditer(src))
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one method {method}, found {len(matches)}')
    a = matches[0].start()
    m = re.search(r'(?m)^    def [A-Za-z_]\w*\(', src[matches[0].end():])
    b = matches[0].end() + m.start() if m else len(src)
    return a,b

def replace_method(src, method, replacement):
    a,b = region(src, method)
    return src[:a] + replacement.rstrip() + '\n\n' + src[b:]

def exactly(src, old, new, label):
    n=src.count(old)
    if n!=1:
        raise ValueError(f'Expected one occurrence of {label}, found {n}; no files changed')
    return src.replace(old,new,1)

CONTROLLER_METHODS = {
'prepare_zero_verification': '''    def prepare_zero_verification(self):
        """Enter manual-position selection without moving the stage."""
        if self.running or not self.valid_position() or self.calibration_uncertain:
            raise RuntimeError('Stage position is unverified or the motor is busy.')
        st = self.state()
        self.zero_ready = True
        self.cal_offset = 0
        self.cal_original_range = st['range']
        self.calibration_active = False
        self.selected_origin = None
''',
'start_jog': '''    def start_jog(self, delta):
        """Jog with absolute position tracking; never rebase mechanical zero."""
        if (self.running or not self.zero_ready or self.calibration_uncertain
                or not self.valid_position()):
            return False
        if delta not in (-1000, -200, 200, 1000):
            raise ValueError('Unsupported jog distance.')
        st = self.state()
        destination = st['position'] + delta
        if not 0 <= destination <= st['range']:
            raise ValueError('Jog would exceed the calibrated travel range.')
        self.selected_origin = None
        return self._start('jog', self._jog_worker, destination)
''',
'_jog_worker': '''    def _jog_worker(self, destination):
        axis = None
        error = None
        try:
            start = self.state()['position']
            axis = m.Axis(m.SHIFT_STEP_PIN, m.SHIFT_DIR_PIN, self.args.cal_period)
            if self.abort.is_set():
                raise RuntimeError('Jog aborted before movement.')
            # Absolute movement is tracked/persisted by motorlib.
            result = m.move_shift_to(axis, destination, self.abort)
            if result is False or self.abort.is_set() or self.state().get('position') != destination:
                raise RuntimeError('Jog incomplete; stage coordinate may be uncertain.')
            self.events.put(('jog_progress', 100.0))
        except BaseException as exc:
            error = str(exc) or type(exc).__name__
            self.calibration_uncertain = True
            self.zero_ready = False
        finally:
            if axis is not None:
                try:
                    axis.close()
                except Exception as exc:
                    error = error or str(exc)
                    self.calibration_uncertain = True
                    self.zero_ready = False
            self.events.put(('jog_done', error))
''',
'save_new_zero': '''    def save_new_zero(self):
        """Confirm current position as scan start, WITHOUT changing system zero."""
        if self.running or not self.valid_position() or self.calibration_uncertain:
            return False
        self.selected_origin = self.state()['position']
        self.zero_ready = True
        self.calibration_active = False
        self.cal_offset = 0
        return True
''',
'start_scan': '''    def start_scan(self):
        if (self.running or not self.sensors_ready() or not self.valid_position()
                or self.calibration_uncertain or self.calibration_active
                or not self.zero_ready or self.selected_origin is None):
            return False
        st = self.state()
        if st['position'] != self.selected_origin:
            return False
        origin, travel = self.selected_origin, st['range'] - self.selected_origin
        if travel < 6:
            raise RuntimeError('Not enough remaining positive-direction travel for scanning.')
        # Capture exact starting coordinate before worker starts.
        self.zero_ready = False
        return self._start('scan', self._scan_worker, origin, st['range'])
''',
'_scan_worker': '''    def _scan_worker(self, origin, upper_limit):
        shift = rotation = None
        error = None
        try:
            if not self.valid_position() or self.state()['position'] != origin:
                raise RuntimeError('Start position changed or is invalid; scan blocked.')
            if self.state()['range'] != upper_limit:
                raise RuntimeError('Calibrated range changed; scan blocked.')
            remaining = upper_limit - origin
            targets = (origin + remaining // 3,
                       origin + remaining // 2,
                       origin + 2 * remaining // 3)
            if not (origin < targets[0] < targets[1] < targets[2] <= upper_limit):
                raise RuntimeError('Not enough travel for three distinct scan positions.')
            shift = m.Axis(m.SHIFT_STEP_PIN, m.SHIFT_DIR_PIN, self.args.shift_period)
            rotation = m.Axis(m.ROT_STEP_PIN, m.ROT_DIR_PIN, self.args.rot_period)
            for index, target in enumerate(targets, 1):
                self._move(shift, f'move{index}', target)
                self._rotate(rotation, f'rotate{index}')
            # A successful scan is not finished until the origin is reached again.
            self._move(shift, 'return_origin', origin)
            if self.abort.is_set() or self.state().get('position') != origin:
                raise RuntimeError('Return to selected origin did not complete.')
        except BaseException as exc:
            error = str(exc) or type(exc).__name__
        finally:
            for axis in (rotation, shift):
                if axis is not None:
                    try:
                        axis.close()
                    except Exception as exc:
                        error = error or str(exc)
            if self.abort.is_set():
                error = error or 'Scan interrupted; do not assume origin was reached.'
            if error is None and self.state().get('position') != origin:
                error = 'Final position verification failed.'
            self.events.put(('scan_done', error))
'''
}

def controller(src):
    if '"return_origin"' in src or "'return_origin'" in src:
        raise ValueError('Controller already contains return_origin; refusing repeat application.')
    if 'prepare_zero_verification' not in src:
        raise ValueError('Run remove_auto_zero_marginx.py first or use matching updated source files.')
    if 'self.selected_origin' in src:
        raise ValueError('Controller already uses selected_origin; refusing repeat application.')
    src = exactly(src, 'STAGES = {\n', 'STAGES = {\n    "return_origin": (87, 100, "Returning to user-selected origin"),\n', 'STAGES declaration')
    src = exactly(src, '"rotate3": (78, 100, "Scanning at 2/3"),', '"rotate3": (78, 87, "Scanning at 2/3"),', 'rotate3 progress')
    a,b = region(src, '__init__')
    init = src[a:b]
    init = exactly(init, '        self.calibration_uncertain = False\n', '        self.calibration_uncertain = False\n        self.selected_origin = None\n', 'scanner initialization')
    src = src[:a]+init+src[b:]
    for method,body in CONTROLLER_METHODS.items():
        src = replace_method(src, method, body)
    return src

UI_METHODS={
'login': '''    def login(self):
        if self.username.get() != 'admin' or self.password.get() != '000000':
            self.close_system_keyboard()
            self.login_error.config(text='Invalid username or password')
            return
        if self.scanner.running:
            return
        if not self.scanner.valid_position():
            self.show_error('Saved position invalid. Physically recover and verify stage position first.')
            return
        self.close_system_keyboard()
        self.zero_error = ''
        try:
            self.scanner.prepare_zero_verification()
        except Exception as exc:
            self.show_error(str(exc))
            return
        self.show_zero()
''',
'refresh_zero': '''    def refresh_zero(self):
        if self.page != 'zero':
            return
        s = self.scanner
        available = s.zero_ready and not s.running and not s.calibration_uncertain and s.valid_position()
        for btn in self.jog_buttons:
            btn.config(state='normal' if available else 'disabled')
        self.continue_button.config(state='normal' if available and s.selected_origin == s.state().get('position') else 'disabled')
        self.save_button.config(state='normal' if available else 'disabled')
        position = s.state().get('position') if s.valid_position() else None
        if position is not None:
            self.offset_status.config(text=f'Position: {position} steps (~{position / STEPS_PER_MM:.1f} mm)')
        else:
            self.offset_status.config(text='Position: unknown')
        if s.calibration_uncertain:
            status = 'Position uncertain — do not scan'
        elif s.running:
            status = 'Moving stage — keep clear'
        elif s.selected_origin == position and s.selected_origin is not None:
            status = 'Start position confirmed'
        else:
            status = 'Adjust the stage to select scan origin'
        self.zero_status.config(text=status, fg=RED if s.calibration_uncertain else TEXT)
        self.zero_detail.config(text=self.zero_error or
                                'Use jog buttons, then press SET START POSITION.',
                                fg=RED if self.zero_error else MUTED)
''',
'continue_to_prep': '''    def continue_to_prep(self):
        s = self.scanner
        if (not s.running and s.zero_ready and s.valid_position() and
                not s.calibration_uncertain and s.selected_origin == s.state()['position']):
            self.show_preparation()
''',
'save_zero': '''    def save_zero(self):
        s = self.scanner
        if s.running or not s.valid_position() or s.calibration_uncertain:
            return
        position = s.state()['position']
        confirmed = messagebox.askyesno(
            'Confirm Scan Start Position',
            f'Use current stage coordinate {position} steps as the scan origin?\\n\\n'
            'The stage will return to this same coordinate after scanning.\\n'
            'Mechanical zero and travel limits are NOT changed.', parent=self.root)
        if confirmed:
            if s.save_new_zero():
                self.zero_error = 'Start position saved. Press CONTINUE when ready.'
                self.refresh_zero()
''',
'back_to_calibration': '''    def back_to_calibration(self):
        if self.scanner.running:
            return
        try:
            self.scanner.prepare_zero_verification()
        except Exception as exc:
            self.show_error(str(exc))
            return
        self.zero_error = ''
        self.show_zero()
''',
'refresh_preparation': '''    def refresh_preparation(self):
        if self.page != 'prepare':
            return
        s = self.scanner
        cup, cover = s.cup.is_pressed, s.cover.is_pressed
        self.cup_label.config(text='Cup: Inserted' if cup else 'Cup: Waiting',
                              fg=GREEN if cup else TEXT)
        self.cover_label.config(text='Cover: Closed' if cover else 'Cover: Open',
                                fg=GREEN if cover else TEXT)
        self.prep_title.config(text='Stage Ready, Insert Cup' if not cup else
                               ('Cup Inserted' if not cover else 'Ready to Scan'))
        valid = (s.valid_position() and s.selected_origin is not None and
                 s.state().get('position') == s.selected_origin and
                 s.state().get('range', 0) - s.selected_origin >= 6)
        ready = (cup and cover and valid and s.zero_ready and
                 not s.running and not s.calibration_uncertain)
        self.start_button.config(state='normal' if ready else 'disabled')
        self.back_button.config(state='disabled' if s.running else 'normal')
        self.prep_detail.config(text=('Both switches must be closed.' if valid else
                                      'Return to adjustment and confirm a valid start position.'))
'''
}

def ui(src):
    if 'def show_login(' not in src or 'def show_zero(' not in src:
        raise ValueError('UI source does not match expected MarginX UI family.')
    if 'SET START POSITION' in src:
        raise ValueError('UI already appears patched; refusing repeat application.')
    for method,body in UI_METHODS.items():
        src = replace_method(src, method, body)
    src = exactly(src, "'Verify Zero Position'", "'Set Scan Start Position'", 'calibration page title')
    src = exactly(src, "'Returning to saved zero...'", "'Select scan start position'", 'calibration initial status')
    src = exactly(src, "'ZERO CORRECT · CONTINUE'", "'CONTINUE'", 'continue button title')
    src = exactly(src, "'SET NEW ZERO'", "'SET START POSITION'", 'save button title')
    src = exactly(src, "'1/3  →  1/2  →  2/3  →  FINISHED'", "'1/3  →  1/2  →  2/3  →  RETURN TO START  →  FINISHED'", 'scan timeline')
    src = exactly(src, "'All scanning positions completed · stage remains at its final scan position'", "'All scan positions completed · returned to selected start position'", 'finished subtitle')
    src = exactly(src, "('move1', 'move2', 'move3')", "('move1', 'move2', 'move3', 'return_origin')", 'movement animation phases')
    src = exactly(src, "'Scanning finished — at zero'", "'Scanning finished — back at selected start'", 'scan-completed status')
    return src

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--dir', type=Path, default=DEFAULT)
    args=ap.parse_args()
    root=args.dir.expanduser().resolve()
    cpath=root/'marginx_control.py'; upath=root/'marginx_ui.py'
    if not cpath.is_file() or not upath.is_file():
        raise ValueError(f'Expected files not found in {root}')
    oldc=cpath.read_text(encoding='utf-8'); oldu=upath.read_text(encoding='utf-8')
    newc=controller(oldc); newu=ui(oldu)
    ast.parse(newc, filename=str(cpath)); ast.parse(newu, filename=str(upath))
    if args.dry_run:
        for label,a,b in [(str(cpath),oldc,newc),(str(upath),oldu,newu)]:
            print(''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True),
                  fromfile=label+' before',tofile=label+' after')))
        print('DRY RUN — no files changed')
        return
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    for p in (cpath,upath):
        backup=p.with_name(p.name+'.before_user_origin_'+stamp)
        shutil.copy2(p,backup)
        print('Backup:', backup)
    cpath.write_text(newc,encoding='utf-8')
    upath.write_text(newu,encoding='utf-8')
    print('Updated:',cpath,upath)
    print('No motorlib or calibration JSON changes. Test with motor supply off first.')

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('ABORT:',exc,file=sys.stderr)
        raise SystemExit(1)
