# mawkbox format, version 1

All multibyte integers use big-endian byte order. `.mawkbox` contains only the frame. No plaintext filename, passphrase, or message is embedded in audiovisual metadata.

| Field | Bytes | Value |
| --- | ---: | --- |
| Magic | 4 | ASCII `MWK1` |
| Version | 1 | `1` |
| Flags | 1 | `0` plain, `1` encrypted |
| Payload length | 4 | Payload size in bytes |
| Payload | variable | UTF-8 or encrypted payload |
| CRC32 | 4 | IEEE CRC32 of header + payload |

Encrypted payload: 16-byte random salt, 12-byte random nonce, then ChaCha20-Poly1305 ciphertext including its 16-byte tag. Passphrases are UTF-8 with no normalization. scrypt uses N=16384, r=8, p=1, producing a 32-byte key. The complete 10-byte header is AEAD associated data. Reusing passphrases is supported; salt and nonce are regenerated for every encode. Authentication must succeed before text is returned.

Maximum plaintext: 4096 UTF-8 bytes. Maximum encrypted payload: 4140 bytes. The decoder rejects unsupported versions/flags, inconsistent lengths, damaged CRCs and failed authentication.

## Audio transport

The waveform is 48,000 samples/s, mono signed 16-bit PCM in WAV. Every symbol lasts 240 samples (200 baud), carrying two bits. Each byte is emitted most significant dibit first.

| Dibit | Frequency |
| --- | ---: |
| `00` | 1200 Hz |
| `01` | 1600 Hz |
| `10` | 2000 Hz |
| `11` | 2400 Hz |

Each tone begins at phase zero, amplitude 0.65 full scale. Frequencies complete integer cycles per symbol. A transmission consists of 100 ms silence, an eight-byte stem `1b e4 93 6c 27 d8 b1 4e`, the frame, then 100 ms silence. The stem is outside the frame and is not part of the CRC.

Demodulation locates the stem by waveform cross-correlation and selects the strongest of four FFT tone bins per symbol. A candidate is accepted only after frame validation and CRC. Encrypted messages additionally require AEAD authentication. This version provides synchronization and error detection, without error correction or a guarantee under channel distortion.

Video is 800 × 450 at 24 fps, H.264/yuv420p, with AAC audio at 192 kbit/s. Its scope draws a 15 ms window of the corresponding generated waveform at each frame timestamp. The audio is authoritative for decoding; the video is a rendering of it. Encrypted output is intentionally randomized, even for identical input text and passphrases.
