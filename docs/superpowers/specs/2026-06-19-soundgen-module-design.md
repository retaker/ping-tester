# SoundGen: Programmatic Sound Generation & Playback Module

## Overview

A reusable Python module (`soundgen.py`) that generates WAV audio from
user-defined parameters (frequency, waveform, amplitude, volume, duration) and
plays it.  Designed as a general-purpose library: callable via a one-liner
convenience function, an object-oriented API for re-use/saving, or standalone
from the command line.

## API

### Quick function

```python
from soundgen import play
play(frequency=440, amplitude=1.0, volume=80, duration=1000, waveform='sine')
```

### OOP interface

```python
from soundgen import Sound

s = Sound(frequency=440, amplitude=1.0, volume=80, duration=1000, waveform='sine')
s.play()          # play through speakers
s.save('a.wav')   # persist to disk
data = s.to_wav() # return WAV bytes
```

### CLI

```
python soundgen.py --freq 440 --vol 80 --dur 1000 --wave sine
python soundgen.py --freq 440 --vol 80 --dur 1000 --wave sine --save out.wav
```

## Parameters

| Parameter    | Range          | Default | Unit | Description                     |
|--------------|----------------|---------|------|---------------------------------|
| frequency    | 20 – 20 000    | 440     | Hz   | Pitch                           |
| amplitude    | 0.0 – 1.0      | 1.0     | —    | Waveform amplitude (timbre)     |
| volume       | 0 – 100        | 80      | —    | Final loudness (PCM scaling)    |
| duration     | >0             | 1000    | ms   | Playback length                 |
| waveform     | sine / square / sawtooth | sine | — | Oscillator shape |
| sample_rate  | >0             | 44100   | Hz   | Sample rate (optional)          |

## Internal pipeline

1. Generate `int(sample_rate * duration / 1000)` floating-point samples
   according to the selected waveform.
2. Multiply by `amplitude`, then by `volume / 100`.
3. Clamp to `[-1.0, 1.0]` and convert to signed 16-bit integers.
4. Wrap in WAV header producing in-memory `bytes`.
5. **Playback (Windows):** write to temp `.wav` file, call
   `winsound.PlaySound(path, winsound.SND_FILENAME)`, then delete.
6. **Playback (Linux):** write to temp `.wav` file, spawn `aplay`; fallback:
   print path.
7. **Playback (macOS):** write to temp `.wav` file, spawn `afplay`; fallback:
   print path.

## Dependencies

- Standard library only (`wave`, `struct`, `math`, `io`, `tempfile`,
  `subprocess`, `os`, `sys`).
- On Windows: `winsound` (stdlib).
- No external packages.

## File

`soundgen.py` — single file, zero dependencies beyond stdlib.
