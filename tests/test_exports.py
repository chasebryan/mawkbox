from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np
from mawkbox.exports import export_transmission
from mawkbox.signal import RATE, decode, demodulate, unpack


class Exports(unittest.TestCase):
    def test_encrypted_wav_saves_without_external_media_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'message.wav'
            # Even a missing/broken media installation must not prevent saving.
            with patch('subprocess.run', side_effect=AssertionError('No subprocess needed')), \
                 patch('subprocess.Popen', side_effect=AssertionError('No player needed')):
                result = export_transmission(target, 'Hello 🍒', 'secret')
            self.assertEqual(result.media.path, target)
            self.assertFalse(result.media.video)
            self.assertTrue(result.media.audio)
            self.assertTrue(all(path.is_file() for path in result.files))
            with wave.open(str(target), 'rb') as stream:
                self.assertEqual(stream.getframerate(), RATE)
                self.assertEqual(stream.getnchannels(), 1)
                self.assertAlmostEqual(result.media.duration, stream.getnframes()/RATE)
                samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2') / 32767
            self.assertEqual(unpack(demodulate(samples), 'secret'), 'Hello 🍒')
            self.assertEqual(unpack(target.with_suffix('.mawkbox').read_bytes(), 'secret'), 'Hello 🍒')

    def test_selected_filename_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            for selected, expected in [('report.v1', 'report.v1.wav'), ('file.WAV', 'file.WAV'), ('note', 'note.wav')]:
                with self.subTest(selected=selected):
                    result = export_transmission(Path(directory)/selected, 'Hello')
                    self.assertEqual(result.media.path.name, expected)
                    self.assertTrue(result.media.path.is_file())
                    self.assertEqual(unpack(result.media.path.with_suffix('.mawkbox').read_bytes()), 'Hello')

    def test_missing_passphrase_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'passphrase'):
                export_transmission(Path(directory)/'message.wav', 'Hello', '')
            self.assertEqual(list(Path(directory).iterdir()), [])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_mp4_export_still_recovers_its_message(self):
        with tempfile.TemporaryDirectory() as directory:
            result = export_transmission(Path(directory)/'message.v1.mp4', 'Video export', 'secret', video=True)
            self.assertTrue(result.media.video)
            self.assertEqual(len(result.files), 3)
            self.assertEqual(decode(result.media.path, 'secret'), 'Video export')
