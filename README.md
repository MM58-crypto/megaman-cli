# Mega Man CLI

Display Mega Man sprites as ANSI truecolor pixel art in a UTF-8 terminal. Written
in C++17; uses libpng to decode the images. No image viewer, Python, network
connection, or terminal-specific graphics protocol is needed at runtime.

Running the command without arguments prints a random sprite and exits—there is
no interactive menu, so it can be used in a shell startup file.

## Build

Requirements: Linux, a C++17 compiler, CMake 3.16 or newer, and libpng development
headers. Kitty supports the required Unicode half-blocks and 24-bit ANSI colors.

On Arch Linux:

```sh
sudo pacman -S --needed base-devel cmake libpng
```

On Debian/Ubuntu:

```sh
sudo apt install build-essential cmake libpng-dev
```

Build and run from this directory:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
./build/megaman-cli
```

Optional renderer edge-case checks (requires Python 3, standard library only):

```sh
ctest --test-dir build --output-on-failure
```

CMake registers these checks when Python 3 is available. They exercise rendered
pixel colors/transparency, detail-preserving downsampling, sharp enlargement,
padding, odd image heights, corrupt PNG input, and the 15% artwork-area limit
on pseudo-terminals (including explicit size requests).

## Usage

```sh
./build/megaman-cli                         # Random sprite
./build/megaman-cli --list                   # Available PNG names
./build/megaman-cli --name x4_x_ultimate_idle
./build/megaman-cli x4_black_zero_saber
./build/megaman-cli x1_sigma_saber
./build/megaman-cli x1_storm_eagle_wings --no-title
./build/megaman-cli x5_falcon_flight --width 60 --height 30
./build/megaman-cli x4_iris_stand --no-title
./build/megaman-cli --help
```

| Option | Meaning |
| --- | --- |
| `-r`, `--random` | Display one random sprite; also the default action |
| `-n`, `--name NAME` or positional `NAME` | Select a filename without `.png` |
| `-l`, `--list` | List all available names without color escapes |
| `-w`, `--width COLUMNS` | Maximum artwork width, default 28; subject to the 15% area cap |
| `--height ROWS` | Maximum artwork height, default 14; subject to the 15% area cap |
| `--no-title` | Omit the sprite name |
| `--sprites-dir DIR` | Read PNGs from a different directory |
| `-h`, `--help` | Show help without loading any assets |

Names match exactly first, then case-insensitively if unambiguous. Selection,
listing, and explicit random selection are mutually exclusive. Errors go to
standard error and return a nonzero exit status.

The renderer trims transparent padding, uses area-averaged sampling when shrinking,
and packs two vertical image pixels into each terminal cell. This reduces jagged
edges and retains contributions from fine details that nearest-neighbor sampling
would skip. Native-size and enlarged sprites still use nearest-neighbor sampling
to keep their palette and sharp edges. The fixed ANSI cell grid still limits
fine detail; no sprite replacements or terminal configuration changes are needed.
Width and height are bounding limits, not independent stretching controls; proportions are
preserved apart from integer-pixel rounding. The default 28-column by 14-row
bounding box keeps sprites small to medium. Artwork also shrinks so its bounding
rectangle occupies **at most 15% of the terminal's total cells**: artwork columns
times artwork rows, including transparent cells and the final half-block row.
The optional title is not part of that artwork area. `--width` and `--height`
cannot override this cap; smaller requested limits are still honored.

The renderer uses the attached terminal's reported dimensions, leaving one column
to avoid wrapping and reserving rows for the title and following prompt. Unknown
dimensions, including redirected output, use an 80-column by 24-row fallback.
A terminal too small to fit even one artwork cell within 15% reports an error.
Size values must be integers from 1 to 1000. PNGs are limited to 8192 pixels per
axis and 16 megapixels decoded.

ANSI cells cannot represent partial opacity: source alpha below 128 is transparent;
alpha at least 128 contributes its RGB color. When shrinking, each output pixel
averages visible source colors weighted by their overlapping area and is shown
only when at least half its source footprint is visible. Hidden RGB never tints
the result. Transparent pixels keep your terminal's default background, and colors
are reset after every row. Opaque
black remains black. Existing opaque artwork, including the blue/green backdrop
in `X_nova_strike_blue.png`, is rendered as supplied rather than guessing which
colors should be removed. Output retains ANSI colors when redirected to a file.

## Install and use on shell startup

Install under your account; this does not edit terminal or shell configuration:

```sh
cmake --install build --prefix "$HOME/.local"
```

This installs the executable to `~/.local/bin/megaman-cli`, PNGs to
`~/.local/share/megaman-cli/sprites`, and this file with its asset credits to
`~/.local/share/doc/megaman-cli/README.md`. Ensure `~/.local/bin` is on `PATH`.
The installed command finds its assets independently of the working directory.
Keep the installed share directory alongside the executable when relocating it;
copying the executable alone does not bundle the PNGs.

To display a sprite when opening Kitty (or another terminal), put the command in
its interactive shell's startup file—not directly in `kitty.conf`.

For Bash (`~/.bashrc`) or Zsh (`~/.zshrc`):

```sh
if [[ $- == *i* ]] && [[ -t 1 ]] && command -v megaman-cli >/dev/null 2>&1; then
    megaman-cli --random --no-title
fi
```

For Fish (`~/.config/fish/config.fish`):

```fish
if status is-interactive; and isatty stdout; and type -q megaman-cli
    megaman-cli --random --no-title
end
```

These examples run on each interactive shell, including nested shells. For a
fixed character, replace `--random` with `--name x4_black_zero_idle`, for example.
No startup files are modified by the build or installation.

## Add your own sprites

Put individual PNG poses, not whole sprite sheets, in `mm-sprites/pngs/` during
development and rerun installation to copy additions into an installed setup.
The filename stem becomes the CLI name. Transparent, tightly cropped,
native-resolution pixel art gives the best results. Original supplied assets
and filenames are retained; the old shell-style files outside `pngs/` are not
executed or used by the renderer.

You can also use any PNG directory without rebuilding:

```sh
megaman-cli --sprites-dir /path/to/poses --list
MEGAMAN_SPRITES_DIR=/path/to/poses megaman-cli --random
```

Lookup order: `--sprites-dir`, then nonempty `MEGAMAN_SPRITES_DIR`, then installed
assets relative to the executable, `mm-sprites/pngs` beside the executable, the
configured installation path, the configured source tree, and finally
`mm-sprites/pngs` in the current directory. An explicit directory override is
authoritative: missing or empty directories report an error rather than silently
falling back to unrelated assets.

## Sprite collection and credits

The collection contains **29 PNGs**: the 12 originally supplied images plus these
17 additional poses. **Falcon Armor is from Mega Man X5, not X4.**

| Game / character | Added CLI names |
| --- | --- |
| X1 Sigma | `x1_sigma_cape`, `x1_sigma_saber` |
| X1 Chill Penguin | `x1_chill_penguin_idle`, `x1_chill_penguin_jump` |
| X1 Storm Eagle | `x1_storm_eagle_idle`, `x1_storm_eagle_wings` |
| X4 Ultimate Armor X | `x4_x_ultimate_idle`, `x4_x_ultimate_dash`, `x4_x_ultimate_nova_strike` |
| X4 Iris | `x4_iris_stand`, `x4_iris_float` |
| X4 Black Zero | `x4_black_zero_idle`, `x4_black_zero_run`, `x4_black_zero_saber` |
| X5 Falcon Armor X | `x5_falcon_idle`, `x5_falcon_shoot`, `x5_falcon_flight` |

- **Sigma:** ripped by **Eureka Drama X**; hosted by
  [Sprite Database](https://spritedatabase.net/file/19523)
  ([source sheet](https://spritedatabase.net/files/snes/464/Sprite/MMX_Sigma.png)).
  Native caped and saber-swing frames from Mega Man X (SNES), preserving the
  source PNG's transparency and the complete saber arc.
- **Chill Penguin:** sheet credits **Blarcox**; contributed to
  [Sprite Database by Freedom Fighter](https://spritedatabase.net/file/8187)
  ([source sheet](https://spritedatabase.net/files/snes/464/Sprite/ChillPenguin.gif)).
  Native standing and airborne frames from Mega Man X (SNES). Only the exact
  green sheet background, RGB `(152, 224, 155)`, was made transparent.
- **Storm Eagle:** ripped and contributed by **Freedom Fighter**; hosted by
  [Sprite Database](https://spritedatabase.net/file/8197)
  ([source sheet](https://spritedatabase.net/files/snes/464/Sprite/StormEagle.gif)).
  Native standing and raised-wing frames from Mega Man X (SNES). Only the exact
  pink sheet background, RGB `(222, 160, 160)`, was made transparent.
- **Ultimate Armor X:** ripped by **NIK**, who requests credit; hosted by
  [Sprite Database](https://spritedatabase.net/file/5029)
  ([source sheet](https://spritedatabase.net/files/ps1/879/Sprite/X4-UltimateArmor.PNG)).
  Native frames from the sheet's IDLE, DASH, and NOVA STRIKE rows, not its
  custom/MISC section. The black sheet background was made transparent; character
  colors were retained. The Nova Strike pose includes the armored body without
  the large attack trail.
- **Iris:** [Sprites INC X4 archive](https://sprites-inc.com/sprite.php?local=X/X4/Boss/FortressBoss/ScreenCapture/)
  ([source sheet](https://sprites-inc.com/files/X/X4/Boss/FortressBoss/ScreenCapture/x4_Iris.gif)).
  Native frames with the GIF's transparency preserved. This archive labels the
  sheet as a screen capture/reference with an uncorrected palette; these PNGs
  preserve that archived palette, not an independently corrected tile rip.
- **Black Zero:** [Sprites INC Zero archive](https://sprites-inc.com/sprite.php?local=X/Zero/X4-X5/)
  ([pose sheet](https://sprites-inc.com/files/X/Zero/X4-X5/zerox4sheet.gif),
  [palette reference](https://sprites-inc.com/files/X/Zero/X4-X5/zerox4recolours.gif)).
  X4 poses use the exact color mapping between the reference normal Zero and
  green-saber Black Zero frames. No colors were invented; the entire saber arc
  is retained.
- **Falcon Armor X:** [Sprites INC X5 armor archive](https://sprites-inc.com/sprite.php?local=X/X/Armors/X5/)
  ([source sheet](https://sprites-inc.com/files/X/X/Armors/X5/x5sheet1falcon.gif)).
  Native idle, shooting, and flight poses, preserving source colors and
  transparency. Shooting/flight effects are included.

No individual ripper credit was identified on the accessible Sprites INC sheets
or pages above. The original 12 PNGs were supplied with this project; their
original sources were not recorded here. All added poses were extracted without
resampling; Black Zero, Falcon, and all six X1 boss images have a one-pixel
transparent margin.

**Artwork rights:** Mega Man characters and original game graphics belong to
Capcom. Archive/ripper attribution is not permission from the copyright holder.
Sprite Database states private/non-commercial use; Sprites INC asserts copyright
and no explicit open redistribution license was found. Do not assume these
assets are public domain, openly licensed, or covered by a software license.
Check permissions before publishing or redistributing a package containing them.

Inspired by [pokego](https://github.com/rubiin/pokego).
