
import argparse
import math
import time
from gpiozero import OutputDevice

MAX_STEPS = 4000
MIN_PERIOD_S = 0.004
PULSE_HIGH_S = 0.001
DIR_SETUP_S = 0.010

ROT_STEP_PIN = 23
ROT_DIR_PIN = 24

SHIFT_STEP_PIN = 17
SHIFT_DIR_PIN = 27


def create_motor(step_pin, dir_pin, steps, reverse, period, invert):
    step = OutputDevice(
        step_pin,
        active_high=not invert,
        initial_value=False
    )

    try:
        direction = OutputDevice(
            dir_pin,
            active_high=not invert,
            initial_value=False
        )
    except Exception:
        step.close()
        raise

    if reverse:
        direction.on()
    else:
        direction.off()

    return {
        "step": step,
        "direction": direction,
        "remaining": steps,
        "period": period,
        "high": False,
        "next_on": 0.0,
        "off_at": 0.0,
    }


def run_motors(motors):
    time.sleep(DIR_SETUP_S)

    start = time.monotonic()

    for motor in motors:
        motor["next_on"] = start

    while any(m["remaining"] > 0 or m["high"] for m in motors):
        now = time.monotonic()
        deadlines = []

        for motor in motors:
            if motor["high"]:
                if now >= motor["off_at"]:
                    motor["step"].off()
                    motor["high"] = False
                else:
                    deadlines.append(motor["off_at"])

            elif motor["remaining"] > 0:
                if now >= motor["next_on"]:
                    motor["step"].on()
                    motor["high"] = True
                    motor["remaining"] -= 1

                    motor["off_at"] = now + PULSE_HIGH_S
                    motor["next_on"] = now + motor["period"]

                    deadlines.append(motor["off_at"])
                else:
                    deadlines.append(motor["next_on"])

        if deadlines:
            delay = min(deadlines) - time.monotonic()

            if delay > 0:
                time.sleep(delay)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--motor",
        choices=["rotation", "shift", "both"],
        default="rotation"
    )

    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--shift-steps", type=int, default=None)

    parser.add_argument("--reverse", action="store_true")
    parser.add_argument("--shift-reverse", action="store_true")

    # Rotation motor period
    parser.add_argument(
        "--period",
        type=float,
        default=0.020
    )

    # Shift motor period (4x faster by default)
    parser.add_argument(
        "--shift-period",
        type=float,
        default=0.005
    )

    parser.add_argument("--invert", action="store_true")

    args = parser.parse_args()

    if not all(
        math.isfinite(v) and v >= MIN_PERIOD_S
        for v in (args.period, args.shift_period)
    ):
        parser.error(
            f"Periods must be at least {MIN_PERIOD_S} seconds"
        )

    rotation_steps = max(0, min(args.steps, MAX_STEPS))

    shift_steps = (
        rotation_steps
        if args.shift_steps is None
        else max(0, min(args.shift_steps, MAX_STEPS))
    )

    motors = []

    try:
        if args.motor in ("rotation", "both"):
            motors.append(
                create_motor(
                    ROT_STEP_PIN,
                    ROT_DIR_PIN,
                    rotation_steps,
                    args.reverse,
                    args.period,
                    args.invert
                )
            )

        if args.motor in ("shift", "both"):
            motors.append(
                create_motor(
                    SHIFT_STEP_PIN,
                    SHIFT_DIR_PIN,
                    shift_steps,
                    args.shift_reverse,
                    args.shift_period,
                    args.invert
                )
            )

        print(f"Selected motor: {args.motor}")
        print(f"Rotation speed: {1 / args.period:.0f} pulses/s")
        print(f"Shift speed: {1 / args.shift_period:.0f} pulses/s")

        run_motors(motors)

        print("Done")

    except KeyboardInterrupt:
        print("\nMotor test interrupted")

    finally:
        for motor in motors:
            motor["step"].off()
            motor["step"].close()
            motor["direction"].off()
            motor["direction"].close()


if __name__ == "__main__":
    main()
