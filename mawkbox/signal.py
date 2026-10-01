"""Versioned framing, authenticated encryption and four-tone audio transport."""
import os
import struct
import subprocess
import wave
import zlib
from pathlib import Path

import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

RATE = 48000
BAUD = 200
SAMPLES = RATE // BAUD
TONES = (1200, 1600, 2000, 2400)
MAX_TEXT = 4096
MAX_FRAME = MAX_TEXT + 64
HEADER = struct.Struct('>4sBBI')
MAGIC = b'MWK1'
STEM = bytes.fromhex('1be4936c27d8b14e')
TABLE = np.sin(2 * np.pi * np.array(TONES)[:, None] * np.arange(SAMPLES) / RATE)


def key(password, salt):
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode('utf-8'))


def pack(text, password=None):
    payload = text.encode('utf-8')
    if len(payload) > MAX_TEXT:
        raise ValueError('Message exceeds 4096 UTF-8 bytes.')
    flags = int(password is not None)
    if flags and not password:
        raise ValueError('Enter a passphrase or select plain encoding.')
    salt, nonce = (os.urandom(16), os.urandom(12)) if flags else (b'', b'')
    size = len(payload) + (44 if flags else 0)
    header = HEADER.pack(MAGIC, 1, flags, size)
    if flags:
        payload = salt + nonce + ChaCha20Poly1305(key(password, salt)).encrypt(nonce, payload, header)
    frame = header + payload
    return frame + struct.pack('>I', zlib.crc32(frame))


def unpack(frame, password=None):
    if len(frame) < HEADER.size + 4:
        raise ValueError('Truncated mawkbox frame.')
    magic, version, flags, size = HEADER.unpack_from(frame)
    if magic != MAGIC or version != 1 or flags not in (0, 1) or size > MAX_TEXT + (44 if flags else 0):
        raise ValueError('Unsupported or invalid mawkbox frame.')
    if len(frame) != HEADER.size + size + 4:
        raise ValueError('Invalid frame length.')
    if zlib.crc32(frame[:-4]) != struct.unpack('>I', frame[-4:])[0]:
        raise ValueError('Signal is damaged: checksum failed.')
    payload = frame[HEADER.size:-4]
    if flags:
        if len(payload) < 44:
            raise ValueError('Truncated encrypted payload.')
        if not password:
            raise ValueError('This transmission requires a passphrase.')
        try:
            payload = ChaCha20Poly1305(key(password, payload[:16])).decrypt(payload[16:28], payload[28:], frame[:HEADER.size])
        except InvalidTag as exc:
            raise ValueError('Authentication failed: wrong passphrase or altered message.') from exc
    return payload.decode('utf-8')


def symbols(data):
    b = np.frombuffer(data, dtype=np.uint8)
    return ((b[:, None] >> np.array([6, 4, 2, 0])) & 3).ravel()


def modulate(frame):
    signal = (TABLE[symbols(STEM + frame)] * 0.65).ravel()
    return np.concatenate((np.zeros(RATE // 10), signal, np.zeros(RATE // 10)))


def write_wav(path, audio):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        stream.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())


def read_audio(path):
    # ffmpeg provides one consistent PCM path for WAV, MP4 and resampling.
    result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
                             '-t', '90', '-f', 'f32le', '-ac', '1', '-ar', str(RATE), 'pipe:1'],
                            capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError('Cannot read audio: ' + result.stderr.decode(errors='replace')[-500:])
    return np.frombuffer(result.stdout, dtype='<f4').astype(float)


def demodulate(audio):
    if len(audio) < (len(STEM) + HEADER.size + 4) * 4 * SAMPLES:
        raise ValueError('Audio is too short for a mawkbox transmission.')
    # Locate the known stem using FFT cross-correlation. Search only the first
    # two seconds; arbitrary recordings/channel impairments are not supported.
    template = TABLE[symbols(STEM)].ravel()
    search = audio[:2 * RATE + len(template)]
    length = 1 << (len(search) + len(template) - 1).bit_length()
    correlation = np.fft.irfft(np.fft.rfft(search, length) * np.fft.rfft(template[::-1], length), length)
    scores = correlation[len(template)-1:len(search)]
    candidates = []
    for _ in range(12):
        start = int(np.argmax(scores))
        candidates.append(start)
        scores[max(0, start-SAMPLES//2):start+SAMPLES//2] = -np.inf
    bins = np.array(TONES) * SAMPLES // RATE
    for start in candidates:
        data = audio[start:]
        count = min(len(data)//SAMPLES, (len(STEM)+MAX_FRAME+HEADER.size+4)*4)
        energy = np.abs(np.fft.rfft(data[:count*SAMPLES].reshape(count, SAMPLES), axis=1)[:, bins])
        dibits = energy.argmax(axis=1).astype(np.uint8)
        dibits = dibits[:len(dibits)//4*4].reshape(-1, 4)
        raw = ((dibits[:,0]<<6) | (dibits[:,1]<<4) | (dibits[:,2]<<2) | dibits[:,3]).tobytes()
        if not raw.startswith(STEM + MAGIC) or len(raw) < len(STEM) + HEADER.size:
            continue
        frame = raw[len(STEM):]
        magic, version, flags, size = HEADER.unpack_from(frame)
        if version == 1 and flags in (0, 1) and size <= MAX_FRAME:
            frame = frame[:HEADER.size+size+4]
            if len(frame) == HEADER.size+size+4 and zlib.crc32(frame[:-4]) == struct.unpack('>I', frame[-4:])[0]:
                return frame
    raise ValueError('No intact mawkbox signal found. Use an original WAV or MP4 export.')


def decode(path, password=None):
    path = Path(path)
    if path.suffix.lower() == '.mawkbox':
        if path.stat().st_size > MAX_FRAME + HEADER.size + 4:
            raise ValueError('Frame exceeds the format size limit.')
        frame = path.read_bytes()
    else:
        frame = demodulate(read_audio(path))
    return unpack(frame, password)
