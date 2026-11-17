"""MarginX: test FSR before enabling motor scanning.
Run from ~/marginx/tools/ using ~/marginx/.venv/bin/python3 test_fsr.py
"""
import time
from fsr_sensor import CupFSR


def main():
    fsr = CupFSR()
    try:
        print("FSR test: remove cup, then insert cup. Ctrl+C to quit.")
        while True:
            status = fsr.is_pressed
            print(f"FSR={fsr.last_value:.3f}  cup={'INSERTED' if status else 'WAITING'}")
            time.sleep(0.10)
    except KeyboardInterrupt:
        pass
    finally:
        fsr.close()


if __name__ == '__main__':
    main()
