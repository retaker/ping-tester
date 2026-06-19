# Ping Tester

一个持续监控多主机网络连通性的命令行工具，支持 IPv4/IPv6 自动检测、延迟阈值判定和声音告警。

## 安装

```bash
git clone https://github.com/retaker/ping-tester.git
cd ping-tester
```

依赖 Python 3.8+，仅使用标准库和项目自带的 `soundgen` 模块，无需 `pip install`。

## 快速开始

```bash
# 监控单个主机
python ping_tester.py baidu.com

# 监控多个主机（自动检测 IPv4/IPv6，首次成功后锁定）
python ping_tester.py baidu.com 8.8.8.8 google.com

# 指定特定主机使用 IPv6（--ipv6 之后的主机强制 IPv6）
python ping_tester.py baidu.com --ipv6 bing.com

# 竞技游戏配置
python ping_tester.py baidu.com 8.8.8.8 --latency-ms 150 --interval 1
```

按 `Ctrl+C` 停止。

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `HOST ...` | (必填) | 一个或多个域名或 IP，IPv4/IPv6 自动检测 |
| `--ipv6 HOST ...` | - | `--ipv6` 之后的主机强制使用 IPv6 |
| `--latency-ms` | 200 | 高延迟阈值 (ms)，超过视为 SLOW |
| `--volume` | 100 | 提示音音量 0-100 |
| `--interval` | 1 | 每轮 ping 间隔秒数 |

> 默认情况下，每个主机会在首次 ping 成功后锁定该地址族，后续不再切换。使用 `--ipv6` 可以强制其后的主机使用 IPv6。

## 输出说明

### 控制台与日志

```
Time                   Host                 Target (IP)                      Result               Loss
----------------------------------------------------------------------------------------------------------------
2026-06-19 14:23:16    [IPv4] [baidu]       baidu.com (1.2.3.4)              OK (45ms)            loss: 0/10 (0.0%)
2026-06-19 14:23:18    [IPv6] [google]      google.com (2404:6800::)          SLOW (320ms)         loss: 2/10 (20.0%)
2026-06-19 14:23:20    [IPv4] [8.8.8.8]     8.8.8.8 (8.8.8.8)                FAIL (timeout)       loss: 5/10 (50.0%)
```

每行包含：时间戳、地址族标记 `[IPv4]`/`[IPv6]`、主机标签、目标 IP、结果和丢包率。

### 结果分类

| 结果 | 条件 |
|------|------|
| **OK** | ping 成功，延迟 ≤ 阈值 |
| **SLOW** | ping 成功，延迟 > 阈值 |
| **FAIL** | ping 失败（超时、不可达、DNS 失败等） |

### 日志文件

- `logs/YYYYMMDD-HHMMSS_Full_log` — 全部记录
- `logs/YYYYMMDD-HHMMSS_Fail_log` — 仅 SLOW 和 FAIL

## 声音告警

网络异常时通过 `soundgen` 模块播放 sine wave 提示音。

每个主机独立维护告警状态机：

```
正常 ──fail=2──→ 一声短鸣 ──fail=5──→ 三声短鸣 → 静默
  ↑                                              │
  └──────────── success=3 ←─────────────────────┘
```

| 阶段 | 触发条件 | 行为 |
|------|----------|------|
| 首次告警 | 连续 2 次失败 | 750Hz / 300ms / 半音量，单声 |
| 最终告警 | 连续 5 次失败 | 1000Hz / 300ms × 3（无间隔），随后进入静默 |
| 静默 | 已触发最终告警 | 后续失败不再发声，避免反复干扰 |
| 恢复 | 连续 3 次成功 | 清零计数器，解除静默，恢复正常 |

> **关键设计：** 无论在哪个阶段（首次告警后、最终告警后、静默中），都需要连续 3 次成功才清零失败计数。这防止了网络短暂波动导致告警反复触发。

## 许可

MIT

---

# Ping Tester

A CLI tool for continuous multi-host network connectivity monitoring with IPv4/IPv6 auto-detection, latency threshold classification, and audible alerts.

## Installation

```bash
git clone https://github.com/retaker/ping-tester.git
cd ping-tester
```

Requires Python 3.8+. No `pip install` needed — uses only stdlib and the bundled `soundgen` module.

## Quick Start

```bash
# Single host
python ping_tester.py baidu.com

# Multiple hosts (auto-detect IPv4/IPv6, locks on first success)
python ping_tester.py baidu.com 8.8.8.8 google.com

# Force specific hosts to use IPv6
python ping_tester.py baidu.com --ipv6 bing.com

# Competitive gaming
python ping_tester.py baidu.com 8.8.8.8 --latency-ms 150 --interval 1
```

Press `Ctrl+C` to stop.

## CLI Options

| Argument | Default | Description |
|----------|---------|-------------|
| `HOST ...` | (required) | One or more hostnames or IPs; IPv4/IPv6 auto-detected |
| `--ipv6 HOST ...` | - | Hosts after `--ipv6` are forced to use IPv6 |
| `--latency-ms` | 200 | Latency threshold in ms; exceeded → SLOW |
| `--volume` | 100 | Beep volume 0–100 |
| `--interval` | 1 | Seconds between ping rounds |

> By default, each host locks onto the first successful address family. Use `--ipv6` to force subsequent hosts to use IPv6.

## Output

### Console & Logs

```
Time                   Host                 Target (IP)                      Result               Loss
----------------------------------------------------------------------------------------------------------------
2026-06-19 14:23:16    [IPv4] [baidu]       baidu.com (1.2.3.4)              OK (45ms)            loss: 0/10 (0.0%)
2026-06-19 14:23:18    [IPv6] [google]      google.com (2404:6800::)          SLOW (320ms)         loss: 2/10 (20.0%)
2026-06-19 14:23:20    [IPv4] [8.8.8.8]     8.8.8.8 (8.8.8.8)                FAIL (timeout)       loss: 5/10 (50.0%)
```

Each line shows: timestamp, address family tag `[IPv4]`/`[IPv6]`, host label, target IP, result, and loss rate.

### Result Classification

| Result | Condition |
|--------|-----------|
| **OK** | Ping succeeded, latency ≤ threshold |
| **SLOW** | Ping succeeded, latency > threshold |
| **FAIL** | Ping failed (timeout, unreachable, DNS failure, etc.) |

### Log Files

- `logs/YYYYMMDD-HHMMSS_Full_log` — All records
- `logs/YYYYMMDD-HHMMSS_Fail_log` — SLOW and FAIL only

## Sound Alerts

Audible alerts via `soundgen` module (sine wave) when network issues are detected.

Each host maintains an independent alert state machine:

```
normal ──fail=2──→ single beep ──fail=5──→ triple beep → silenced
  ↑                                                    │
  └──────────────── success=3 ←───────────────────────┘
```

| Stage | Trigger | Behavior |
|-------|---------|----------|
| First alert | 2 consecutive fails | 750Hz / 300ms / half volume, single beep |
| Final alert | 5 consecutive fails | 1000Hz / 300ms × 3 (no gap), then enters silenced |
| Silenced | After final alert | Further failures are silent, no more beeps |
| Recovery | 3 consecutive successes | Resets counters, lifts silence, returns to normal |

> **Key design:** Recovery always requires 3 consecutive successes — whether after the first alert, final alert, or in silenced state. This prevents brief network blips from restarting the alert cycle.

## License

MIT
