import time


class SimAxis:
    """Simulated motor axis: moves in real time, so the state machine sees 'busy'."""

    def __init__(self, name, home_time=1.0):
        self.name = name
        self._home_time = home_time
        self._start = self._target = 0.0
        self._t0 = self._t1 = 0.0

    @property
    def position(self):
        now = time.monotonic()
        if now >= self._t1:
            return self._target
        f = (now - self._t0) / (self._t1 - self._t0)
        return self._start + (self._target - self._start) * f

    @property
    def busy(self):
        return time.monotonic() < self._t1

    def _go(self, target, duration):
        now = time.monotonic()
        self._start = self.position
        self._target = target
        self._t0, self._t1 = now, now + duration

    def move_abs(self, pos, speed):
        self._go(pos, abs(pos - self.position) / speed)

    def home(self):
        self._go(0.0, self._home_time)

    def stop(self):
        cur = self.position
        self._start = self._target = cur
        self._t1 = 0.0


class SimInput:
    """Simulated switch/sensor (door, bottle). Real version will read a GPIO pin."""

    def __init__(self, name, value=False):
        self.name = name
        self.value = value

    def toggle(self):
        self.value = not self.value


class SimImaging:
    def capture(self, y_mm, angle_deg):
        pass  # real version will call the imaging software
