
"""MarginX shared motor control and persistent position storage."""

import json
import math
import os
import tempfile
import time

from gpiozero import OutputDevice

# GPIO assignments
ROT_STEP_PIN, ROT_DIR_PIN = 23, 24
SHIFT_STEP_PIN, SHIFT_DIR_PIN = 17, 27
BUTTON_PIN = 25

# Electrical settings
INVERT = True
PULSE_HIGH_S = 0.0001
DIR_SETUP_S = 0.010

# Speed settings
MIN_PERIOD_S = 0.0005
SHIFT_START_PERIOD_S = 0.004
SHIFT_RAMP_STEPS = 300

STATE_FILE = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "config",
        "shift_state.json"
    )
)


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save_state(**changes):
    state = load_state()
    state.update(changes)

    directory = os.path.dirname(STATE_FILE)
    os.makedirs(directory, exist_ok=True)
    path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=directory,
            prefix=".shift_state_",
            suffix=".tmp",
            delete=False
        ) as f:
            path = f.name
            json.dump(state, f, indent=4)
            f.flush()
            os.fsync(f.fileno())

        os.replace(path, STATE_FILE)

        if hasattr(os, "O_DIRECTORY"):
            fd = os.open(
                directory,
                os.O_RDONLY | os.O_DIRECTORY
            )
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def _wait_until(t):
    while True:
        remaining = t - time.perf_counter()

        if remaining <= 0:
            return

        if remaining > 0.002:
            time.sleep(remaining - 0.001)


class Axis:
    def __init__(self, step_pin, dir_pin, period):
        if not math.isfinite(period) or period <= 0:
            raise ValueError("Invalid motor period")

        self.period = max(period, MIN_PERIOD_S)

        # Acceleration applies only to the shift motor.
        self.is_shift = step_pin == SHIFT_STEP_PIN

        self.step = OutputDevice(
            step_pin,
            active_high=not INVERT,
            initial_value=False
        )

        try:
            self.dir = OutputDevice(
                dir_pin,
                active_high=not INVERT,
                initial_value=False
            )
        except Exception:
            self.step.close()
            raise

    def close(self):
        self.step.off()
        self.dir.off()
        self.step.close()
        self.dir.close()

    def set_direction(self, forward):
        if forward:
            self.dir.off()
        else:
            self.dir.on()

        time.sleep(DIR_SETUP_S)

    def _step_period(self, index, count):
        """Generate trapezoidal acceleration/deceleration."""

        if not self.is_shift or count is None:
            return self.period

        if self.period >= SHIFT_START_PERIOD_S:
            return self.period

        ramp = min(SHIFT_RAMP_STEPS, count // 2)

        if ramp <= 0:
            return SHIFT_START_PERIOD_S

        # Acceleration at the beginning
        start_fraction = min(1.0, index / ramp)

        # Deceleration near the end
        end_fraction = min(
            1.0,
            (count - 1 - index) / ramp
        )

        fraction = max(
            0.0,
            min(start_fraction, end_fraction)
        )

        return (
            SHIFT_START_PERIOD_S
            + (self.period - SHIFT_START_PERIOD_S)
            * fraction
        )

    def _pulse_train(self, keep_going, count=None):
        sent = 0
        t = time.perf_counter()

        try:
            while keep_going(sent):
                period = self._step_period(sent, count)
                high = min(PULSE_HIGH_S, period / 2)

                self.step.on()
                _wait_until(t + high)
                self.step.off()

                sent += 1

                t += period
                _wait_until(t)

                # Avoid attempting to catch up with
                # excessively delayed pulses.
                t = max(t, time.perf_counter())

        finally:
            self.step.off()

        return sent

    def pulses(self, count, abort=None):
        if type(count) is not int or count < 0:
            raise ValueError("Count must be a nonnegative integer")

        return self._pulse_train(
            lambda n: (
                n < count
                and not (abort and abort.is_set())
            ),
            count=count
        )

    def run_for(self, seconds, abort=None):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Invalid duration")

        end = time.perf_counter() + seconds

        return self._pulse_train(
            lambda n: (
                time.perf_counter() < end
                and not (abort and abort.is_set())
            )
        )


def move_shift_to(axis, target, abort=None):
    """Move shift to a saved-coordinate target."""

    st = load_state()
    pos = st.get("position")
    rng = st.get("range")

    if (
        type(pos) is not int
        or type(rng) is not int
        or rng <= 0
        or not 0 <= pos <= rng
    ):
        raise RuntimeError(
            "Shift position unknown. Recalibration required."
        )

    if type(target) is not int or not 0 <= target <= rng:
        raise ValueError("Target outside calibrated range")

    if abort is not None and abort.is_set():
        return False

    delta = target - pos

    if delta == 0:
        print(f"Shift already at {target}")
        return True

    print(f"Shift: {pos} -> {target}")

    axis.set_direction(delta > 0)

    # Mark position unknown during motion.
    save_state(position=None)

    try:
        sent = axis.pulses(abs(delta), abort)

        if type(sent) is not int or not 0 <= sent <= abs(delta):
            raise RuntimeError("Invalid pulse count")

        new_pos = pos + sent if delta > 0 else pos - sent

        save_state(position=new_pos)

        print(f"Estimated shift position: {new_pos}")

        return sent == abs(delta)

    except BaseException:
        # Unexpected interruption requires re-zeroing.
        save_state(position=None)
        raise


def go_to_zero(axis, abort=None):
    """Return to saved zero (not sensor-based homing)."""

    print("Returning shift to saved zero...")
    return move_shift_to(axis, 0, abort)
