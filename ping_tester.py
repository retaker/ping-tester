#!/usr/bin/env python3
"""
Multi-host ping monitor with IPv4/IPv6 auto-detection, latency tracking and alerting.

Usage:
    python ping_tester.py HOST [HOST ...] [--ipv6 HOST ...] [--latency-ms 200] [--volume 100] [--interval 1]

Example:
    python ping_tester.py baidu.com google.com --latency-ms 150 --volume 80
    python ping_tester.py baidu.com --ipv6 bing.com
"""

import argparse
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

LOGS_DIR = "logs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def host_label(host):
    """Derive a short display label from a hostname."""
    # For IP addresses, return as-is (truncate long IPv6 for display)
    if ':' in host:
        parts = host.split(':')
        label = ':'.join(p for p in parts[:2] if p)
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


# ---------------------------------------------------------------------------
# Audio alert
# ---------------------------------------------------------------------------

def play_alert_first(volume=100):
    """1000Hz sine wave, 600ms duration, 300ms warmup before tone."""
    from soundgen import Sound
    Sound(frequency=750, duration=300, warmup=300, volume=int(volume/2),
          waveform='sine').play()


def play_alert_repeat(volume=100):
    """3 short beeps: each 300ms, warmup 300ms, no gap."""
    from soundgen import Sound
    for _ in range(3):
        Sound(frequency=1000, duration=300, warmup=300, volume=volume,
              waveform='sine').play()


# ---------------------------------------------------------------------------
# Alert state machine (per domain, independent)
# ---------------------------------------------------------------------------

class AlertState:
    """
    Per-host alert state machine.

    State transitions:

      normal ──fail=2──→ beep×1 ──fail=5──→ beep×3 → silenced
        ↑                    ↑                     │
        └──── success=3 ←────┴──── success=3 ←─────┘

    Recovery always requires 3 consecutive successes, regardless of
    whether the host is in beep_1, beep_3, or silenced state. This
    prevents brief network blips from restarting the alert cycle.

    - fail=1: no alert. If 3 OKs follow, counter resets silently.
    - fail=2: triggers beep_1 (first warning). Needs 3 OKs to reset.
    - fail=3,4: no additional alert, continuing toward beep_3.
    - fail=5: triggers beep_3 (final alert), enters silenced state.
      Silenced state suppresses all further beeps.
    - success=3: resets fail counter, clears silenced flag, resets
      success counter. Back to normal.

    NOTE: isolated single failures (fail=1 followed by 3 OKs) are
    discarded from the FAIL log by the handle() caller.
    """

    def __init__(self):
        self.fails = 0          # consecutive failure count
        self.successes = 0      # consecutive success count (for unsilence)
        self.silenced = False   # alert suppressed after 5-fail beep_3

    def record_fail(self):
        """Call when a ping fails or exceeds latency threshold.
        Returns 'beep_1', 'beep_3', or None.

        Silenced state: always returns None (alerts are suppressed).
        Normal state:  fail=2 → 'beep_1'   (first warning)
                       fail=5 → 'beep_3'   (final alert, then silenced)
        """
        self.fails += 1
        self.successes = 0          # any fail resets recovery progress

        if self.silenced:
            return None             # suppressed — do not beep
        if self.fails == 2:
            return 'beep_1'         # two consecutive fails: first alert
        if self.fails == 5:
            self.silenced = True    # five fails: final alert, then silence
            return 'beep_3'
        return None                 # fail=1,3,4: no alert yet

    def record_success(self):
        """Call when a ping succeeds within latency threshold.

        Requires 3 consecutive successes to reset the fail counter
        and clear the silenced flag. This prevents brief recoveries
        from instantly restarting the full alert cycle.
        """
        self.successes += 1
        if self.successes >= 3:
            self.fails = 0
            self.successes = 0
            self.silenced = False

    @property
    def in_fail_group(self):
        return self.fails >= 2


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------

def resolve_ip(domain, use_ipv6=False):
    """Resolve *domain* to an IP address. Returns the IP string, or None on failure."""
    family = socket.AF_INET6 if use_ipv6 else socket.AF_INET
    try:
        for res in socket.getaddrinfo(domain, None, family=family, type=socket.SOCK_DGRAM):
            addr = str(res[4][0])
            if use_ipv6:
                # omit scope-id for display
                idx = addr.find('%')
                return addr[:idx] if idx != -1 else addr
            return addr
    except socket.gaierror:
        return None


def ping_host(domain, force_ipv6=None):
    """Ping domain with auto IPv4/IPv6 detection.
    Returns (success: bool, detail: str, ip: str, family: str).
    force_ipv6: None=auto, True=IPv6 only, False=IPv4 only."""
    last_detail = 'Ping failed'
    last_ip = domain
    last_family = 'IPv4'
    families = (True,) if force_ipv6 is True else \
               (False,) if force_ipv6 is False else \
               (False, True)
    for use_ipv6 in families:
        ip = resolve_ip(domain, use_ipv6)
        if ip is None:
            continue
        last_ip = ip
        last_family = 'IPv6' if use_ipv6 else 'IPv4'

        if sys.platform == 'win32':
            flag = '-6' if use_ipv6 else '-4'
            cmd = ['ping', flag, '-n', '1', domain]
        else:
            cmd = (['ping6', '-c', '1', domain] if use_ipv6
                   else ['ping', '-c', '1', domain])

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output = r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            last_detail = 'Ping timeout'
            continue
        except Exception as e:
            last_detail = str(e)
            continue

        if r.returncode == 0:
            m = re.search(r'(?:time|时间|時間)[=<]\s*(\d+\.?\d*)\s*ms', output)
            family = 'IPv6' if use_ipv6 else 'IPv4'
            return True, f'{m.group(1)}ms' if m else 'OK', ip, family

        # --- failure classification (English + Chinese) ---
        lower = output.lower()
        if 'could not find host' in lower or 'unknown host' in lower or \
           'name or service not known' in lower \
           or '找不到主机' in output or '找不到' in output or '找不到主機' in output:
            return False, 'DNS resolution failed', ip, 'IPv6' if use_ipv6 else 'IPv4'
        if 'ttl expired' in lower:
            return False, 'TTL expired', ip, 'IPv6' if use_ipv6 else 'IPv4'
        if 'general failure' in lower or '一般故障' in output or '一般失敗' in output:
            return False, 'General failure', ip, 'IPv6' if use_ipv6 else 'IPv4'
        # Transient failures — try next address family
        if 'timed out' in lower or '请求超时' in output or '要求等候逾時' in output:
            last_detail = 'Request timed out'
            continue
        if 'unreachable' in lower or '无法访问' in output or '無法連線' in output:
            last_detail = 'Destination unreachable'
            continue
        if '100% packet loss' in lower or '100% 丢失' in output or '100% 遗失' in output:
            last_detail = '100% packet loss'
            continue
        last_detail = 'No response'
        continue

    return False, last_detail, last_ip, last_family


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class Logger:
    def __init__(self, ts):
        Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
        self.full = Path(LOGS_DIR) / f'{ts}_Full_log'
        self.fail = Path(LOGS_DIR) / f'{ts}_Fail_log'
        self._lock = threading.Lock()

    def full_log(self, msg):
        with self._lock:
            with open(self.full, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')

    def fail_log(self, msg):
        with self._lock:
            with open(self.fail, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Multi-host ping monitor with IPv4/IPv6 auto-detection')
    parser.add_argument('--latency-ms', type=int, default=200,
                        help='Latency threshold in ms (default: 200)')
    parser.add_argument('--volume', type=int, default=100,
                        help='Beep volume 0-100 (default: 100)')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Seconds between ping rounds (default: 1)')
    known, unknown = parser.parse_known_args()

    # Process remaining args: hosts with optional --ipv6 marker
    hosts = []
    host_ipv6 = {}
    current_ipv6 = None  # None = auto
    for arg in unknown:
        if arg == '--ipv6':
            current_ipv6 = True
        else:
            hosts.append(arg)
            host_ipv6[arg] = current_ipv6
    if not hosts:
        parser.error('at least one HOST is required')

    vol = max(0, min(100, known.volume))
    threshold = max(1, known.latency_ms)
    interval = max(0.1, known.interval)

    # Logger
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    logger = Logger(ts)

    print(f'Ping Tester  |  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'  Hosts  : {", ".join(hosts)}')
    print(f'  Latency threshold: {threshold}ms')
    print(f'  Interval: {interval}s')
    print(f'  Vol     : {vol}%')
    print(f'  Full log: {logger.full}')
    print(f'  Fail log: {logger.fail}')
    print()
    header = (f'{"Time":<22} {"Host":<20} {"Target (IP)":<42} '
              f'{"Result":<28} Loss')
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

    for host in hosts:
        alerts[host] = AlertState()
        fail_buf[host] = []
        sent[host] = 0
        lost[host] = 0

    def handle(host, ip, success, detail, latency_ms, family):
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

        st = alerts[host]

        # Predict alert action for this line (before state change)
        pending_action = None
        if classification != 'OK' and not st.silenced:
            if st.fails == 1:   # about to trigger beep_1
                pending_action = 'beep_1'
            elif st.fails == 4:  # about to trigger beep_3
                pending_action = 'beep_3'

        COLOR_RESET = '\033[0m'
        COLOR_BEEP1 = '\033[38;5;178m'   # dark gold — readable on light & dark
        COLOR_BEEP3 = '\033[38;5;203m'   # salmon red — readable on light & dark

        # Console
        with print_lock:
            if pending_action == 'beep_1':
                print(f'{COLOR_BEEP1}{now:<22} [{family}] [{label}] {target:<42} '
                      f'{result_str:<28} {loss_str}{COLOR_RESET}')
            elif pending_action == 'beep_3':
                print(f'{COLOR_BEEP3}{now:<22} [{family}] [{label}] {target:<42} '
                      f'{result_str:<28} {loss_str}{COLOR_RESET}')
            else:
                print(f'{now:<22} [{family}] [{label}] {target:<42} '
                      f'{result_str:<28} {loss_str}')

        # Full log
        logger.full_log(
            f'[{now}] [{family}] [{label}] {target} - {result_str} - {loss_str}')

        entry = (f'[{now}] [{family}] [{label}] {target} - '
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
                if st.fails == 2:
                    for e in fail_buf[host]:
                        logger.fail_log(e)
                    fail_buf[host].clear()
                elif st.fails > 2:
                    logger.fail_log(entry)
                    fail_buf[host].clear()

            if action == 'beep_1':
                threading.Thread(target=play_alert_first,
                                 args=(vol,), daemon=True).start()
            elif action == 'beep_3':
                threading.Thread(target=play_alert_repeat,
                                 args=(vol,), daemon=True).start()

    force_ipv6 = host_ipv6  # dict: host -> None (auto) or True (IPv6)

    def worker(host, offset):
        if offset:
            time.sleep(offset)
        prefer = force_ipv6.get(host)  # None=auto, True=IPv6 forced
        while running:
            ok, detail, ip, family = ping_host(host, prefer)
            if ok and force_ipv6.get(host) is None:
                prefer = (family == 'IPv6')  # lock in first successful family
            latency_ms = 0
            if ok:
                m = re.match(r'(\d+\.?\d*)', detail)
                if m:
                    latency_ms = float(m.group(1))
                else:
                    latency_ms = 0
            handle(host, ip, ok, detail, latency_ms, family)
            if running:
                time.sleep(interval)

    # Start threads, staggered to spread load
    threads = []
    for i, host in enumerate(hosts):
        t = threading.Thread(
            target=worker,
            args=(host, i * (interval / len(hosts))),
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


if __name__ == '__main__':
    main()
