#!/usr/bin/env python3
"""
Web GUI for Emergency VoIP System
Flask + Flask-SocketIO backend wrapping existing sender/receiver/proxy.
"""
import sys
import os
import json
import base64
import glob
import threading
import time
import socket
import logging
import io
import wave
import struct as _struct

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False
    print("[WARN] speech_recognition not installed — server-side STT disabled")

# Add parent dir so we can import common/, sender/, receiver/, tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO

# ── Flask app ───────────────────────────────────────────────
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SECRET_KEY"] = "voip-emergency-2026"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Suppress verbose Flask logs
log = logging.getLogger("werkzeug")
log.setLevel(logging.WARNING)

# ── Global state ────────────────────────────────────────────
active_components = {
    "sender":   None,   # VoIPSender instance or None
    "receiver": None,   # VoIPReceiver instance or None
    "proxy":    None,   # ImpairmentProxy instance or None
}
component_threads = {}
log_buffer = []       # recent log lines pushed to browser
LOG_MAX = 200
transcription_active = False   # whether to stream audio to browser for STT

# ── Server-side STT state ───────────────────────────────────
stt_lock = threading.Lock()
stt_audio_buffer = bytearray()         # accumulated raw PCM (16-bit LE, 8kHz, mono)
stt_worker_thread = None
stt_worker_running = False
STT_CHUNK_SECONDS = 3                  # transcribe every N seconds of audio
STT_SAMPLE_RATE = 8000
STT_SAMPLE_WIDTH = 2                   # 16-bit = 2 bytes
STT_CHANNELS = 1
STT_CHUNK_BYTES = STT_CHUNK_SECONDS * STT_SAMPLE_RATE * STT_SAMPLE_WIDTH * STT_CHANNELS

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def push_log(msg: str, level: str = "info"):
    """Buffer a log line and emit via WebSocket."""
    entry = {"ts": time.time(), "level": level, "msg": msg}
    log_buffer.append(entry)
    if len(log_buffer) > LOG_MAX:
        log_buffer.pop(0)
    socketio.emit("log_message", entry)


# ── Helper: get local IPs ──────────────────────────────────
def get_local_ips():
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ip.startswith("127.") or ":" in ip:
                continue
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            ips.append("Could not detect")
    return ips


# ── Static file serving ────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ── API: Network info ──────────────────────────────────────
@app.route("/api/network-info")
def network_info():
    return jsonify({"ips": get_local_ips()})


# ── API: Status ─────────────────────────────────────────────
@app.route("/api/status")
def status():
    result = {}
    for name, comp in active_components.items():
        if comp is not None:
            running = getattr(comp, "running", False)
            result[name] = "running" if running else "stopped"
        else:
            result[name] = "stopped"
    return jsonify(result)


# ── API: Reports ────────────────────────────────────────────
@app.route("/api/reports")
def list_reports():
    pattern = os.path.join(PROJECT_ROOT, "report_*.json")
    files = glob.glob(pattern)
    reports = []
    for f in sorted(files):
        try:
            with open(f, "r") as fp:
                data = json.load(fp)
            data["_filename"] = os.path.basename(f)
            reports.append(data)
        except Exception:
            pass
    return jsonify(reports)


@app.route("/api/reports/<name>")
def get_report(name):
    safe = os.path.basename(name)
    path = os.path.join(PROJECT_ROOT, safe)
    if not os.path.isfile(path):
        return jsonify({"error": "Not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


# ── API: Sender ─────────────────────────────────────────────
@app.route("/api/sender/start", methods=["POST"])
def start_sender():
    if active_components["sender"] is not None:
        return jsonify({"error": "Sender already running"}), 400

    data = request.json or {}
    host = data.get("host", "")
    port = int(data.get("port", 5004))
    scenario = data.get("scenario", "Web Test")
    bitrate = int(data.get("bitrate", 12000))

    if not host:
        return jsonify({"error": "Host IP is required"}), 400

    try:
        from sender.sender import VoIPSender
        sender = VoIPSender(host, port, scenario, bitrate)
        active_components["sender"] = sender

        def run():
            push_log(f"[SENDER] Starting → {host}:{port} | {scenario} | {bitrate//1000}kbps", "info")
            try:
                sender.start()
            except Exception as e:
                push_log(f"[SENDER] Error: {e}", "error")
            finally:
                active_components["sender"] = None
                push_log("[SENDER] Stopped", "warn")

        t = threading.Thread(target=run, daemon=True)
        t.start()
        component_threads["sender"] = t
        return jsonify({"status": "started"})
    except Exception as e:
        active_components["sender"] = None
        return jsonify({"error": str(e)}), 500


@app.route("/api/sender/stop", methods=["POST"])
def stop_sender():
    sender = active_components.get("sender")
    if sender is None:
        return jsonify({"error": "Sender not running"}), 400
    try:
        sender.stop()
    except Exception:
        pass
    active_components["sender"] = None
    push_log("[SENDER] Stop requested", "warn")
    return jsonify({"status": "stopped"})


# ── API: Receiver ───────────────────────────────────────────
@app.route("/api/receiver/start", methods=["POST"])
def start_receiver():
    if active_components["receiver"] is not None:
        return jsonify({"error": "Receiver already running"}), 400

    data = request.json or {}
    port = int(data.get("port", 5004))
    scenario = data.get("scenario", "Web Test")
    jitter_ms = int(data.get("jitter_ms", 60))

    try:
        from receiver.receiver import VoIPReceiver
        recv = VoIPReceiver(port, scenario, jitter_ms)
        active_components["receiver"] = recv

        # Attach audio-frame callback for server-side speech-to-text
        def audio_frame_cb(pcm_bytes):
            if transcription_active:
                with stt_lock:
                    stt_audio_buffer.extend(pcm_bytes)

        recv.on_audio_frame = audio_frame_cb

        def run():
            push_log(f"[RECEIVER] Starting on :{port} | {scenario} | jitter={jitter_ms}ms", "info")
            try:
                recv.start()
            except Exception as e:
                push_log(f"[RECEIVER] Error: {e}", "error")
            finally:
                active_components["receiver"] = None
                push_log("[RECEIVER] Stopped", "warn")

        t = threading.Thread(target=run, daemon=True)
        t.start()
        component_threads["receiver"] = t
        return jsonify({"status": "started"})
    except Exception as e:
        active_components["receiver"] = None
        return jsonify({"error": str(e)}), 500


@app.route("/api/receiver/stop", methods=["POST"])
def stop_receiver():
    recv = active_components.get("receiver")
    if recv is None:
        return jsonify({"error": "Receiver not running"}), 400
    try:
        recv.stop()
    except Exception:
        pass
    active_components["receiver"] = None
    push_log("[RECEIVER] Stop requested", "warn")
    return jsonify({"status": "stopped"})


# ── API: Proxy ──────────────────────────────────────────────
@app.route("/api/proxy/start", methods=["POST"])
def start_proxy():
    if active_components["proxy"] is not None:
        return jsonify({"error": "Proxy already running"}), 400

    data = request.json or {}
    listen_port = int(data.get("listen_port", 5005))
    fwd_host = data.get("forward_host", "")
    fwd_port = int(data.get("forward_port", 5004))
    loss = float(data.get("loss", 25))
    delay = float(data.get("delay", 80))
    jitter = float(data.get("jitter", 30))

    if not fwd_host:
        return jsonify({"error": "Forward host IP is required"}), 400

    try:
        from tests.impairment_proxy import ImpairmentProxy
        proxy = ImpairmentProxy(listen_port, fwd_host, fwd_port, loss, delay, jitter)
        active_components["proxy"] = proxy
        # Monkey-patch a stop flag
        proxy.running = True

        def run():
            push_log(f"[PROXY] Starting :{listen_port} → {fwd_host}:{fwd_port} | loss={loss}% delay={delay}ms jitter=±{jitter}ms", "info")
            try:
                # Override the run loop to be stoppable
                while proxy.running:
                    try:
                        proxy.in_sock.settimeout(1.0)
                        data_pkt, _ = proxy.in_sock.recvfrom(4096)
                    except socket.timeout:
                        continue
                    except Exception:
                        if proxy.running:
                            continue
                        break

                    proxy.total += 1
                    import random
                    if random.random() < proxy.loss_pct:
                        proxy.dropped += 1
                        if proxy.total % 50 == 0:
                            push_log(f"[PROXY] Dropped {proxy.dropped}/{proxy.total} packets", "warn")
                        continue

                    jit = random.uniform(-proxy.jitter_s, proxy.jitter_s)
                    d = max(0, proxy.delay_s + jit)
                    threading.Thread(target=proxy._forward, args=(data_pkt, d), daemon=True).start()

                    if proxy.total % 100 == 0:
                        push_log(f"[PROXY] Forwarded {proxy.total - proxy.dropped}/{proxy.total} packets", "info")
            except Exception as e:
                push_log(f"[PROXY] Error: {e}", "error")
            finally:
                active_components["proxy"] = None
                push_log("[PROXY] Stopped", "warn")

        t = threading.Thread(target=run, daemon=True)
        t.start()
        component_threads["proxy"] = t
        return jsonify({"status": "started"})
    except Exception as e:
        active_components["proxy"] = None
        return jsonify({"error": str(e)}), 500


@app.route("/api/proxy/stop", methods=["POST"])
def stop_proxy():
    proxy = active_components.get("proxy")
    if proxy is None:
        return jsonify({"error": "Proxy not running"}), 400
    proxy.running = False
    try:
        proxy.in_sock.close()
    except Exception:
        pass
    active_components["proxy"] = None
    push_log("[PROXY] Stop requested", "warn")
    return jsonify({"status": "stopped"})


# ── API: Live metrics ──────────────────────────────────────
@app.route("/api/metrics")
def live_metrics():
    result = {}
    for name in ["sender", "receiver"]:
        comp = active_components.get(name)
        if comp and hasattr(comp, "metrics"):
            try:
                result[name] = comp.metrics.get_live_snapshot()
            except Exception:
                result[name] = None
        else:
            result[name] = None

    # Proxy stats
    proxy = active_components.get("proxy")
    if proxy:
        result["proxy"] = {
            "total": getattr(proxy, "total", 0),
            "dropped": getattr(proxy, "dropped", 0),
        }
    else:
        result["proxy"] = None

    return jsonify(result)


# ── WebSocket: transcription toggle ────────────────────────
@socketio.on('toggle_transcription')
def handle_toggle_transcription(data):
    global transcription_active, stt_worker_thread, stt_worker_running, stt_audio_buffer
    transcription_active = data.get('active', False)
    state = 'ON' if transcription_active else 'OFF'
    push_log(f"[STT] Live transcription toggled {state}", "info")
    socketio.emit('transcription_state', {'active': transcription_active})

    if transcription_active:
        # Clear any stale audio and start the STT worker
        with stt_lock:
            stt_audio_buffer.clear()
        if stt_worker_thread is None or not stt_worker_thread.is_alive():
            stt_worker_running = True
            stt_worker_thread = threading.Thread(target=_stt_worker_loop, daemon=True)
            stt_worker_thread.start()
    else:
        stt_worker_running = False
        # Flush any remaining audio for a final transcription
        with stt_lock:
            remaining = bytes(stt_audio_buffer)
            stt_audio_buffer.clear()
        if remaining and len(remaining) >= STT_SAMPLE_RATE * STT_SAMPLE_WIDTH:
            _transcribe_chunk(remaining)


def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Wrap raw PCM (16-bit LE, 8kHz, mono) in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(STT_CHANNELS)
        wf.setsampwidth(STT_SAMPLE_WIDTH)
        wf.setframerate(STT_SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _transcribe_chunk(pcm_bytes: bytes):
    """Transcribe a chunk of PCM audio using speech_recognition."""
    if not SR_AVAILABLE:
        push_log("[STT] speech_recognition not installed", "error")
        return

    try:
        wav_data = _pcm_to_wav(pcm_bytes)
        recognizer = sr.Recognizer()
        audio = sr.AudioData(pcm_bytes, STT_SAMPLE_RATE, STT_SAMPLE_WIDTH)

        try:
            text = recognizer.recognize_google(audio)
            if text.strip():
                socketio.emit('stt_transcript', {'text': text.strip(), 'final': True})
                push_log(f"[STT] {text.strip()}", "info")
        except sr.UnknownValueError:
            # Could not understand — silence or noise, not an error
            pass
        except sr.RequestError as e:
            push_log(f"[STT] Google API error: {e}", "error")
    except Exception as e:
        push_log(f"[STT] Transcription error: {e}", "error")


def _stt_worker_loop():
    """Background worker: collect audio from the jitter-buffer output and
    transcribe in chunks.  Because audio only enters stt_audio_buffer AFTER
    the jitter buffer pops it, the transcription naturally inherits the
    correct delay/timing."""
    global stt_worker_running
    push_log("[STT] Server-side transcription worker started", "info")

    while stt_worker_running and transcription_active:
        time.sleep(0.5)  # poll interval

        with stt_lock:
            if len(stt_audio_buffer) < STT_CHUNK_BYTES:
                continue
            # Grab exactly one chunk
            chunk = bytes(stt_audio_buffer[:STT_CHUNK_BYTES])
            del stt_audio_buffer[:STT_CHUNK_BYTES]

        _transcribe_chunk(chunk)

    push_log("[STT] Server-side transcription worker stopped", "info")


# ── WebSocket: periodic metric push ────────────────────────
def metrics_emitter():
    """Background thread that pushes metrics every 500ms."""
    while True:
        time.sleep(0.5)
        payload = {}
        for name in ["sender", "receiver"]:
            comp = active_components.get(name)
            if comp and hasattr(comp, "metrics"):
                try:
                    payload[name] = comp.metrics.get_live_snapshot()
                except Exception:
                    payload[name] = None
            else:
                payload[name] = None

        proxy = active_components.get("proxy")
        if proxy:
            payload["proxy"] = {
                "total": getattr(proxy, "total", 0),
                "dropped": getattr(proxy, "dropped", 0),
            }
        else:
            payload["proxy"] = None

        # Status
        payload["status"] = {}
        for name, comp in active_components.items():
            if comp is not None:
                payload["status"][name] = "running"
            else:
                payload["status"][name] = "stopped"

        socketio.emit("metrics_update", payload)


# ── Main ────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n+------------------------------------------------------+")
    print("|   LOW-BANDWIDTH EMERGENCY VoIP - Web Dashboard       |")
    print("+------------------------------------------------------+")
    ips = get_local_ips()
    print(f"\n  Local IPs: {', '.join(ips)}")
    print(f"  Dashboard: http://localhost:5000")
    print(f"  Press Ctrl+C to stop\n")

    # Start background metric emitter
    t = threading.Thread(target=metrics_emitter, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
