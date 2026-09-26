"""Black-box checks for RGBA-to-terminal boundaries; no image dependencies."""

import base64
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

    def run_cli(self, *args, outline=False):
        return subprocess.run(
            [BINARY, "--sprites-dir", str(self.directory), "--no-title",
             *([] if outline else ["--no-outline"]), *args],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
            env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"})

    def run_terminal(self, columns, rows, *args, cell=(0, 0), term="xterm-256color",
                     environment=None):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, columns, columns * cell[0], rows * cell[1]))
            process = subprocess.Popen(
                [BINARY, "--sprites-dir", str(self.directory), "--no-title", *args],
                stdout=slave, stderr=subprocess.PIPE,
                env={**{key: value for key, value in os.environ.items()
                        if key not in ("TMUX", "STY")}, "TERM": term, **(environment or {})})
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

    def test_native_detail_is_not_shrunk_to_an_area_budget(self):
        red = (255, 0, 0, 255)
        blue = (0, 0, 255, 255)
        rows = [[blue if x == y else red for x in range(35)] for y in range(49)]
        write_png(self.directory / "native.png", rows)
        output = self.run_terminal(80, 30, "native", "--no-outline")
        pixels, _, _ = terminal_pixels(output)
        self.assertEqual(pixels, [[color[:3] for color in row] for row in rows]
                         + [[None] * 35])

    def test_compact_graphics_preserve_every_source_pixel(self):
        red, blue, clear = (255, 0, 0, 255), (0, 0, 255, 255), (90, 80, 70, 0)
        rows = [[blue if x == y else clear if x == 17 else red
                 for x in range(35)] for y in range(49)]
        write_png(self.directory / "native.png", rows)
        output = self.run_terminal(80, 30, "native", "--no-outline",
                                   cell=(10, 20), term="xterm-kitty")
        width, height, rgba = self.graphics_pixels(output)
        # Same one-pixel diagonal and transparency in half the physical footprint.
        self.assertLessEqual(width, 35 * 10 // 2)
        self.assertLessEqual(height, 49 * 10 // 2)
        scale = width // 35
        self.assertGreaterEqual(scale, 1)
        expected = b"".join(
            b"".join(bytes(color if color[3] else (0, 0, 0, 0)) * scale for color in row)
            * scale for row in rows)
        self.assertEqual((width, height, rgba), (35 * scale, 49 * scale, expected))

    def graphics_pixels(self, output):
        chunks = re.findall(r"\x1b_G([^;]*);([A-Za-z0-9+/=]*)\x1b\\", output)
        self.assertTrue(chunks, "Expected a Kitty image, not oversized text blocks")
        headers = [dict(item.split("=") for item in header.split(",")) for header, _ in chunks]
        self.assertEqual(headers[0]["f"], "32")
        self.assertEqual(headers[0]["q"], "2")  # No protocol replies in the next shell prompt.
        self.assertEqual([header["m"] for header in headers], ["1"] * (len(chunks) - 1) + ["0"])
        self.assertTrue(all(len(data) <= 4096 and len(data) % 4 == 0 for _, data in chunks))
        data = base64.b64decode("".join(data for _, data in chunks), validate=True)
        width, height = int(headers[0]["s"]), int(headers[0]["v"])
        self.assertEqual(len(data), width * height * 4)
        # Placement is pinned to whole cells so Kitty rescales the image on font zoom.
        columns, rows = int(headers[0]["c"]), int(headers[0]["r"])
        self.assertEqual((width, height), (columns * 10, rows * 20))
        # Trim the transparent cell padding added on the right and bottom edges.
        pixels = [data[(y * width + x) * 4:(y * width + x + 1) * 4]
                  for y in range(height) for x in range(width)]
        opaque = [(x, y) for y in range(height) for x in range(width)
                  if pixels[y * width + x][3]]
        right = max(x for x, _ in opaque) + 1
        bottom = max(y for _, y in opaque) + 1
        self.assertEqual((right + 9) // 10, columns)
        self.assertEqual((bottom + 19) // 20, rows)
        trimmed = b"".join(data[y * width * 4:(y * width + right) * 4] for y in range(bottom))
        return right, bottom, trimmed

    def test_graphics_limits_include_outline_without_blending(self):
        red = (255, 0, 0, 255)
        write_png(self.directory / "square.png", [[red] * 8] * 8)
        output = self.run_terminal(80, 30, "square", "--width", "2", "--height", "1",
                                   cell=(10, 20), term="xterm-kitty")
        width, height, data = self.graphics_pixels(output)
        self.assertLessEqual(width, 20)
        self.assertLessEqual(height, 20)
        black, clear = bytes((0, 0, 0, 255)), bytes(4)
        # Two device pixels per source pixel, plus a one-device-pixel contour.
        edge = clear + black * 16 + clear
        self.assertEqual((width, height, data),
                         (18, 18, edge + (black + bytes(red) * 16 + black) * 16 + edge))

    def test_ansi_fallback_without_usable_graphics(self):
        red = (255, 0, 0, 255)
        write_png(self.directory / "single.png", [[red]])
        for args, cell, term, environment in [
            (("--ansi",), (10, 20), "xterm-kitty", {}),
            ((), (0, 0), "xterm-kitty", {}),
            ((), (10, 20), "xterm-256color", {}),
            ((), (10, 20), "xterm-kitty", {"TMUX": "/tmp/example"}),
            ((), (10, 20), "xterm-kitty", {"STY": "example"}),
        ]:
            with self.subTest(args=args, cell=cell, term=term, environment=environment):
                output = self.run_terminal(80, 30, "single", "--no-outline", *args,
                                           cell=cell, term=term, environment=environment)
                self.assertEqual(terminal_pixels(output)[0], [[red[:3]], [None]])

    def test_terminal_fit_includes_outline_and_half_block_rounding(self):
        for width, height, columns, rows in [(27, 27, 30, 15), (1, 67, 8, 20),
                                           (67, 1, 80, 4), (7, 67, 20, 10)]:
            with self.subTest(sprite=(width, height), terminal=(columns, rows)):
                write_png(self.directory / "shape.png",
                          [[(255, 0, 0, 255)] * width] * height)
                output = self.run_terminal(columns, rows, "shape",
                                           "--width", "1000", "--height", "1000")
                pixels, _, _ = terminal_pixels(output)
                self.assertLess(len(pixels[0]), columns)
                self.assertLess(len(pixels) // 2, rows)
                content = [[pixel for pixel in row if pixel == (255, 0, 0)]
                           for row in pixels]
                content_height = sum(bool(row) for row in content)
                content_width = max(map(len, content))
                self.assertLessEqual(abs(content_width * height - content_height * width),
                                     max(width, height))

    def test_outline_is_one_pixel_and_preserves_original_colors(self):
        red, blue, clear = (255, 0, 0, 255), (0, 0, 255, 255), (90, 80, 70, 0)
        write_png(self.directory / "edge.png", [
            [red, clear, clear],
            [red, blue, clear],
            [clear, clear, red],
        ])
        result = self.run_cli("edge", outline=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, foreground, background = terminal_pixels(result.stdout)
        black, r, b = (0, 0, 0), red[:3], blue[:3]
        self.assertEqual(pixels, [
            [None, black, None, None, None],
            [black, r, black, None, None],
            [black, r, b, black, None],
            [None, black, black, r, black],
            [None, None, None, black, None],
            [None] * 5,
        ])
        self.assertIsNone(foreground)
        self.assertIsNone(background)

    def test_outline_respects_explicit_limits_when_shrinking(self):
        write_png(self.directory / "square.png", [[(255, 0, 0, 255)] * 8] * 8)
        result = self.run_cli("square", "--width", "5", "--height", "3", outline=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, _, _ = terminal_pixels(result.stdout)
        black, red = (0, 0, 0), (255, 0, 0)
        self.assertEqual(pixels, [[None, black, black, black, None]]
                         + [[black, red, red, red, black]] * 3
                         + [[None, black, black, black, None], [None] * 5])

    def test_impossible_outline_limits_fail_before_artwork(self):
        write_png(self.directory / "tiny.png", [[(255, 0, 0, 255)]])
        result = self.run_cli("tiny", "--width", "2", outline=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)
        unoutlined = self.run_cli("tiny", "--width", "2")
        self.assertEqual(unoutlined.returncode, 0, unoutlined.stderr)

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

    def test_downsampling_keeps_source_palette(self):
        red, blue, green = (255, 0, 0, 255), (0, 0, 255, 255), (0, 255, 0, 255)
        write_png(self.directory / "detail.png", [[red, red, blue, green, green]] * 2)
        result = self.run_cli("detail", "--width", "2", "--height", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, _, _ = terminal_pixels(result.stdout)
        self.assertEqual(pixels, [[red[:3], green[:3]], [None, None]])

    def test_downsampling_keeps_alpha_cutoff_without_color_bleeding(self):
        red, clear = (255, 0, 0, 128), (0, 255, 0, 127)
        stripe = [red, clear, red, red, clear, clear, clear, red]
        write_png(self.directory / "coverage.png", [stripe] * 2)
        result = self.run_cli("coverage", "--width", "4", "--height", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, _, _ = terminal_pixels(result.stdout)
        self.assertEqual(pixels, [[None, red[:3], None, red[:3]], [None] * 4])

    def test_enlargement_uses_equal_sized_source_pixel_blocks(self):
        red, blue = (255, 0, 0, 255), (0, 0, 255, 255)
        write_png(self.directory / "small.png", [[red, blue], [blue, red]])
        result = self.run_cli("small", "--width", "7", "--height", "5")
        self.assertEqual(result.returncode, 0, result.stderr)
        pixels, _, _ = terminal_pixels(result.stdout)
        self.assertEqual(pixels, [[red[:3]] * 3 + [blue[:3]] * 3] * 3
                         + [[blue[:3]] * 3 + [red[:3]] * 3] * 3)

    def test_corrupt_png_fails_without_partial_artwork(self):
        (self.directory / "broken.png").write_bytes(b"not a PNG")
        result = self.run_cli("broken")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)


if __name__ == "__main__":
    unittest.main()
