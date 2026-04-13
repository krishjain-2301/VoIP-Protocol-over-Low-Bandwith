#!/usr/bin/env python3
"""
Automated Test Runner — guides you through all 5 test scenarios.
Run this on PC A. PC B must be running receiver.py --scenario matching each test.

Usage: python run_tests.py --host <PC_B_IP>
"""
import argparse
import subprocess
import sys
import time
import os

SCENARIOS = [
    {
        "name":    "Scenario 1 - Same Room (0-1m)",
        "desc":    "Place both PCs on the same desk, clear line of sight.",
        "bitrate": 20_000,
        "duration": 30,
        "expect":  "Latency < 10ms, loss ≈ 0%, MOS > 4.0",
    },
    {
        "name":    "Scenario 2 - Same Room with Obstacle (3-5m, wall nearby)",
        "desc":    "Place PCs 3-5m apart with a furniture obstacle between them.",
        "bitrate": 12_000,
        "duration": 30,
        "expect":  "Latency < 20ms, loss < 1%, MOS > 3.8",
    },
    {
        "name":    "Scenario 3 - Different Rooms (wall in between)",
        "desc":    "PC A in Room 1, PC B in Room 2. WiFi through a wall.",
        "bitrate": 12_000,
        "duration": 45,
        "expect":  "Latency < 50ms, loss < 3%, MOS > 3.5",
    },
    {
        "name":    "Scenario 4 - Far End of Building (10m+ multi-wall)",
        "desc":    "PCs at opposite ends of a corridor or different floors.",
        "bitrate": 6_000,
        "duration": 45,
        "expect":  "Latency < 100ms, loss < 8%, MOS > 2.8",
    },
    {
        "name":    "Scenario 5 - Simulated Emergency (25% loss + 80ms delay)",
        "desc":    "Run impairment_proxy.py with --loss 25 --delay 80 --jitter 30",
        "bitrate": 6_000,
        "duration": 30,
        "expect":  "Still intelligible, MOS > 1.5, FEC+jitter buffer recovery",
    },
]


def separator(title=""):
    print("\n" + "═"*60)
    if title:
        print(f"  {title}")
        print("═"*60)


def run_scenario(idx, sc, host, port):
    separator(sc["name"])
    print(f"\n  Description : {sc['desc']}")
    print(f"  Target      : {sc['expect']}")
    print(f"  Bitrate     : {sc['bitrate']//1000} kbps")
    print(f"  Duration    : {sc['duration']}s")
    print(f"\n  ⚠  On PC B, run:")
    print(f"     python receiver/receiver.py --port {port} --scenario \"{sc['name']}\"")
    input("\n  Press ENTER when PC B receiver is ready...")

    print(f"\n  [SENDER] Starting in 3s...")
    time.sleep(3)

    cmd = [
        sys.executable, "sender/sender.py",
        "--host", host,
        "--port", str(port),
        "--scenario", sc["name"],
        "--bitrate", str(sc["bitrate"]),
    ]
    proc = subprocess.Popen(cmd, cwd=os.path.dirname(__file__) or ".")

    print(f"  [SENDER] Streaming for {sc['duration']}s — speak into microphone now!")
    try:
        proc.wait(timeout=sc["duration"] + 5)
    except subprocess.TimeoutExpired:
        proc.terminate()

    print(f"\n  [DONE] Scenario {idx+1} complete.")
    input("  Press ENTER to continue to next scenario...")


def main():
    p = argparse.ArgumentParser(description="VoIP Test Runner")
    p.add_argument("--host", required=True, help="IP of PC B")
    p.add_argument("--port", type=int, default=5004)
    p.add_argument("--start-at", type=int, default=1,
                   help="Start at scenario number (1-5)")
    args = p.parse_args()

    separator("VoIP Emergency Communication — Test Suite")
    print(f"\n  PC B IP: {args.host}:{args.port}")
    print(f"  Running {len(SCENARIOS)} scenarios")
    print("\n  Prerequisites on BOTH PCs:")
    print("    pip install pyaudio opuslib")
    print("    Enable mic permissions, same WiFi network")

    for i, sc in enumerate(SCENARIOS):
        if i + 1 < args.start_at:
            continue
        run_scenario(i, sc, args.host, args.port)

    separator("All Scenarios Complete!")
    print("\n  Reports saved as report_*.json in the working directory.")
    print("  Use these for your CN project observations table.\n")


if __name__ == "__main__":
    main()
