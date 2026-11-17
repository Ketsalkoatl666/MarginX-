
"""MarginX supervised zero calibration.

Positive shift direction = left.
Negative shift direction = right.

This script does not change motorlib.py.
Never run alongside the MarginX GUI.
"""

import argparse
import math

import motorlib as m


MAX_RIGHT_STEPS = 8000
MAX_JOG_STEPS = 1000
DEFAULT_PERIOD = 0.004


def integer(value):
    return type(value) is int


def read_calibration():
    state = m.load_state()

    if state.get("calibration_active"):
        if state.get("calibration_in_motion"):
            raise RuntimeError(
                "A calibration movement was interrupted. "
                "Physical position cannot be trusted. "
                "Do not resume automatically."
            )

        offset = state.get("calibration_offset_steps")
        original_range = state.get(
            "calibration_original_range"
        )

        if not (
            integer(offset)
            and integer(original_range)
            and original_range > 0
        ):
            raise RuntimeError(
                "Invalid calibration checkpoint."
            )

        return offset, original_range

    if state.get("position_valid") is False:
        raise RuntimeError(
            "Saved position is flagged invalid."
        )

    if state.get("position") != 0:
        raise RuntimeError(
            "Start calibration only from saved "
            "position zero."
        )

    original_range = state.get("range")

    if not integer(original_range) or original_range <= 0:
        raise RuntimeError("Invalid saved range.")

    m.save_state(
        position=None,
        calibration_active=True,
        calibration_in_motion=False,
        calibration_offset_steps=0,
        calibration_original_range=original_range
    )

    return 0, original_range


def print_status(offset, original_range):
    print()
    print("--------------------------------")
    print(f"Offset from OLD zero: {offset} steps")
    print(
        "Approximate displacement: "
        f"{offset / 200:.2f} mm"
    )
    print(f"Original range: {original_range}")
    print("--------------------------------")
    print()

    print("r 200    Move RIGHT 200 steps (~1 mm)")
    print("l 200    Move LEFT  200 steps (~1 mm)")
    print("r 1000   Move RIGHT 1000 steps (~5 mm)")
    print("status   Show calibration status")
    print("set      Set current location as new zero")
    print("cancel   Restore state only at old zero")
    print("q        Exit; calibration remains pending")
    print()


def jog(axis, offset, original_range, direction, steps):
    if not integer(steps) or not 1 <= steps <= MAX_JOG_STEPS:
        print(
            f"Use 1 to {MAX_JOG_STEPS} "
            "steps per jog."
        )
        return offset

    delta = -steps if direction == "r" else steps
    target_offset = offset + delta

    # Restrict this calibration utility to a small
    # region between old zero and the expected new zero.
    if not -MAX_RIGHT_STEPS <= target_offset <= 0:
        print(
            "Movement blocked by calibration "
            "software limit."
        )
        return offset

    print()
    print(
        f"Requested: {direction.upper()} "
        f"{steps} steps."
    )
    print(
        "Verify physical clearance and "
        "keep a way to disconnect motor power."
    )

    answer = input("Type MOVE to execute: ").strip()

    if answer != "MOVE":
        print("Movement cancelled.")
        return offset

    # If the program stops during movement, the
    # stored position remains invalid.
    m.save_state(calibration_in_motion=True)

    axis.set_direction(direction == "l")

    sent = axis.pulses(steps)

    if sent != steps:
        raise RuntimeError(
            "Incomplete jog. Position is uncertain."
        )

    new_offset = offset + (
        sent if direction == "l" else -sent
    )

    m.save_state(
        calibration_offset_steps=new_offset,
        calibration_in_motion=False
    )

    print(f"Commanded offset: {new_offset} steps")

    return new_offset


def set_zero(offset, original_range):
    if offset == 0:
        print(
            "No calibration offset has been applied."
        )
        return False

    # Only valid if the original positive-direction
    # physical endpoint is being preserved.
    new_range = original_range - offset

    print()
    print("PROPOSED NEW CALIBRATION")
    print(f"Old zero offset: {offset} steps")
    print("New position: 0 steps")
    print(f"New range: {new_range} steps")
    print()
    print(
        "This assumes the ORIGINAL physical "
        "left endpoint is still the intended "
        "maximum travel endpoint."
    )

    answer = input(
        "Have you physically reached the "
        "desired cup insertion zero? (YES/no): "
    ).strip()

    if answer != "YES":
        print("Calibration not saved.")
        return False

    answer = input(
        "Have you verified that preserving "
        "the old left endpoint is correct? "
        "(YES/no): "
    ).strip()

    if answer != "YES":
        print(
            "Calibration not saved. "
            "The range must be checked first."
        )
        return False

    answer = input(
        "Type SET ZERO to save: "
    ).strip()

    if answer != "SET ZERO":
        print("Calibration not saved.")
        return False

    m.save_state(
        position=0,
        range=new_range,
        position_valid=True,
        calibration_active=False,
        calibration_in_motion=False,
        calibration_offset_steps=0,
        calibration_original_range=None
    )

    print()
    print("New zero saved successfully.")
    print(
        "Check physical endpoints before "
        "running any automatic scan."
    )

    return True


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--period",
        type=float,
        default=DEFAULT_PERIOD
    )

    args = parser.parse_args()

    if (
        not math.isfinite(args.period)
        or args.period < m.MIN_PERIOD_S
    ):
        parser.error("Invalid jog period.")

    offset, original_range = read_calibration()

    axis = None

    try:
        axis = m.Axis(
            m.SHIFT_STEP_PIN,
            m.SHIFT_DIR_PIN,
            args.period
        )

        while True:
            print_status(offset, original_range)

            command = input(
                "Calibration > "
            ).strip().lower()

            if command in ("q", "quit", "exit"):
                print(
                    "Calibration pending. "
                    "Do not run the GUI yet."
                )
                break

            if command == "status":
                continue

            if command == "set":
                if set_zero(offset, original_range):
                    break
                continue

            if command == "cancel":
                if offset != 0:
                    print(
                        "Jog back to old zero "
                        "before cancelling."
                    )
                    continue

                answer = input(
                    "Type CANCEL to restore "
                    "old zero: "
                ).strip()

                if answer == "CANCEL":
                    m.save_state(
                        position=0,
                        calibration_active=False,
                        calibration_in_motion=False,
                        calibration_offset_steps=0,
                        calibration_original_range=None
                    )
                    print("Original zero restored.")
                    break

                continue

            parts = command.split()

            if (
                len(parts) == 2
                and parts[0] in ("r", "l")
            ):
                try:
                    steps = int(parts[1])
                except ValueError:
                    print("Invalid step count.")
                    continue

                offset = jog(
                    axis,
                    offset,
                    original_range,
                    parts[0],
                    steps
                )
                continue

            print("Unknown command.")

    finally:
        if axis is not None:
            axis.close()


if __name__ == "__main__":
    main()
