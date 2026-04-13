"""
VoIP Packet Protocol - Low Bandwidth Emergency Voice Communication
Packet structure: | seq(4B) | timestamp(8B) | codec(1B) | payload_len(2B) | payload |
"""
import struct
import time

HEADER_FORMAT = "!IQBH"          # big-endian: uint32 seq, uint64 ts_us, uint8 codec, uint16 length
HEADER_SIZE   = struct.calcsize(HEADER_FORMAT)   # 15 bytes

SAMPLE_RATE   = 8000    # Hz  — narrowband (telephone quality, minimum bandwidth)
CHANNELS      = 1       # mono
FRAME_MS      = 20      # ms per OPUS frame
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)  # 160 samples

# Codec flags
CODEC_RAW  = 0   # raw PCM (uncompressed)
CODEC_OPUS = 1   # Opus compressed

# Adaptive bitrate levels (kbps)
BITRATE_HIGH   = 20_000   # clear LOS
BITRATE_MEDIUM = 12_000   # mild obstacle
BITRATE_LOW    =  6_000   # severe conditions / emergency

def pack_packet(seq: int, payload: bytes, codec: int = CODEC_RAW) -> bytes:
    ts_us = int(time.monotonic() * 1_000_000)
    header = struct.pack(HEADER_FORMAT, seq, ts_us, codec, len(payload))
    return header + payload


def unpack_packet(data: bytes):
    """Returns (seq, send_ts_us, codec, payload) or raises ValueError on bad data."""
    if len(data) < HEADER_SIZE:
        raise ValueError("Packet too short")
    seq, ts_us, codec, plen = struct.unpack_from(HEADER_FORMAT, data)
    payload = data[HEADER_SIZE: HEADER_SIZE + plen]
    if len(payload) != plen:
        raise ValueError("Truncated payload")
    return seq, ts_us, codec, payload

