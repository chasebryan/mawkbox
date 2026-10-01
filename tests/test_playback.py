import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from mawkbox.playback import Player, inspect_media
from mawkbox.signal import modulate, pack, write_wav
from mawkbox.video import render_video


TOOLS_READY = all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe', 'ffplay'))


@unittest.skipUnless(TOOLS_READY, 'full FFmpeg package required')
class Playback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.wav = Path(cls.folder.name) / 'transmission.wav'
        cls.mp4 = Path(cls.folder.name) / 'transmission.mp4'
        audio = modulate(pack('Encrypted playback. ' * 6, 'secret'))
        write_wav(cls.wav, audio)
        render_video(cls.mp4, audio, cls.wav)
        cls.short = Path(cls.folder.name) / 'short.wav'
        write_wav(cls.short, modulate(pack('hi')))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        # Exercise real audio decoding/output without requiring CI speakers.
        self.environment = patch.dict(os.environ, {'SDL_AUDIODRIVER': 'dummy', 'SDL_VIDEODRIVER': 'dummy'})
        self.environment.start()
        self.player = Player()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.player.close)

    def wait_for_frame(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            image = self.player.tick()
            if image is not None:
                return image
            time.sleep(.02)
        self.fail('No embedded video frame received.')

    def test_encrypted_mp4_plays_pauses_seeks_and_resumes(self):
        self.player.load(inspect_media(self.mp4))
        self.player.play()
        self.assertEqual(self.wait_for_frame().size, (640, 360))
        self.assertEqual(self.player.state, 'playing')
        self.assertLessEqual(self.player.frames.qsize(), 2)
        processes = (self.player._audio, self.player._video)
        self.player.pause()
        position = self.player.position
        time.sleep(.04)
        self.assertEqual(self.player.position, position)
        self.assertTrue(all(process.poll() is not None for process in processes))
        self.player.seek(.4)
        self.assertEqual(self.wait_for_frame().size, (640, 360))
        self.assertAlmostEqual(self.player.position, .4)
        self.player.resume()
        self.wait_for_frame()
        self.assertGreater(self.player.position, .4)
        self.player.stop()
        self.assertEqual(self.player.position, 0)
        self.assertEqual(self.player.state, 'ready')

    def test_audio_finishes_and_replays_without_video(self):
        self.player.load(inspect_media(self.short))
        self.player.play(video=False)
        self.assertIsNone(self.player._video)
        deadline = time.monotonic() + 5
        while self.player.state == 'playing' and time.monotonic() < deadline:
            self.player.tick()
            time.sleep(.02)
        self.assertEqual(self.player.state, 'ended')
        self.assertEqual(self.player.position, self.player.media.duration)
        self.player.play(video=False)
        self.assertLess(self.player.position, .1)
        process = self.player._audio
        self.player.close()
        self.assertIsNotNone(process.poll())

    def test_audio_mode_and_loading_another_file_stop_video(self):
        self.player.load(inspect_media(self.mp4))
        self.player.play()
        self.wait_for_frame()
        old = self.player._video
        self.player.play(0, video=False)
        self.assertIsNotNone(old.poll())
        self.assertIsNone(self.player._video)
        old_audio = self.player._audio
        self.player.load(inspect_media(self.wav))
        self.assertIsNotNone(old_audio.poll())
        self.assertEqual(self.player.state, 'ready')
        self.assertEqual(self.player.position, 0)

    def test_missing_audio_tool_cleans_up_video(self):
        self.player.load(inspect_media(self.mp4))
        which = shutil.which
        with patch('mawkbox.playback.shutil.which', side_effect=lambda name: None if name == 'ffplay' else which(name)):
            with self.assertRaisesRegex(RuntimeError, 'ffplay is missing'):
                self.player.play()
        self.assertIsNone(self.player._audio)
        self.assertIsNone(self.player._video)
        self.assertEqual(self.player.state, 'error')

    def test_audio_device_failure_is_reported(self):
        self.player.load(inspect_media(self.wav))
        with patch.dict(os.environ, {'SDL_AUDIODRIVER': 'mawkbox_nonexistent_driver'}):
            self.player.play(video=False)
            deadline = time.monotonic() + 5
            with self.assertRaisesRegex(RuntimeError, 'Playback failed'):
                while time.monotonic() < deadline:
                    self.player.tick()
                    time.sleep(.02)
        self.assertEqual(self.player.state, 'error')
        self.assertIsNone(self.player._audio)

    def test_invalid_media_is_rejected(self):
        bad = Path(self.folder.name) / 'invalid.mp4'
        bad.write_bytes(b'not a video')
        with self.assertRaises(ValueError):
            inspect_media(bad)
        with self.assertRaises(ValueError):
            inspect_media(Path(self.folder.name) / 'missing.wav')
        with self.assertRaises(ValueError):
            self.player.play()
