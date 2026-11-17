"""MarginX control: zero-free manual positioning and relative scan travel.

No absolute coordinates, no homing, and no edits to shift_state.json.
The operator must verify mechanical clearance for every manual move and scan.
"""
import queue
import threading
import time

import motorlib as m
from gpiozero import Button, OutputDevice

CUP_PIN = 16
COVER_PIN = 6
LED_PIN = 26
STEPS_PER_MM = 200.0

# CRITICAL: replace this EXAMPLE after measuring the safely available
# leftward travel from EVERY position where users can begin a scan.
# Here 6000 steps = 30 mm. No limit switches are installed to enforce it.
SCAN_SPAN_STEPS = 6000

STAGES = {
    "move1": (0, 10, "Moving to 1/3 of scan travel"),
    "rotate1": (10, 30, "Scanning at 1/3"),
    "move2": (30, 40, "Moving to 1/2 of scan travel"),
    "rotate2": (40, 60, "Scanning at 1/2"),
    "move3": (60, 70, "Moving to 2/3 of scan travel"),
    "rotate3": (70, 90, "Scanning at 2/3"),
    "return": (90, 99, "Returning to pre-scan position"),
}


class Scanner:
    def __init__(self, args):
        self.args = args
        self.cup = Button(CUP_PIN, pull_up=True, bounce_time=0.05)
        self.cover = Button(COVER_PIN, pull_up=True, bounce_time=0.05)
        self.scan_led = OutputDevice(LED_PIN, active_high=True, initial_value=False)
        self.events = queue.Queue()
        self.abort = threading.Event()
        self.worker = None
        self.running = False
        self.operation = None
        self.ready_to_scan = False
        self.needs_inspection = False
        self.jog_session_steps = 0  # purely relative display, not physical position
        self.scan_span_steps = SCAN_SPAN_STEPS

    def sensors_ready(self):
        return self.cup.is_pressed and self.cover.is_pressed

    def prepare_manual_position(self):
        if self.running:
            return False
        self.ready_to_scan = False
        self.jog_session_steps = 0
        return True

    def _start(self, operation, function, *args):
        if self.running:
            return False
        self.running = True
        self.operation = operation
        self.abort.clear()

        def runner():
            try:
                function(*args)
            finally:
                self.running = False
                self.operation = None

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()
        return True

    def start_jog(self, delta):
        if self.running:
            raise RuntimeError("Motor is still moving")
        if self.needs_inspection:
            raise RuntimeError("Previous motion was interrupted. Inspect the stage before further movement")
        if delta not in (-1000, -200, 200, 1000):
            raise ValueError("Unsupported jog amount")
        self.ready_to_scan = False
        return self._start("jog", self._jog_worker, delta)

    def _jog_worker(self, delta):
        axis = None
        error = None
        try:
            axis = m.Axis(m.SHIFT_STEP_PIN, m.SHIFT_DIR_PIN, self.args.cal_period)
            axis.set_direction(delta > 0)  # left is positive
            self.events.put(("jog_progress", 0.0))
            sent = axis.pulses(abs(delta), self.abort)
            if sent != abs(delta) or self.abort.is_set():
                raise RuntimeError("Jog interrupted; inspect stage before any more motion")
            self.jog_session_steps += delta
            self.events.put(("jog_progress", 100.0))
        except BaseException as exc:
            error = str(exc) or type(exc).__name__
            self.needs_inspection = True
        finally:
            if axis is not None:
                try:
                    axis.close()
                except Exception as exc:
                    error = error or str(exc)
                    self.needs_inspection = True
            self.events.put(("jog_done", error))

    def confirm_start_position(self):
        """Implicitly capture physical pre-scan position: no zero or coordinate."""
        if self.running or self.needs_inspection:
            raise RuntimeError("Stage is moving or requires inspection")
        self.ready_to_scan = True
        return True

    def start_scan(self):
        if self.running or self.needs_inspection or not self.ready_to_scan or not self.sensors_ready():
            return False
        if type(self.scan_span_steps) is not int or self.scan_span_steps < 6:
            raise ValueError("Configure a valid relative scan span")
        self.ready_to_scan = False
        return self._start("scan", self._scan_worker)

    def _move_relative(self, axis, name, delta):
        if self.abort.is_set() or not self.sensors_ready():
            raise RuntimeError("Scan stopped by abort or sensor state")
        count = abs(delta)
        self.events.put(("phase", (name, count)))
        if count:
            axis.set_direction(delta > 0)
            sent = axis.pulses(count, self.abort)
            if sent != count or self.abort.is_set():
                raise RuntimeError("Shift interrupted; physical position uncertain")
        self.events.put(("phase_done", name))

    def _rotate(self, axis, name):
        self.events.put(("phase", (name, 0)))
        axis.set_direction(True)
        elapsed = 0.0
        while elapsed < self.args.seconds:
            if self.abort.is_set() or not self.sensors_ready():
                raise RuntimeError("Rotation stopped by abort or sensor state")
            duration = min(0.1, self.args.seconds - elapsed)
            start = time.monotonic()
            result = axis.run_for(duration, self.abort)
            if result is False or self.abort.is_set():
                raise RuntimeError("Rotation interrupted")
            elapsed += time.monotonic() - start
            self.events.put(("rotation_progress", (name, min(elapsed, self.args.seconds))))
        self.events.put(("phase_done", name))

    def _scan_worker(self):
        shift = None
        rotation = None
        error = None
        displacement = 0
        try:
            span = self.scan_span_steps
            targets = (span // 3, span // 2, (2 * span) // 3)
            if not (0 < targets[0] < targets[1] < targets[2]):
                raise RuntimeError("Scan span too small")
            shift = m.Axis(m.SHIFT_STEP_PIN, m.SHIFT_DIR_PIN, self.args.shift_period)
            rotation = m.Axis(m.ROT_STEP_PIN, m.ROT_DIR_PIN, self.args.rot_period)
            self.scan_led.on()
            for i, target in enumerate(targets, 1):
                self._move_relative(shift, f"move{i}", target - displacement)
                displacement = target
                self._rotate(rotation, f"rotate{i}")
            # Only successful, uninterrupted scans return automatically.
            self._move_relative(shift, "return", -displacement)
            displacement = 0
            if self.abort.is_set():
                raise RuntimeError("Scan interrupted")
        except BaseException as exc:
            error = str(exc) or type(exc).__name__
            self.needs_inspection = True
        finally:
            for axis in (rotation, shift):
                if axis is not None:
                    try:
                        axis.close()
                    except Exception as exc:
                        error = error or str(exc)
                        self.needs_inspection = True
            self.scan_led.off()
            if self.abort.is_set():
                error = error or "Scan interrupted"
                self.needs_inspection = True
            self.events.put(("scan_done", error))

    def request_stop(self):
        self.abort.set()
        self.scan_led.off()

    def close(self):
        if self.worker and self.worker.is_alive():
            raise RuntimeError("Cannot close GPIO while motor worker is running")
        self.scan_led.off()
        self.scan_led.close()
        self.cup.close()
        self.cover.close()
