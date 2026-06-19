#!/usr/bin/env python3
"""
Dual IPv4/IPv6 ping monitor with logging and alerting.

Usage:
    python ping_tester.py <domain1> <domain2> [--volume 0-100]

Example:
    python ping_tester.py google.com ipv6.google.com --volume 80
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

def resolve_ip(domain, use_ipv6):
    """Resolve *domain* to an IP address. Returns the IP string, or domain on failure."""
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
        return domain


def ping_host(domain, use_ipv6):
    """Ping *domain*.  Returns (success: bool, detail: str, ip: str)."""
    ip = resolve_ip(domain, use_ipv6)
    if sys.platform == 'win32':
        flag = '-6' if use_ipv6 else '-4'
        cmd = ['ping', flag, '-n', '1', domain]
    else:
        cmd = ['ping6', '-c', '1', domain] if use_ipv6 else ['ping', '-c', '1', domain]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return False, 'Ping timeout', ip
    except Exception as e:
        return False, str(e), ip

    # Exit-code based success / failure (language-independent)
    if r.returncode == 0:
        m = re.search(r'(?:time|时间|時間)[=<]\s*(\d+\.?\d*)\s*ms', output)
        return True, f'{m.group(1)}ms' if m else 'OK', ip

    # --- failure classification (English + Chinese) ---
    lower = output.lower()
    if 'could not find host' in lower or 'unknown host' in lower or 'name or service not known' in lower \
       or '找不到主机' in output or '找不到' in output or '找不到主機' in output:
        return False, 'DNS resolution failed', ip
    if 'timed out' in lower or '请求超时' in output or '要求等候逾時' in output:
        return False, 'Request timed out', ip
    if 'unreachable' in lower or '无法访问' in output or '無法連線' in output:
        return False, 'Destination unreachable', ip
    if 'ttl expired' in lower:
        return False, 'TTL expired', ip
    if '100% packet loss' in lower or '100% 丢失' in output or '100% 遗失' in output:
        return False, '100% packet loss', ip
    if 'general failure' in lower or '一般故障' in output or '一般失敗' in output:
        return False, 'General failure', ip
    return False, 'No response', ip


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
    parser = argparse.ArgumentParser(description='Dual IPv4/IPv6 ping monitor')
    parser.add_argument('domain1', help='Domain for IPv4 ping')
    parser.add_argument('domain2', help='Domain for IPv6 ping')
    parser.add_argument('--volume', type=int, default=100, help='Beep volume 0-100 (default: 100)')
    args = parser.parse_args()

    vol = max(0, min(100, args.volume))

    # ---- Logger ----
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    logger = Logger(ts)

    print(f'Ping Tester  |  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'  IPv4 : {args.domain1}')
    print(f'  IPv6 : {args.domain2}')
    print(f'  Vol  : {vol}%')
    print(f'  Full : {logger.full}')
    print(f'  Fail : {logger.fail}')
    print()
    print(f'{"Time":<22} {"Type":<6} {"Target (IP)":<42} {"Result":<28} Loss')
    print('-' * 100)

    # ---- Shared state ----
    running = True
    print_lock = threading.Lock()

    alert = {'IPv4': AlertState(), 'IPv6': AlertState()}

    # per-domain fail-log buffer
    fail_buf = {'IPv4': [], 'IPv6': []}
    buf_lock = threading.Lock()

    # per-domain packet counters
    sent = {'IPv4': 0, 'IPv6': 0}
    lost = {'IPv4': 0, 'IPv6': 0}
    counter_lock = threading.Lock()

    # ---- Result handler ----
    def handle(label, domain, ip, success, detail):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ts_str = f'[{now}]'

        with counter_lock:
            sent[label] += 1
            if not success:
                lost[label] += 1
            total = sent[label]
            failed = lost[label]
            pct = f'{failed / total * 100:.1f}%' if total > 0 else '0%'

        if success:
            result_str = f'OK ({detail})'
        else:
            result_str = f'FAIL ({detail})'

        target = f'{domain} ({ip})'
        loss_str = f'loss rate: {pct}'

        # console
        with print_lock:
            print(f'{ts_str:<22} [{label}] {target:<42} {result_str:<28} {loss_str}')

        # full log
        logger.full_log(f'{ts_str} [{label}] {target} - {result_str} - {loss_str}')

        st = alert[label]
        entry = f'{ts_str} [{label}] {target} - FAIL'

        if success:
            was_group = st.fails >= 2
            st.record_success()
            if not was_group:
                with buf_lock:
                    fail_buf[label].clear()  # discard isolated fail(s)
        else:
            action = st.record_fail()

            with buf_lock:
                fail_buf[label].append(entry)
                if st.fails >= 2:  # 2+ consecutive fails → flush buffer
                    for e in fail_buf[label]:
                        logger.fail_log(e)
                    fail_buf[label].clear()

            # alert
            if action == 'beep_1':
                threading.Thread(target=play_alert_first, args=(vol,), daemon=True).start()
            elif action == 'beep_3':
                threading.Thread(target=play_alert_repeat, args=(vol,), daemon=True).start()

    # ---- Workers ----
    def worker(label, domain, ipv6, offset):
        if offset:
            time.sleep(offset)
        while running:
            ok, detail, ip = ping_host(domain, ipv6)
            handle(label, domain, ip, ok, detail)
            if running:
                time.sleep(2)

    t1 = threading.Thread(target=worker, args=('IPv4', args.domain1, False, 0), daemon=True)
    t2 = threading.Thread(target=worker, args=('IPv6', args.domain2, True, 1), daemon=True)

    t1.start()
    t2.start()

    try:
        while t1.is_alive() or t2.is_alive():
            t1.join(0.5)
            t2.join(0.5)
    except KeyboardInterrupt:
        print('\nShutting down …')
        running = False
        t1.join(timeout=2)
        t2.join(timeout=2)
        print('Stopped.')


if __name__ == '__main__':
    main()
