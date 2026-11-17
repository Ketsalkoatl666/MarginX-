
"""MarginX button controller.

Press:
    1. Return shift motor to saved zero.
    2. Move shift motor to the midpoint.
    3. Run rotation motor for N seconds.

Press again during movement:
    Stop the current cycle.

Requires previous shift calibration.
"""

import argparse
import math
import sys
import threading

from gpiozero import Button
import motorlib as m

MAX_ROTATE_S = 600


def run_cycle(shift, rot, abort, seconds):
    # Step 1: Return to zero first.
    if not m.go_to_zero(shift, abort):
        print("Stopped while returning to zero.")
        return

    if abort.is_set():
        return

    # Step 2: Move to the midpoint.
    st = m.load_state()
    rng = st.get("range")

    if type(rng) is not int or rng <= 0:
        raise RuntimeError("Invalid calibrated travel range")

    target = rng // 2

    print(f"Moving shift to midpoint: {target}")

    if not m.move_shift_to(shift, target, abort):
        print("Stopped while moving to midpoint.")
        return

    if abort.is_set():
        return

    # Step 3: Run rotation motor.
    print(f"Rotation running for {seconds:.1f} seconds")

    rot.set_direction(True)
    rot.run_for(seconds, abort)

    print(
        "Rotation stopped."
        if abort.is_set()
        else "Cycle finished."
    )


def main():
    p = argparse.ArgumentParser()

    p.add_argument(
        "--seconds",
        type=float,
        default=60
    )
    p.add_argument(
        "--shift-period",
        type=float,
        default=0.0005
    )
    p.add_argument(
        "--rot-period",
        type=float,
        default=0.020
    )

    a = p.parse_args()

    if not math.isfinite(a.seconds):
        p.error("--seconds must be finite")

    if not all(
        math.isfinite(v) and v >= m.MIN_PERIOD_S
        for v in (a.shift_period, a.rot_period)
    ):
        p.error("Invalid motor period")

    seconds = max(0.0, min(a.seconds, MAX_ROTATE_S))

    if m.BUTTON_PIN in (
        m.ROT_STEP_PIN,
        m.ROT_DIR_PIN,
        m.SHIFT_STEP_PIN,
        m.SHIFT_DIR_PIN
    ):
        sys.exit("BUTTON_PIN clashes with a motor pin.")

    st = m.load_state()
    pos, rng = st.get("position"), st.get("range")

    if (
        type(pos) is not int
        or type(rng) is not int
        or rng <= 0
        or not 0 <= pos <= rng
    ):
        sys.exit(
            "Shift position/range unknown. "
            "Recalibrate before automatic movement."
        )

    print("MarginX Controller")
    print(f"Saved shift position: {pos}")
    print(f"Travel range: {rng}")
    print(f"Midpoint: {rng // 2}")

    shift = None
    rot = None
    button = None

    start = threading.Event()
    abort = threading.Event()
    running = threading.Event()

    try:
        shift = m.Axis(
            m.SHIFT_STEP_PIN,
            m.SHIFT_DIR_PIN,
            a.shift_period
        )

        rot = m.Axis(
            m.ROT_STEP_PIN,
            m.ROT_DIR_PIN,
            a.rot_period
        )

        button = Button(
            m.BUTTON_PIN,
            pull_up=True,
            bounce_time=0.05
        )

        def pressed():
            if running.is_set():
                abort.set()
            else:
                start.set()

        button.when_pressed = pressed

        print("Ready. Press button to start/stop.")

        while True:
            start.wait()
            running.set()
            start.clear()
            abort.clear()

            try:
                run_cycle(
                    shift,
                    rot,
                    abort,
                    seconds
                )
            except Exception as e:
                print(f"Cycle failed: {e}")
                print("Controller stopping for safety.")
                break
            finally:
                running.clear()

    except KeyboardInterrupt:
        print("\nController interrupted.")

    finally:
        if button is not None:
            button.close()
        if shift is not None:
            shift.close()
        if rot is not None:
            rot.close()

        print("Motor controller closed.")
        print("Saved shift state retained if valid.")


if __name__ == "__main__":
    main()
