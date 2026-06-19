# Ping Tester Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `ping_tester.py` to support N hosts with auto IPv4/IPv6 detection, latency-based failure classification, soundgen-based alerts, and configurable interval/threshold.

**Architecture:** Single-file rewrite of `ping_tester.py`. All logic stays in one file. `soundgen.py` is imported for alerts (already exists, no changes needed). Tests added in `tests/test_ping_tester.py`.

**Tech Stack:** Python 3, stdlib only (argparse, subprocess, socket, threading, time, pathlib), plus project-local `soundgen.py`.

## Global Constraints

- IPv4/IPv6: auto-detect per host (let system choose address family)
- Latency threshold: `--latency-ms` default 200ms
- Ping interval: `--interval` default 1s
- Volume: `--volume` default 100, range 0-100
- Alert sounds: 1000Hz sine wave via soundgen.Sound
- Log files: `logs/YYYYMMDD-HHMMSS_Full_log` + `_Fail_log`
- Fail classification: exit≠0 → FAIL, exit=0 & latency>threshold → SLOW, exit=0 & latency≤threshold → OK
- State machine: fail=2 → beep_1, fail=5 → beep_3 → silenced, success=3 → normal
- Isolated single fails not written to FAIL log
- No WAV file support

---

### Task 1: Add host_label() and classify_result() with tests

**Files:**
- Create: `tests/test_ping_tester.py`
- Modify: `ping_tester.py` (add two new functions at top after imports)

**Interfaces:**
- Produces: `host_label(host: str) -> str` — derive short label from hostname for display
- Produces: `classify_result(success: bool, latency_ms: float, threshold: int) -> str` — returns 'OK', 'SLOW', or 'FAIL'

- [ ] **Step 1: Write the failing test for host_label**

```python
import pytest
from ping_tester import host_label, classify_result


class TestHostLabel:
    def test_simple_domain(self):
        assert host_label("baidu.com") == "baidu"

    def test_subdomain(self):
        assert host_label("ipv6.google.com") == "google"

    def test_ipv4_address(self):
        assert host_label("8.8.8.8") == "8.8.8.8"

    def test_ipv6_address(self):
        assert host_label("2001:4860:4860::8888") == "2001:4860"

    def test_single_label(self):
        assert host_label("localhost") == "localhost"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ping_tester.py::TestHostLabel -v`
Expected: FAIL with "function not defined" (ImportError)

- [ ] **Step 3: Write the failing test for classify_result**

```python
class TestClassifyResult:
    def test_ok(self):
        assert classify_result(True, 45.0, 200) == 'OK'

    def test_slow(self):
        assert classify_result(True, 320.0, 200) == 'SLOW'

    def test_slow_at_threshold(self):
        # exactly at threshold is OK (not SLOW)
        assert classify_result(True, 200.0, 200) == 'OK'

    def test_fail(self):
        assert classify_result(False, 0, 200) == 'FAIL'

    def test_fail_ignores_latency(self):
        # FAIL always takes priority over latency check
        assert classify_result(False, 999.0, 200) == 'FAIL'
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_ping_tester.py::TestClassifyResult -v`
Expected: FAIL with "function not defined" (ImportError — both functions missing)

- [ ] **Step 5: Implement both functions in ping_tester.py**

Add these functions after the imports block (before the existing Logger class):

```python
def host_label(host):
    """Derive a short display label from a hostname."""
    # For IP addresses, return as-is (truncate long IPv6 for display)
    if ':' in host:
        parts = host.split(':')
        label = ':'.join(p for p in parts[:4] if p)
        return label or host
    if host.replace('.', '').isdigit():
        return host
    # For domain names, take the first meaningful segment
    parts = host.split('.')
    if len(parts) >= 2:
        return parts[-2]
    return host


def classify_result(success, latency_ms, threshold):
    """Classify ping result as 'OK', 'SLOW', or 'FAIL'."""
    if not success:
        return 'FAIL'
    if latency_ms > threshold:
        return 'SLOW'
    return 'OK'
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_ping_tester.py::TestHostLabel tests/test_ping_tester.py::TestClassifyResult -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_ping_tester.py ping_tester.py
git commit -m "feat: add host_label and classify_result functions"
```

---

### Task 2: Add soundgen-based alert functions with tests

**Files:**
- Modify: `ping_tester.py` (add two new functions, remove old `_alert_sound`, `_play_wav`, `_adjust_volume`, `_load_wav`)
- Modify: `tests/test_ping_tester.py` (add AlertState tests)

**Interfaces:**
- Consumes: `soundgen.Sound` class (already exists)
- Produces: `play_alert_first(volume: int) -> None` — 1000Hz/600ms/300ms warmup
- Produces: `play_alert_repeat(volume: int) -> None` — 3× 1000Hz/300ms with 150ms gap, 300ms warmup before first only

- [ ] **Step 1: Write AlertState tests**

```python
class TestAlertState:
    def test_initial_normal(self):
        from ping_tester import AlertState
        s = AlertState()
        assert not s.in_fail_group
        assert s.fails == 0

    def test_isolated_fail_no_alert(self):
        from ping_tester import AlertState
        s = AlertState()
        result = s.record_fail()
        assert result is None  # fail=1, no alert
        s.record_success()     # succeeds right after
        assert s.fails == 0

    def test_two_fails_triggers_beep_1(self):
        from ping_tester import AlertState
        s = AlertState()
        s.record_fail()
        result = s.record_fail()
        assert result == 'beep_1'

    def test_five_fails_triggers_beep_3_and_silences(self):
        from ping_tester import AlertState
        s = AlertState()
        for _ in range(4):
            s.record_fail()
        result = s.record_fail()  # 5th fail
        assert result == 'beep_3'
        assert s.silenced is True

    def test_silenced_stays_silent(self):
        from ping_tester import AlertState
        s = AlertState()
        for _ in range(5):
            s.record_fail()
        assert s.silenced
        result = s.record_fail()  # 6th fail
        assert result is None

    def test_recovery_resets_silenced(self):
        from ping_tester import AlertState
        s = AlertState()
        for _ in range(5):
            s.record_fail()
        assert s.silenced
        for _ in range(3):
            s.record_success()
        assert not s.silenced
        assert s.fails == 0

    def test_fail_then_success_before_threshold(self):
        from ping_tester import AlertState
        s = AlertState()
        s.record_fail()  # fail=1
        s.record_success()  # resets
        assert s.fails == 0
        # next single fail should still be isolated
        assert s.record_fail() is None
```

- [ ] **Step 2: Run AlertState tests (should pass — AlertState already exists)**

Run: `pytest tests/test_ping_tester.py::TestAlertState -v`
Expected: all PASS (AlertState class already exists in ping_tester.py)

- [ ] **Step 3: Remove old alert code, add new soundgen-based alert functions**

In `ping_tester.py`:

Remove these functions completely: `_alert_sound`, `_play_wav`, `_load_wav`, `_adjust_volume`.

Add these new functions in their place:

```python
def play_alert_first(volume=100):
    """1000Hz sine wave, 600ms duration, 300ms warmup before tone."""
    from soundgen import Sound
    Sound(frequency=1000, duration=600, warmup=300, volume=volume,
          waveform='sine').play()


def play_alert_repeat(volume=100):
    """3 short beeps: each 300ms, 150ms gap, 300ms warmup before first only."""
    import time
    from soundgen import Sound
    Sound(frequency=1000, duration=300, warmup=300, volume=volume,
          waveform='sine').play()
    time.sleep(0.15)
    Sound(frequency=1000, duration=300, volume=volume,
          waveform='sine').play()
    time.sleep(0.15)
    Sound(frequency=1000, duration=300, volume=volume,
          waveform='sine').play()
```

Remove the `io` and `struct` and `wave` imports at the top if they are no longer needed (check: `io`, `struct`, `wave` were only used by `_adjust_volume` and `_play_wav` — yes, remove them).

- [ ] **Step 4: Verify tests still pass**

Run: `pytest tests/test_ping_tester.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ping_tester.py tests/test_ping_tester.py
git commit -m "feat: replace winsound alerts with soundgen-based alerts"
```

---

### Task 3: Rewrite main() for multi-host support

**Files:**
- Modify: `ping_tester.py` (rewrite `main()` function)

**Interfaces:**
- Consumes: `host_label`, `classify_result`, `play_alert_first`, `play_alert_repeat`, `AlertState`, `Logger`, `resolve_ip`, `ping_host`
- Produces: complete working multi-host ping tester

- [ ] **Step 1: Rewrite main()**

Replace the entire `main()` function:

```python
def main():
    parser = argparse.ArgumentParser(
        description='Multi-host ping monitor with IPv4/IPv6 auto-detection')
    parser.add_argument('hosts', nargs='+', help='Hostnames or IPs to ping')
    parser.add_argument('--latency-ms', type=int, default=200,
                        help='Latency threshold in ms (default: 200)')
    parser.add_argument('--volume', type=int, default=100,
                        help='Beep volume 0-100 (default: 100)')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Seconds between ping rounds (default: 1)')
    args = parser.parse_args()

    vol = max(0, min(100, args.volume))
    threshold = max(1, args.latency_ms)
    interval = max(0.1, args.interval)

    # Logger
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    logger = Logger(ts)

    print(f'Ping Tester  |  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'  Hosts  : {", ".join(args.hosts)}')
    print(f'  Latency threshold: {threshold}ms')
    print(f'  Interval: {interval}s')
    print(f'  Vol     : {vol}%')
    print(f'  Full log: {logger.full}')
    print(f'  Fail log: {logger.fail}')
    print()
    header = (f'{"Time":<22} {"Host":<14} {"Target (IP)":<42} '
              f'{"Result":<20} Loss')
    print(header)
    print('-' * len(header))

    # Shared state
    running = True
    print_lock = threading.Lock()
    alerts = {}
    fail_buf = {}
    buf_lock = threading.Lock()
    sent = {}
    lost = {}
    counter_lock = threading.Lock()

    for host in args.hosts:
        label = host_label(host)
        alerts[host] = AlertState()
        fail_buf[host] = []
        sent[host] = 0
        lost[host] = 0

    def handle(host, ip, success, detail, latency_ms):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        label = host_label(host)

        classification = classify_result(success, latency_ms, threshold)

        with counter_lock:
            sent[host] += 1
            if classification != 'OK':
                lost[host] += 1
            total = sent[host]
            failed = lost[host]
            pct = f'{failed / total * 100:.1f}%' if total > 0 else '0%'

        if classification == 'OK':
            result_str = f'OK ({detail})'
        elif classification == 'SLOW':
            result_str = f'SLOW ({detail})'
        else:
            result_str = f'FAIL ({detail})'

        target = f'{host} ({ip})'
        loss_str = f'loss: {failed}/{total} ({pct})'

        # Console
        with print_lock:
            print(f'{now:<22} [{label:<12}] {target:<42} '
                  f'{result_str:<20} {loss_str}')

        # Full log
        logger.full_log(
            f'[{now}] [{label}] {target} - {result_str} - {loss_str}')

        st = alerts[host]
        entry = (f'[{now}] [{label}] {target} - '
                 f'{classification} ({detail})')

        if classification == 'OK':
            was_group = st.fails >= 2
            st.record_success()
            if not was_group:
                with buf_lock:
                    fail_buf[host].clear()
        else:
            action = st.record_fail()

            with buf_lock:
                fail_buf[host].append(entry)
                if st.fails >= 2:
                    for e in fail_buf[host]:
                        logger.fail_log(e)
                    logger.fail_sep()
                    fail_buf[host].clear()

            if action == 'beep_1':
                threading.Thread(target=play_alert_first,
                                 args=(vol,), daemon=True).start()
            elif action == 'beep_3':
                threading.Thread(target=play_alert_repeat,
                                 args=(vol,), daemon=True).start()

    def worker(host, offset):
        if offset:
            time.sleep(offset)
        while running:
            ok, detail, ip = ping_host(host)
            latency_ms = 0
            if ok:
                m = re.match(r'(\d+\.?\d*)', detail)
                if m:
                    latency_ms = float(m.group(1))
                else:
                    latency_ms = 0
            handle(host, ip, ok, detail, latency_ms)
            if running:
                time.sleep(interval)

    # Start threads, staggered to spread load
    threads = []
    for i, host in enumerate(args.hosts):
        t = threading.Thread(
            target=worker,
            args=(host, i * (interval / len(args.hosts))),
            daemon=True)
        t.start()
        threads.append(t)

    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(0.3)
    except KeyboardInterrupt:
        print('\nShutting down ...')
        running = False
        for t in threads:
            t.join(timeout=3)
        print('Stopped.')
```

- [ ] **Step 2: Update imports**

Remove: `import io`, `import struct`, `import wave` (no longer needed).

Keep: `import argparse`, `import os`, `import re`, `import socket`, `import subprocess`, `import sys`, `import threading`, `import time`, `from datetime import datetime`, `from pathlib import Path`.

- [ ] **Step 3: Verify the program starts**

Run: `python ping_tester.py baidu.com --interval 2 2>&1 | head -20` (run briefly, Ctrl+C)
Expected: header output shows, ping results appear with host labels and loss stats

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ping_tester.py
git commit -m "feat: rewrite main() for multi-host support with soundgen alerts"
```
