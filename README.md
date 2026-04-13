# Low-Bandwidth Emergency Voice Communication System
### Computer Networks (CN) Project — VoIP over UDP with Socket Programming

---

## Project Overview

A real-time voice over IP (VoIP) system designed for **emergency communication in smart cities**
where bandwidth is severely constrained (6–20 kbps). Built from scratch using raw UDP sockets,
the OPUS codec, and an adaptive jitter buffer.

### Key Concepts Demonstrated
- UDP socket programming (non-TCP for low latency)
- Custom packet framing (sequence numbers + timestamps)
- OPUS codec (narrowband, DTX, FEC)
- Jitter buffer for reorder/loss recovery
- Network metrics: latency, jitter, packet loss, MOS
- Controlled scenario testing (distance, walls, simulated loss)

---

## Architecture

```
PC A (Sender)                          PC B (Receiver)
──────────────                         ──────────────
Microphone                             Speaker
   │                                      ▲
PyAudio capture (8kHz mono)           PyAudio playback
   │                                      │
OPUS Encoder (6–20kbps, DTX+FEC)     OPUS Decoder (PLC)
   │                                      │
Custom Header:                        Jitter Buffer
  [seq:4B][ts:8B][len:2B][payload]       │
   │                                      │
UDP Socket TX ──── Network ────► UDP Socket RX
```

**Why UDP over TCP?**
- No retransmission delays (critical for voice)
- Lower overhead
- We handle reliability ourselves (sequence numbers, FEC, jitter buffer)

---

## Installation

### Both PCs
```bash
# Python 3.8+
pip install pyaudio opuslib

# Windows: if pyaudio fails:
pip install pipwin && pipwin install pyaudio

# Linux: if opuslib fails:
sudo apt install libopus-dev
pip install opuslib
```

---

## Running the System

### Step 1 — Find IP addresses
```bash
# Windows
ipconfig

# Linux/Mac
ip addr   # or ifconfig
```
Both PCs must be on the **same WiFi/LAN network**.

### Step 2 — Start Receiver (PC B) FIRST
```bash
python receiver/receiver.py --port 5004 --scenario "Scenario 1 - Same Room"

# Options:
#   --port       UDP listen port (default 5004)
#   --scenario   Label for the report
#   --jitter     Jitter buffer delay ms (default 60)
```

### Step 3 — Start Sender (PC A)
```bash
python sender/sender.py --host 192.168.1.X --port 5004 \
    --scenario "Scenario 1 - Same Room" --bitrate 20000

# Options:
#   --host     PC B IP address (required)
#   --port     UDP port (must match receiver)
#   --scenario Label for the report
#   --bitrate  6000 / 12000 / 20000 (bps)
```

### Step 4 — Run all scenarios with the automated runner
```bash
# On PC A:
python tests/run_tests.py --host 192.168.1.X
# Guides you through all 5 scenarios with prompts
```

---

## Test Scenarios

| # | Setup | Distance | Bitrate | Expected Latency | Expected Loss |
|---|-------|----------|---------|-----------------|---------------|
| 1 | Same room, LOS | 0–1 m | 20 kbps | < 10 ms | ≈ 0% |
| 2 | Same room, obstacle | 3–5 m | 12 kbps | < 20 ms | < 1% |
| 3 | Different rooms (1 wall) | ~8 m | 12 kbps | < 50 ms | < 3% |
| 4 | Far rooms / multi-wall | 10+ m | 6 kbps | < 100 ms | < 8% |
| 5 | Simulated emergency | (proxy) | 6 kbps | +80 ms | 25% |

### Scenario 5 — Simulated Impairment
Run the proxy on **either PC** (as a middleman):
```bash
python tests/impairment_proxy.py \
    --listen-port 5005 \
    --forward-host 192.168.1.X \   # PC B IP
    --forward-port 5004 \
    --loss 25 --delay 80 --jitter 30

# Then point sender at the proxy port:
python sender/sender.py --host <proxy_PC_IP> --port 5005 ...
```

---

## Metrics & Reports

After stopping (Ctrl+C), both sender and receiver save a JSON report:
```
report_Scenario_1_-_Same_Room.json
```

### Sample Report Output
```
====================================================
  SCENARIO: Scenario 1 - Same Room (0-1m)
====================================================
  Packets sent/recv : 1500 / 1498
  Packet loss       : 0.13 %
  Latency avg/min/max: 4.2 / 3.1 / 8.5 ms
  Jitter            : 1.2 ms
  Bitrate           : 18.4 kbps
  MOS estimate      : 4.3 / 5.0
====================================================
```

### MOS Score Reference
| MOS | Quality | Equivalent |
|-----|---------|------------|
| 5.0 | Excellent | Studio |
| 4.0–4.5 | Good | VoIP (Zoom/Teams) |
| 3.5–4.0 | Fair | Acceptable voice |
| 2.5–3.5 | Poor | Emergency usable |
| 1.0–2.5 | Bad | Barely intelligible |

---

## File Structure

```
voip_project/
├── common/
│   ├── protocol.py       # Packet format, constants
│   ├── jitter_buffer.py  # Adaptive jitter buffer
│   └── metrics.py        # Latency/loss/MOS tracking
├── sender/
│   └── sender.py         # PC A: mic → OPUS → UDP TX
├── receiver/
│   └── receiver.py       # PC B: UDP RX → OPUS → speaker
├── tests/
│   ├── impairment_proxy.py  # Simulate loss/delay
│   └── run_tests.py         # Automated scenario runner
└── README.md
```

---

## CN Concepts Addressed

| Topic | Implementation |
|-------|---------------|
| Transport layer | UDP sockets (SOCK_DGRAM) |
| Application layer | Custom VoIP protocol |
| Packet framing | sequence + timestamp + length |
| Reliability | Sequence numbers, FEC, jitter buffer |
| QoS metrics | Latency, jitter, loss, MOS, bitrate |
| Low bandwidth | OPUS narrowband 6–20 kbps, DTX |
| Error concealment | Packet Loss Concealment (PLC) |
| Network conditions | Distance, walls, interference, loss |

---

## Troubleshooting

**No audio / one-way only**
- Check firewall: allow UDP port 5004 on both PCs
- Windows: `netsh advfirewall firewall add rule name="VoIP" protocol=UDP dir=in localport=5004 action=allow`
- Linux: `sudo ufw allow 5004/udp`

**opuslib not installing**
- Linux: `sudo apt install libopus0 libopus-dev` then `pip install opuslib`
- Windows: Download opus.dll and place in the script directory

**PyAudio issues on macOS**
- `brew install portaudio && pip install pyaudio`
