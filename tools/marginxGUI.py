"""MarginX app entry point. Run this file from ~/marginx/tools/."""

import argparse
import math
import tkinter as tk

import motorlib as m
from marginx_ui import MarginXApp


def main():
    parser = argparse.ArgumentParser(description="MarginX touchscreen scanner")
    parser.add_argument("--seconds", type=float, default=30.0,
                        help="rotation seconds per scan position")
    parser.add_argument("--shift-period", type=float, default=0.001)
    parser.add_argument("--rot-period", type=float, default=0.020)
    parser.add_argument("--cal-period", type=float, default=0.004)
    args = parser.parse_args()

    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 600:
        parser.error("--seconds must be greater than 0 and no more than 600")
    for key in ("shift_period", "rot_period", "cal_period"):
        value = getattr(args, key)
        if not math.isfinite(value) or value < m.MIN_PERIOD_S:
            parser.error(f"Invalid {key}")

    root = tk.Tk()
    MarginXApp(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
