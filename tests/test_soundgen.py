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
