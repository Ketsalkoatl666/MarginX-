
"""MarginX motor control, calibration, and scan indicator."""

import queue
import threading
import time

import motorlib as m
from gpiozero import Button, OutputDevice


# GPIO assignments (BCM numbering)
CUP_PIN = 16
COVER_PIN = 6
LED_PIN = 26

# Calibration settings
STEPS_PER_MM = 200.0
MAX_CAL_OFFSET = 8000
JOG_CHUNK = 100

STAGES = {
    "move1": (0, 10, "Moving to 1/3 of range"),
    "rotate1": (10, 30, "Scanning at 1/3"),
    "move2": (30, 40, "Moving to 1/2 of range"),
    "rotate2": (40, 60, "Scanning at 1/2"),
    "move3": (60, 70, "Moving to 2/3 of range"),
    "rotate3": (70, 90, "Scanning at 2/3"),
    "home": (90, 99, "Returning to zero"),
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
    # Initial return to zero
    # ---------------------------------

    def start_home(self):
        if not self.valid_position():
            raise RuntimeError(
                "Saved position is invalid; "
                "manual recovery required."
            )

        if self.running:
            return False

        self.zero_ready = False
        self.cal_offset = 0
        self.cal_original_range = self.state()["range"]
        self.calibration_active = False
        self.calibration_uncertain = False

        return self._start(
            "home", self._home_worker
        )

    def _home_worker(self):
        axis = None
        error = None

        try:
            axis = m.Axis(
                m.SHIFT_STEP_PIN,
                m.SHIFT_DIR_PIN,
                self.args.shift_period
            )

            result = m.go_to_zero(
                axis, self.abort
            )

            if result is False or self.abort.is_set():
                raise RuntimeError(
                    "Return to saved zero was interrupted."
                )

            if self.state().get("position") != 0:
                raise RuntimeError(
                    "Saved position did not reach zero."
                )

        except BaseException as exc:
            error = str(exc) or type(exc).__name__

        finally:
            if axis is not None:
                try:
                    axis.close()
                except Exception as exc:
                    error = error or str(exc)

            if self.abort.is_set():
                error = error or (
                    "Return to zero was interrupted."
                )

            self.zero_ready = error is None

            self.events.put(
                ("home_done", error)
            )

    # ---------------------------------
    # Zero calibration
    # ---------------------------------

    def start_jog(self, delta):
        if (
            self.running
            or not self.zero_ready
            or self.calibration_uncertain
        ):
            return False

        if delta not in (-1000, -200, 200, 1000):
            raise ValueError(
                "Unsupported jog distance."
            )

        new_offset = self.cal_offset + delta

        if not -MAX_CAL_OFFSET <= new_offset <= MAX_CAL_OFFSET:
            raise ValueError(
                "Calibration offset exceeds software limit."
            )

        if self.cal_original_range - new_offset <= 0:
            raise ValueError(
                "Proposed range would not be positive."
            )

        if not self.calibration_active:
            m.save_state(
                position=None,
                calibration_active=True,
                calibration_in_motion=False,
                calibration_offset_steps=0,
                calibration_original_range=(
                    self.cal_original_range
                )
            )
            self.calibration_active = True

        return self._start(
            "jog", self._jog_worker, delta
        )

    def _jog_worker(self, delta):
        axis = None
        error = None
        sent_total = 0
        target_count = abs(delta)

        try:
            m.save_state(
                calibration_in_motion=True
            )

            axis = m.Axis(
                m.SHIFT_STEP_PIN,
                m.SHIFT_DIR_PIN,
                self.args.cal_period
            )

            # Positive = left; negative = right.
            axis.set_direction(delta > 0)

            while sent_total < target_count:
                if self.abort.is_set():
                    raise RuntimeError(
                        "Jog interrupted; position is uncertain."
                    )

                chunk = min(
                    JOG_CHUNK,
                    target_count - sent_total
                )

                sent = axis.pulses(
                    chunk, self.abort
                )
                sent_total += sent

                self.events.put(
                    (
                        "jog_progress",
                        100 * sent_total / target_count
                    )
                )

                if sent != chunk:
                    raise RuntimeError(
                        "Incomplete jog; position is uncertain."
                    )

            if self.abort.is_set():
                raise RuntimeError(
                    "Jog interrupted; position is uncertain."
                )

            new_offset = self.cal_offset + delta

            m.save_state(
                calibration_offset_steps=new_offset,
                calibration_in_motion=False
            )

            self.cal_offset = new_offset

            if new_offset == 0:
                m.save_state(
                    position=0,
                    calibration_active=False,
                    calibration_in_motion=False,
                    calibration_offset_steps=0,
                    calibration_original_range=None
                )
                self.calibration_active = False

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

            self.events.put(
                ("jog_done", error)
            )

    def save_new_zero(self):
        if (
            self.running
            or not self.zero_ready
            or self.calibration_uncertain
            or not self.calibration_active
            or self.cal_offset == 0
        ):
            return False

        new_range = (
            self.cal_original_range - self.cal_offset
        )

        if new_range <= 0:
            raise ValueError("Invalid new range.")

        # Preserve the original LEFT endpoint.
        m.save_state(
            position=0,
            range=new_range,
            position_valid=True,
            calibration_active=False,
            calibration_in_motion=False,
            calibration_offset_steps=0,
            calibration_original_range=None
        )

        self.cal_original_range = new_range
        self.cal_offset = 0
        self.calibration_active = False

        return True

    # ---------------------------------
    # Scanning
    # ---------------------------------

    def start_scan(self):
        if (
            self.running
            or not self.zero_ready
            or not self.sensors_ready()
            or not self.valid_position()
            or self.state().get("position") != 0
        ):
            return False

        self.zero_ready = False

        return self._start(
            "scan", self._scan_worker
        )

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

    def _scan_worker(self):
        shift = None
        rotation = None
        error = None

        try:
            # LED ON at the beginning of the scan.
            self.scan_led.on()

            rng = self.state()["range"]

            targets = (
                rng // 3,
                rng // 2,
                2 * rng // 3
            )

            if not (
                0 < targets[0]
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

            # Keep LED ON during final return.
            self._move(
                shift,
                "home",
                0
            )

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
