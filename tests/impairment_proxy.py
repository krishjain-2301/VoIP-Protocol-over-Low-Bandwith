#!/usr/bin/env python3
"""
Network Impairment Proxy — simulates packet loss, delay, and jitter.
Run on either PC between sender and receiver for controlled testing.

Usage: python impairment_proxy.py --loss 5 --delay 50 --jitter 20
       Then point sender at this machine's IP instead of PC B directly.
"""
import argparse
import socket
import random
import time
import threading


class ImpairmentProxy:
    def __init__(self, listen_port, forward_host, forward_port,
                 loss_pct, delay_ms, jitter_ms):
        self.listen_port  = listen_port
        self.fwd_host     = forward_host
        self.fwd_port     = forward_port
        self.loss_pct     = loss_pct / 100.0
        self.delay_s      = delay_ms / 1000.0
        self.jitter_s     = jitter_ms / 1000.0

        self.in_sock  = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.in_sock.bind(("", listen_port))

        self.total   = 0
        self.dropped = 0

    def run(self):
        print(f"[PROXY] Listening :{self.listen_port} → {self.fwd_host}:{self.fwd_port}")
        print(f"[PROXY] Loss={self.loss_pct*100:.1f}% | Delay={self.delay_s*1000:.0f}ms | "
              f"Jitter±{self.jitter_s*1000:.0f}ms")

        while True:
            data, _ = self.in_sock.recvfrom(4096)
            self.total += 1

            # Simulate packet loss
            if random.random() < self.loss_pct:
                self.dropped += 1
                if self.total % 50 == 0:
                    print(f"[PROXY] Dropped {self.dropped}/{self.total} packets")
                continue

            # Simulate delay + jitter in background thread
            jitter = random.uniform(-self.jitter_s, self.jitter_s)
            delay  = max(0, self.delay_s + jitter)
            threading.Thread(
                target=self._forward, args=(data, delay), daemon=True
            ).start()

    def _forward(self, data, delay):
        if delay > 0:
            time.sleep(delay)
        self.out_sock.sendto(data, (self.fwd_host, self.fwd_port))


def main():
    p = argparse.ArgumentParser(description="Network Impairment Proxy")
    p.add_argument("--listen-port",  type=int, default=5005)
    p.add_argument("--forward-host", required=True, help="PC B IP")
    p.add_argument("--forward-port", type=int, default=5004)
    p.add_argument("--loss",   type=float, default=0,  help="Packet loss %")
    p.add_argument("--delay",  type=float, default=0,  help="Extra delay ms")
    p.add_argument("--jitter", type=float, default=0,  help="Jitter ± ms")
    args = p.parse_args()

    proxy = ImpairmentProxy(
        args.listen_port, args.forward_host, args.forward_port,
        args.loss, args.delay, args.jitter
    )
    proxy.run()


if __name__ == "__main__":
    main()
