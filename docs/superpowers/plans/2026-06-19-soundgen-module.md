# SoundGen Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable `soundgen.py` module that generates WAV audio from
user-defined parameters and plays it via OS audio facilities.

**Architecture:** Single file `soundgen.py` containing a `Sound` class (OOP
interface for generation/playback/save) and a `play()` convenience function.
CLI support via `if __name__ == '__main__'`. Stdlib only — `wave`, `struct`,
`math`, `io`, `tempfile`, `subprocess`, `os`, `sys`, plus `winsound` on Windows.

**Tech Stack:** Python 3, stdlib only, pytest for tests.

## Global Constraints

- Single file: `soundgen.py`, no external dependencies beyond stdlib
- `duration` unit: milliseconds
- Waveforms: `sine`, `square`, `sawtooth`
- `frequency`: 20–20000 Hz, `amplitude`: 0.0–1.0, `volume`: 0–100
- Sample rate default: 44100 Hz
- Windows playback via `winsound.SND_FILENAME` from temp file
- Linux fallback: `aplay`; macOS fallback: `afplay`
- Test runner: `pytest`

---

### Task 1: Module skeleton and waveform generation

**Files:**
- Create: `soundgen.py`
- Create: `tests/test_soundgen.py`

**Interfaces:**
- Produces: `Sound.__init__(self, frequency: float, amplitude: float, volume: int, duration: int, waveform: str, sample_rate: int)` — stores params, validates ranges
- Produces: `Sound._generate(self) -> bytes` — returns signed 16-bit PCM WAV data
- Produces: Known-good exports tested via reading back with `wave.open`

- [ ] **Step 1: Write failing tests for Sound construction and waveform generation**

Create `tests/test_soundgen.py`:

```python
import io
import math
import struct
import wave
import pytest
from soundgen import Sound


class TestSoundInit:
    def test_defaults(self):
        s = Sound()
        assert s.frequency == 440
        assert s.amplitude == 1.0
        assert s.volume == 80
        assert s.duration == 1000
        assert s.waveform == 'sine'
        assert s.sample_rate == 44100

    def test_custom_params(self):
        s = Sound(frequency=1000, amplitude=0.5, volume=50, duration=500, waveform='square')
        assert s.frequency == 1000
        assert s.amplitude == 0.5
        assert s.volume == 50
        assert s.duration == 500
        assert s.waveform == 'square'

    def test_frequency_clamped(self):
        s = Sound(frequency=0)
        assert s.frequency == 20
        s = Sound(frequency=30000)
        assert s.frequency == 20000

    def test_amplitude_clamped(self):
        s = Sound(amplitude=-0.5)
        assert s.amplitude == 0.0
        s = Sound(amplitude=2.0)
        assert s.amplitude == 1.0

    def test_volume_clamped(self):
        s = Sound(volume=-10)
        assert s.volume == 0
        s = Sound(volume=200)
        assert s.volume == 100

    def test_duration_clamped(self):
        s = Sound(duration=0)
        assert s.duration == 1

    def test_invalid_waveform_raises(self):
        with pytest.raises(ValueError, match='waveform'):
            Sound(waveform='triangle')


class TestGenerate:
    def _read_wav(self, data):
        buf = io.BytesIO(data)
        wf = wave.open(buf, 'rb')
        params = wf.getparams()
        frames = wf.readframes(params.nframes)
        wf.close()
        return params, frames

    def test_produces_valid_wav(self):
        s = Sound(frequency=440, amplitude=1.0, volume=80, duration=100, sample_rate=44100)
        data = s._generate()
        params, frames = self._read_wav(data)
        assert params.nchannels == 1
        assert params.sampwidth == 2
        assert params.framerate == 44100
        assert params.nframes > 0

    def test_sample_count_matches_duration(self):
        s = Sound(frequency=440, duration=100, sample_rate=44100)  # 100 ms
        data = s._generate()
        params, _ = self._read_wav(data)
        expected_frames = int(44100 * 100 / 1000)
        assert params.nframes == expected_frames

    def test_sine_starts_near_zero(self):
        s = Sound(frequency=440, amplitude=1.0, volume=80, duration=100, waveform='sine')
        data = s._generate()
        _, frames = self._read_wav(data)
        # unpack first 10 samples as signed 16-bit ints
        samples = struct.unpack('<10h', frames[:20])
        # sine of 0 is 0, so first sample should be near 0
        assert abs(samples[0]) < 1000  # generous threshold

    def test_square_is_binary_like(self):
        s = Sound(frequency=440, amplitude=1.0, volume=80, duration=100, waveform='square')
        data = s._generate()
        _, frames = self._read_wav(data)
        samples = struct.unpack(f'<{len(frames)//2}h', frames)
        # square wave samples should be mostly near max or min
        abs_samples = [abs(v) for v in samples]
        max_val = max(abs_samples)
        # most samples should be close to the max
        near_max = sum(1 for v in abs_samples if v > max_val * 0.9)
        assert near_max > len(samples) * 0.8

    def test_sawtooth_ramps(self):
        s = Sound(frequency=440, amplitude=1.0, volume=80, duration=100, waveform='sawtooth')
        data = s._generate()
        _, frames = self._read_wav(data)
        samples = struct.unpack(f'<{len(frames)//2}h', frames)
        # look for at least one rising edge: find where sample[i] < sample[i+1]
        rising_edges = sum(1 for i in range(len(samples) - 1) if samples[i] < samples[i + 1])
        assert rising_edges > len(samples) * 0.4

    def test_amplitude_reduces_peak(self):
        s_full = Sound(frequency=440, amplitude=1.0, volume=100, duration=100)
        s_half = Sound(frequency=440, amplitude=0.5, volume=100, duration=100)
        _, full_frames = self._read_wav(s_full._generate())
        _, half_frames = self._read_wav(s_half._generate())
        full_max = max(abs(v) for v in struct.unpack(f'<{len(full_frames)//2}h', full_frames))
        half_max = max(abs(v) for v in struct.unpack(f'<{len(half_frames)//2}h', half_frames))
        assert half_max < full_max * 0.8

    def test_volume_zero_is_silent(self):
        s = Sound(frequency=440, amplitude=1.0, volume=0, duration=100)
        data = s._generate()
        _, frames = self._read_wav(data)
        samples = struct.unpack(f'<{len(frames)//2}h', frames)
        assert all(v == 0 for v in samples)

    def test_volume_one_hundred_is_full(self):
        s = Sound(frequency=440, amplitude=1.0, volume=100, duration=100)
        data = s._generate()
        _, frames = self._read_wav(data)
        samples = struct.unpack(f'<{len(frames)//2}h', frames)
        max_val = max(abs(v) for v in samples)
        assert max_val > 20000  # near 16-bit max
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_soundgen.py -v
```

Expected: FAIL — `soundgen` module not found or `Sound` not defined.

- [ ] **Step 3: Write minimal Sound class with `__init__`, `_generate`, helpers**

Create `soundgen.py`:

```python
#!/usr/bin/env python3
"""Programmatic sound generation and playback."""

import io
import math
import os
import struct
import subprocess
import sys
import tempfile
import wave

WAVEFORMS = ('sine', 'square', 'sawtooth')


class Sound:
    def __init__(self, frequency=440, amplitude=1.0, volume=80, duration=1000,
                 waveform='sine', sample_rate=44100):
        self.frequency = max(20, min(20000, frequency))
        self.amplitude = max(0.0, min(1.0, amplitude))
        self.volume = max(0, min(100, volume))
        self.duration = max(1, duration)
        if waveform not in WAVEFORMS:
            raise ValueError(f'waveform must be one of {WAVEFORMS}, got {waveform!r}')
        self.waveform = waveform
        self.sample_rate = max(1, sample_rate)

    def _generate(self):
        nframes = int(self.sample_rate * self.duration / 1000)
        factor = self.amplitude * (self.volume / 100.0)
        raw = self._generate_samples(nframes, factor)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(raw)
        return buf.getvalue()

    def _generate_samples(self, nframes, factor):
        samples = []
        for i in range(nframes):
            t = i / self.sample_rate
            phase = 2.0 * math.pi * self.frequency * t
            if self.waveform == 'sine':
                val = math.sin(phase)
            elif self.waveform == 'square':
                val = 1.0 if math.sin(phase) >= 0 else -1.0
            else:  # sawtooth
                val = 2.0 * (self.frequency * t % 1.0) - 1.0
            val *= factor
            val = max(-1.0, min(1.0, val))
            samples.append(int(val * 32767))
        return struct.pack(f'<{len(samples)}h', *samples)

    def play(self):
        data = self.to_wav()
        fd, tmp = tempfile.mkstemp(suffix='.wav')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            self._play_file(tmp)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.to_wav())

    def to_wav(self):
        return self._generate()

    @staticmethod
    def _play_file(path):
        if sys.platform == 'win32':
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
        elif sys.platform == 'darwin':
            subprocess.run(['afplay', path], capture_output=True)
        else:
            try:
                subprocess.run(['aplay', path], capture_output=True)
            except FileNotFoundError:
                pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_soundgen.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add soundgen.py tests/test_soundgen.py
git commit -m "feat: add Sound class with waveform generation"
```

---

### Task 2: Convenience function and CLI

**Files:**
- Modify: `soundgen.py`
- Modify: `tests/test_soundgen.py`

**Interfaces:**
- Consumes: `Sound` class from Task 1
- Produces: `play(frequency, amplitude, volume, duration, waveform, sample_rate)` — creates Sound and calls `.play()`
- Produces: `if __name__ == '__main__'` CLI with argparse

- [ ] **Step 1: Write failing tests for `play()` and CLI**

Append to `tests/test_soundgen.py`:

```python
from soundgen import play
from unittest import mock


class TestPlayFunction:
    def test_play_creates_sound_and_calls_play(self):
        with mock.patch('soundgen.Sound') as MockSound:
            instance = MockSound.return_value
            play(frequency=523, amplitude=0.8, volume=90, duration=200, waveform='square')
            MockSound.assert_called_once_with(
                frequency=523, amplitude=0.8, volume=90, duration=200,
                waveform='square', sample_rate=44100
            )
            instance.play.assert_called_once()

    def test_play_defaults(self):
        with mock.patch('soundgen.Sound') as MockSound:
            instance = MockSound.return_value
            play()
            MockSound.assert_called_once_with(
                frequency=440, amplitude=1.0, volume=80, duration=1000,
                waveform='sine', sample_rate=44100
            )
            instance.play.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_soundgen.py::TestPlayFunction -v
```

Expected: FAIL — `play` not defined.

- [ ] **Step 3: Add `play()` function to soundgen.py**

Append to `soundgen.py`:

```python
def play(frequency=440, amplitude=1.0, volume=80, duration=1000,
         waveform='sine', sample_rate=44100):
    """Generate and play a sound with the given parameters."""
    Sound(frequency=frequency, amplitude=amplitude, volume=volume,
          duration=duration, waveform=waveform,
          sample_rate=sample_rate).play()
```

Append CLI block to `soundgen.py`:

```python
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate and play a sound')
    parser.add_argument('--freq', type=float, default=440, help='Frequency in Hz (default: 440)')
    parser.add_argument('--amp', type=float, default=1.0, help='Amplitude 0.0-1.0 (default: 1.0)')
    parser.add_argument('--vol', type=int, default=80, help='Volume 0-100 (default: 80)')
    parser.add_argument('--dur', type=int, default=1000, help='Duration in ms (default: 1000)')
    parser.add_argument('--wave', choices=WAVEFORMS, default='sine', help='Waveform (default: sine)')
    parser.add_argument('--rate', type=int, default=44100, help='Sample rate in Hz (default: 44100)')
    parser.add_argument('--save', help='Save to WAV file instead of playing')
    args = parser.parse_args()

    s = Sound(frequency=args.freq, amplitude=args.amp, volume=args.vol,
              duration=args.dur, waveform=args.wave, sample_rate=args.rate)
    if args.save:
        s.save(args.save)
        print(f'Saved to {args.save}')
    else:
        s.play()
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
python -m pytest tests/test_soundgen.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add soundgen.py tests/test_soundgen.py
git commit -m "feat: add play() convenience function and CLI"
```

---

### Task 3: Manual smoke test and verification

**Files:**
- (none modified)

- [ ] **Step 1: Play a tone via CLI**

```bash
python soundgen.py --freq 440 --dur 500
```

Expected: Hear a 440 Hz tone for 0.5 seconds.

- [ ] **Step 2: Save to file and verify WAV structure**

```bash
python soundgen.py --freq 880 --dur 300 --wave square --save test_out.wav
python -c "import wave; w=wave.open('test_out.wav','rb'); print(w.getparams())"
```

Expected: `_wave_params(nchannels=1, sampwidth=2, framerate=44100, nframes=..., comptype='NONE', compname='not compressed')`

- [ ] **Step 3: Clean up test artifact**

```bash
rm -f test_out.wav
```
