# MarginX — Raspberry Pi Touchscreen Scanning Demo

**Hardware and software operating guide for collaborators and demo operators**

> **Status:** Prototype / research demo. This guide describes the **zero-free, relative-motion MarginX v4** workflow and the later **reversed shift-motor direction** change. Verify the exact installed revision, wiring, motor-driver settings, power supplies, and emergency-stop circuit **on the physical device** before use. This repository is not a safety-certified motion-control system.

## 1. What MarginX does

MarginX is a Raspberry Pi 4B-based scanning demonstrator with a touchscreen interface, a **shift (linear travel) stepper motor**, a **rotation stepper motor**, a **cup-presence microswitch**, and a **cover-closed microswitch**.

**Operator workflow:**

```text
Power on → MarginX login → Manual Positioning (LEFT / RIGHT 1 or 5 mm)
         → Confirm unobstructed scan travel → Insert cup → Close cover
         → START SCANNING → Three scan positions → Return to scan start
         → Finished
```

The v4 workflow **does not home the stage**, does not calibrate a zero position, and does not use an absolute encoder or limit sensor. The operator selects the starting location manually. **The software cannot know how much physical travel remains.**

## 2. Repository and Pi folder layout

The application files currently used by the demo are:

```text
~/marginx/
├── tools/
│   ├── marginxGUI.py          # Application entry point
│   ├── marginx_ui.py         # Tkinter touchscreen pages
│   ├── marginx_control.py    # Scan sequence, switches and relative moves
│   └── motorlib.py           # Motor step / direction pulse generation
├── config/                   # Pi-local data; do not overwrite via Git
├── .venv/                    # Pi-local Python environment
├── start_marginx.sh         # Optional launcher; depends on Pi setup
├── update_marginx.sh        # Optional pre-launch Git updater
└── README.md
```

Additional files may exist in a development checkout. **Do not execute old migration/calibration scripts** (`apply_fsr_marginx.py`, `remove_auto_zero_marginx.py`, etc.) on a functioning v4 installation.

Recommended `.gitignore` entries:

```gitignore
.venv/
config/
__pycache__/
*.pyc
*.log
backup*/
*.zip
```

Check with `git ls-files` that no secrets, device-specific positions, credential files, backups or generated data were committed. `.gitignore` alone does **not** remove already-tracked files.

## 3. Hardware overview and GPIO connections

The following are **BCM GPIO numbers**, not physical header pin numbers. Verify against the shipped Pi and driver documentation.

| Device | Pi BCM GPIO | Physical 40-pin header | Connection / function |
|---|---:|---:|---|
| Shift motor STEP | GPIO17 | Pin 11 | DM430 shift driver's STEP/PUL input (+, per the prototype wiring) |
| Shift motor DIR | GPIO27 | Pin 13 | DM430 shift driver's DIR input (+, per the prototype wiring) |
| Rotation motor STEP | GPIO23 | Pin 16 | DM430 rotation driver's STEP/PUL input (+, per the prototype wiring) |
| Rotation motor DIR | GPIO24 | Pin 18 | DM430 rotation driver's DIR input (+, per the prototype wiring) |
| Cup microswitch NO | GPIO16 | Pin 36 | Cup-sense signal; normally-open contact |
| Cover microswitch NO | GPIO6 | Pin 31 | Cover-sense signal; normally-open contact |
| Cup/cover COM | GND | Any appropriate Pi GND | Shared switch reference |
| Scan indicator output | GPIO26 | Pin 37 | Logic output for scan LED / **appropriate LED driver** |
| Indicator ground | GND | Pin 39, if wired accordingly | Return for a suitably driven indicator |

### Power and driver cautions

- **Raspberry Pi:** use a suitable **regulated 5 V Pi power supply**. The stepper-motor supply is **separate**.
- **Stepper motor drivers:** the previous prototype used **DM430 drivers and a nominal 24 V supply**. Confirm the actual supply's **current capability**, the motor/driver ratings, microstep settings, polarity, and wire pairs before connecting power. A supply merely labeled `24 V / 1 A` must **not** be assumed adequate for both motors.
- **Driver GPIO compatibility:** the Pi outputs 3.3 V logic. Confirm that each installed DM430's opto-isolated PUL/DIR inputs reliably accept the actual interface circuit. Do not apply 24 V to the Pi GPIO pins.
- **LED:** GPIO26 is a **logic output**, not a 5 V or 12 V lamp power supply. The exact indicator model and driver/wiring must be verified. Do not connect a high-current LED directly to a GPIO pin.
- **Cup and cover switches:** the code expects **COM → GND, NO → GPIO**, using internal pull-ups. With the switch pressed, `is_pressed` should be `True`.
- **Emergency stop:** the emergency-stop assembly should interrupt motor power through an appropriately rated, independently verified hardware safety circuit. Its **actual installed wiring has not been validated by this README**. It must not rely on the Pi software alone. Verify manual reset behavior.
- Keep hands, hair, wiring, and loose objects away from the moving stage and rotation assembly. Never unplug/replug motor wiring with driver power applied.

## 4. Before the first operation

1. Place the demo on a stable surface and inspect the mounted stage, cup holder, cover, cable strain relief, and all exposed moving parts.
2. Confirm motor power is **off** while inspecting wiring and mechanics. Check the emergency-stop behavior against the actual installed hardware.
3. Verify the two motor-driver configurations, Pi power supply, motor supply rating, and the motor's physically available travel.
4. Verify the shift motor's LEFT/RIGHT orientation. In the reversed-orientation controller, `SHIFT_DIRECTION_REVERSED = True` affects both manual jog and scanning. **Do not assume other units have the same orientation.**
5. With motor power properly enabled, the physical emergency stop accessible, and clear travel on **both** sides, test the smallest movement: LEFT 1 mm then RIGHT 1 mm. Check that the stage returns to its original position.
6. Test Cup and Cover states. Both must respond consistently before a scan. If either signal flickers unexpectedly, stop and diagnose it; do not bypass sensor checks to make a scan continue.
7. **Confirm scan clearance at the actual manually selected starting position** before pressing Continue. No software end-stop detection is provided.

**Do not issue Jog or Scan commands while the stepper motor supply is off.** Software may count output pulses even when the motor does not physically move.

## 5. Operating the demo

### 5.1 Start and log in

From the Pi desktop/terminal (after dependencies have been installed):

```bash
cd ~/marginx
.venv/bin/python3 tools/marginxGUI.py
```

If the Pi has an approved desktop autostart shortcut, it may launch automatically. The v4 prototype's local login defaults are **`admin` / `000000`** in `marginx_ui.py`; **these are demonstration credentials, not real access security**. Change or replace them if the device will be accessible beyond a supervised demonstration.

### 5.2 Select a manual starting position

On **Manual Positioning**, use the four touchscreen buttons:

| Button | Commanded linear movement |
|---|---|
| LEFT 1 mm | 200 shift steps left |
| RIGHT 1 mm | 200 shift steps right |
| LEFT 5 mm | 1,000 shift steps left |
| RIGHT 5 mm | 1,000 shift steps right |

`STEPS_PER_MM = 200` is the configuration in the supplied v4 controller; **verify the actual travel per step** on the shipped mechanism. The UI's relative movement display is a session count, **not an independent position sensor**.

When positioned correctly, click **CONTINUE TO CUP / COVER CHECK** and confirm the safety-clearance dialog. There is **no Set Zero button**.

### 5.3 Prepare the sample

Insert the cup and close the cover. Confirm the UI shows **Cup: Inserted** and **Cover: Closed** and enables **START SCANNING**. The switch inputs are monitored while scanning. An unexpected open state can abort the operation.

### 5.4 Scan and automatic return

The three scan locations are defined relative to the operator's selected start position. In the supplied v4 controller:

```python
SCAN_SPAN_STEPS = 6000  # EXAMPLE ONLY: 30 mm at 200 steps/mm
```

The programmed targets are **1/3**, **1/2**, and **2/3** of this *configured span* from the starting location—not 1/3, 1/2, and 2/3 of an automatically measured total machine travel.

| Scan phase | Relative target for the 6,000-step example |
|---|---:|
| Position 1 | +2,000 steps (10 mm) |
| Position 2 | +3,000 steps (15 mm) |
| Position 3 | +4,000 steps (20 mm) |
| Successful return | −4,000 steps, back to the chosen start |

The shift direction is **logical left** in the updated reversed-orientation controller. At each position, the rotation motor runs for **30 s by default** (`--seconds` can change this when launching). A successful, uninterrupted scan commands the return to the pre-scan starting position, then shows **Finished**.

**Very important:** The `6000`-step span was supplied as an **example**, not a verified mechanical limit. The current v4 UI asks the operator to verify the entire configured span (30 mm in this example), even though the farthest current target is at 2/3 (20 mm). Confirm physical clearance for the whole path and a suitable safety margin before scanning. Adjust `SCAN_SPAN_STEPS` only after measuring the actual safe travel and testing the change.

### 5.5 Abort, faults, and shutdown

- If the cup is removed, the cover opens, or a scan aborts, stop and inspect the mechanism. **Do not assume it is at the selected start position.**
- If the hardware emergency stop is activated, investigate and reset it using the verified hardware procedure. Do not resume automatically.
- Do not manually command the return distance after an interrupted movement without establishing where the stage actually is.
- Use the GUI's **EXIT** button for normal shutdown. Wait until movement has stopped before powering down or unplugging the Pi.
- The **CHECK THE REPORT** button in the supplied v4 is a placeholder; it does not generate a validated scanning report.

## 6. Software installation on another Raspberry Pi

**Supported reference device:** Raspberry Pi 4B with Raspberry Pi OS desktop and a touchscreen. The instructions assume the project lives in `~/marginx`, with the four application files under `~/marginx/tools`. Test on the recipient's exact OS and hardware before the demo.

1. Install Git, Python 3, the Tkinter OS package, and the GPIO libraries appropriate for that Pi / OS. On Raspberry Pi OS, common starting packages are:

   ```bash
   sudo apt update
   sudo apt install -y git python3-venv python3-tk python3-gpiozero
   ```

   GPIOZero on some newer Raspberry Pi OS versions uses `lgpio`. Verify the installed GPIOZero/pin-factory backend on the target Pi. If using a virtual environment, system-installed GPIO packages may require `--system-site-packages`, or install compatible dependencies within the environment.

2. Get the approved repository version (replace the URL with the real repository):

   ```bash
   cd ~
   git clone git@github.com:OWNER/MarginX.git marginx
   cd ~/marginx
   python3 -m venv --system-site-packages .venv
   ```

   **If the directory already exists, do not clone over it.** Instead use the existing checkout and validate it. For a private repository, set up authorized, **read-only** GitHub SSH access on each device first.

3. Check Python imports and syntax before enabling motor power:

   ```bash
   cd ~/marginx
   .venv/bin/python3 -m py_compile tools/marginxGUI.py tools/marginx_ui.py tools/marginx_control.py tools/motorlib.py
   .venv/bin/python3 -c 'import tkinter, gpiozero; print("Imports OK")'
   ```

4. With motors stationary, launch manually and validate the display and the input status:

   ```bash
   cd ~/marginx
   .venv/bin/python3 tools/marginxGUI.py
   ```

**If the recipient is using the very same shipped Pi**, Git, the Python environment, touchscreen and hardware are typically already set up. They should use its existing `~/marginx` checkout rather than reinstalling or cloning over it.

## 7. GitHub collaboration and automatic updates

**Intended roles:**

- **Developers** receive write access to the repository and propose or push updates.
- **Demo Raspberry Pis** receive **read-only** access and download only approved versions.

**Recommended release process:** contributors create changes on development branches; changes are reviewed and tested with the physical prototype; then approved changes are published to a deployment branch such as `demo-stable`. This prevents a partially tested motion-control change in `main` from reaching a shipped demo.

### 7.1 Give collaborators access

In GitHub, invite collaborators under the repository's **Settings → Collaborators / Collaborators and teams**, depending on the account type. Developers use **their own** GitHub credentials, not the owner's password or the Pi's SSH keys.

### 7.2 Give the Pi read-only access (private repository)

For a private repository, configure a **separate read-only SSH deploy key per Pi**. Add each Pi's **public** key in the GitHub repository settings under **Deploy keys** with write access disabled. **Never publish private keys, personal access tokens, or GitHub passwords in the repository or README.**

GitHub setup should be verified interactively during commissioning, and subsequently work noninteractively. To inspect the configured remote:

```bash
cd ~/marginx
git remote -v
git branch --show-current
git status --short
```

### 7.3 Update manually

Once read-only authentication works and local tracked files are clean:

```bash
cd ~/marginx
git pull --ff-only
```

This updates **the currently checked-out, tracking branch**. To deploy from `demo-stable`, the Pi must actually check out that branch and track `origin/demo-stable`; simply pulling another branch into `main` is not a substitute for a deliberate release setup.

### 7.4 Update automatically before the GUI starts

The optional `update_marginx.sh` updater is intended to run **once before** starting the GUI. It performs a best-effort `git pull --ff-only`, skips tracked local modifications, and allows the currently installed application to start if the network/update is unavailable. It should **never** run during a scan.

On an existing Pi, first check that the updater is installed and executable:

```bash
cd ~/marginx
chmod +x update_marginx.sh
./update_marginx.sh
tail -n 20 update.log
```

The updater must be linked into the **actual** Pi desktop launcher/autostart configuration (which can differ between devices). The intended order is:

```text
Pi boots → network may become available → updater checks GitHub
         → GUI launches using the locally installed files
```

**Deployment limitations:** the current updater is *best-effort*; it does not provide automatic syntax validation, atomic multi-file installation, or rollback to a prior proven release. Test deployment on one Pi before rolling it out to multiple motorized units. A Git pull can succeed while a newly introduced runtime error prevents the GUI from launching. Maintain a known-good release and an offline recovery procedure.

### 7.5 Local changes on recipient Pis

Git may report `Tracked local changes present; skipping.` This is intentional. Do not fix it with `git reset --hard` or `git clean -fd` on an active demo Pi. Use `git status --short`, identify which tracked files changed, and decide whether to preserve them in a separate branch or patch. Keep local experiments outside tracked application paths when possible.

**Do not commit or sync** `config/shift_state.json`, API tokens, private keys, `.venv`, logs, or recipient-only research data.

## 8. Troubleshooting

| Symptom | Check / safe action |
|---|---|
| GUI will not start | Run it from a terminal; inspect Python traceback and use `py_compile` to detect syntax errors |
| `GPIO busy` | Close any other MarginX, switch-test, or GPIO process before starting the GUI; do not force GPIO ownership while motors are active |
| Cover status incorrect | Independently test GPIO6, cover switch actuation and GND |
| LEFT moves RIGHT | Inspect shift-motor installation and the `SHIFT_DIRECTION_REVERSED` setting in `marginx_control.py`; verify both manual moves and scan/return before use |
| Scan stops halfway | Check sensor states, whether the GUI requested abort, and motor/driver conditions. After abort, treat physical position as uncertain |
| Stage does not move | Inspect power, E-stop, driver state, and STEP/DIR wiring; **do not repeatedly issue moves without confirming the motor is powered** |
| Updater skips | `git status --short` and `tail -n 20 update.log`; local tracked changes or missing authorization may prevent pulling |
| Pi offline | Keep running last tested installed version; update at the next safe boot with internet access |
| Old `Invalid Position` error | Confirm the Pi is actually using the latest **v4 no-zero** files; older calibration controller versions use `shift_state.json` |

## 9. Handover checklist

Before shipping the demo or granting another team access:

- [ ] Confirm recipient's Pi model, SD-card image, user account, touchscreen, and working offline launcher.
- [ ] Record the GitHub repository URL, deployed branch, and release commit/tag.
- [ ] Back up the known-good code and provide an offline recovery copy.
- [ ] Verify all GPIO connections, power supplies, stepper settings, motor polarity, and travel clearance on the **actual** unit.
- [ ] Document and physically test the emergency-stop circuit and its reset procedure.
- [ ] Check Cup/Cover states and that the scan refuses to start with either switch open.
- [ ] Measure and approve `SCAN_SPAN_STEPS`; ensure the intended motion fits within the available travel from **every** user-selectable start position.
- [ ] Verify LEFT 1 mm → RIGHT 1 mm and a complete supervised three-position scan with automatic return.
- [ ] Test GitHub read-only updates on the actual Pi, including what happens with no internet.
- [ ] Brief the recipient: no sensor-based homing, no software limit switches, do not restart movement after an interrupted scan without inspecting the stage.

---

## 10. Maintainer notes

- The current v4 is a **relative-motion demo**, not a calibrated motion-measurement platform.
- Defaults in the supplied version: `STEPS_PER_MM = 200`, `SCAN_SPAN_STEPS = 6000`, three scan targets at one-third/one-half/two-thirds of span, and **30 seconds of rotation per target**. These values are **software settings**, not guaranteed mechanical or experimental specifications.
- The shipped shift motor orientation may require `SHIFT_DIRECTION_REVERSED = True`; check the recipient's controller and installed hardware.
- The current touchscreen report page is a placeholder.
- Update scripts and startup services are **device-specific deployment infrastructure**; store and maintain their working versions in GitHub once verified.

**Maintainer / support contact:** _Add your team name, contact email, repository URL, version, and a photo of the actual assembled wiring before distribution._
