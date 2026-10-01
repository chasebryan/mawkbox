import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('DISPLAY'), 'desktop display required')
class DesktopSmoke(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from mawkbox.gui import Workspace
        self.root = tk.Tk()
        self.workspace = Workspace(self.root)
        self.root.update()
        self.addCleanup(self.workspace.close)

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(.02)
        self.fail('Desktop playback did not reach the expected state: ' + self.workspace.status.get())

    def test_workspace_and_signal_draw(self):
        from mawkbox.signal import modulate, pack
        workspace = self.workspace
        self.assertEqual(self.root.title(), 'mawkbox')
        self.assertFalse(workspace.plain.get())
        self.assertTrue(workspace.autoplay.get())
        workspace.audio = modulate(pack('GUI smoke test'))
        workspace.draw()
        self.root.update()
        self.assertGreater(len(workspace.canvas.find_all()), 2)
        self.assertEqual(len(workspace.buttons), 4)
        self.assertEqual(str(workspace.transport[0]['state']), 'disabled')
        # Keep all controls visible in the compact default window.
        box = self.root.winfo_children()[0]
        for widget in box.winfo_children():
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())
        self.assertTrue(self.workspace.receipt.winfo_ismapped())

    def test_export_button_requires_passphrase_before_save_dialog(self):
        with patch('mawkbox.gui.filedialog.asksaveasfilename') as dialog, \
             patch('mawkbox.gui.messagebox.showerror') as error:
            self.workspace.buttons[0].invoke()
        dialog.assert_not_called()
        error.assert_called_once_with('Cannot export', 'Enter a passphrase or select plain encoding.', parent=self.root)
        self.assertFalse(self.workspace.busy)
        self.assertIn('passphrase', self.workspace.status.get())

    def test_export_wav_button_saves_without_probe_or_autoplay(self):
        from mawkbox.signal import unpack
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'message.wav'
            self.workspace.password.insert(0, 'secret')
            self.workspace.autoplay.set(False)
            with patch('mawkbox.gui.filedialog.asksaveasfilename', return_value=str(target)) as dialog, \
                 patch('mawkbox.gui.inspect_media', side_effect=AssertionError('Export must not probe')):
                self.workspace.buttons[0].invoke()
                self.wait_for(lambda: self.workspace.saved_file.get() == f'Last saved: {target}')
            self.assertEqual(dialog.call_args.kwargs['parent'], self.root)
            self.assertTrue(target.is_file())
            self.assertEqual(unpack(target.with_suffix('.mawkbox').read_bytes(), 'secret'), 'Good morning, NSA.')
            self.assertEqual(self.workspace.player.state, 'ready')
            self.assertEqual(self.workspace.status.get(), 'Export complete.')

    def test_successful_save_receipt_survives_playback_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'message.wav'
            self.workspace.plain.set(True)
            with patch('mawkbox.gui.filedialog.asksaveasfilename', return_value=str(target)), \
                 patch('mawkbox.gui.Player.play', side_effect=RuntimeError('Audio device unavailable')):
                self.workspace.buttons[0].invoke()
                self.wait_for(lambda: not self.workspace.busy)
            self.assertTrue(target.is_file())
            self.assertEqual(self.workspace.saved_file.get(), f'Last saved: {target}')
            self.assertEqual(self.workspace.status.get(), 'Audio device unavailable')

    def test_write_error_is_visible_and_buttons_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'message.wav'
            self.workspace.plain.set(True)
            with patch('mawkbox.gui.filedialog.asksaveasfilename', return_value=str(target)), \
                 patch('mawkbox.exports.write_wav', side_effect=OSError('Disk full')), \
                 patch('mawkbox.gui.messagebox.showerror') as error:
                self.workspace.buttons[0].invoke()
                self.wait_for(lambda: not self.workspace.busy)
            error.assert_called_once_with('Export failed', 'Disk full', parent=self.root)
            self.assertEqual(self.workspace.saved_file.get(), 'No export yet.')
            self.assertFalse(target.exists())
            self.assertEqual(str(self.workspace.buttons[0]['state']), 'normal')

    def test_save_dialog_cancel_does_not_start_export(self):
        self.workspace.plain.set(True)
        with patch('mawkbox.gui.filedialog.asksaveasfilename', return_value=''), \
             patch('mawkbox.gui.export_transmission') as save:
            self.workspace.buttons[0].invoke()
        save.assert_not_called()
        self.assertEqual(self.workspace.status.get(), 'Export cancelled.')
        self.assertFalse(self.workspace.busy)

    @unittest.skipUnless(all(shutil.which(x) for x in ('ffmpeg', 'ffplay', 'ffprobe')), 'full FFmpeg package required')
    def test_export_autoplays_audio_with_pause_and_seek(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'SDL_AUDIODRIVER': 'dummy', 'SDL_VIDEODRIVER': 'dummy'}):
            target = Path(directory) / 'message.wav'
            self.workspace.plain.set(True)
            with patch('mawkbox.gui.filedialog.asksaveasfilename', return_value=str(target)):
                self.workspace.export(False)
            self.wait_for(lambda: self.workspace.player.state == 'playing')
            self.assertTrue(target.exists())
            self.assertEqual(str(self.workspace.transport[1]['state']), 'normal')
            self.workspace.pause()
            self.assertEqual(self.workspace.player.state, 'paused')
            self.workspace.seek_value.set(.2)
            self.workspace.seek()
            self.assertAlmostEqual(self.workspace.player.position, .2)
            self.workspace.pause()
            self.assertEqual(self.workspace.player.state, 'playing')
            self.workspace.stop()
            self.assertEqual(self.workspace.player.position, 0)

    @unittest.skipUnless(all(shutil.which(x) for x in ('ffmpeg', 'ffplay', 'ffprobe')), 'full FFmpeg package required')
    def test_open_encrypted_video_without_decoding_and_close(self):
        from mawkbox.signal import modulate, pack, write_wav
        from mawkbox.video import render_video
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'SDL_AUDIODRIVER': 'dummy', 'SDL_VIDEODRIVER': 'dummy'}):
            wav, mp4 = Path(directory) / 'message.wav', Path(directory) / 'message.mp4'
            audio = modulate(pack('Encrypted, playable without a key.' * 3, 'secret'))
            write_wav(wav, audio)
            render_video(mp4, audio, wav)
            original = self.workspace.message.get('1.0', 'end-1c')
            with patch('mawkbox.gui.filedialog.askopenfilename', return_value=str(mp4)):
                self.workspace.open_media()
            self.wait_for(lambda: self.workspace._video_frame is not None)
            self.assertTrue(self.workspace.player.video_enabled)
            self.assertEqual(self.workspace.message.get('1.0', 'end-1c'), original)
            self.assertEqual(self.workspace.password.get(), '')
            process = self.workspace.player._audio
            self.workspace.close()
            self.assertIsNotNone(process.poll())
            # Closing twice is harmless, including test cleanup.
