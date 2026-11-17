from enum import Enum


class S(str, Enum):
    BOOT = "BOOT"
    HOMING = "HOMING"
    IDLE = "IDLE"
    CUP_IN = "CUP_IN"
    READY = "READY"
    SCANNING = "SCANNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


TEXT = {
    S.BOOT: "Starting up",
    S.HOMING: "Homing",
    S.IDLE: "Place the bottle",
    S.CUP_IN: "Bottle in place - close the door",
    S.READY: "Ready - press Start",
    S.SCANNING: "Scanning",
    S.FINISHED: "Scan complete - remove the bottle",
    S.ERROR: "Error - acknowledge to re-home",
}


class Machine:
    def __init__(self, bus, cup, door, y, a, sequencer):
        self.bus, self.cup, self.door = bus, cup, door
        self.y, self.a, self.seq = y, a, sequencer
        self.state = None
        self._scan = None
        self._start = self._abort = self._ack = False
        self._set(S.BOOT)

    # --- commands from the UI (just set flags; tick() does the work) ---
    def cmd_start(self):
        self._start = True

    def cmd_abort(self):
        self._abort = True

    def cmd_ack(self):
        self._ack = True

    def _set(self, state, **info):
        self.state = state
        self.bus.publish("state", state=state.value, text=TEXT[state], **info)

    def _fail(self, reason):
        self.y.stop()
        self.a.stop()
        if self._scan:
            self._scan.close()
            self._scan = None
        self._set(S.ERROR, reason=reason)

    def tick(self):
        start, abort, ack = self._start, self._abort, self._ack
        self._start = self._abort = self._ack = False
        s = self.state

        if s == S.BOOT:
            self.y.home()
            self._set(S.HOMING)
        elif s == S.HOMING:
            if not self.y.busy:
                self._set(S.IDLE)
        elif s == S.IDLE:
            if self.cup.value:
                self._set(S.CUP_IN)
        elif s == S.CUP_IN:
            if not self.cup.value:
                self._set(S.IDLE)
            elif self.door.value:
                self._set(S.READY)
        elif s == S.READY:
            if not self.cup.value:
                self._set(S.IDLE)
            elif not self.door.value:
                self._set(S.CUP_IN)
            elif start:
                self._scan = self.seq.scan()
                self._set(S.SCANNING)
        elif s == S.SCANNING:
            if abort:
                self._fail("aborted by operator")
            elif not self.door.value:
                self._fail("door opened during scan")
            else:
                try:
                    next(self._scan)
                except StopIteration:
                    self._scan = None
                    self._set(S.FINISHED)
        elif s == S.FINISHED:
            if not self.cup.value:
                self._set(S.IDLE)
        elif s == S.ERROR:
            if ack:
                self.y.home()
                self._set(S.HOMING)
