class Sequencer:
    """Scan plan as a generator: each 'yield' lets the state machine check safety."""

    def __init__(self, bus, cfg, y, a, imaging):
        self.bus, self.cfg, self.y, self.a, self.imaging = bus, cfg, y, a, imaging

    def scan(self):
        s = self.cfg["scan"]
        y_speed = self.cfg["axes"]["y"]["speed_mm_s"]
        a_speed = self.cfg["axes"]["a"]["speed_deg_s"]
        ys = [s["y_start_mm"] + i * s["y_step_mm"] for i in range(s["y_positions"])]
        n = s["angles_per_rev"]
        angles = [i * 360.0 / n for i in range(n)]
        total, done = len(ys) * len(angles), 0

        for y in ys:
            self.y.move_abs(y, y_speed)
            while self.y.busy:
                yield
            for ang in angles:
                self.a.move_abs(ang, a_speed)
                while self.a.busy:
                    yield
                self.imaging.capture(y, ang)
                done += 1
                self.bus.publish("progress", percent=100.0 * done / total)
                yield

        self.y.move_abs(0.0, y_speed)
        self.a.move_abs(0.0, a_speed)
        while self.y.busy or self.a.busy:
            yield
