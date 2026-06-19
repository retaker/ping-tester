# Ping Tester 重设计

## 目标

将 `ping_tester.py` 从固定的双主机（1 IPv4 + 1 IPv6）扩展为支持任意数量主机的通用 ping 监控工具，
使用 `soundgen` 模块替代系统提示音，并增加延迟阈值判定。

## 决策记录

- IPv4/IPv6 判定：自动检测（由系统 DNS 解析决定地址族），不要求用户指定
- 延迟阈值：默认 200ms，超过阈值视为 SLOW
- 告警方式：仅使用 soundgen 模块生成 1000Hz sine wave，移除 WAV 文件支持
- 音量默认值：100
- Ping 间隔默认值：1s

## CLI

```
python ping_tester.py HOST [HOST ...] [--latency-ms 200] [--volume 100] [--interval 1]
```

| 参数 | 说明 |
|------|------|
| `HOST` | 一个或多个域名或 IP 地址，IPv4/IPv6 由系统自动选择 |
| `--latency-ms` | 高延迟判定阈值（毫秒），默认 200 |
| `--volume` | 提示音音量 0-100，默认 100 |
| `--interval` | 每轮 ping 间隔秒数，默认 1 |

## 架构

```
ping_tester.py
├── CLI (argparse)
├── Ping 工作线程 — 每个 host 一个线程，间隔由 --interval 指定
│   ├── resolve_ip() — DNS 解析
│   ├── ping_host() — subprocess 调用系统 ping
│   ├── 结果分类 — OK / FAIL / SLOW
│   └── 更新 AlertState，写入 Logger
├── AlertState — 每个 host 独立的状态机
├── Logger — 写入 logs/YYYYMMDD-HHMMSS_Full_log + _Fail_log
└── Sound 告警 — 调用 soundgen.Sound
```

## 失败判定

| 结果 | 条件 | 逻辑 |
|------|------|------|
| **OK** | ping 返回码=0，延迟 ≤ latency-ms 阈值 | 推进 AlertState.record_success() |
| **SLOW** | ping 返回码=0，延迟 > latency-ms 阈值 | 推进 AlertState.record_fail() |
| **FAIL** | ping 返回码≠0（超时、不可达、DNS失败、100%丢包等） | 推进 AlertState.record_fail() |

## 告警状态机（每个 host 独立）

```
normal ──fail=2──→ beep_1 ──fail=5──→ beep_3 → silenced
  ↑                                              │
  └──────────── success=3 ←──────────────────────┘
```

- **beep_1**: 首次检测到连续失败（fail=2），播放 1000Hz sine wave 600ms，300ms warmup
- **beep_3**: 持续失败（fail=5），播放 3 次短促 beep（300ms beep, 150ms 间隔），首次前 300ms warmup，之后静默
- **恢复**: 连续成功 3 次后重置到 normal 状态
- 孤立的单次失败（fail=1 后立即 OK）不会写入 FAIL 日志

## 声音告警实现

使用 `soundgen.Sound` 类：

```python
from soundgen import Sound

# 首次失败告警
Sound(frequency=1000, duration=600, warmup=300, volume=volume, waveform='sine').play()

# 持续失败告警 (3次短促beep)
Sound(frequency=1000, duration=300, warmup=300, volume=volume, waveform='sine').play()
time.sleep(0.15)
Sound(frequency=1000, duration=300, volume=volume, waveform='sine').play()
time.sleep(0.15)
Sound(frequency=1000, duration=300, volume=volume, waveform='sine').play()
```

## 输出格式

### 控制台 & FULL 日志

```
[2026-06-19 14:30:05] [host_label] host (ip) - OK (45ms) - loss: 2/100 (2.0%)
[2026-06-19 14:30:07] [host_label] host (ip) - SLOW (320ms) - loss: 15/100 (15.0%)
[2026-06-19 14:30:09] [host_label] host (ip) - FAIL (timeout) - loss: 16/101 (15.8%)
```

### FAIL 日志

仅记录 FAIL 和 SLOW 行。失败事件之间用分隔线隔开。

### 日志文件

- `logs/YYYYMMDD-HHMMSS_Full_log` — 全部记录
- `logs/YYYYMMDD-HHMMSS_Fail_log` — 仅失败记录
