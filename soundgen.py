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
                 waveform='sine', sample_rate=44100, warmup=0):
        self.frequency = max(20, min(20000, frequency))
        self.amplitude = max(0.0, min(1.0, amplitude))
        self.volume = max(0, min(100, volume))
        self.duration = max(1, duration)
        if waveform not in WAVEFORMS:
            raise ValueError(f'waveform must be one of {WAVEFORMS}, got {waveform!r}')
        self.waveform = waveform
        self.sample_rate = max(1, sample_rate)
        self.warmup = max(0, warmup)

    def _generate(self):
        nframes = int(self.sample_rate * self.duration / 1000)
        warmup_frames = int(self.sample_rate * self.warmup / 1000)
        factor = self.amplitude * (self.volume / 100.0)
        raw = self._generate_samples(nframes, factor)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            if warmup_frames > 0:
                wf.writeframes(b'\x00\x00' * warmup_frames)
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
            try:
                subprocess.run(['afplay', path], capture_output=True)
            except FileNotFoundError:
                pass
        else:
            try:
                subprocess.run(['aplay', path], capture_output=True)
            except FileNotFoundError:
                pass


def play(frequency=440, amplitude=1.0, volume=80, duration=1000,
         waveform='sine', sample_rate=44100, warmup=0):
    """Generate and play a sound with the given parameters."""
    Sound(frequency=frequency, amplitude=amplitude, volume=volume,
          duration=duration, waveform=waveform,
          sample_rate=sample_rate, warmup=warmup).play()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate and play a sound')
    parser.add_argument('--freq', type=float, default=440, help='Frequency in Hz (default: 440)')
    parser.add_argument('--amp', type=float, default=1.0, help='Amplitude 0.0-1.0 (default: 1.0)')
    parser.add_argument('--vol', type=int, default=80, help='Volume 0-100 (default: 80)')
    parser.add_argument('--dur', type=int, default=1000, help='Duration in ms (default: 1000)')
    parser.add_argument('--wave', choices=WAVEFORMS, default='sine', help='Waveform (default: sine)')
    parser.add_argument('--rate', type=int, default=44100, help='Sample rate in Hz (default: 44100)')
    parser.add_argument('--warmup', type=int, default=0, help='Silent lead-in before tone, in ms (default: 0)')
    parser.add_argument('--save', help='Save to WAV file instead of playing')
    args = parser.parse_args()

    s = Sound(frequency=args.freq, amplitude=args.amp, volume=args.vol,
              duration=args.dur, waveform=args.wave, sample_rate=args.rate,
              warmup=args.warmup)
    if args.save:
        s.save(args.save)
        print(f'Saved to {args.save}')
    else:
        s.play()
