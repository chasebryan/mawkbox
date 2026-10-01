import os
import unittest


@unittest.skipUnless(os.environ.get('DISPLAY'), 'desktop display required')
class DesktopSmoke(unittest.TestCase):
    def test_workspace_and_signal_draw(self):
        import tkinter as tk
        from mawkbox.gui import Workspace
        from mawkbox.signal import modulate, pack
        root = tk.Tk()
        try:
            workspace = Workspace(root)
            root.update()
            self.assertEqual(root.title(), 'mawkbox')
            self.assertFalse(workspace.plain.get())
            workspace.audio = modulate(pack('GUI smoke test'))
            workspace.draw()
            root.update()
            self.assertGreater(len(workspace.canvas.find_all()), 3)
            self.assertEqual(len(workspace.buttons), 3)
        finally:
            root.destroy()
