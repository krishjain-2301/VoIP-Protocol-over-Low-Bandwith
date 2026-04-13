"""
Metrics Collector — tracks latency, jitter, packet loss, and bitrate.
Thread-safe; call record_packet() from the receive loop, dump_report() at end.
"""
import time
import statistics
import json
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class Metrics:
    scenario: str
    start_time: float = field(default_factory=time.time)

    _lock:          Lock  = field(default_factory=Lock, repr=False)
    _latencies_ms:  list  = field(default_factory=list, repr=False)
    _recv_seq:      set   = field(default_factory=set,  repr=False)
    _expected_seq:  int   = field(default=0, repr=False)
    _total_sent:    int   = field(default=0, repr=False)
    _bytes_recv:    int   = field(default=0, repr=False)

    def record_sent(self):
        with self._lock:
            self._total_sent += 1

    def record_packet(self, seq: int, send_ts_us: int, payload_len: int):
        now_us = int(time.monotonic() * 1_000_000)
        latency_ms = (now_us - send_ts_us) / 1000.0
        with self._lock:
            self._latencies_ms.append(latency_ms)
            self._recv_seq.add(seq)
            self._bytes_recv += payload_len

    def _packet_loss_pct(self):
        # If this is the Sender (we track sent packets but receive none), we can't calculate loss, return 0
        if self._total_sent > 0 and not self._recv_seq:
            return 0.0
        
        # If this is the Receiver (we receive packets but send none), use sequence numbers
        if self._total_sent == 0:
            if not self._recv_seq:
                return 0.0
            expected = max(self._recv_seq) + 1
            lost = expected - len(self._recv_seq)
            return max(0.0, lost / expected * 100)

        # If somehow we do both:
        lost = self._total_sent - len(self._recv_seq)
        return max(0.0, lost / self._total_sent * 100)

    def _mos_estimate(self, loss_pct, avg_latency):
        """Simple E-Model approximation → MOS 1–5."""
        r = 93.2 - (avg_latency / 10) - (2.5 * loss_pct)
        r = max(0, min(100, r))
        if r < 0:
            return 1.0
        mos = 1 + 0.035*r + r*(r-60)*(100-r)*7e-6
        return round(max(1.0, min(5.0, mos)), 2)

    def get_live_snapshot(self) -> dict:
        """Return current metrics snapshot for real-time dashboard (no file write)."""
        elapsed = time.time() - self.start_time
        with self._lock:
            lats = self._latencies_ms[-200:] if self._latencies_ms else [0]
            loss = self._packet_loss_pct()
            avg_lat = statistics.mean(lats)
            jitter = statistics.stdev(lats) if len(lats) > 1 else 0
            bitrate_kbps = (self._bytes_recv * 8 / 1000) / elapsed if elapsed > 0 else 0
            return {
                "packets_sent":    self._total_sent,
                "packets_recv":    len(self._recv_seq),
                "packet_loss_pct": round(loss, 2),
                "latency_avg_ms":  round(avg_lat, 2),
                "latency_min_ms":  round(min(lats), 2),
                "latency_max_ms":  round(max(lats), 2),
                "jitter_ms":       round(jitter, 2),
                "bitrate_kbps":    round(bitrate_kbps, 2),
                "mos_estimate":    self._mos_estimate(loss, avg_lat),
                "duration_s":      round(elapsed, 1),
            }

    def dump_report(self) -> dict:
        elapsed = time.time() - self.start_time
        with self._lock:
            lats = self._latencies_ms or [0]
            loss = self._packet_loss_pct()
            avg_lat = statistics.mean(lats)
            jitter   = statistics.stdev(lats) if len(lats) > 1 else 0
            bitrate_kbps = (self._bytes_recv * 8 / 1000) / elapsed if elapsed > 0 else 0

        report = {
            "scenario":        self.scenario,
            "packets_sent":    self._total_sent,
            "packets_recv":    len(self._recv_seq),
            "packet_loss_pct": round(loss, 2),
            "latency_avg_ms":  round(avg_lat, 2),
            "latency_min_ms":  round(min(lats), 2),
            "latency_max_ms":  round(max(lats), 2),
            "jitter_ms":       round(jitter, 2),
            "bitrate_kbps":    round(bitrate_kbps, 2),
            "mos_estimate":    self._mos_estimate(loss, avg_lat),
            "duration_s":      round(elapsed, 1),
        }

        print("\n" + "="*52)
        print(f"  SCENARIO: {self.scenario}")
        print("="*52)
        print(f"  Packets sent/recv : {report['packets_sent']} / {report['packets_recv']}")
        print(f"  Packet loss       : {report['packet_loss_pct']} %")
        print(f"  Latency avg/min/max: {report['latency_avg_ms']} / {report['latency_min_ms']} / {report['latency_max_ms']} ms")
        print(f"  Jitter            : {report['jitter_ms']} ms")
        print(f"  Bitrate           : {report['bitrate_kbps']} kbps")
        print(f"  MOS estimate      : {report['mos_estimate']} / 5.0")
        print("="*52)

        import re
        safe_name = re.sub(r'[\\/*?:"<>|]', '-', self.scenario).replace(' ', '_')
        fname = f"report_{safe_name}.json"
        with open(fname, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  Report saved → {fname}\n")
        return report
