"""MarginX cup-presence detector using a two-wire FSR and MCP3008 CH0.

Electrical circuit: 3.3V -- FSR -- MCP3008 CH0 -- 10k ohm -- GND.
This is a presence detector, NOT a safety-rated interlock or a scale.
"""
import time
from gpiozero import MCP3008


class CupFSR:
    def __init__(
        self,
        channel=0,
        press_threshold=0.25,
        release_threshold=0.15,
        press_delay=0.20,
        release_delay=0.10,
    ):
        if not 0 <= release_threshold < press_threshold <= 1:
            raise ValueError("Require 0 <= release_threshold < press_threshold <= 1")
        self.adc = MCP3008(channel=channel, max_voltage=3.3)
        self.press_threshold = press_threshold
        self.release_threshold = release_threshold
        self.press_delay = press_delay
        self.release_delay = release_delay
        self._pressed = False
        self._pending = None
        self._pending_since = None
        self.last_value = 0.0

    @property
    def value(self):
        """Normalized analog reading, 0.0 to 1.0; increases when pressed."""
        self.last_value = float(self.adc.value)
        return self.last_value

    @property
    def is_pressed(self):
        """Hysteresis and time-qualified presence; sensor errors propagate."""
        v = self.value
        target = (v >= self.release_threshold) if self._pressed else (v >= self.press_threshold)
        if target == self._pressed:
            self._pending = None
            self._pending_since = None
            return self._pressed

        now = time.monotonic()
        if self._pending is not target:
            self._pending = target
            self._pending_since = now
            return self._pressed

        hold = self.press_delay if target else self.release_delay
        if now - self._pending_since >= hold:
            self._pressed = target
            self._pending = None
            self._pending_since = None
        return self._pressed

    def close(self):
        self.adc.close()
