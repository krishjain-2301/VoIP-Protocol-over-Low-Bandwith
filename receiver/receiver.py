#!/usr/bin/env python3
"""
VoIP Receiver — PC B
Usage: python receiver.py [--port 5004] [--scenario "Room A to B"] [--jitter 60]

Requires: pip install pyaudio opuslib
"""
import argparse
import socket
import sys
import threading
import time
import os
import signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pyaudio
try:
    import opuslib
    OPUS_AVAILABLE = True
except Exception:
    OPUS_AVAILABLE = False
    print("[WARN] opuslib not available — using raw PCM mode")

from common.protocol import (
    unpack_packet, SAMPLE_RATE, CHANNELS, FRAME_SAMPLES, FRAME_MS,
    CODEC_OPUS, CODEC_RAW
)
from common.jitter_buffer import JitterBuffer
from common.metrics import Metrics


# Silence frame: 320 bytes = 160 samples × 2 bytes (int16) of zeroes
SILENCE_FRAME = bytes(FRAME_SAMPLES * 2)


class VoIPReceiver:
    def __init__(self, port: int, scenario: str, jitter_ms: int):
        self.port     = port
        self.scenario = scenario
        self.running  = False
        self._stopped = False
        self.metrics  = Metrics(scenario)
        self.jbuf     = JitterBuffer(target_delay_ms=jitter_ms)

        # Audio frame callback for speech-to-text (set externally)
        self.on_audio_frame = None   # callable(pcm_bytes) or None

        # OPUS decoder
        if OPUS_AVAILABLE:
            self.decoder = opuslib.Decoder(SAMPLE_RATE, CHANNELS)
            print(f"[OPUS] Decoder ready: {SAMPLE_RATE}Hz")
        else:
            self.decoder = None

        # UDP socket — listen on all interfaces
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self.sock.settimeout(1.0)
        self.sock.bind(("", self.port))

        # PyAudio will be initialized in start() to avoid cross-thread COM issues on Windows
        self.pa     = None
        self.stream = None

    def start(self):
        self.running = True
        print(f"[RECV] Listening on UDP :{self.port} — scenario: '{self.scenario}'")
        print(f"[RECV] Jitter buffer: {self.jbuf.target_delay*1000:.0f}ms target | Press Ctrl+C to stop\n")

        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=FRAME_SAMPLES,
        )

        recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        recv_thread.start()

        try:
            self._playback_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _recv_loop(self):
        """Network receive thread — push to jitter buffer."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[WARN] Recv error: {e}")
                continue

            try:
                seq, ts_us, codec, payload = unpack_packet(data)
            except ValueError as e:
                print(f"[WARN] Bad packet: {e}")
                continue

            self.jbuf.push(seq, (codec, payload))
            self.metrics.record_packet(seq, ts_us, len(payload))

            if seq % 50 == 0:
                stats = self.jbuf.stats()
                codec_str = "OPUS" if codec == CODEC_OPUS else "PCM"
                print(f"[RX] seq={seq:6d} | {len(payload):4d}B {codec_str} | "
                      f"buf_ok={stats.get('ok',0)} miss={stats.get('missing',0)}")

    def _playback_loop(self):
        """Main thread — pop from jitter buffer, decode, play."""
        frame_duration = FRAME_MS / 1000

        while self.running:
            t_start = time.monotonic()
            result = self.jbuf.pop(silence_frame=None)

            if result is None:
                # Nothing ready — play silence to avoid underrun
                self.stream.write(SILENCE_FRAME)
            else:
                codec, payload = result

                if codec == CODEC_OPUS and self.decoder:
                    # Sender used Opus and we have a decoder
                    try:
                        pcm = self.decoder.decode(payload, FRAME_SAMPLES)
                    except Exception:
                        pcm = SILENCE_FRAME   # PLC: concealment via silence
                elif codec == CODEC_OPUS and not self.decoder:
                    # Sender used Opus but we don't have decoder — skip
                    pcm = SILENCE_FRAME
                    # Log once
                    if not hasattr(self, '_codec_warn'):
                        self._codec_warn = True
                        print("[WARN] Receiving Opus data but no decoder available — playing silence")
                else:
                    # Raw PCM — play directly
                    pcm = payload

                # Fire callback for speech-to-text if set
                if self.on_audio_frame and pcm != SILENCE_FRAME:
                    try:
                        self.on_audio_frame(pcm)
                    except Exception:
                        pass

                self.stream.write(pcm)

            # Maintain pacing
            elapsed = time.monotonic() - t_start
            sleep_t = frame_duration - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self.running = False
        time.sleep(0.2)
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.pa:
            self.pa.terminate()
        self.sock.close()
        self.metrics.dump_report()
        print(f"\n[RECV] Jitter buffer stats: {self.jbuf.stats()}")
        print("[RECV] Stopped.")


def main():
    parser = argparse.ArgumentParser(description="VoIP Emergency Receiver (PC B)")
    parser.add_argument("--port",     type=int, default=5004)
    parser.add_argument("--scenario", default="Test Scenario")
    parser.add_argument("--jitter",   type=int, default=60,
                        help="Jitter buffer target delay in ms (default 60)")
    args = parser.parse_args()

    recv = VoIPReceiver(args.port, args.scenario, args.jitter)
    signal.signal(signal.SIGINT, lambda *_: recv.stop() or sys.exit(0))
    recv.start()


if __name__ == "__main__":
    main()
