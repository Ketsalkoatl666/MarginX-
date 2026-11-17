"""Jog the shift motor by hand to measure its travel range.
Commands (type, then Enter):
  +200   move 200 steps forward        -200   move 200 steps back
  z      call the current position 0   (do this at one end of the travel)
  r      store the current position as the other end -> travel range
  p      show position and range
  q      quit
Keep a little clearance from the hard stops; never jog into them."""
import motorlib as m

MAX_JOG = 40000
SHIFT_PERIOD_S = 0.002


def main():
    st = m.load_state()
    pos = st.get("position")
    if pos is None:
        print("Position unknown: assuming 0. Use 'z' at one end of the travel.")
        pos = 0
    axis = m.Axis(m.SHIFT_STEP_PIN, m.SHIFT_DIR_PIN, SHIFT_PERIOD_S)
    print(__doc__)
    try:
        while True:
            try:
                cmd = input("shift> ").strip().lower()
            except EOFError:
                break
            if cmd in ("q", "quit"):
                break
            elif cmd == "p":
                print(f"position {pos}, range {m.load_state().get('range')}")
            elif cmd == "z":
                pos = 0
                m.save_state(position=0, range=None)
                print("zero set here")
            elif cmd == "r":
                if pos == 0:
                    print("Jog away from the zero end first.")
                    continue
                rng = abs(pos)
                pos = pos if pos > 0 else 0   # new zero = the end we are at
                m.save_state(position=pos, range=rng)
                print(f"range = {rng} steps; position now {pos}")
            elif cmd and cmd[0] in "+-" and cmd[1:].isdigit():
                n = min(int(cmd[1:]), MAX_JOG)
                forward = cmd[0] == "+"
                axis.set_direction(forward)
                try:
                    sent = axis.pulses(n)
                except KeyboardInterrupt:
                    m.save_state(position=None)
                    print("\nInterrupted: position unknown. Re-zero with 'z'.")
                    break
                pos += sent if forward else -sent
                m.save_state(position=pos)
                print(f"position {pos}")
            else:
                print("unknown command")
    finally:
        axis.close()


if __name__ == "__main__":
    main()