
"""MarginX motor control, calibration, and scan indicator."""

import queue
import threading
import time

import motorlib as m
from gpiozero import Button, OutputDevice


# GPIO assignments (BCM numbering)
CUP_PIN = 5
COVER_PIN = 6
LED_PIN = 26

# Position display / jog resolution
STEPS_PER_MM = 200.0

STAGES = {
    "move1": (0, 10, "Moving to 1/3 of range"),
    "rotate1": (10, 30, "Scanning at 1/3"),
    "move2": (30, 40, "Moving to 1/2 of range"),
    "rotate2": (40, 60, "Scanning at 1/2"),
    "move3": (60, 70, "Moving to 2/3 of range"),
    "rotate3": (70, 90, "Scanning at 2/3"),
    "return": (90, 99, "Returning to selected start position"),
}


class Scanner:
    def __init__(self, args):
        self.args = args

        self.cup = Button(
            CUP_PIN, pull_up=True, bounce_time=0.05
        )
        self.cover = Button(
            COVER_PIN, pull_up=True, bounce_time=0.05
        )

        # LED is OFF when the program starts.
        self.scan_led = OutputDevice(
            LED_PIN,
            active_high=True,
            initial_value=False
        )

        self.events = queue.Queue()
        self.abort = threading.Event()
        self.worker = None
        self.running = False
        self.operation = None

        self.zero_ready = False
        self.cal_offset = 0
        self.cal_original_range = None
        self.calibration_active = False
        self.calibration_uncertain = False
        self.start_position = None
        self.start_position_confirmed = False

    def state(self):
        return m.load_state()

    def valid_position(self):
        st = self.state()
        pos = st.get("position")
        rng = st.get("range")

        return (
            type(pos) is int
            and type(rng) is int
            and rng > 0
            and 0 <= pos <= rng
            and st.get("position_valid") is not False
            and not st.get("calibration_active")
            and not st.get("calibration_in_motion")
        )

    def sensors_ready(self):
        return (
            self.cup.is_pressed
            and self.cover.is_pressed
        )

    def _start(self, operation, function, *params):
        if self.running:
            return False

        self.running = True
        self.operation = operation
        self.abort.clear()

        def run():
            try:
                function(*params)
            finally:
                self.running = False
                self.operation = None

        self.worker = threading.Thread(
            target=run,
            daemon=True
        )
        self.worker.start()
        return True

    # ---------------------------------
    # Manual scan start-position selection
    # ---------------------------------

    def prepare_manual_position(self):
        """Enter positioning mode without issuing any motor movement."""
        if self.running:
            return False
        self.zero_ready = self.valid_position()
        self.cal_offset = 0
        self.cal_original_range = self.state().get("range")
        self.calibration_active = False
        self.calibration_uncertain = not self.zero_ready
        self.start_position = None
        self.start_position_confirmed = False
        return self.zero_ready

    def start_jog(self, delta):
        """Jog relative to the persisted absolute coordinate."""
        if self.running or not self.valid_position() or self.calibration_uncertain:
            return False
        if delta not in (-1000, -200, 200, 1000):
            raise ValueError("Unsupported jog distance.")

        state = self.state()
        target = state["position"] + delta
        if not 0 <= target <= state["range"]:
            raise ValueError("Jog would exceed the calibrated travel range.")

        # A jog invalidates the previously confirmed scan origin.
        self.start_position = None
        self.start_position_confirmed = False
        self.zero_ready = False
        return self._start("jog", self._jog_worker, target)

    def _jog_worker(self, target):
        axis = None
        error = None
        try:
            state = self.state()
            axis = m.Axis(
                m.SHIFT_STEP_PIN,
                m.SHIFT_DIR_PIN,
                self.args.cal_period,
            )
            self.events.put(("jog_progress", 0.0))
            result = m.move_shift_to(axis, target, self.abort)
            if result is False or self.abort.is_set() or self.state().get("position") != target:
                raise RuntimeError("Jog interrupted; physical position must be verified.")
            self.events.put(("jog_progress", 100.0))
        except BaseException as exc:
            error = str(exc) or type(exc).__name__
            self.calibration_uncertain = True
            # Physical position is not independently measured by an encoder.
            m.save_state(position=None, position_valid=False)
        finally:
            if axis is not None:
                try:
                    axis.close()
                except Exception as exc:
                    error = error or str(exc)
                    self.calibration_uncertain = True
                    m.save_state(position=None, position_valid=False)
            self.zero_ready = error is None and self.valid_position()
            self.events.put(("jog_done", error))

    def confirm_start_position(self):
        """Confirm an existing coordinate; do NOT redefine mechanical zero."""
        if self.running or self.calibration_uncertain or not self.valid_position():
            return False
        state = self.state()
        pos, limit = state["position"], state["range"]
        remaining = limit - pos
        if remaining < 3:
            raise ValueError("Not enough remaining leftward travel for three scan positions.")
        targets = (
            pos + remaining // 3,
            pos + remaining // 2,
            pos + 2 * remaining // 3,
        )
        if not (pos < targets[0] < targets[1] < targets[2] <= limit):
            raise ValueError("Move the stage to allow distinct scan positions.")
        self.start_position = pos
        self.start_position_confirmed = True
        self.zero_ready = True
        return True

    # Compatibility method for callers from earlier UI versions.
    # It now confirms the scan origin and MUST NOT overwrite range/zero.
    def save_new_zero(self):
        return self.confirm_start_position()

    # ---------------------------------
    # Scanning
    # ---------------------------------

    def start_scan(self):
        if (
            self.running
            or not self.zero_ready
            or not self.sensors_ready()
            or not self.valid_position()
            or not self.start_position_confirmed
            or self.start_position is None
            or self.state().get("position") != self.start_position
        ):
            return False

        # Capture and freeze the exact origin for this scan.
        origin = self.start_position
        self.start_position_confirmed = False
        self.zero_ready = False
        return self._start("scan", self._scan_worker, origin)

    def _move(self, axis, name, target):
        if self.abort.is_set():
            raise RuntimeError("Scan interrupted.")

        pos = self.state().get("position")

        if type(pos) is not int:
            raise RuntimeError(
                "Shift position unknown; "
                "recalibration required."
            )

        self.events.put(
            ("phase", (name, abs(target - pos)))
        )

        result = m.move_shift_to(
            axis, target, self.abort
        )

        if (
            result is False
            or self.abort.is_set()
            or self.state().get("position") != target
        ):
            raise RuntimeError(
                "Shift movement interrupted."
            )

        self.events.put(
            ("phase_done", name)
        )

    def _rotate(self, axis, name):
        self.events.put(
            ("phase", (name, 0))
        )

        axis.set_direction(True)
        elapsed = 0.0

        while elapsed < self.args.seconds:
            if self.abort.is_set():
                raise RuntimeError(
                    "Rotation interrupted."
                )

            segment = min(
                0.1,
                self.args.seconds - elapsed
            )

            started = time.monotonic()

            result = axis.run_for(
                segment, self.abort
            )

            if result is False or self.abort.is_set():
                raise RuntimeError(
                    "Rotation interrupted."
                )

            elapsed += (
                time.monotonic() - started
            )

            self.events.put(
                (
                    "rotation_progress",
                    (
                        name,
                        min(elapsed, self.args.seconds)
                    )
                )
            )

        self.events.put(
            ("phase_done", name)
        )

    def _scan_worker(self, origin):
        shift = None
        rotation = None
        error = None

        try:
            # LED ON at the beginning of the scan.
            self.scan_led.on()

            rng = self.state()["range"]
            remaining = rng - origin
            targets = (
                origin + remaining // 3,
                origin + remaining // 2,
                origin + 2 * remaining // 3,
            )

            if not (
                origin < targets[0]
                < targets[1]
                < targets[2]
                <= rng
            ):
                raise RuntimeError(
                    "Calibrated range is too small."
                )

            shift = m.Axis(
                m.SHIFT_STEP_PIN,
                m.SHIFT_DIR_PIN,
                self.args.shift_period
            )

            rotation = m.Axis(
                m.ROT_STEP_PIN,
                m.ROT_DIR_PIN,
                self.args.rot_period
            )

            for i, target in enumerate(
                targets, 1
            ):
                self._move(
                    shift,
                    f"move{i}",
                    target
                )

                self._rotate(
                    rotation,
                    f"rotate{i}"
                )

            # Return to the exact user-selected pre-scan origin.
            # Never return automatically after a failed/interrupted scan.
            self._move(shift, "return", origin)

            if self.abort.is_set():
                raise RuntimeError(
                    "Scan interrupted."
                )

        except BaseException as exc:
            error = str(exc) or type(exc).__name__

        finally:
            # Stop and release motor GPIO objects.
            for axis in (rotation, shift):
                if axis is not None:
                    try:
                        axis.close()
                    except Exception as exc:
                        error = error or str(exc)

            # LED OFF after scan or any error.
            self.scan_led.off()

            if self.abort.is_set():
                error = error or "Scan interrupted."
            if error:
                # Fail closed after any scan fault: physical position cannot
                # be proven from open-loop step counts alone.
                m.save_state(position=None, position_valid=False)
            self.start_position = None
            self.start_position_confirmed = False
            self.zero_ready = False
            self.events.put(
                ("scan_done", error)
            )

    # ---------------------------------
    # Stop / shutdown
    # ---------------------------------

    def request_stop(self):
        self.abort.set()

        # Request LED off immediately.
        self.scan_led.off()

    def close(self):
        if self.worker and self.worker.is_alive():
            raise RuntimeError(
                "Cannot close GPIO while "
                "motor thread is running."
            )

        self.scan_led.off()
        self.scan_led.close()
        self.cup.close()
        self.cover.close()
