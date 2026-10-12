# VibDet

A small vibration detector for Android phones, written in Python and run in Termux.

It reads the phone's accelerometer and sends a notification when it picks up steady vibration from nearby machinery, such as a washing machine, a drill, or an engine.

It uses only the Python standard library. Tested on a Honor X9a.

## Requirements

- An Android phone
- [Termux](https://termux.dev) and the Termux:API app
- In Termux:

```
pkg install python termux-api
```

## Usage

Run the calibration first. Put the phone on a still surface and leave it alone for about 10 seconds:

```
python vibdet.py --calibrate
```

To keep it running with the screen off, take a wake lock first:

```
termux-wake-lock
```

Then start monitoring:

```
python vibdet.py --mode hand      # phone held in hand or lying on a surface (default)
python vibdet.py --mode pocket    # phone in a pocket
```

While running, it shows a bar that fills as the vibration level approaches the threshold. When the level stays above the threshold long enough, it prints a message and sends a notification. Press Ctrl+C to stop.

## How it works

1. **Sampling.** It reads `linear_acceleration` from `termux-sensor` at about 20 Hz (`-d 50`). The default rate is about 1 Hz, which is too slow to see vibration.
2. **Magnitude.** The three axes are combined into one number: `sqrt(x² + y² + z²)`.
3. **Sliding window.** It keeps the samples from the last `window_sec` seconds. The window is based on time, not on a sample count, so it still works if the sensor rate changes.
4. **Vibration level.** It subtracts the window's mean, then takes the RMS. A steady value gives a level near zero. A shaking value gives a larger one.
5. **Threshold.** `max(baseline × multiplier, threshold_min)`. The baseline comes from the calibration step.
6. **Trigger.** The level must stay above the threshold for `sustain_sec` without a break. This ignores single bumps.
7. **Cooldown and release.** After an alarm, the next one waits `cooldown_sec`. The alarm clears when the level drops below 60% of the threshold. Using a lower level to clear than to trigger keeps the alarm from flickering near the threshold.

The display shows the peak level since the last refresh, not only the latest value. This way a short spike that counts toward the trigger is not hidden.

### Modes

| | hand | pocket |
|---|---|---|
| threshold multiplier | 8 | 12 |
| minimum threshold (m/s²) | 0.08 | 0.15 |
| window (s) | 1.5 | 3.0 |
| sustain time (s) | 0.3 | 1.0 |
| cooldown (s) | 5 | 8 |

Pocket mode is less sensitive and slower on purpose. A pocket damps vibration, and walking would otherwise trigger it.

### Calibration

It collects 200 samples (about 10 seconds), drops the highest 10% so a stray bump does not distort the result, and saves the RMS to `~/.vibdet_baseline`. If that file is missing, a default of 0.065 m/s² is used.

## Limitations

- The numbers in `MODES` are starting points. Tune them for your phone and your environment.
- The calibration baseline is the RMS of the raw magnitudes. The monitoring level is the RMS after subtracting the window mean, which is a different quantity. In practice the fixed `threshold_min` usually sets the threshold, so the baseline has little effect. Making these two consistent would be a good next step.
- Tested on one phone, a Honor X9a. With `termux-wake-lock` active, it keeps working with the screen off.
- The real sample rate depends on the device and on Android's power settings, so results on other phones may differ.

## Ideas

- More alert options through Termux:API

## License

MIT. See [LICENSE](LICENSE).
