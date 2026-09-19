"""Unit tests for the Apple-inspired configuration GUI and About dialog."""
import unittest
import tkinter as tk
from pathlib import Path
from tempfile import NamedTemporaryFile
from PIL import Image

from input_locker import __version__
from input_locker.config import LockerConfig
from input_locker.ui.config_gui import (
    _make_avatar_image,
    _make_thumbnail,
    show_about_dialog,
    show_tutorial_dialog,
    CREATOR_LINKEDIN,
    CREATOR_GITHUB,
)


class TestConfigGui(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except (tk.TclError, Exception):
            self.root = None

    def tearDown(self):
        if self.root:
            try:
                self.root.update_idletasks()
                self.root.destroy()
            except Exception:
                pass

    def test_creator_links(self):
        self.assertEqual(CREATOR_LINKEDIN, "https://www.linkedin.com/in/joseph-sharun/")
        self.assertEqual(CREATOR_GITHUB, "https://github.com/SHARUNJOSEPH")

    def test_make_avatar_image(self):
        img = _make_avatar_image(44, master=self.root)
        self.assertIsNotNone(img)

    def test_make_thumbnail_valid(self):
        with NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
        try:
            im = Image.new("RGB", (100, 100), color="blue")
            im.save(temp_path)
            thumb = _make_thumbnail(temp_path, w=200, h=80, master=self.root)
            self.assertIsNotNone(thumb)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_make_thumbnail_invalid_returns_none(self):
        thumb = _make_thumbnail("non_existent_file.png", w=200, h=80, master=self.root)
        self.assertIsNone(thumb)

    def test_show_about_dialog(self):
        if not self.root:
            self.skipTest("Headless environment: Tk root not available")
        show_about_dialog(parent=self.root)
        toplevels = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertTrue(len(toplevels) >= 1)
        top = toplevels[-1]
        self.assertEqual(top.title(), "About Input Locker")
        top.grab_release()
        top.destroy()
        self.root.update()

    def test_show_tutorial_dialog(self):
        if not self.root:
            self.skipTest("Headless environment: Tk root not available")
        finished = [False]
        def on_fin():
            finished[0] = True
        show_tutorial_dialog(parent=self.root, on_finish=on_fin)
        toplevels = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertTrue(len(toplevels) >= 1)
        top = toplevels[-1]
        self.assertIn("Quick Start Guide", top.title())
        top.grab_release()
        top.destroy()
        self.root.update()


if __name__ == "__main__":
    unittest.main()
