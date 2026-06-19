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
