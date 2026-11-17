"""Five centered, touchscreen-friendly MarginX pages (Tkinter main thread only)."""

import math
import time
import tkinter as tk
from tkinter import ttk, messagebox

from backup.marginx_control import Scanner, STAGES, STEPS_PER_MM

BG = "#0B1220"
CARD = "#182437"
EDGE = "#304159"
TEXT = "#F6F9FF"
MUTED = "#A8B8CC"
BLUE = "#4A91FF"
GREEN = "#70D3A3"
RED = "#FF8799"
SECONDARY = "#35465E"


class MarginXApp:
    def __init__(self, root, args):
        self.root = root
        self.scanner = Scanner(args)
        self.root.title("MarginX Scanner")
        self.root.configure(bg=BG)
        self.root.minsize(760, 440)
        # Dedicated touchscreen appliance: stay fullscreen until EXIT is pressed.
        self.root.attributes("-fullscreen", True)
        self.root.protocol("WM_DELETE_WINDOW", self.request_exit)
        self.root.bind("<ButtonRelease-1>", self._dismiss_keyboard_on_background, add="+")

        self.page = None
        self.layout = None
        self.touch_keyboard = None
        self.active_login_entry = None
        self.closing = False
        self.zero_error = ""
        self.username = tk.StringVar(value="admin")
        self.password = tk.StringVar(value="000000")
        self.progress = tk.DoubleVar(value=0)
        self.display_progress = 0.0
        self.target_progress = 0.0
        self.phase = None
        self.phase_start = 0.0
        self.phase_lo = self.phase_hi = 0.0
        self.phase_expected = 1.0
        self.finish_pending = False

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("MX.Horizontal.TProgressbar", troughcolor=EDGE,
                        background=BLUE, borderwidth=0, thickness=17)
        self.show_login()
        self.root.after(40, self.tick)

    # ---------- Reusable visual components ----------
    def text(self, parent, value, size=15, color=TEXT, bold=False, **options):
        return tk.Label(parent, text=value, bg=parent.cget("bg"), fg=color,
                        font=("Arial", size, "bold" if bold else "normal"),
                        **options)

    def button(self, parent, value, command, primary=True, size=14):
        color = BLUE if primary else SECONDARY
        return tk.Button(parent, text=value, command=command, bg=color,
                         fg=TEXT, activebackground=color, activeforeground=TEXT,
                         disabledforeground="#8A9BB1", relief="flat", bd=0,
                         font=("Arial", size, "bold"), padx=14, pady=9,
                         cursor="hand2")

    def page_base(self, page, title, subtitle=""):
        if page != "login":
            self.close_system_keyboard()
        self.page = page
        if self.layout is not None:
            self.layout.destroy()
        self.layout = tk.Frame(self.root, bg=BG)
        self.layout.pack(fill="both", expand=True)

        top = tk.Frame(self.layout, bg=BG)
        top.pack(fill="x", padx=26, pady=(14, 4))
        self.text(top, "◈  MarginX", 19, BLUE, True).pack(side="left")
        self.button(top, "EXIT", self.request_exit, False, 10).pack(side="right", padx=(8, 0))
        tk.Frame(self.layout, bg=EDGE, height=1).pack(fill="x", padx=26, pady=(5, 0))

        # Center the entire task area regardless of fullscreen dimensions.
        outer = tk.Frame(self.layout, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=(6, 13))
        card = tk.Frame(outer, bg=CARD, highlightbackground=EDGE, highlightthickness=1)
        card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.88, relheight=0.98)
        self.card = card
        self.page_title_widget = self.text(card, title, 25, TEXT, True)
        self.page_title_widget.pack(pady=(13, 3))
        self.page_subtitle_widget = None
        if subtitle:
            self.page_subtitle_widget = self.text(card, subtitle, 12, MUTED,
                                                  wraplength=680, justify="center")
            self.page_subtitle_widget.pack(pady=(0, 7))
        content = tk.Frame(card, bg=CARD)
        self.page_content = content
        content.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        return content

    # ---------- Login and built-in half-screen touch keyboard ----------
    def show_login(self):
        self.close_system_keyboard()
        body = self.page_base("login", "Welcome to MarginX", "Sign in to prepare the scanner")

        # ONE pair of input boxes. The keyboard never creates duplicates.
        form = tk.Frame(body, bg=CARD)
        form.pack(expand=True, fill="x", padx=35)
        inputs = tk.Frame(form, bg=CARD)
        inputs.pack(fill="x", pady=(0, 7))
        inputs.columnconfigure(0, weight=1)
        inputs.columnconfigure(1, weight=1)

        for column, (name, variable, masked) in enumerate((
            ("USERNAME", self.username, False),
            ("PASSWORD", self.password, True),
        )):
            cell = tk.Frame(inputs, bg=CARD)
            cell.grid(row=0, column=column, sticky="ew", padx=8)
            self.text(cell, name, 12, MUTED, True).pack(anchor="w", pady=(0, 3))
            entry = tk.Entry(cell, textvariable=variable, font=("Arial", 19),
                             show="*" if masked else "", justify="center")
            entry.pack(fill="x", ipady=5)
            entry.bind("<ButtonRelease-1>",
                       lambda event, widget=entry: self.open_touch_keyboard(widget))
            if masked:
                self.password_entry = entry
            else:
                self.username_entry = entry

        self.login_error = self.text(form, "", 11, RED)
        self.login_error.pack(pady=(0, 2))
        self.button(form, "LOGIN", self.login, size=15).pack(fill="x", padx=8)
        self.keyboard_hint = self.text(form, "Tap a field to type · tap outside to hide", 10, MUTED)
        self.keyboard_hint.pack(pady=(4, 0))

    def open_touch_keyboard(self, entry):
        """Keep fullscreen; show keyboard over the lower 50% of the display."""
        if self.page != "login" or self.closing:
            return
        self.active_login_entry = entry
        if self.touch_keyboard is not None:
            entry.focus_set()
            return

        # Move the SAME inputs into the visible upper region, without cloning them.
        self.card.place_configure(rely=0.21, relheight=0.40)
        self.page_title_widget.pack_forget()
        if self.page_subtitle_widget is not None:
            self.page_subtitle_widget.pack_forget()
        self.page_content.pack_configure(pady=(3, 3))
        keyboard = tk.Frame(self.root, bg=EDGE, highlightbackground=BLUE,
                            highlightthickness=2)
        self.touch_keyboard = keyboard
        keyboard.place(relx=0, rely=0.50, relwidth=1, relheight=0.50)
        keyboard.lift()

        rows = ("1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")
        for characters in rows:
            row = tk.Frame(keyboard, bg=EDGE)
            row.pack(fill="both", expand=True, padx=8, pady=2)
            for char in characters:
                key = self.button(row, char,
                                  lambda character=char: self.type_character(character),
                                  False, 15)
                key.configure(padx=1, pady=1)
                key.pack(side="left", fill="both", expand=True, padx=2)

        actions = tk.Frame(keyboard, bg=EDGE)
        actions.pack(fill="both", expand=True, padx=8, pady=(2, 5))
        for label, action, weight in (
            ("SPACE", lambda: self.type_character(" "), 2),
            ("BACKSPACE", self.keyboard_backspace, 3),
            ("CLEAR", self.keyboard_clear, 2),
            ("DONE / HIDE", self.close_system_keyboard, 3),
        ):
            key = self.button(actions, label, action, label == "DONE / HIDE", 12)
            key.configure(padx=1, pady=1)
            key.pack(side="left", fill="both", expand=weight, padx=2)
        entry.focus_set()

    def type_character(self, char):
        entry = self.active_login_entry
        if entry is None or not entry.winfo_exists():
            return
        if len(entry.get()) >= 48:
            return
        entry.insert(tk.INSERT, char)
        entry.focus_set()

    def keyboard_backspace(self):
        entry = self.active_login_entry
        if entry is None or not entry.winfo_exists():
            return
        try:
            first = entry.index("sel.first")
            last = entry.index("sel.last")
        except tk.TclError:
            first = last = entry.index(tk.INSERT)
        if first != last:
            entry.delete(first, last)
        elif first > 0:
            entry.delete(first - 1)
        entry.focus_set()

    def keyboard_clear(self):
        entry = self.active_login_entry
        if entry is not None and entry.winfo_exists():
            entry.delete(0, tk.END)
            entry.focus_set()

    def _dismiss_keyboard_on_background(self, event):
        """Close on an exposed non-input region, but not on keyboard keys."""
        if self.page != "login" or self.touch_keyboard is None:
            return
        node = event.widget
        while node is not None:
            if node is self.touch_keyboard:
                return
            if node in (self.username_entry, self.password_entry):
                return
            node = getattr(node, "master", None)
        self.close_system_keyboard()

    def close_system_keyboard(self):
        """Compatibility name; closes the built-in keyboard only."""
        if self.touch_keyboard is not None:
            self.touch_keyboard.destroy()
            self.touch_keyboard = None
        self.active_login_entry = None
        if self.page == "login" and getattr(self, "card", None) is not None:
            try:
                if self.card.winfo_exists():
                    self.card.place_configure(rely=0.5, relheight=0.98)
                    self.page_title_widget.pack(before=self.page_content, pady=(13, 3))
                    if self.page_subtitle_widget is not None:
                        self.page_subtitle_widget.pack(before=self.page_content, pady=(0, 7))
                    self.page_content.pack_configure(pady=(0, 12))
            except tk.TclError:
                pass

    def login(self):
        if self.username.get() != "admin" or self.password.get() != "000000":
            self.close_system_keyboard()
            self.login_error.config(text="Invalid username or password")
            return
        if self.scanner.running:
            return
        if not self.scanner.valid_position():
            self.show_error("Saved position invalid or calibration pending. Recover the physical position before scanning.")
            return
        self.close_system_keyboard()
        self.zero_error = ""
        self.show_zero()
        try:
            self.scanner.start_home()
        except Exception as exc:
            self.show_error(str(exc))

    # ---------- Zero calibration ----------
    def show_zero(self):
        body = self.page_base("zero", "Verify Zero Position")
        # The screen is designed for an 800 x 480 touchscreen:
        # two large rows of jog controls in the middle, confirmation below.
        self.zero_status = self.text(body, "Returning to saved zero...", 17, TEXT, True)
        self.zero_status.pack(pady=(0, 1))
        self.offset_status = self.text(body, "Offset: 0 steps", 14, BLUE, True)
        self.offset_status.pack(pady=(0, 4))

        center = tk.Frame(body, bg=CARD)
        center.pack(fill="x", expand=True, padx=12)
        grid = tk.Frame(center, bg=CARD)
        grid.pack(fill="x", pady=(2, 1))
        self.jog_buttons = []
        for index, (name, delta) in enumerate((
            ("◀  LEFT 1 mm", 200), ("RIGHT 1 mm  ▶", -200),
            ("◀  LEFT 5 mm", 1000), ("RIGHT 5 mm  ▶", -1000),
        )):
            b = self.button(grid, name, lambda n=delta: self.jog(n), False, 15)
            b.configure(pady=10, padx=4)
            b.grid(row=index // 2, column=index % 2, sticky="nsew", padx=5, pady=3)
            self.jog_buttons.append(b)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        self.jog_value = tk.DoubleVar(value=0)
        ttk.Progressbar(center, variable=self.jog_value, maximum=100,
                        style="MX.Horizontal.TProgressbar").pack(fill="x", padx=5, pady=(5, 1))
        self.jog_text = self.text(center, "Jog progress: 0%", 12, MUTED)
        self.jog_text.pack(pady=(0, 2))

        self.zero_detail = self.text(body, "", 12, MUTED, wraplength=650,
                                     justify="center")
        self.zero_detail.pack(pady=(1, 2))

        actions = tk.Frame(body, bg=CARD)
        actions.pack(fill="x", padx=12, pady=(1, 0))
        buttons = tk.Frame(actions, bg=CARD)
        buttons.pack(fill="x")
        self.continue_button = self.button(buttons, "ZERO CORRECT · CONTINUE",
                                           self.continue_to_prep, size=14)
        self.continue_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.save_button = self.button(buttons, "SET NEW ZERO",
                                       self.save_zero, False, 14)
        self.save_button.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.refresh_zero()

    def refresh_zero(self):
        if self.page != "zero":
            return
        s = self.scanner
        available = s.zero_ready and not s.running and not s.calibration_uncertain
        for button in self.jog_buttons:
            button.config(state="normal" if available else "disabled")
        self.continue_button.config(state="normal" if available and not s.calibration_active else "disabled")
        can_save = available and s.calibration_active and s.cal_offset != 0
        self.save_button.config(state="normal" if can_save else "disabled")
        self.offset_status.config(text=f"Calibration offset: {s.cal_offset:+d} steps  (~{s.cal_offset / STEPS_PER_MM:+.1f} mm)")
        if s.calibration_uncertain:
            status = "Position uncertain — do not scan"
        elif s.running:
            status = "Moving stage — keep clear"
        elif s.calibration_active:
            status = "Adjustment pending — save new zero"
        elif s.zero_ready:
            status = "Stage at saved zero — verify position"
        else:
            status = "Returning to saved zero..."
        self.zero_status.config(text=status, fg=RED if s.calibration_uncertain else TEXT)
        self.zero_detail.config(text=self.zero_error or
                                "Remove cup · check clearance · jog toward the correct zero.",
                                fg=RED if self.zero_error else MUTED)

    def jog(self, delta):
        self.zero_error = ""
        self.jog_value.set(0)
        self.jog_text.config(text="Movement progress: 0%")
        try:
            self.scanner.start_jog(delta)
        except Exception as exc:
            self.zero_error = str(exc)
        self.refresh_zero()

    def continue_to_prep(self):
        s = self.scanner
        if not s.running and s.zero_ready and not s.calibration_active and not s.calibration_uncertain:
            self.show_preparation()

    def save_zero(self):
        """Save the new reference and remain on the verification screen."""
        s = self.scanner
        if (s.running or not s.zero_ready or s.calibration_uncertain
                or not s.calibration_active or s.cal_offset == 0):
            return

        proposed_range = s.cal_original_range - s.cal_offset
        confirmed = messagebox.askyesno(
            "Confirm New Zero",
            "The stage is at the intended cup-insertion position.\n\n"
            f"Offset: {s.cal_offset:+d} steps\n"
            f"New usable range: {proposed_range} steps\n\n"
            "This keeps the OLD left travel endpoint.\n"
            "Have you physically verified that endpoint is safe?",
            parent=self.root,
        )
        if not confirmed:
            return

        try:
            if s.save_new_zero():
                self.zero_error = "New zero saved. Press CONTINUE when ready."
                self.jog_value.set(0)
                self.jog_text.config(text="Movement progress: 0%")
                self.refresh_zero()
        except Exception as exc:
            self.zero_error = str(exc)
            self.refresh_zero()

    # ---------- Preparation ----------
    def show_preparation(self):
        body = self.page_base("prepare", "Sample Preparation", "Stage ready · insert the cup and close the cover")
        center = tk.Frame(body, bg=CARD)
        center.pack(expand=True, fill="x", padx=16)
        self.prep_title = self.text(center, "Stage Ready, Insert Cup", 23, TEXT, True)
        self.prep_title.pack(pady=(7, 16))
        self.cup_label = self.text(center, "Cup: Waiting", 17)
        self.cup_label.pack(pady=5)
        self.cover_label = self.text(center, "Cover: Open", 17)
        self.cover_label.pack(pady=5)
        self.start_button = self.button(center, "START SCANNING", self.start_scan, size=16)
        self.start_button.pack(fill="x", padx=50, pady=(16, 7))
        self.back_button = self.button(
            center, "BACK TO CALIBRATION", self.back_to_calibration, False, 14
        )
        self.back_button.pack(fill="x", padx=50, pady=(0, 9))
        self.prep_detail = self.text(center, "Both switches must be closed.", 11, MUTED)
        self.prep_detail.pack()
        self.refresh_preparation()

    def back_to_calibration(self):
        """Return to verification without re-homing or changing state."""
        if self.scanner.running:
            return
        self.zero_error = ""
        self.show_zero()

    def refresh_preparation(self):
        if self.page != "prepare":
            return
        s = self.scanner
        cup, cover = s.cup.is_pressed, s.cover.is_pressed
        self.cup_label.config(text="Cup: Inserted" if cup else "Cup: Waiting", fg=GREEN if cup else TEXT)
        self.cover_label.config(text="Cover: Closed" if cover else "Cover: Open", fg=GREEN if cover else TEXT)
        self.prep_title.config(text="Stage Ready, Insert Cup" if not cup else
                               ("Cup Inserted" if not cover else "Ready to Scan"))
        valid = s.valid_position() and s.state().get("position") == 0
        self.start_button.config(state="normal" if cup and cover and valid and not s.running and s.zero_ready else "disabled")
        self.back_button.config(state="disabled" if s.running else "normal")
        self.prep_detail.config(text="Both switches must be closed." if valid else "Saved position invalid; do not scan.")

    # ---------- Scan ----------
    def show_scanning(self):
        body = self.page_base("scan", "Scanning", "Keep the cup inserted and the cover closed")
        center = tk.Frame(body, bg=CARD)
        center.pack(expand=True, fill="x", padx=20)
        self.scan_status = self.text(center, "Initializing scan", 20, TEXT, True)
        self.scan_status.pack(pady=(10, 20))
        ttk.Progressbar(center, variable=self.progress, maximum=100,
                        style="MX.Horizontal.TProgressbar").pack(fill="x", padx=12, pady=8)
        self.scan_pct = self.text(center, "0%", 25, BLUE, True)
        self.scan_pct.pack(pady=(3, 15))
        self.text(center, "1/3  →  1/2  →  2/3  →  ZERO  →  FINISHED", 12, MUTED).pack(pady=5)

    def start_scan(self):
        if self.scanner.start_scan():
            self.progress.set(0)
            self.display_progress = self.target_progress = 0.0
            self.phase = None
            self.finish_pending = False
            self.show_scanning()

    def begin_phase(self, stage, steps):
        self.phase = stage
        self.phase_start = time.monotonic()
        self.phase_lo, self.phase_hi, label = STAGES[stage]
        self.phase_expected = max(0.5, steps * self.scanner.args.shift_period * 1.6)
        self.target_progress = max(self.target_progress, self.phase_lo)
        if self.page == "scan":
            self.scan_status.config(text=label)

    def animate_scan(self):
        if self.page != "scan":
            return
        if self.phase in ("move1", "move2", "move3", "home"):
            elapsed = time.monotonic() - self.phase_start
            estimate = self.phase_lo + (self.phase_hi - self.phase_lo - 0.5) * (
                1 - math.exp(-elapsed / self.phase_expected))
            self.target_progress = max(self.target_progress, estimate)
        diff = self.target_progress - self.display_progress
        if diff > 0:
            self.display_progress += min(diff, max(diff * 0.22, 0.06))
        self.progress.set(self.display_progress)
        self.scan_pct.config(text=f"{self.display_progress:.0f}%")
        if self.finish_pending and self.display_progress >= 99.6:
            self.finish_pending = False
            self.show_finished()

    # ---------- Finish / error / application shutdown ----------
    def show_finished(self):
        body = self.page_base("finished", "Finished", "All three scanning positions completed · stage returned to zero")
        center = tk.Frame(body, bg=CARD)
        center.pack(expand=True, fill="x", padx=35)
        self.text(center, "✓  Scanning completed successfully", 18, GREEN, True).pack(pady=19)
        self.button(center, "CHECK THE REPORT", self.check_report, size=15).pack(fill="x", pady=7)
        self.button(center, "RETURN TO LOGIN", self.show_login, False, 15).pack(fill="x", pady=7)

    def check_report(self):
        popup = tk.Toplevel(self.root)
        popup.title("MarginX Report")
        popup.geometry("360x150")
        popup.configure(bg=BG)
        self.text(popup, "Report feature coming soon", 15).pack(pady=20)
        self.button(popup, "OK", popup.destroy).pack()

    def show_error(self, message):
        body = self.page_base("error", "Operation Interrupted", "The stage may require physical position recovery")
        center = tk.Frame(body, bg=CARD)
        center.pack(expand=True, fill="x", padx=25)
        self.text(center, message, 15, RED, wraplength=650, justify="center").pack(pady=15)
        self.button(center, "RETURN TO LOGIN", self.show_login, False).pack(pady=8)

    def tick(self):
        if self.closing:
            return
        s = self.scanner
        if s.operation == "scan" and self.page == "scan":
            try:
                if not s.sensors_ready():
                    s.request_stop()
            except Exception:
                s.request_stop()

        while not s.events.empty():
            try:
                kind, data = s.events.get_nowait()
            except Exception:
                break
            if kind == "home_done":
                if data:
                    self.show_error(data)
                else:
                    self.refresh_zero()
            elif kind == "jog_progress" and self.page == "zero":
                self.jog_value.set(data)
                self.jog_text.config(text=f"Movement progress: {data:.0f}%")
            elif kind == "jog_done":
                if data:
                    self.zero_error = data
                self.refresh_zero()
            elif kind == "phase":
                self.begin_phase(*data)
            elif kind == "phase_done":
                self.target_progress = max(self.target_progress, STAGES[data][1])
                if self.phase == data:
                    self.phase = None
            elif kind == "rotation_progress":
                stage, elapsed = data
                low, high, _ = STAGES[stage]
                self.target_progress = max(self.target_progress,
                                           low + (high - low) * elapsed / s.args.seconds)
            elif kind == "scan_done":
                if data:
                    self.finish_pending = False
                    self.show_error(data)
                else:
                    self.phase = None
                    self.target_progress = 100.0
                    self.finish_pending = True
                    if self.page == "scan":
                        self.scan_status.config(text="Scanning finished — at zero")

        if self.page == "zero":
            self.refresh_zero()
        elif self.page == "prepare":
            self.refresh_preparation()
        elif self.page == "scan":
            self.animate_scan()
        self.root.after(40, self.tick)

    def request_exit(self):
        if self.closing:
            return
        self.close_system_keyboard()
        self.closing = True
        self.scanner.request_stop()
        self.wait_for_stop()

    def wait_for_stop(self):
        if self.scanner.worker and self.scanner.worker.is_alive():
            self.root.after(100, self.wait_for_stop)
            return
        self.scanner.close()
        self.root.destroy()
