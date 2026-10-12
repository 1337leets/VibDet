#!/usr/bin/env python3
"""
vibdet.py — Mechanical Vibration Detector (Termux)

Detects nearby machinery (washing machines, engines, etc.) using the phone's
linear-acceleration sensor. Requires Termux and the Termux:API app/package.

Usage:
    python vibdet.py --calibrate        # run this first, on a still surface
    python vibdet.py --mode hand        # hand mode (default)
    python vibdet.py --mode pocket      # pocket mode
"""

import os
import json
import math
import subprocess
import argparse
import time
from collections import deque

# ─── MODES ───────────────────────────────────────────────────────────────────
MODES = {
    "hand": {
        "label": "Hand mode",
        "threshold_multiplier": 8.0,   # alarm when RMS exceeds baseline x this
        "threshold_min": 0.08,         # absolute floor, even if baseline is very low
        "window_sec": 1.5,             # sliding window length (time-based, not sample-based)
        "sustain_sec": 0.3,            # threshold must be exceeded continuously this long
        "cooldown_sec": 5,             # minimum gap between alarms
    },
    "pocket": {
        "label": "Pocket mode",
        "threshold_multiplier": 12.0,  # higher: the pocket damps vibration
        "threshold_min": 0.15,         # higher floor for the pocket
        "window_sec": 3.0,
        "sustain_sec": 1.0,            # must last longer (to reject body movement)
        "cooldown_sec": 8,
    },
}

# Fallback baseline (m/s², RMS of quiet moments); overwritten by --calibrate
DEFAULT_BASELINE = 0.065
BASELINE_FILE = os.path.join(os.path.expanduser("~"), ".vibdet_baseline")

# Sensor polling delay in ms (50 ms ~ 20 Hz). termux-sensor defaults to ~1 Hz,
# which is far too slow for vibration detection.
SENSOR_DELAY_MS = "50"

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def magnitude(ax, ay, az):
    return math.sqrt(ax*ax + ay*ay + az*az)

def rms(values):
    if not values:
        return 0.0
    return math.sqrt(sum(v*v for v in values) / len(values))

def load_baseline():
    try:
        with open(BASELINE_FILE) as f:
            return float(f.read().strip())
    except Exception:
        return DEFAULT_BASELINE

def save_baseline(value):
    with open(BASELINE_FILE, "w") as f:
        f.write(str(value))

def send_notification(title, message):
    try:
        subprocess.run([
            "termux-notification",
            "--title", title,
            "--content", message,
            "--id", "vibdet",
            "--priority", "high",
            "--sound",
            "--vibrate", "500,200,500"
        ], timeout=3)
    except Exception as e:
        print(f"[WARNING] Could not send notification: {e}")

def clear_notification():
    try:
        subprocess.run(["termux-notification-remove", "vibdet"], timeout=2)
    except Exception:
        pass

# ─── CALIBRATION ─────────────────────────────────────────────────────────────
def calibrate():
    """
    Put the phone on a still surface and leave it alone for ~10 seconds.
    Measures the baseline RMS of the quiet environment and saves it.
    """
    print("=" * 50)
    print("CALIBRATION MODE")
    print("=" * 50)
    print("Place the phone on a flat, stable surface.")
    print("Measurement starts in 3 seconds...")
    time.sleep(3)
    print("Measuring (~10 s) — please don't touch the phone!")

    samples = []
    proc = subprocess.Popen(
        ["termux-sensor", "-s", "linear_acceleration",
         "-n", "200", "-d", SENSOR_DELAY_MS],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1
    )

    buffer = ""
    depth = 0
    for line in proc.stdout:
        buffer += line
        depth += line.count("{") - line.count("}")
        if depth == 0 and buffer.strip():
            try:
                obj = json.loads(buffer.strip())
                v = obj["linear_acceleration"]["values"]
                samples.append(magnitude(v[0], v[1], v[2]))
            except Exception:
                pass
            buffer = ""

    proc.wait()

    if len(samples) < 10:
        print("Not enough samples collected. Please try again.")
        return

    # Drop the top 10% so sudden movements don't distort the baseline
    samples_sorted = sorted(samples)
    clean = samples_sorted[:int(len(samples_sorted) * 0.90)]
    baseline = rms(clean)

    save_baseline(baseline)
    print(f"\n✓ Calibration complete.")
    print(f"  Samples      : {len(samples)}")
    print(f"  Baseline RMS : {baseline:.4f} m/s²")
    print(f"  Saved to     : {BASELINE_FILE}")
    print(f"\nNow start monitoring with:")
    print(f"  python vibdet.py --mode pocket")
    print(f"  python vibdet.py --mode hand")

# ─── MAIN MONITORING LOOP ────────────────────────────────────────────────────
def monitor(mode_name):
    cfg = MODES[mode_name]
    baseline = load_baseline()
    threshold = max(baseline * cfg["threshold_multiplier"], cfg["threshold_min"])

    # Time-based sliding window: stores (timestamp, magnitude) pairs, so it
    # works regardless of the real sensor sampling rate (varies by device/Android).
    window = deque()
    min_samples_for_decision = 5  # need at least this many samples before judging

    above_since = None       # when the threshold was first exceeded (continuously)
    alarm_active = False
    last_alarm_time = 0
    last_print_time = 0
    peak_since_print = 0.0
    print_interval = 0.2     # refresh the display ~5 times per second

    print("=" * 50)
    print(f"VIBDET — {cfg['label']}")
    print("=" * 50)
    print(f"  Baseline      : {baseline:.4f} m/s²")
    t_from_mult = baseline * cfg["threshold_multiplier"]
    t_source = f"x{cfg['threshold_multiplier']}" if t_from_mult >= cfg["threshold_min"] else "fixed minimum"
    print(f"  Threshold     : {threshold:.4f} m/s²  ({t_source})")
    print(f"  Window        : {cfg['window_sec']} s (time-based)")
    print(f"  Sustain time  : threshold must be exceeded for {cfg['sustain_sec']} s continuously")
    print(f"  Cooldown      : {cfg['cooldown_sec']} s")
    print("-" * 50)
    print("Monitoring... (Ctrl+C to quit)\n")

    proc = subprocess.Popen(
        ["termux-sensor", "-s", "linear_acceleration", "-d", SENSOR_DELAY_MS],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1
    )

    buffer = ""
    depth = 0

    try:
        for line in proc.stdout:
            buffer += line
            depth += line.count("{") - line.count("}")

            if depth != 0 or not buffer.strip():
                continue

            # A complete JSON object has been collected
            try:
                obj = json.loads(buffer.strip())
                v = obj["linear_acceleration"]["values"]
                mag = magnitude(v[0], v[1], v[2])
            except Exception:
                buffer = ""
                continue
            finally:
                buffer = ""

            now = time.time()
            window.append((now, mag))

            # Time-based window: drop samples older than window_sec
            cutoff = now - cfg["window_sec"]
            while window and window[0][0] < cutoff:
                window.popleft()

            # Don't judge until the window has enough data
            if len(window) < min_samples_for_decision:
                continue

            # High-pass effect: subtract the window mean, then take the RMS
            vals = [m for _, m in window]
            mean = sum(vals) / len(vals)
            hp_vals = [m - mean for m in vals]
            current_rms = rms(hp_vals)

            peak_since_print = max(peak_since_print, current_rms)

            # Display: refreshed ~5x per second (wall-clock), but it shows the
            # PEAK seen since the last refresh so short spikes aren't hidden.
            if now - last_print_time >= print_interval:
                display_rms = peak_since_print
                bar_len = min(40, int(display_rms / threshold * 20))
                bar = "█" * bar_len + "░" * (40 - bar_len)
                status = "🔴 ALARM" if alarm_active else "🟢 normal"
                print(f"\r[{bar}] RMS:{display_rms:.3f} THR:{threshold:.3f} {status}  ",
                      end="", flush=True)
                last_print_time = now
                peak_since_print = 0.0

            cooldown_ok = (now - last_alarm_time) > cfg["cooldown_sec"]

            if current_rms > threshold:
                if above_since is None:
                    above_since = now
            else:
                # Dropped below threshold: the sustain timer restarts from zero
                above_since = None

            # Trigger: threshold exceeded continuously for sustain_sec
            if (above_since is not None
                    and (now - above_since) >= cfg["sustain_sec"]
                    and not alarm_active and cooldown_ok):
                alarm_active = True
                last_alarm_time = now
                print(f"\n\n⚠️  VIBRATION DETECTED!")
                print(f"   RMS: {current_rms:.4f}  |  Threshold: {threshold:.4f}")
                print(f"   Mode: {cfg['label']}")
                send_notification(
                    "⚠️ Vibration detected",
                    f"Mechanical vibration started! RMS: {current_rms:.3f} m/s² ({cfg['label']})"
                )

            # Clear the alarm once RMS falls well below the threshold
            if alarm_active and current_rms < threshold * 0.6:
                alarm_active = False
                above_since = None
                print("\n✓  Vibration stopped.\n")

    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        proc.terminate()
        clear_notification()

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Mechanical vibration detector (Termux / linear_acceleration)"
    )
    parser.add_argument(
        "--mode",
        choices=["pocket", "hand"],
        default="hand",
        help="pocket = in-pocket mode, hand = hand-held mode (default)"
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Calibrate the baseline first (in a quiet, still environment)"
    )
    args = parser.parse_args()

    if args.calibrate:
        calibrate()
    else:
        monitor(args.mode)

if __name__ == "__main__":
    main()
