"""Black-box checks for RGBA-to-terminal boundaries; no image dependencies."""

import errno
import fcntl
import os
from pathlib import Path
import re
import struct
import select
import subprocess
import sys
import tempfile
import termios
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

    def run_terminal(self, columns, rows, *args):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
            process = subprocess.Popen(
                [BINARY, "--sprites-dir", str(self.directory), "--no-title", *args],
                stdout=slave, stderr=subprocess.PIPE)
        finally:
            os.close(slave)
        output = bytearray()
        with process:
            try:
                while True:
                    if not select.select([master], [], [], 5)[0]:
                        self.fail("Renderer did not finish writing to the terminal")
                    try:
                        data = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        break
                    if not data:
                        break
                    output.extend(data)
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr.decode())
            finally:
                if process.poll() is None:
                    process.kill()
        return output.decode("utf-8")

    def test_default_artwork_stays_within_fifteen_percent(self):
        write_png(self.directory / "square.png", [[(255, 0, 0, 255)] * 32] * 32)
        for columns, rows in [(80, 24), (40, 12), (120, 40)]:
            with self.subTest(terminal=(columns, rows)):
                output = self.run_terminal(columns, rows, "square")
                pixels, _, _ = terminal_pixels(output)
                width, height = len(pixels[0]), len(pixels) // 2
                self.assertLessEqual(width * height * 100, columns * rows * 15)
                self.assertLess(width, columns)
                self.assertLess(height, rows)

    def test_area_cap_includes_half_block_rounding_and_explicit_sizes(self):
        # A continuous-area limit alone admits 27x27 pixels here, but the
        # rounded 27x14 terminal cells exceed 15% of a 45x55 terminal.
        for width, height, columns, rows in [(27, 27, 45, 55), (1, 67, 8, 20),
                                              (67, 1, 80, 3), (7, 67, 20, 10)]:
            with self.subTest(sprite=(width, height), terminal=(columns, rows)):
                write_png(self.directory / "shape.png",
                          [[(255, 0, 0, 255)] * width] * height)
                output = self.run_terminal(columns, rows, "shape",
                                           "--width", "1000", "--height", "1000")
                pixels, _, _ = terminal_pixels(output)
                self.assertLessEqual(len(pixels[0]) * (len(pixels) // 2) * 100,
                                     columns * rows * 15)
                # Scaling must retain proportions to within one sampled pixel.
                visible_height = sum(any(pixel is not None for pixel in row) for row in pixels)
                self.assertLessEqual(abs(len(pixels[0]) * height - visible_height * width),
                                     max(width, height))

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

    def test_downsampling_retains_detail_between_sample_centers(self):
        red, blue, green = (255, 0, 0, 255), (0, 0, 255, 255), (0, 255, 0, 255)
        stripe = [red, red, blue, green, green]
        for vertical in (False, True):
            with self.subTest(vertical=vertical):
                rows = [[color] * 2 for color in stripe] if vertical else [stripe] * 2
                write_png(self.directory / "detail.png", rows)
                result = self.run_cli("detail", "--width", "1" if vertical else "2",
                                      "--height", "1")
                self.assertEqual(result.returncode, 0, result.stderr)
                pixels, _, _ = terminal_pixels(result.stdout)
                left, right = (204, 0, 51), (0, 204, 51)
                self.assertEqual(pixels, [[left], [right]] if vertical
                                 else [[left, right], [None, None]])

    def test_downsampling_ignores_hidden_rgb_and_preserves_half_coverage(self):
        red, clear = (255, 0, 0, 128), (0, 255, 0, 127)
        stripe = [red, clear, red, red, clear, clear, clear, red]
        write_png(self.directory / "coverage.png", [stripe] * 2)
        result = self.run_cli("coverage", "--width", "4", "--height", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, _, _ = terminal_pixels(result.stdout)
        self.assertEqual(pixels, [[red[:3], red[:3], None, red[:3]], [None] * 4])

    def test_upscaling_keeps_pixel_art_sharp(self):
        red, blue = (255, 0, 0, 255), (0, 0, 255, 255)
        write_png(self.directory / "small.png", [[red, blue]])
        result = self.run_cli("small", "--width", "3", "--height", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, _, _ = terminal_pixels(result.stdout)
        self.assertEqual(pixels, [[red[:3], blue[:3], blue[:3]], [None] * 3])

    def test_corrupt_png_fails_without_partial_artwork(self):
        (self.directory / "broken.png").write_bytes(b"not a PNG")
        result = self.run_cli("broken")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)


if __name__ == "__main__":
    unittest.main()
