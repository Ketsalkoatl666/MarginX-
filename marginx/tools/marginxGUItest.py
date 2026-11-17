
"""MarginX touchscreen GUI with zero verification.

Pages:
1. Login
2. Zero verification / calibration
3. Sample preparation
4. Scanning
5. Finished

Uses the existing motorlib.py.
"""

import argparse
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from gpiozero import Button
import motorlib as m


# GPIO
CUP_PIN = 16
COVER_PIN = 6

# Prototype credentials (not secure authentication)
USERNAME = "admin"
PASSWORD = "000000"

# Display
BG = "#101827"
PANEL = "#1E293B"
WHITE = "#FFFFFF"
MUTED = "#B6C3D6"
BLUE = "#3B82F6"
GREEN = "#86EFAC"
RED = "#FCA5A5"
GRAY = "#475569"

# Calibration
STEPS_PER_MM = 200.0  # Approximate value
MAX_CAL_OFFSET = 8000  # Steps, either direction
JOG_CHUNK = 100

# Scan progress allocations
STAGES = {
    "move1": (0, 10, "Moving to 1/3 of Range"),
    "rotate1": (10, 30, "Scanning at 1/3"),
    "move2": (30, 40, "Moving to 1/2 of Range"),
    "rotate2": (40, 60, "Scanning at 1/2"),
    "move3": (60, 70, "Moving to 2/3 of Range"),
    "rotate3": (70, 90, "Scanning at 2/3"),
    "home": (90, 99, "Returning to Zero"),
}


class MarginXApp:

    def __init__(self, root, args):
        self.root = root
        self.args = args

        root.title("MarginX Scanner")
        root.configure(bg=BG)
        root.minsize(760, 440)

        self.fullscreen = True
        root.attributes("-fullscreen", True)

        root.bind(
            "<Escape>",
            lambda e: self.set_fullscreen(False)
        )
        root.bind(
            "<F11>",
            lambda e: self.set_fullscreen(
                not self.fullscreen
            )
        )
        root.protocol(
            "WM_DELETE_WINDOW",
            self.request_exit
        )

        self.cup = Button(
            CUP_PIN,
            pull_up=True,
            bounce_time=0.05
        )

        self.cover = Button(
            COVER_PIN,
            pull_up=True,
            bounce_time=0.05
        )

        self.events = queue.Queue()
        self.abort = threading.Event()

        self.worker = None
        self.running = False
        self.closing = False
        self.page = ""
        self.frame = None
        self.keyboard = None

        self.user_var = tk.StringVar(
            value=USERNAME
        )
        self.password_var = tk.StringVar(
            value=PASSWORD
        )

        # Zero verification state
        self.zero_ready = False
        self.zero_error = ""
        self.cal_offset = 0
        self.cal_original_range = None
        self.calibration_active = False
        self.calibration_uncertain = False
        self.endpoint_confirmed = tk.BooleanVar(
            value=False
        )

        # Progress state
        self.status_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)
        self.percent_var = tk.StringVar(value="0%")

        self.phase = None
        self.phase_started = 0
        self.phase_start_pct = 0
        self.phase_end_pct = 0
        self.phase_expected = 1
        self.target_progress = 0
        self.display_progress = 0
        self.finish_pending = False

        self.show_login()
        root.after(33, self.ui_tick)

    # -------------------------
    # GENERAL UI
    # -------------------------

    def label(
        self, parent, text,
        size=16, color=WHITE,
        bold=False, **kwargs
    ):
        return tk.Label(
            parent,
            text=text,
            bg=BG,
            fg=color,
            font=(
                "Arial",
                size,
                "bold" if bold else "normal"
            ),
            **kwargs
        )

    def button(
        self, parent, text,
        command, color=BLUE,
        size=14
    ):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=WHITE,
            activebackground=color,
            activeforeground=WHITE,
            disabledforeground="#94A3B8",
            relief="flat",
            bd=0,
            font=("Arial", size, "bold"),
            padx=12,
            pady=9
        )

    def set_fullscreen(self, enabled):
        self.fullscreen = enabled
        self.root.attributes(
            "-fullscreen", enabled
        )
        if hasattr(self, "window_button"):
            try:
                self.window_button.config(
                    text=(
                        "WINDOW MODE"
                        if enabled else "FULLSCREEN"
                    )
                )
            except tk.TclError:
                pass

    def make_page(self, title):
        if self.keyboard is not None:
            self.keyboard.destroy()
            self.keyboard = None

        if self.frame is not None:
            self.frame.destroy()

        self.frame = tk.Frame(
            self.root,
            bg=BG
        )
        self.frame.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=10
        )

        header = tk.Frame(
            self.frame,
            bg=BG
        )
        header.pack(fill="x")

        self.label(
            header,
            "MarginX",
            21,
            BLUE,
            True
        ).pack(side="left")

        self.button(
            header,
            "EXIT",
            self.request_exit,
            "#9B3344",
            11
        ).pack(side="right", padx=5)

        self.window_button = self.button(
            header,
            "WINDOW MODE"
            if self.fullscreen else "FULLSCREEN",
            lambda: self.set_fullscreen(
                not self.fullscreen
            ),
            GRAY,
            11
        )
        self.window_button.pack(side="right")

        tk.Frame(
            self.frame,
            bg="#334155",
            height=2
        ).pack(fill="x", pady=8)

        self.label(
            self.frame,
            title,
            25,
            WHITE,
            True
        ).pack(pady=(4, 9))

        content = tk.Frame(
            self.frame, bg=BG
        )
        content.pack(
            fill="both", expand=True
        )

        return content

    # -------------------------
    # LOGIN
    # -------------------------

    def show_login(self):
        self.page = "login"

        body = self.make_page(
            "Welcome to MarginX"
        )

        form = tk.Frame(body, bg=BG)
        form.pack(expand=True)

        self.label(
            form, "Username", 14, MUTED
        ).pack(pady=(0, 4))

        user_entry = tk.Entry(
            form,
            textvariable=self.user_var,
            font=("Arial", 19),
            justify="center",
            width=22
        )
        user_entry.pack(ipady=5)

        user_entry.bind(
            "<ButtonRelease-1>",
            lambda e: self.open_keyboard(
                self.user_var, False
            )
        )

        self.label(
            form, "Password", 14, MUTED
        ).pack(pady=(12, 4))

        password_entry = tk.Entry(
            form,
            textvariable=self.password_var,
            font=("Arial", 19),
            show="*",
            justify="center",
            width=22
        )
        password_entry.pack(ipady=5)

        password_entry.bind(
            "<ButtonRelease-1>",
            lambda e: self.open_keyboard(
                self.password_var, True
            )
        )

        self.login_error = self.label(
            form, "", 12, RED
        )
        self.login_error.pack(pady=7)

        self.button(
            form,
            "LOGIN",
            self.login,
            BLUE,
            16
        ).pack(fill="x", pady=5)

    def open_keyboard(self, variable, secret):
        if self.page != "login":
            return

        if self.keyboard is not None:
            self.keyboard.destroy()

        self.keyboard = tk.Frame(
            self.root,
            bg=BG,
            highlightbackground=BLUE,
            highlightthickness=2
        )
        self.keyboard.place(
            relx=0,
            rely=0,
            relwidth=1,
            relheight=1
        )

        kb = self.keyboard

        self.label(
            kb,
            "Enter Password"
            if secret else "Enter Username",
            22,
            WHITE,
            True
        ).pack(pady=(8, 4))

        preview_var = tk.StringVar()

        def refresh():
            value = variable.get()
            preview_var.set(
                "●" * len(value)
                if secret else value
            )

        def insert(ch):
            if len(variable.get()) < 48:
                variable.set(variable.get() + ch)
                refresh()

        def backspace():
            variable.set(variable.get()[:-1])
            refresh()

        def clear():
            variable.set("")
            refresh()

        def done():
            if self.keyboard is not None:
                self.keyboard.destroy()
                self.keyboard = None

        refresh()

        tk.Label(
            kb,
            textvariable=preview_var,
            font=("Arial", 19),
            bg=PANEL,
            fg=WHITE
        ).pack(
            fill="x",
            padx=30,
            ipady=5
        )

        keys = tk.Frame(kb, bg=BG)
        keys.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=7
        )

        for key_row in [
            "1234567890",
            "QWERTYUIOP",
            "ASDFGHJKL",
            "ZXCVBNM"
        ]:
            line = tk.Frame(keys, bg=BG)
            line.pack(
                fill="both",
                expand=True,
                pady=2
            )

            for ch in key_row:
                self.button(
                    line,
                    ch,
                    lambda c=ch: insert(c),
                    "#334155",
                    12
                ).pack(
                    side="left",
                    fill="both",
                    expand=True,
                    padx=2
                )

        footer = tk.Frame(kb, bg=BG)
        footer.pack(
            fill="x",
            padx=12,
            pady=(0, 8)
        )

        for text, command in [
            ("SPACE", lambda: insert(" ")),
            ("BACKSPACE", backspace),
            ("CLEAR", clear),
            ("DONE", done)
        ]:
            self.button(
                footer,
                text,
                command,
                BLUE if text == "DONE" else GRAY,
                11
            ).pack(
                side="left",
                expand=True,
                fill="x",
                padx=2
            )

    def login(self):
        if (
            self.user_var.get() != USERNAME
            or self.password_var.get() != PASSWORD
        ):
            self.login_error.config(
                text="Invalid username or password"
            )
            return

        if self.running:
            return

        state = m.load_state()

        if (
            state.get("calibration_active")
            or state.get("calibration_in_motion")
        ):
            self.show_error(
                "A previous calibration is pending. "
                "Use the calibration recovery utility "
                "before running MarginX."
            )
            return

        if not self.valid_position():
            self.show_error(
                "Saved position is invalid. "
                "Manual position recovery is required."
            )
            return

        self.begin_zero_verification()

    # -------------------------
    # CALIBRATION / ZERO PAGE
    # -------------------------

    def valid_position(self):
        st = m.load_state()
        pos = st.get("position")
        rng = st.get("range")

        return (
            type(pos) is int
            and type(rng) is int
            and rng > 0
            and 0 <= pos <= rng
            and st.get("position_valid") is not False
            and not st.get("calibration_active")
            and not st.get("calibration_in_motion")
        )

    def begin_zero_verification(self):
        self.page = "zero"
        self.zero_ready = False
        self.zero_error = ""
        self.cal_offset = 0
        self.calibration_active = False
        self.calibration_uncertain = False
        self.endpoint_confirmed.set(False)

        state = m.load_state()
        self.cal_original_range = state["range"]

        self.show_zero_page()
        self.start_initial_home()

    def show_zero_page(self):
        self.page = "zero"
        body = self.make_page(
            "Verify Zero Position"
        )

        self.zero_message = self.label(
            body,
            "Returning to Saved Zero",
            18,
            WHITE,
            True
        )
        self.zero_message.pack(pady=5)

        self.label(
            body,
            "Remove the cup and keep clear of the stage "
            "before adjusting its position.",
            12,
            MUTED,
            wraplength=680
        ).pack(pady=4)

        self.offset_label = self.label(
            body,
            "Calibration offset: 0 steps",
            15,
            BLUE,
            True
        )
        self.offset_label.pack(pady=6)

        jog_frame = tk.Frame(body, bg=BG)
        jog_frame.pack(fill="x", pady=7)

        commands = [
            ("RIGHT 1 mm", -200),
            ("LEFT 1 mm", 200),
            ("RIGHT 5 mm", -1000),
            ("LEFT 5 mm", 1000)
        ]

        self.jog_buttons = []

        for index, (name, delta) in enumerate(commands):
            btn = self.button(
                jog_frame,
                name,
                lambda d=delta: self.request_jog(d),
                GRAY,
                13
            )
            btn.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=5,
                pady=4
            )
            self.jog_buttons.append(btn)

        jog_frame.columnconfigure(0, weight=1)
        jog_frame.columnconfigure(1, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "MX.Horizontal.TProgressbar",
            troughcolor=PANEL,
            background=BLUE,
            thickness=18
        )

        self.jog_progress = tk.DoubleVar(value=0)

        ttk.Progressbar(
            body,
            variable=self.jog_progress,
            maximum=100,
            style="MX.Horizontal.TProgressbar"
        ).pack(
            fill="x",
            padx=10,
            pady=(8, 3)
        )

        self.jog_percent = self.label(
            body, "0%", 12, MUTED
        )
        self.jog_percent.pack()

        self.zero_detail = self.label(
            body, "", 12, MUTED,
            wraplength=680,
            justify="center"
        )
        self.zero_detail.pack(pady=5)

        self.continue_button = self.button(
            body,
            "ZERO IS CORRECT / CONTINUE",
            self.confirm_existing_zero,
            BLUE,
            14
        )
        self.continue_button.pack(
            fill="x",
            padx=10,
            pady=(7, 4)
        )

        self.endpoint_check = tk.Checkbutton(
            body,
            text=(
                "I verified the original left endpoint "
                "is still the intended safe range endpoint"
            ),
            variable=self.endpoint_confirmed,
            bg=BG,
            fg=MUTED,
            selectcolor=PANEL,
            activebackground=BG,
            activeforeground=WHITE,
            font=("Arial", 11),
            wraplength=680
        )
        self.endpoint_check.pack(pady=5)

        self.save_zero_button = self.button(
            body,
            "SET CURRENT POSITION AS NEW ZERO",
            self.save_new_zero,
            GREEN,
            13
        )
        self.save_zero_button.pack(
            fill="x",
            padx=10,
            pady=4
        )

        self.refresh_zero_page()

    def refresh_zero_page(self):
        if self.page != "zero":
            return

        busy = self.running
        available = (
            self.zero_ready
            and not busy
            and not self.calibration_uncertain
        )

        for btn in self.jog_buttons:
            btn.config(
                state="normal" if available else "disabled"
            )

        self.continue_button.config(
            state=(
                "normal"
                if available
                and not self.calibration_active
                else "disabled"
            )
        )

        self.save_zero_button.config(
            state=(
                "normal"
                if available
                and self.calibration_active
                and self.cal_offset != 0
                and self.endpoint_confirmed.get()
                else "disabled"
            ),
            fg="#101827"
        )

        self.offset_label.config(
            text=(
                f"Calibration offset: "
                f"{self.cal_offset:+d} steps "
                f"(~{self.cal_offset / STEPS_PER_MM:+.1f} mm)"
            )
        )

        if self.calibration_uncertain:
            message = (
                "Position uncertain. Do not scan. "
                "Recover physical position manually."
            )
            color = RED
        elif busy:
            message = (
                "Moving stage — please keep clear"
            )
            color = MUTED
        elif self.calibration_active:
            message = (
                "Adjustment pending — save new zero "
                "after confirming the endpoint."
            )
            color = BLUE
        elif self.zero_ready:
            message = (
                "Stage at Saved Zero — Verify Position"
            )
            color = GREEN
        else:
            message = "Returning to Saved Zero"
            color = MUTED

        self.zero_message.config(
            text=message,
            fg=color
        )

        if self.zero_error:
            self.zero_detail.config(
                text=self.zero_error,
                fg=RED
            )
        else:
            self.zero_detail.config(
                text=(
                    "Positive steps move LEFT; "
                    "negative steps move RIGHT. "
                    "Jog only with verified clearance."
                ),
                fg=MUTED
            )

    def start_initial_home(self):
        if self.running:
            return

        self.running = True
        self.abort.clear()

        self.worker = threading.Thread(
            target=self.initial_home_worker,
            daemon=True
        )
        self.worker.start()

    def initial_home_worker(self):
        axis = None
        error = None

        try:
            axis = m.Axis(
                m.SHIFT_STEP_PIN,
                m.SHIFT_DIR_PIN,
                self.args.shift_period
            )

            result = m.go_to_zero(
                axis, self.abort
            )

            if (
                result is False
                or self.abort.is_set()
                or m.load_state().get("position") != 0
            ):
                raise RuntimeError(
                    "Return to saved zero was interrupted."
                )

        except BaseException as exc:
            error = str(exc) or type(exc).__name__

        finally:
            if axis is not None:
                try:
                    axis.close()
                except Exception as exc:
                    error = error or str(exc)

            self.events.put(
                ("initial_home_done", error)
            )

    def request_jog(self, delta):
        if (
            self.running
            or not self.zero_ready
            or self.calibration_uncertain
        ):
            return

        if not -MAX_CAL_OFFSET <= (
            self.cal_offset + delta
        ) <= MAX_CAL_OFFSET:
            self.zero_error = (
                "Calibration offset exceeds "
                "the permitted software limit."
            )
            self.refresh_zero_page()
            return

        # Keep the proposed range positive.
        new_range = (
            self.cal_original_range
            - (self.cal_offset + delta)
        )

        if new_range <= 0:
            self.zero_error = (
                "Proposed calibration range invalid."
            )
            self.refresh_zero_page()
            return

        self.zero_error = ""
        self.jog_progress.set(0)
        self.jog_percent.config(text="0%")

        if not self.calibration_active:
            m.save_state(
                position=None,
                calibration_active=True,
                calibration_in_motion=False,
                calibration_offset_steps=0,
                calibration_original_range=(
                    self.cal_original_range
                )
            )
            self.calibration_active = True

        self.running = True
        self.abort.clear()

        self.worker = threading.Thread(
            target=self.jog_worker,
            args=(delta,),
            daemon=True
        )
        self.worker.start()

        self.refresh_zero_page()

    def jog_worker(self, delta):
        axis = None
        error = None
        sent_total = 0
        target_count = abs(delta)

        try:
            m.save_state(
                calibration_in_motion=True
            )

            axis = m.Axis(
                m.SHIFT_STEP_PIN,
                m.SHIFT_DIR_PIN,
                self.args.cal_period
            )

            axis.set_direction(delta > 0)

            while sent_total < target_count:
                if self.abort.is_set():
                    raise RuntimeError(
                        "Jog interrupted. Position is uncertain."
                    )

                count = min(
                    JOG_CHUNK,
                    target_count - sent_total
                )

                sent = axis.pulses(
                    count, self.abort
                )
                sent_total += sent

                self.events.put(
                    (
                        "jog_progress",
                        100 * sent_total / target_count
                    )
                )

                if sent != count:
                    raise RuntimeError(
                        "Incomplete jog. Position is uncertain."
                    )

            if self.abort.is_set():
                raise RuntimeError(
                    "Jog interrupted. Position is uncertain."
                )

            new_offset = self.cal_offset + delta

            m.save_state(
                calibration_offset_steps=new_offset,
                calibration_in_motion=False
            )

        except BaseException as exc:
            error = str(exc) or type(exc).__name__

        finally:
            if axis is not None:
                try:
                    axis.close()
                except Exception as exc:
                    error = error or str(exc)

            self.events.put(
                ("jog_done", (delta, error))
            )

    def confirm_existing_zero(self):
        if (
            self.running
            or not self.zero_ready
            or self.calibration_active
        ):
            return

        self.show_preparation()

    def save_new_zero(self):
        if (
            self.running
            or not self.zero_ready
            or self.calibration_uncertain
            or not self.calibration_active
            or self.cal_offset == 0
            or not self.endpoint_confirmed.get()
        ):
            return

        new_range = (
            self.cal_original_range
            - self.cal_offset
        )

        if new_range <= 0:
            return

        # The offset is signed:
        # Negative offset = toward the motor (right).
        # Preserves the old positive-direction endpoint.
        m.save_state(
            position=0,
            range=new_range,
            position_valid=True,
            calibration_active=False,
            calibration_in_motion=False,
            calibration_offset_steps=0,
            calibration_original_range=None
        )

        self.cal_offset = 0
        self.calibration_active = False
        self.zero_ready = True

        self.show_preparation()

    # -------------------------
    # SAMPLE PREPARATION
    # -------------------------

    def sensors_ready(self):
        return (
            self.cup.is_pressed
            and self.cover.is_pressed
        )

    def show_preparation(self):
        self.page = "prepare"
        body = self.make_page(
            "Sample Preparation"
        )

        self.prep_message = self.label(
            body,
            "Stage Ready, Insert Cup",
            24,
            WHITE,
            True
        )
        self.prep_message.pack(pady=15)

        panel = tk.Frame(
            body, bg=PANEL
        )
        panel.pack(
            fill="x",
            padx=20,
            pady=10
        )

        self.cup_label = tk.Label(
            panel,
            bg=PANEL,
            fg=WHITE,
            font=("Arial", 18)
        )
        self.cup_label.pack(pady=12)

        self.cover_label = tk.Label(
            panel,
            bg=PANEL,
            fg=WHITE,
            font=("Arial", 18)
        )
        self.cover_label.pack(pady=12)

        self.start_button = self.button(
            body,
            "START SCANNING",
            self.start_scan,
            BLUE,
            17
        )
        self.start_button.pack(
            fill="x",
            padx=20,
            pady=18
        )

        self.prep_detail = self.label(
            body,
            "",
            12,
            MUTED
        )
        self.prep_detail.pack()

        self.update_preparation()

    def update_preparation(self):
        if self.page != "prepare":
            return

        cup_ok = self.cup.is_pressed
        cover_ok = self.cover.is_pressed

        self.cup_label.config(
            text=(
                "Cup: Inserted"
                if cup_ok else "Cup: Waiting"
            ),
            fg=GREEN if cup_ok else WHITE
        )

        self.cover_label.config(
            text=(
                "Cover: Closed"
                if cover_ok else "Cover: Open"
            ),
            fg=GREEN if cover_ok else WHITE
        )

        if not cup_ok:
            message = "Stage Ready, Insert Cup"
        elif not cover_ok:
            message = "Cup Inserted"
        else:
            message = "Ready to Scan"

        self.prep_message.config(text=message)

        ready = (
            cup_ok
            and cover_ok
            and not self.running
            and self.valid_position()
            and m.load_state().get("position") == 0
        )

        self.start_button.config(
            state="normal" if ready else "disabled"
        )

        self.prep_detail.config(
            text=(
                "Both switches must be closed."
                if self.valid_position()
                else "Position invalid — do not scan."
            )
        )

    # -------------------------
    # SCANNING
    # -------------------------

    def show_scanning(self):
        self.page = "scan"
        body = self.make_page("Scanning")

        self.label(
            body,
            "Keep the cup inserted and cover closed.",
            14,
            MUTED
        ).pack(pady=12)

        self.scan_status = tk.Label(
            body,
            textvariable=self.status_var,
            font=("Arial", 20, "bold"),
            fg=WHITE,
            bg=BG
        )
        self.scan_status.pack(pady=18)

        ttk.Progressbar(
            body,
            variable=self.progress_var,
            maximum=100,
            style="MX.Horizontal.TProgressbar"
        ).pack(
            fill="x",
            padx=20,
            pady=15
        )

        self.label(
            body,
            "",
            22,
            WHITE
        ).destroy()

        tk.Label(
            body,
            textvariable=self.percent_var,
            bg=BG,
            fg=WHITE,
            font=("Arial", 23, "bold")
        ).pack(pady=10)

        self.label(
            body,
            "1/3  →  1/2  →  2/3  →  ZERO  →  FINISHED",
            13,
            MUTED
        ).pack(pady=10)

    def start_scan(self):
        if (
            self.running
            or not self.sensors_ready()
            or not self.valid_position()
            or m.load_state().get("position") != 0
        ):
            return

        self.running = True
        self.zero_ready = False
        self.abort.clear()
        self.finish_pending = False

        self.phase = None
        self.target_progress = 0
        self.display_progress = 0
        self.progress_var.set(0)
        self.percent_var.set("0%")
        self.status_var.set("Initializing Scan")

        self.show_scanning()

        self.worker = threading.Thread(
            target=self.scan_worker,
            daemon=True
        )
        self.worker.start()

    def move_scan(self, axis, name, target):
        if self.abort.is_set():
            raise RuntimeError("Scan interrupted.")

        pos = m.load_state().get("position")
        if type(pos) is not int:
            raise RuntimeError("Shift position unknown.")

        steps = abs(target - pos)

        self.events.put(
            ("phase", (name, steps))
        )

        result = m.move_shift_to(
            axis, target, self.abort
        )

        if (
            result is False
            or self.abort.is_set()
            or m.load_state().get("position") != target
        ):
            raise RuntimeError(
                "Shift movement interrupted."
            )

        self.events.put(
            ("phase_done", name)
        )

    def rotate_scan(self, axis, name):
        self.events.put(
            ("phase", (name, 0))
        )

        axis.set_direction(True)
        elapsed = 0.0

        while elapsed < self.args.seconds:
            if self.abort.is_set():
                raise RuntimeError(
                    "Rotation interrupted."
                )

            duration = min(
                0.1,
                self.args.seconds - elapsed
            )

            start = time.monotonic()

            axis.run_for(
                duration, self.abort
            )

            if self.abort.is_set():
                raise RuntimeError(
                    "Rotation interrupted."
                )

            elapsed += (
                time.monotonic() - start
            )

            self.events.put(
                ("rotation_progress", (
                    name,
                    min(elapsed, self.args.seconds)
                ))
            )

        self.events.put(
            ("phase_done", name)
        )

    def scan_worker(self):
        shift = None
        rotation = None
        error = None

        try:
            state = m.load_state()
            rng = state["range"]

            positions = [
                rng // 3,
                rng // 2,
                (2 * rng) // 3
            ]

            if not (
                0 < positions[0]
                < positions[1]
                < positions[2]
                <= rng
            ):
                raise RuntimeError(
                    "Calibrated range is too small."
                )

            shift = m.Axis(
                m.SHIFT_STEP_PIN,
                m.SHIFT_DIR_PIN,
                self.args.shift_period
            )

            rotation = m.Axis(
                m.ROT_STEP_PIN,
                m.ROT_DIR_PIN,
                self.args.rot_period
            )

            for i, target in enumerate(
                positions, start=1
            ):
                self.move_scan(
                    shift,
                    f"move{i}",
                    target
                )

                self.rotate_scan(
                    rotation,
                    f"rotate{i}"
                )

            self.move_scan(
                shift,
                "home",
                0
            )

            if self.abort.is_set():
                raise RuntimeError(
                    "Scan interrupted."
                )

        except BaseException as exc:
            error = str(exc) or type(exc).__name__

        finally:
            for axis in (rotation, shift):
                if axis is not None:
                    try:
                        axis.close()
                    except Exception as exc:
                        error = error or str(exc)

            if self.abort.is_set():
                error = error or "Scan interrupted."

            self.events.put(
                ("scan_done", error)
            )

    def begin_phase(self, name, steps):
        self.phase = name
        self.phase_started = time.monotonic()

        start, end, message = STAGES[name]

        self.phase_start_pct = start
        self.phase_end_pct = end
        self.status_var.set(message)

        self.phase_expected = max(
            0.5,
            steps * self.args.shift_period * 1.6
        )
        self.target_progress = max(
            self.target_progress,
            start
        )

    def animate_scan_progress(self):
        if self.page != "scan":
            return

        if self.phase in (
            "move1", "move2", "move3", "home"
        ):
            elapsed = (
                time.monotonic()
                - self.phase_started
            )

            fraction = (
                1.0 - math.exp(
                    -elapsed / self.phase_expected
                )
            )

            estimate = (
                self.phase_start_pct
                + (
                    self.phase_end_pct
                    - self.phase_start_pct
                    - 0.5
                ) * fraction
            )

            self.target_progress = max(
                self.target_progress,
                estimate
            )

        diff = (
            self.target_progress
            - self.display_progress
        )

        if diff > 0:
            self.display_progress += min(
                diff,
                max(diff * 0.22, 0.06)
            )

        self.progress_var.set(
            self.display_progress
        )
        self.percent_var.set(
            f"{self.display_progress:.0f}%"
        )

        if (
            self.finish_pending
            and self.display_progress >= 99.6
        ):
            self.finish_pending = False
            self.display_progress = 100
            self.show_finished()

    # -------------------------
    # FINISHED
    # -------------------------

    def show_finished(self):
        self.page = "finished"
        body = self.make_page("Finished")

        self.label(
            body,
            "Scanning completed successfully.",
            19,
            GREEN,
            True
        ).pack(pady=30)

        self.button(
            body,
            "CHECK THE REPORT",
            self.check_report,
            BLUE,
            16
        ).pack(
            fill="x",
            padx=40,
            pady=10
        )

        self.button(
            body,
            "RETURN TO LOGIN",
            self.show_login,
            GRAY,
            16
        ).pack(
            fill="x",
            padx=40,
            pady=10
        )

    def check_report(self):
        popup = tk.Toplevel(self.root)
        popup.title("MarginX Report")
        popup.geometry("380x160")
        popup.configure(bg=BG)

        self.label(
            popup,
            "Report feature coming soon",
            15
        ).pack(pady=20)

        self.button(
            popup,
            "OK",
            popup.destroy
        ).pack()

    # -------------------------
    # ERRORS / EVENTS
    # -------------------------

    def show_error(self, message):
        self.page = "error"
        body = self.make_page(
            "Operation Interrupted"
        )

        self.label(
            body,
            message,
            16,
            RED,
            wraplength=680,
            justify="center"
        ).pack(pady=30)

        self.button(
            body,
            "RETURN TO LOGIN",
            self.show_login,
            GRAY,
            15
        ).pack(pady=15)

    def ui_tick(self):
        if self.closing:
            return

        # Software switch interlock
        if (
            self.running
            and self.page == "scan"
        ):
            try:
                if not self.sensors_ready():
                    self.abort.set()
            except Exception:
                self.abort.set()

        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break

            if kind == "initial_home_done":
                self.running = False

                if data or self.abort.is_set():
                    self.zero_ready = False
                    self.show_error(
                        data or "Return to zero interrupted."
                    )
                else:
                    self.zero_ready = True
                    self.refresh_zero_page()

            elif kind == "jog_progress":
                if self.page == "zero":
                    self.jog_progress.set(data)
                    self.jog_percent.config(
                        text=f"{data:.0f}%"
                    )

            elif kind == "jog_done":
                delta, error = data
                self.running = False

                if error or self.abort.is_set():
                    self.calibration_uncertain = True
                    self.zero_ready = False
                    self.zero_error = (
                        error or "Jog interrupted."
                    )
                else:
                    self.cal_offset += delta
                    self.zero_error = ""
                    self.jog_progress.set(100)
                    self.jog_percent.config(text="100%")

                    # If back at the old zero, clear
                    # the pending calibration safely.
                    if self.cal_offset == 0:
                        m.save_state(
                            position=0,
                            calibration_active=False,
                            calibration_in_motion=False,
                            calibration_offset_steps=0,
                            calibration_original_range=None
                        )
                        self.calibration_active = False

                self.refresh_zero_page()

            elif kind == "phase":
                self.begin_phase(*data)

            elif kind == "phase_done":
                self.target_progress = max(
                    self.target_progress,
                    STAGES[data][1]
                )
                if self.phase == data:
                    self.phase = None

            elif kind == "rotation_progress":
                stage, elapsed = data
                lo, hi, _ = STAGES[stage]

                fraction = (
                    elapsed / self.args.seconds
                )

                self.target_progress = max(
                    self.target_progress,
                    lo + (hi - lo) * fraction
                )

            elif kind == "scan_done":
                self.running = False

                if data or self.abort.is_set():
                    self.finish_pending = False
                    self.show_error(
                        data or "Scan interrupted."
                    )
                else:
                    self.phase = None
                    self.status_var.set(
                        "Scanning Finished - At Zero"
                    )
                    self.target_progress = 100
                    self.finish_pending = True

        if self.page == "zero":
            self.refresh_zero_page()

        if self.page == "prepare":
            self.update_preparation()

        if self.page == "scan":
            self.animate_scan_progress()

        self.root.after(
            33,
            self.ui_tick
        )

    # -------------------------
    # EXIT
    # -------------------------

    def request_exit(self):
        if self.closing:
            return

        if self.running:
            self.abort.set()

        self.closing = True
        self.wait_for_worker()

    def wait_for_worker(self):
        if (
            self.worker is not None
            and self.worker.is_alive()
        ):
            self.root.after(
                100,
                self.wait_for_worker
            )
            return

        self.cup.close()
        self.cover.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--seconds",
        type=float,
        default=30.0
    )

    parser.add_argument(
        "--shift-period",
        type=float,
        default=0.001
    )

    parser.add_argument(
        "--rot-period",
        type=float,
        default=0.020
    )

    parser.add_argument(
        "--cal-period",
        type=float,
        default=0.004
    )

    args = parser.parse_args()

    if (
        not math.isfinite(args.seconds)
        or not 0 < args.seconds <= 600
    ):
        parser.error(
            "Scanning seconds must be between 0 and 600."
        )

    for name in [
        "shift_period",
        "rot_period",
        "cal_period"
    ]:
        value = getattr(args, name)

        if (
            not math.isfinite(value)
            or value < m.MIN_PERIOD_S
        ):
            parser.error(
                f"Invalid {name}"
            )

    root = tk.Tk()
    MarginXApp(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
