#!/usr/bin/env python3
"""
Multi-host ping monitor with IPv4/IPv6 auto-detection, latency tracking and alerting.

Usage:
    python ping_tester.py HOST [HOST ...] [--latency-ms 200] [--volume 100] [--interval 1]

Example:
    python ping_tester.py baidu.com google.com --latency-ms 150 --volume 80
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


# ---------------------------------------------------------------------------
# Alert state machine (per domain, independent)
# ---------------------------------------------------------------------------

class AlertState:
    """
    State machine for one domain's alert behaviour:

      normal ──fail=2──→ beep×1 ──fail=5──→ beep×3 → silenced
        ↑                                                  │
        └──── success=3 ──────────────────────────────────┘
    """

    def __init__(self):
        self.fails = 0
        self.successes = 0
        self.silenced = False

    def record_fail(self):
        self.fails += 1
        self.successes = 0

        if self.silenced:
            return None
        if self.fails == 2:
            return 'beep_1'
        if self.fails == 5:
            self.silenced = True
            return 'beep_3'
        return None

    def record_success(self):
        was_in_group = self.fails >= 2
        self.fails = 0
        self.successes += 1

        if self.silenced and self.successes >= 3:
            self.silenced = False
            self.successes = 0
            return 'reset'
        return 'reset' if was_in_group else None  # signal group-end for logging

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
            addr = res[4][0]
            if use_ipv6:
                # omit scope-id for display
                idx = addr.find('%')
                return addr[:idx] if idx != -1 else addr
            return addr
    except socket.gaierror:
        return None


def ping_host(domain):
    """Ping domain with auto IPv4/IPv6 detection.
    Returns (success: bool, detail: str, ip: str)."""
    last_detail = 'Ping failed'
    last_ip = domain
    for use_ipv6 in (False, True):
        ip = resolve_ip(domain, use_ipv6)
        if ip is None:
            continue
        last_ip = ip

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
            return True, f'{m.group(1)}ms' if m else 'OK', ip

        # --- failure classification (English + Chinese) ---
        lower = output.lower()
        if 'could not find host' in lower or 'unknown host' in lower or \
           'name or service not known' in lower \
           or '找不到主机' in output or '找不到' in output or '找不到主機' in output:
            return False, 'DNS resolution failed', ip
        if 'ttl expired' in lower:
            return False, 'TTL expired', ip
        if 'general failure' in lower or '一般故障' in output or '一般失敗' in output:
            return False, 'General failure', ip
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

    return False, last_detail, last_ip


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

    def fail_sep(self):
        self.fail_log('-------------------')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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


if __name__ == '__main__':
    main()
