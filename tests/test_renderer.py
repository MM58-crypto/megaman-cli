"""Black-box checks for RGBA-to-terminal boundaries; no image dependencies."""

import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib


BINARY = str(Path(sys.argv.pop(1)).resolve())


def write_png(path, rows):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 6, 0, 0, 0)
    raw = b"".join(b"\0" + bytes(channel for pixel in row for channel in pixel)
                   for row in rows)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def terminal_pixels(output):
    """Interpret colors and half-blocks as a consumer terminal would."""
    rows = []
    foreground = background = None
    for line in output.splitlines():
        upper, lower = [], []
        for token in re.findall(r"\x1b\[[0-9;]*m|[^\x1b]", line):
            if token.startswith("\x1b["):
                codes = [int(value) for value in token[2:-1].split(";") if value] or [0]
                while codes:
                    code = codes.pop(0)
                    if code == 0:
                        foreground = background = None
                    elif code == 39:
                        foreground = None
                    elif code == 49:
                        background = None
                    elif code in (38, 48) and codes[0] == 2:
                        color = tuple(codes[1:4])
                        del codes[:4]
                        if code == 38:
                            foreground = color
                        else:
                            background = color
                    else:
                        raise AssertionError(f"Unsupported SGR: {token!r}")
            else:
                cells = {"▀": (foreground, background), "▄": (background, foreground),
                         "█": (foreground, foreground), " ": (background, background)}
                if token not in cells:
                    raise AssertionError(f"Unexpected terminal character: {token!r}")
                top, bottom = cells[token]
                upper.append(top)
                lower.append(bottom)
        rows.extend((upper, lower))
    return rows, foreground, background


class RendererEdges(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def run_cli(self, *args):
        return subprocess.run(
            [BINARY, "--sprites-dir", str(self.directory), "--no-title", *args],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
            env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"})

    def test_transparency_black_pixels_and_odd_last_row(self):
        red, green, blue = (255, 0, 0), (0, 255, 0), (0, 0, 255)
        black, yellow = (0, 0, 0), (255, 255, 0)
        clear = (123, 45, 67, 0)
        write_png(self.directory / "alpha.png", [
            [(*red, 255), clear, (*black, 255)],
            [(*blue, 255), (*green, 255), clear],
            [clear, (*yellow, 128), (200, 100, 50, 127)],
        ])
        result = self.run_cli("alpha", "--width", "3", "--height", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, foreground, background = terminal_pixels(result.stdout)
        self.assertEqual(pixels, [
            [red, None, black], [blue, green, None],
            [None, yellow, None], [None, None, None],
        ])
        self.assertIsNone(foreground, "The following shell prompt must not inherit sprite colors")
        self.assertIsNone(background)

    def test_transparent_padding_is_cropped_without_resampling_palette(self):
        clear, red, blue = (0, 0, 0, 0), (255, 0, 0, 255), (0, 0, 255, 255)
        write_png(self.directory / "padded.png", [
            [clear] * 6,
            [clear, red, red, blue, blue, clear],
            [clear, red, red, blue, blue, clear],
            [clear] * 6,
        ])
        result = self.run_cli("padded", "--width", "2", "--height", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, _, _ = terminal_pixels(result.stdout)
        self.assertEqual(pixels, [[red[:3], blue[:3]], [None, None]])

    def test_corrupt_png_fails_without_partial_artwork(self):
        (self.directory / "broken.png").write_bytes(b"not a PNG")
        result = self.run_cli("broken")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)


if __name__ == "__main__":
    unittest.main()
