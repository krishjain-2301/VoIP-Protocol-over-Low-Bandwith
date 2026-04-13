#!/usr/bin/env python3
"""
main.py — Emergency VoIP Launcher
Run this on BOTH PCs. It will:
  1. Install dependencies automatically
  2. Show your IP address (share this with the other PC)
  3. Ask: are you Sender (PC A) or Receiver (PC B)?
  4. Ask for the scenario and settings, then launch.
"""
import subprocess
import sys
import os
import socket


# ─────────────────────────────────────────────
# Step 1: Auto-install dependencies
# ─────────────────────────────────────────────
def install_deps():
    print("=" * 54)
    print("  Checking dependencies...")
    print("=" * 54)
    req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file, "-q"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("[ERROR] Dependency install failed:")
        print(result.stderr)
        print("\nTry manually:\n  pip install pyaudio opuslib")
        print("\nLinux fix:  sudo apt install libopus-dev portaudio19-dev")
        print("macOS fix:  brew install portaudio opus")
        print("Windows:    pip install pipwin && pipwin install pyaudio")
        input("\nPress ENTER to continue anyway...")
    else:
        print("  ✓  Dependencies OK (pyaudio, opuslib)")


# ─────────────────────────────────────────────
# Step 2: Show local IPs
# ─────────────────────────────────────────────
def get_local_ips():
    ips = []
    try:
        # Get all network interfaces
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ip.startswith("127.") or ":" in ip:
                continue
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    # Fallback
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            ips.append("Could not detect")
    return ips


def show_ip_info():
    ips = get_local_ips()
    print("\n" + "=" * 54)
    print("  YOUR IP ADDRESS(ES) — share with the other PC:")
    print("=" * 54)
    for ip in ips:
        print(f"    →  {ip}")
    print("=" * 54)
    print("  (Use the 192.168.x.x address if on WiFi/LAN)")
    print()


# ─────────────────────────────────────────────
# Step 3: Interactive menu
# ─────────────────────────────────────────────
SCENARIOS = [
    ("Scenario 1 - Same Room (0-1m)",             20_000, 60),
    ("Scenario 2 - Same Room with Obstacle (3-5m)", 12_000, 60),
    ("Scenario 3 - Different Rooms (1 wall)",       12_000, 80),
    ("Scenario 4 - Far Rooms / Multi-wall (10m+)",   6_000, 100),
    ("Scenario 5 - Simulated Emergency (via proxy)", 6_000, 120),
]


def pick_scenario():
    print("  Select test scenario:")
    for i, (name, br, _) in enumerate(SCENARIOS, 1):
        print(f"    {i}. {name}  [{br//1000} kbps]")
    while True:
        try:
            choice = int(input("\n  Enter number (1-5): ").strip())
            if 1 <= choice <= 5:
                return SCENARIOS[choice - 1]
        except ValueError:
            pass
        print("  Invalid — enter a number 1 to 5.")


def launch_receiver(port):
    scenario_name, _, jitter_ms = pick_scenario()
    print(f"\n  [RECEIVER] Listening on UDP port {port}")
    print(f"  Scenario  : {scenario_name}")
    print(f"  Jitter buf: {jitter_ms}ms\n")
    input("  Press ENTER to start receiving...")

    try:
        result = subprocess.run([
            sys.executable,
            os.path.join(os.path.dirname(__file__), "receiver", "receiver.py"),
            "--port",     str(port),
            "--scenario", scenario_name,
            "--jitter",   str(jitter_ms),
        ])
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


def launch_sender(port):
    # Ask for PC B's IP
    print("\n  Enter the IP address of PC B (the receiver).")
    print("  PC B should have shown its IP when it launched main.py.")
    while True:
        host = input("  PC B IP address: ").strip()
        if host:
            break
        print("  IP cannot be empty.")

    scenario_name, bitrate, _ = pick_scenario()
    print(f"\n  [SENDER] Will stream to {host}:{port}")
    print(f"  Scenario : {scenario_name}")
    print(f"  Bitrate  : {bitrate//1000} kbps\n")
    print("  Make sure PC B receiver is already running!")
    input("  Press ENTER to start sending...")

    try:
        result = subprocess.run([
            sys.executable,
            os.path.join(os.path.dirname(__file__), "sender", "sender.py"),
            "--host",     host,
            "--port",     str(port),
            "--scenario", scenario_name,
            "--bitrate",  str(bitrate),
        ])
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


def main():
    print("\n")
    print("╔══════════════════════════════════════════════════════╗")
    print("║   LOW-BANDWIDTH EMERGENCY VoIP — Smart Cities       ║")
    print("║   CN Project  |  Socket Programming  |  OPUS Codec  ║")
    print("╚══════════════════════════════════════════════════════╝")

    install_deps()
    show_ip_info()

    PORT = 5004

    print("  Are you the SENDER (PC A / mic) or RECEIVER (PC B / speaker)?")
    print("  1. Sender   — PC A  (captures mic, transmits)")
    print("  2. Receiver — PC B  (receives, plays audio)")
    print("  3. Impairment Proxy — simulate packet loss/delay")

    while True:
        try:
            role = int(input("\n  Enter 1, 2, or 3: ").strip())
            if role in (1, 2, 3):
                break
        except ValueError:
            pass
        print("  Invalid choice.")

    if role == 1:
        launch_sender(PORT)
    elif role == 2:
        launch_receiver(PORT)
    else:
        # Proxy mode
        print("\n  [PROXY] Network Impairment Proxy")
        fwd_host = input("  Forward to PC B IP: ").strip()
        loss   = input("  Packet loss % (e.g. 25): ").strip() or "25"
        delay  = input("  Extra delay ms (e.g. 80): ").strip() or "80"
        jitter = input("  Jitter ± ms (e.g. 30): ").strip() or "30"
        print(f"\n  Point PC A sender at THIS machine's IP, port 5005")
        input("  Press ENTER to start proxy...")
        try:
            result = subprocess.run([
                sys.executable,
                os.path.join(os.path.dirname(__file__), "tests", "impairment_proxy.py"),
                "--listen-port",  "5005",
                "--forward-host", fwd_host,
                "--forward-port", str(PORT),
                "--loss",   loss,
                "--delay",  delay,
                "--jitter", jitter,
            ])
            sys.exit(result.returncode)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
