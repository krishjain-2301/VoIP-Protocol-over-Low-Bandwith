"""
Adaptive Jitter Buffer
Holds incoming packets, releases them in order after a target delay.
Discards late packets; generates silence for lost ones (PLC fallback).
"""
import time
import threading
from collections import defaultdict


class JitterBuffer:
    def __init__(self, target_delay_ms: int = 60, max_delay_ms: int = 200):
        self.target_delay  = target_delay_ms / 1000
        self.max_delay     = max_delay_ms    / 1000
        self._buf          = {}           # seq → (arrive_time, payload)
        self._next_seq     = None
        self._lock         = threading.Lock()
        self._stats        = defaultdict(int)  # late, missing, ok

    def push(self, seq: int, payload: bytes):
        with self._lock:
            if self._next_seq is None:
                self._next_seq = seq
            self._buf[seq] = (time.monotonic(), payload)

    def pop(self, silence_frame: bytes = b"\x00" * 320):
        """
        Returns the next in-order payload, or silence_frame if missing/late.
        Returns None if buffer not ready yet.
        """
        with self._lock:
            if self._next_seq is None:
                return None

            seq = self._next_seq
            now = time.monotonic()

            if seq in self._buf:
                arrive_time, payload = self._buf[seq]
                wait = (arrive_time + self.target_delay) - now
                if wait > 0:
                    return None          # not ready yet — wait
                del self._buf[seq]
                self._next_seq += 1
                self._stats["ok"] += 1
                return payload

            # Check if we've waited too long for this seq
            # Look at oldest buffered packet
            if self._buf:
                oldest_seq = min(self._buf)
                oldest_arrive, _ = self._buf[oldest_seq]
                if (now - oldest_arrive) > self.target_delay:
                    # seq is lost; return silence
                    self._next_seq += 1
                    self._stats["missing"] += 1
                    return silence_frame

            return None   # buffer empty / nothing ready

    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)
