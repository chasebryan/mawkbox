import shutil
import tempfile
import unittest
import zlib
from pathlib import Path
import numpy as np
from mawkbox.signal import pack, unpack, modulate, demodulate, write_wav, decode, RATE
from mawkbox.video import render_video


class RoundTrips(unittest.TestCase):
    def test_plain_unicode_empty_and_limit(self):
        for text in ['', 'Good morning, NSA.', '你好 🍒\nmawkbox', 'a'*4096]:
            frame = pack(text)
            self.assertEqual(unpack(frame), text)
            self.assertEqual(unpack(demodulate(modulate(frame))), text)
        with self.assertRaises(ValueError):
            pack('a'*4097)

    def test_encryption_and_wrong_key(self):
        frame = pack('private message', 'correct horse')
        self.assertEqual(unpack(frame, 'correct horse'), 'private message')
        self.assertNotEqual(frame, pack('private message', 'correct horse'))
        for password in [None, 'wrong']:
            with self.assertRaises(ValueError):
                unpack(frame, password)
        with self.assertRaises(ValueError):
            pack('message', '')

    def test_tampering_even_with_recomputed_checksum(self):
        frame = bytearray(pack('private message', 'secret'))
        frame[-5] ^= 1
        with self.assertRaises(ValueError):
            unpack(bytes(frame), 'secret')
        frame[-4:] = zlib.crc32(frame[:-4]).to_bytes(4, 'big')
        with self.assertRaisesRegex(ValueError, 'Authentication failed'):
            unpack(bytes(frame), 'secret')

    def test_bad_inputs(self):
        for frame in [b'', b'MWK1', b'x'*100]:
            with self.assertRaises(ValueError):
                unpack(frame)
        with self.assertRaises(ValueError):
            demodulate(np.zeros(RATE))
        with self.assertRaises(ValueError):
            demodulate(np.zeros(5))

    def test_leading_silence_gain_and_noise(self):
        audio = modulate(pack('offset'))
        rng = np.random.default_rng(3)
        audio = np.concatenate([np.zeros(731), audio*.4])
        audio += rng.normal(0, .002, len(audio))
        self.assertEqual(unpack(demodulate(audio)), 'offset')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required')
    def test_wav_and_aac_mp4_encrypted_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for text, password in [('Good morning, NSA. 你好 🍒', 'secret'), ('', None)]:
                audio = modulate(pack(text, password))
                wav, mp4 = base/'message.wav', base/'message.mp4'
                write_wav(wav, audio)
                self.assertEqual(decode(wav, password), text)
                render_video(mp4, audio, wav)
                self.assertEqual(decode(mp4, password), text)


if __name__ == '__main__':
    unittest.main()
