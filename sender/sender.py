#!/usr/bin/env python3
"""
VoIP Sender — PC A
Usage: python sender.py --host <PC_B_IP> [--port 5004] [--scenario "Room A to B"] [--bitrate 12000]

Requires: pip install pyaudio opuslib
"""
import argparse
import socket
import sys
import time
import threading
import signal
import os

# Adjust import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    import opuslib
    OPUS_AVAILABLE = True
except Exception:
    OPUS_AVAILABLE = False
    print("[WARN] opuslib not available — using raw PCM (higher bandwidth, dev mode)")

from common.protocol import (
    pack_packet, SAMPLE_RATE, CHANNELS, FRAME_SAMPLES,
    FRAME_MS, BITRATE_MEDIUM, CODEC_OPUS, CODEC_RAW
)
from common.metrics import Metrics


class VoIPSender:
    def __init__(self, host: str, port: int, scenario: str, bitrate: int):
        self.host     = host
        self.port     = port
        self.scenario = scenario
        self.bitrate  = bitrate
        self.running  = False
        self._stopped = False
        self.seq      = 0
        self.metrics  = Metrics(scenario)

        # OPUS encoder
        if OPUS_AVAILABLE:
            self.encoder = opuslib.Encoder(SAMPLE_RATE, CHANNELS, opuslib.APPLICATION_VOIP)
            self.encoder.bitrate = bitrate
            # DTX and FEC — use try/except because opuslib property setters
            # are buggy in some versions
            try:
                self.encoder.dtx = True
            except TypeError:
                pass
            try:
                self.encoder.inband_fec = True
            except TypeError:
                pass
            print(f"[OPUS] Encoder: {SAMPLE_RATE}Hz, {bitrate//1000}kbps, DTX+FEC")
        else:
            self.encoder = None

        # UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)

        # PyAudio will be initialized in start() to avoid cross-thread COM issues on Windows
        self.pa    = None
        self.stream = None

    def start(self):
        self.running = True
        print(f"[SENDER] Streaming to {self.host}:{self.port} — scenario: '{self.scenario}'")
        print(f"[SENDER] Bitrate: {self.bitrate//1000} kbps | Frame: {FRAME_MS}ms | Press Ctrl+C to stop\n")

        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=FRAME_SAMPLES,
        )

        try:
            self._capture_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _capture_loop(self):
        while self.running:
            try:
                raw = self.stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            except Exception as e:
                print(f"[WARN] Read error: {e}")
                continue

            # Encode
            if self.encoder:
                try:
                    payload = self.encoder.encode(raw, FRAME_SAMPLES)
                except Exception as e:
                    print(f"[WARN] Encode error: {e}")
                    continue
            else:
                payload = raw   # raw PCM fallback

            # Pack and send (include codec flag so receiver knows how to decode)
            codec = CODEC_OPUS if self.encoder else CODEC_RAW
            packet = pack_packet(self.seq, payload, codec)
            try:
                self.sock.sendto(packet, (self.host, self.port))
                self.metrics.record_sent()
                if self.seq % 50 == 0:   # print every ~1s
                    print(f"[TX] seq={self.seq:6d} | {len(payload):4d} bytes | "
                          f"bitrate~={len(payload)*8*1000//FRAME_MS//1000}kbps")
                self.seq += 1
            except Exception as e:
                print(f"[WARN] Send error: {e}")

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.pa:
            self.pa.terminate()
        self.sock.close()
        self.metrics.dump_report()
        print("[SENDER] Stopped.")


def main():
    parser = argparse.ArgumentParser(description="VoIP Emergency Sender (PC A)")
    parser.add_argument("--host",     required=True, help="IP address of PC B")
    parser.add_argument("--port",     type=int, default=5004)
    parser.add_argument("--scenario", default="Test Scenario")
    parser.add_argument("--bitrate",  type=int, default=BITRATE_MEDIUM,
                        help="OPUS bitrate (6000/12000/20000)")
    args = parser.parse_args()

    sender = VoIPSender(args.host, args.port, args.scenario, args.bitrate)
    signal.signal(signal.SIGINT, lambda *_: sender.stop() or sys.exit(0))
    sender.start()


if __name__ == "__main__":
    main()
