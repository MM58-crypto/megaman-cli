# Mega Man CLI: code walkthrough

This guide explains the project **by file, then by logical code block**: what each
block does, how it works, and the practical reason for its approach. Start with
the big picture, then read beside the linked source.

It covers the C++ program, CMake build, Python tests, helper script, legacy sprite
scripts, assets, and commands in the README. Repeated sprite-color data is
explained as a format rather than repeated character by character. Generated
files under `build/` are build output, not another implementation to learn.

**About “why”:** behavior and explicit comments come from the source. Explanations
marked **[INFERENCE]** describe the engineering tradeoff visible in the code, not
a claim about the author's undocumented intentions.

Code excerpts illustrate the named block; they are not standalone programs unless
identified as runnable commands. See [README.md](README.md) for installation
instructions and artwork credits.

## Contents

1. [The big picture](#1-the-big-picture)
2. [Libraries and language features](#2-libraries-and-language-features)
3. [Every logical block in main.cpp](#3-every-logical-block-in-maincpp)
4. [One image through the whole renderer](#4-one-image-through-the-whole-renderer)
5. [CMakeLists.txt: building and installing](#5-cmakeliststxt-building-and-installing)
6. [tests/test_renderer.py: checking observable behavior](#6-teststest_rendererpy-checking-observable-behavior)
7. [Other project files](#7-other-project-files)
8. [README command blocks explained](#8-readme-command-blocks-explained)
9. [Quick reference](#9-quick-reference)

## 1. The big picture

The program turns a PNG into colored text and exits. It does not open a window,
start an interactive menu, or ask the terminal to display an actual image file.

```text
Command-line arguments
        |
        v
parseOptions ------------------ --help --> printHelp --> exit
        |
        v
spriteDirectory --> listSprites --list --> print names --> exit
        |
        v
selectSprite --> loadImage --> visibleBounds --> renderSize
                                                    |
                                                    v
                                          optional title + render
                                                    |
                                                    v
                                            colored terminal text
```

Inside `render`, two smaller helpers do the work:

- `sample`: choose or area-average source colors for an output position.
- `appendColor`: append an ANSI instruction when a color needs to change.

### Three units to keep separate

| Term | Meaning | Example |
| --- | --- | --- |
| Source pixel | One pixel decoded from the PNG | Red with alpha 255 |
| Output pixel | One sampled pixel after cropping and scaling | The top half of a terminal cell |
| Terminal cell | One character position | `▀` showing two vertically stacked output pixels |

A terminal cell is usually taller than it is wide. The program uses `▀` and `▄`
to represent **two vertical pixels per cell**. Thus an output image of 24 × 24
pixels occupies 24 columns × 12 terminal rows. The exact appearance still depends
on the terminal font and cell proportions.

### Project map

| File or directory | Responsibility |
| --- | --- |
| [main.cpp](main.cpp) | Argument parsing, asset lookup, PNG decoding, sizing, and rendering |
| [CMakeLists.txt](CMakeLists.txt) | Compiler settings, dependencies, installation, and test registration |
| [tests/test_renderer.py](tests/test_renderer.py) | Run the executable with small generated PNGs and interpret its output |
| [mm-sprites/pngs/](mm-sprites/pngs/) | PNG assets loaded at runtime |
| [mm-sprites/X_1](mm-sprites/X_1), [mm-sprites/X_ultimate_armor](mm-sprites/X_ultimate_armor) | Legacy, pre-rendered shell artwork; not used by the C++ program |
| [auto_git.sh](auto_git.sh) | Convenience script that stages, commits, and pushes repository changes |
| [.gitignore](.gitignore) | Excludes the root `build/` directory from ordinary Git tracking |
| [README.md](README.md) | Usage, setup, asset provenance, and rights information |
| [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md) | This explanation; not executable code |

## 2. Libraries and language features

### The dependency choices

| Tool or library | What it supplies here | Why it fits this job |
| --- | --- | --- |
| C++17 and its standard library | Strings, paths, containers, numeric conversion, random selection, errors | **[INFERENCE]** These cover the small CLI without additional utility libraries. C++17 provides `filesystem`, `string_view`, and `charconv`. |
| libpng | Decode PNG files into RGBA bytes | **[INFERENCE]** PNG decoding involves compression, color formats, and error handling; using a dedicated decoder avoids implementing that format inside the renderer. |
| Linux/POSIX interfaces | Locate the executable and query terminal dimensions | **[INFERENCE]** Direct OS calls provide the required information without invoking shell commands. They also make this implementation Linux-oriented rather than platform-neutral. |
| ANSI colors and Unicode half-blocks | Display artwork using ordinary terminal output | **[INFERENCE]** This avoids a terminal-specific image protocol or full-screen UI library. The tradeoff is character-cell resolution and no partial opacity. |
| CMake | Configure, build, install, and register tests | **[INFERENCE]** It keeps dependency discovery and installation paths in one build description instead of a machine-specific compiler command. |
| Python 3 standard library | Generate PNG fixtures, launch the CLI, emulate a terminal, and assert results | **[INFERENCE]** It makes black-box checks possible without a Python imaging dependency. Python is optional for tests, not required by the C++ renderer. |

libpng is the external image library directly used by the application. Its
underlying compression dependency is handled through the library/build setup;
`main.cpp` does not implement decompression or call Python.

### C++ headers, one group at a time

Source: [main.cpp, lines 1–16](main.cpp#L1-L16).

| Header | Used for |
| --- | --- |
| `<png.h>` | `png_image`, PNG read functions, format constants, and cleanup |
| `<algorithm>` | `std::min`, `std::max`, and sorting paths |
| `<charconv>` | `std::from_chars` for input numbers; `std::to_chars` for RGB output |
| `<cstdint>` | Explicitly sized integers for multiplication that needs a wider range |
| `<cstdlib>` | `std::getenv` for `MEGAMAN_SPRITES_DIR` |
| `<filesystem>` | Paths, directory iteration, file checks, and executable symlink lookup |
| `<iostream>` | `std::cout` for results and `std::cerr` for errors |
| `<random>` | Random seed, generator, and uniform sprite index |
| `<stdexcept>` | `std::runtime_error` for meaningful failures |
| `<string>` | Owned names, messages, and output buffers |
| `<string_view>` | A non-owning view of argument text |
| `<vector>` | A list of sprite paths and the decoded pixel buffer |
| `<sys/ioctl.h>` | `winsize`, `ioctl`, and `TIOCGWINSZ` |
| `<unistd.h>` | `isatty` and `STDOUT_FILENO` |

A `std::string` owns its characters. A `std::string_view` only refers to existing
characters. Argument text remains available during parsing, so it can be viewed
without first copying each argument into a new string. Values saved in `Options`
are owned strings or paths.

## 3. Every logical block in main.cpp

The sections below follow source order. After this section, every struct,
function, and nested helper in `main.cpp` has been covered.

### 3.1 Compile-time paths and the private namespace

Source: [lines 18–29](main.cpp#L18-L29), closing at [line 423](main.cpp#L423).

```cpp
#ifndef MEGAMAN_SOURCE_SPRITE_DIR
#define MEGAMAN_SOURCE_SPRITE_DIR ""
#endif
```

There are three path macros:

- `MEGAMAN_SOURCE_SPRITE_DIR`: PNG directory in the source checkout.
- `MEGAMAN_INSTALL_SPRITE_DIR`: configured absolute installed asset directory.
- `MEGAMAN_RELATIVE_SPRITE_DIR`: path from the executable directory to installed
  assets; its source fallback is `../share/megaman-cli/sprites`.

`#ifndef` means “define this only if it has not already been defined.” CMake
normally supplies all three values. The fallbacks let this file compile without
those definitions, though the compiler and linker still need libpng configured.

`namespace { ... }` gives the helpers internal linkage: they belong to this
translation unit, not a public library API. `main` is outside it.
`namespace fs = std::filesystem;` is only a shorter spelling, not a new library.

**Why [INFERENCE]:** the same executable can find development or installed assets,
and implementation helpers do not need externally visible names.

### 3.2 `Options`: collect the requested behavior

Source: [lines 31–40](main.cpp#L31-L40).

`Options` is a small record, not a class hierarchy:

| Field | Initial value | Meaning |
| --- | --- | --- |
| `name` | Empty | No named sprite selected |
| `directory` | Empty | No command-line asset override |
| `width` | `28` | Maximum artwork columns |
| `height` | `14` | Maximum artwork terminal rows |
| `random` | `false` | Whether `--random` was explicitly supplied |
| `list` | `false` | Whether to list names instead of rendering |
| `help` | `false` | Whether to print help |
| `title` | `true` | Whether to print the sprite name above the art |

**Important:** `random == false` does not mean “never choose randomly.” An empty
`name` makes `selectSprite` choose randomly. The flag records an explicit request
so the parser can reject combinations such as `--random --name X_1`.

**Example:** `X_1 --width 12 --no-title` produces a name of `X_1`, width limit 12,
height limit 14, and `title == false`.

**Why [INFERENCE]:** one record separates interpreting arguments from rendering.
The later functions receive settings rather than parsing command text again.

### 3.3 `positiveNumber`: reject invalid size arguments

Source: [lines 42–50](main.cpp#L42-L50).

```cpp
const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
```

The function requires all three conditions:

1. Conversion succeeded (`parsed.ec` reports no error).
2. Conversion consumed the entire string (`parsed.ptr` reached its end).
3. The value is between 1 and 1000, inclusive.

| Input | Result |
| --- | --- |
| `"12"` | Returns `12` |
| `"12px"` | Error: only part of the input is numeric |
| `"0"`, `"1001"` | Error: outside the accepted range |
| `"abc"` or an overflowing integer | Error: conversion failed |

The `option` argument makes the error identify `--width` or `--height`.

**Why [INFERENCE]:** `from_chars` parses directly from the existing character
range, without allocating or throwing its own conversion exception. Checking the
end pointer prevents accepting a valid numeric prefix followed by garbage.

### 3.4 `parseOptions`: turn arguments into an `Options` value

Source: [lines 52–95](main.cpp#L52-L95).

#### The loop and the nested `value` lambda

`argv[0]` is the program invocation; real arguments start at index 1. Each loop
iteration views one argument as `std::string_view`.

```cpp
const auto value = [&]() -> std::string_view {
    if (++i == argc || argv[i][0] == '\0') {
        throw std::runtime_error(std::string(arg) + " requires a value");
    }
    return argv[i];
};
```

A lambda is a small function defined where it is used. `[&]` lets this one access
surrounding variables by reference. Calling `value()` advances `i` to consume the
next argument. It rejects a missing or empty value. The loop then advances past
that consumed argument.

**Example:** with `--width 12`, the branch sees `--width`, `value()` consumes `12`,
and `positiveNumber` validates it.

#### The option branches

| Input | Action |
| --- | --- |
| `--help`, `-h` | Set `help` |
| `--list`, `-l` | Set `list` |
| `--random`, `-r` | Set `random` |
| `--name`, `-n` | Consume a name; reject a second name |
| `--width`, `-w` | Consume and validate a width |
| `--height` | Consume and validate a height |
| `--sprites-dir` | Consume a directory path |
| `--no-title` | Clear `title` |
| Nonempty text not starting with `-` | Treat it as a positional name; reject a second name |
| Anything else | Report an unknown option |

This is a deliberately small parser: write `--width 12`, not `--width=12`.
Repeated width, height, or directory options replace the earlier value; a second
name is rejected instead.

#### The final conflict check

Unless help was requested, the parser rejects mixing listing, explicit random
selection, and named selection. For example, `--list --random` fails.

Help skips this final action-conflict check, **not all parsing**. `--help` works
without assets, but `--help --width bad` still has an invalid numeric argument.

**Why [INFERENCE]:** a direct loop keeps this small option set visible in one
place, without adding a command-line parsing dependency. The shared `value`
helper avoids repeating missing-value checks.

### 3.5 `printHelp`: print usage, without touching assets

Source: [lines 97–113](main.cpp#L97-L113).

This function sends a fixed usage message to `std::cout`. Adjacent C++ string
literals are joined by the compiler; `\n` introduces a line break.

It explains the options, default random behavior, 15% area cap, 80 × 24 fallback,
terminal requirements, and environment variable.

**Example:** `./build/megaman-cli --help` does not need a readable sprite directory.

**Why [INFERENCE]:** help should remain available when asset lookup is precisely
what the user needs help fixing.

### 3.6 `spriteDirectory`: find the asset directory

Source: [lines 115–148](main.cpp#L115-L148).

#### Explicit overrides

First use `options.directory`. If it is empty, inspect the nonempty environment
variable `MEGAMAN_SPRITES_DIR`.

If either supplies an override, require that path to be a directory and return
it. A bad override reports an error rather than searching elsewhere. An existing
but empty override is returned here; `listSprites` subsequently rejects it.

#### Locate the executable

`fs::read_symlink("/proc/self/exe", error)` asks Linux for the running executable's
path. If that fails, the code uses `fs::absolute(program)`.

The fallback turns `argv[0]` into an absolute path; it is not a general search of
`PATH`. The `/proc` lookup is what normally supplies the actual binary location
on Linux.

#### Try the default locations in order

1. Installed assets relative to the executable.
2. `mm-sprites/pngs` beside the executable.
3. The configured absolute installation path.
4. The configured source-tree path.
5. `mm-sprites/pngs` relative to the current working directory.

The first existing directory wins. This function does **not** inspect whether it
contains PNGs before choosing it. If that directory has no PNGs, listing fails;
the program does not keep searching later candidates.

**Example:** `/home/alex/.local/bin/megaman-cli` can find
`/home/alex/.local/share/megaman-cli/sprites` even when launched from `/tmp`.

**Why [INFERENCE]:** executable-relative paths support installation and relocation;
source paths support development. An authoritative override avoids silently
showing unrelated artwork after the user explicitly chose a directory.

### 3.7 `foldCase`: normalize ASCII uppercase letters

Source: [lines 150–157](main.cpp#L150-L157).

The function receives a string by value, changes each `A`–`Z` into `a`–`z`, and
returns it. Other characters remain unchanged.

**Example:** `X_1.PNG` becomes `x_1.png`.

This is ASCII case folding, not Unicode-aware case conversion.

**Why [INFERENCE]:** the project names and PNG extension need a small, predictable
comparison rule. Taking an owned string lets the function modify its local value
without changing the caller's original name.

### 3.8 `listSprites`: discover PNGs and sort them

Source: [lines 159–171](main.cpp#L159-L171).

For each entry directly inside the chosen directory:

1. Require a regular file.
2. Fold the filename extension and compare it to `.png`.
3. Append accepted paths to a vector.

It sorts the vector and rejects an empty result. This is not a recursive search,
and extension checking does not decode or validate a file's contents.

**Example:** `X_1.png` and `pose.PNG` qualify. `notes.txt` does not. A PNG inside a
subdirectory is not found by this loop.

**Why [INFERENCE]:** filesystem iteration avoids a shell command, a vector stores
the discovered collection directly, and sorting makes listing stable rather
than dependent on directory iteration order. Sorting is by path, not by folded
name.

### 3.9 `selectSprite`: random, exact, or unambiguous matching

Source: [lines 173–198](main.cpp#L173-L198).

#### No name: select a random index

```cpp
std::mt19937 generator(std::random_device{}());
return paths[std::uniform_int_distribution<std::size_t>(0, paths.size() - 1)(generator)];
```

`random_device` supplies a seed; `mt19937` is the pseudo-random generator;
`uniform_int_distribution` maps its output to a valid index. With three sprites,
the possible indices are 0, 1, and 2. `listSprites` guarantees the vector is not
empty before this function is called.

**Why [INFERENCE]:** a uniform distribution expresses equal-probability selection
without the bias that a naive remainder operation can introduce. This is artwork
selection, not cryptographic randomness.

#### A name: exact spelling wins

For every path, `stem()` removes the extension. An exact match returns at once.
Otherwise, the function remembers case-insensitive matches and whether more than
one exists. It continues searching so a later exact match still wins.

**Example:** if `X_1.png` and `x_1.png` both exist:

- `X_1` chooses `X_1.png` exactly.
- `x_1` chooses `x_1.png` exactly.

For an ambiguity example, imagine `Pose.png` and `POSE.png`: the input `pose`
matches both after folding, but neither exactly, so the program asks for exact
spelling. A name with no match reports an unknown sprite.

The returned `const fs::path &` is a reference to an existing vector element,
not a copied path. In `main`, the vector outlives the reference and is not modified.

**Why [INFERENCE]:** exact-first matching provides convenience without arbitrarily
choosing between distinct files on a case-sensitive filesystem.

### 3.10 `Image` and `Image::at`: store RGBA pixels in one buffer

Source: [lines 200–208](main.cpp#L200-L208).

`Image` stores width, height, and `std::vector<unsigned char> pixels`. Every pixel
occupies four consecutive bytes: red, green, blue, alpha. Each channel is 0–255.
Pixels are stored row by row.

```text
pixel index = y * width + x
byte offset = pixel index * 4
```

**Example:** in a three-pixel-wide image, `(x=2, y=1)` is pixel index 5, so its RGBA
bytes begin at offset 20.

`at` returns a pointer to those bytes. Thus `image.at(x, y)[3]` reads alpha. It
does not perform bounds checking; its callers calculate valid coordinates. The
cast to `std::size_t` performs the buffer-offset calculation in the size type.

**Why [INFERENCE]:** a flat owned buffer matches libpng's RGBA output and avoids
allocating a separate object or container for every pixel or row.

### 3.11 `loadImage`: decode safely into that buffer

Source: [lines 210–233](main.cpp#L210-L233).

#### The local `PngHandle` cleanup block

```cpp
struct PngHandle {
    png_image image{};
    ~PngHandle() { png_image_free(&image); }
} handle;
```

`image{}` zero-initializes libpng's state. The destructor calls
`png_image_free` when `handle` leaves scope, including when an exception exits
the function. This is **RAII**: tie a resource's cleanup to an object's lifetime.
`png_image &png = handle.image` is a shorter reference to the same state.

#### Read the header and validate dimensions

The code sets `PNG_IMAGE_VERSION`, then calls
`png_image_begin_read_from_file`. Failure becomes an exception containing the
filename and libpng's diagnostic.

Before allocating decoded pixels, it rejects:

- Zero width or height.
- Either axis above 8192 pixels.
- More than `16 * 1024 * 1024` pixels in total: 16,777,216 pixels.

The 64-bit multiplication prevents the dimension product from overflowing a
narrower integer. At four bytes per pixel, that count allows at most 64 MiB for
the RGBA pixel vector; this is not a cap on all process or decoder memory.

#### Request RGBA and finish decoding

`PNG_FORMAT_RGBA` asks libpng for a consistent four-channel output format.
`PNG_IMAGE_SIZE(png)` supplies the required buffer size. The vector owns that
memory, and `png_image_finish_read` fills it. A decode failure throws; success
returns the `Image`.

**Example:** a 3 × 3 decoded image needs `3 * 3 * 4 = 36` RGBA bytes, regardless of
how small its compressed PNG file is.

**Why [INFERENCE]:** libpng's simplified image API keeps format handling outside
the renderer; one RGBA representation keeps downstream code straightforward.
RAII covers cleanup on both success and errors. The source comment explicitly
places dimension limits before trusting the PNG's decoded allocation size.

### 3.12 `Bounds` and `visibleBounds`: ignore transparent padding

Source: [lines 235–259](main.cpp#L235-L259).

`Bounds` contains `left`, `top`, `right`, and `bottom`. Right and bottom are
**exclusive**: they point just beyond the visible region.

```text
visible width  = right - left
visible height = bottom - top
```

The scan starts with an empty rectangle. For each pixel whose alpha is at least
128, it expands the rectangle using `min` and `max`. The `x + 1` and `y + 1`
updates create the exclusive edges. If no pixel qualified, the function throws
“sprite has no visible pixels.”

**Example:** a 6 × 4 PNG with colored pixels only at columns 1–4 and rows 1–2
produces `{left=1, top=1, right=5, bottom=3}`: a visible region of 4 × 2 pixels.

This does not create a cropped image or copy pixels. It records the rectangle;
`sample` later reads from that rectangle inside the original buffer. Transparent
holes inside the rectangle remain holes.

**Why:** the code comment explains that ANSI cells have no alpha channel, so
alpha is thresholded instead of blending against an invented background.
**[INFERENCE]** Recording bounds avoids copying the cropped image and prevents
outer transparent margins from consuming the chosen artwork dimensions.

### 3.13 `Size` and `renderSize`: fit the artwork to the terminal

Source: [lines 261–313](main.cpp#L261-L313).

`Size` holds the final **output-pixel** width and height. Its height is not a
terminal-row count; the renderer packs those pixels two per row.

#### A. Determine terminal dimensions

Start with 80 columns and 24 rows. If standard output is a terminal and
`ioctl(..., TIOCGWINSZ, ...)` succeeds, replace each fallback dimension with its
reported value when that value is nonzero.

`isatty` checks the destination of stdout, not whether the application was started
from a terminal. Redirecting stdout to a file therefore uses fallback dimensions.
This code does not consult `COLUMNS` or `LINES` environment variables.

#### B. Set width and height limits

The program combines requested limits with terminal space:

```text
available columns = max(1, terminal columns - 1)
available rows    = max(1, terminal rows - (title enabled ? 2 : 1))
columns           = min(requested width, available columns)
rows              = min(requested height, available rows)
```

The source comment explains the reserved space: avoid wrapping in the final
column and leave rows for the title and following prompt. The minimum of one is
a calculation safeguard, not a guarantee of spare space on a one-row terminal.

#### C. Compute the artwork cell budget

```cpp
const auto cellBudget = static_cast<std::int64_t>(terminalColumns) * terminalRows * 15 / 100;
```

Integer division rounds down. An 80 × 24 terminal permits
`80 * 24 * 15 / 100 = 288` artwork cells. The budget uses the terminal's full
reported area; the title is not included in the artwork's cell count.

If the budget is zero, not even one cell fits, so the function reports an error.
Large `--width` and `--height` requests do not bypass this budget.

#### D. `sizeAt`: express proportional sizes with one number

Let `width` and `height` be the cropped source dimensions, and `longest` their
maximum. The nested lambda computes:

```cpp
return {std::max(1, pixels * width / longest),
        std::max(1, pixels * height / longest)};
```

`pixels` controls the target length of the longer axis. For a 40 × 20 source,
`sizeAt(20)` gives 20 × 10. Integer rounding and the minimum dimension of one
mean proportions are approximate, especially at very small sizes.

Nothing forbids enlargement: a small PNG can be scaled up when limits allow it.

#### E. `fits`: count actual terminal cells

```text
artwork rows  = (output height + 1) / 2, using integer division
artwork cells = output width * artwork rows
fits          = artwork cells <= cellBudget
```

**Example:** a height of 3 needs 2 terminal rows, not 1.5. The missing bottom pixel
still occupies the bottom half of the final character cell.

#### F. Find the largest permitted size in the search range

`high` first limits the longer-axis parameter using both available columns and
available rows. `rows * 2` converts terminal rows into output pixels.

If `sizeAt(high)` fits the area budget, return it immediately. Otherwise, binary
search between 1 and `high`:

- Try the upper midpoint: `low + (high - low + 1) / 2`.
- If it fits, move `low` up to that midpoint.
- Otherwise, move `high` below it.
- When they meet, return `sizeAt(low)`.

As the parameter increases, neither output dimension decreases, so the cell
count cannot decrease. That monotonic behavior makes binary search valid. The
upper midpoint also ensures progress when only two candidates remain.

**Worked example: a square sprite on an 80 × 24 terminal**

| Candidate | Artwork cells | Fits 288 cells? |
| --- | --- | --- |
| Default bounding limit: 28 × 28 pixels | `28 * 14 = 392` | No |
| 25 × 25 pixels | `25 * 13 = 325` | No |
| 24 × 24 pixels | `24 * 12 = 288` | Yes |

The result is 24 columns × 12 artwork rows, not the whole default 28 × 14 box.

**Why [INFERENCE]:** a single scale parameter avoids independently stretching the
axes. Integer cell accounting respects odd-height rounding. Binary search avoids
trying every smaller size while still selecting the largest fitting candidate
within the computed range.

### 3.14 `sample`: retain detail when shrinking

Source: [lines 315–374](main.cpp#L315-L374).

If `y >= size.height`, return `-1`. This is how an odd final output height gets a
transparent missing lower half.

When either output dimension is smaller than the cropped source, average the
visible source pixels overlapping each output pixel's rectangular footprint:

1. Express horizontal coordinates in units of `1 / outputWidth` and vertical
   coordinates in units of `1 / outputHeight`. Integer intersections then give
   exact area weights, including fractional scale factors.
2. Ignore source pixels with alpha below 128, including their hidden RGB values.
3. Accumulate visible area and area-weighted RGB in 64-bit integers.
4. Return `-1` if less than half the footprint is visible. Otherwise divide each
   color sum by visible area, rounding to the nearest integer, and pack the RGB.

For example, shrinking `[red, red, blue, green, green]` to two pixels includes
half the central blue pixel in each output footprint. Nearest-neighbor sampling
would miss blue entirely. Transparent areas never add a black or colored matte.

At native size or when enlarging, keep sharp pixel-art edges and the original
palette by mapping the output pixel's center into the cropped source region:

```text
sourceX = left + floor((2*x + 1) * croppedWidth  / (2*outputWidth))
sourceY = top  + floor((2*y + 1) * croppedHeight / (2*outputHeight))
```

All quantities are nonnegative here, so integer division supplies the floor.
The wider integer cast protects the intermediate multiplication.

**Example:** enlarging `[red, blue]` from two pixels to three samples source
indices 0, 1, and 1. The result is `[red, blue, blue]`, without a blended middle.

If the selected pixel's alpha is below 128, return `-1`. Otherwise pack RGB into
one integer:

```cpp
return (static_cast<int>(pixel[0]) << 16) | (static_cast<int>(pixel[1]) << 8) | pixel[2];
```

Red occupies the top byte, green the middle, and blue the bottom: `0xRRGGBB`.
Opaque black is `0x000000`, or `0`; transparency is `-1`. They are different.

**Why:** area averaging reduces aliasing and detail loss when shrinking; nearest
neighbor avoids unnecessary blur when enlarging. Sampling on demand avoids a
second resized image buffer. A negative sentinel represents “no color” outside
the valid nonnegative RGB range.

### 3.15 `appendColor`: emit only necessary color changes

Source: [lines 376–393](main.cpp#L376-L393).

Arguments describe the output buffer, desired color, foreground/background
choice, and a reference to the previous color. The reference lets the helper
update the caller's tracked state.

1. If the color already matches, append nothing.
2. Otherwise update `previous`.
3. For a negative color, append a default-color reset.
4. For RGB, append the appropriate truecolor escape and decimal channels.

In C++, `\033` is the escape character. The sequences are not normally visible
text; a supporting terminal interprets them as instructions.

| Sequence | Meaning |
| --- | --- |
| `\033[38;2;R;G;Bm` | Set foreground to RGB |
| `\033[48;2;R;G;Bm` | Set background to RGB |
| `\033[39m` | Restore default foreground |
| `\033[49m` | Restore default background |
| `\033[0m` | Reset text attributes and colors; emitted by `render` |

The loop over `{16, 8, 0}` extracts each byte with a shift and `& 255`.
`std::to_chars` writes its decimal digits into `char number[3]`; three bytes
suffice for 0–255. There is no terminator requirement because `append` receives
the beginning and returned end pointers. Semicolons separate channels; `m` ends
the instruction.

**Example:** requesting red foreground appends `\033[38;2;255;0;0m`. Requesting red
foreground again immediately appends nothing.

**Why [INFERENCE]:** tracking foreground and background separately avoids repeated
escape sequences. The small stack buffer avoids creating a temporary string for
each color component.

### 3.16 `render`: combine two pixels into each character

Source: [lines 395–421](main.cpp#L395-L421).

#### Prepare and reuse a row buffer

`line.reserve(size.width * 48 + 16)` reserves room for characters and color
instructions. It is output-buffer headroom, not an artwork-size calculation.
The string is reused for each terminal row.

The outer loop increases `y` by 2 because each row consumes two output-pixel
rows. Each line starts with `\033[0m`; the tracked foreground and background
both start at `-1`, meaning default colors.

#### Sample the pair and select a character

| Upper pixel | Lower pixel | Character | Foreground | Background |
| --- | --- | --- | --- | --- |
| Transparent | Transparent | Space | Irrelevant to the space | Default |
| Transparent | Colored | `▄` | Lower color | Default |
| Colored | Transparent | `▀` | Upper color | Default |
| Colored | Colored | `▀` | Upper color | Lower color |

A space displays the background across the cell. `▀` fills its upper half with
foreground; the lower half shows background. `▄` reverses those halves.

The first branch does not need to reset foreground: an ordinary space does not
show it. It does reset background so an earlier colored cell cannot fill a
transparent area.

#### Finish the line

Append `\033[0m\n`, then send the row to `std::cout`. Resetting each row prevents
sprite colors from leaking into subsequent terminal text. The code uses a
newline rather than flushing after each character or row; `main` performs an
explicit final flush.

**Example:** upper red and lower blue become a `▀` with red foreground and blue
background. That one character carries both colors.

**Why [INFERENCE]:** half-blocks double vertical sampling resolution compared with
one solid block per cell. Reusing a line buffer groups stream writes and retains
allocated capacity instead of rebuilding storage for every row.

### 3.17 `main`: coordinate the blocks and handle failures

Source: [lines 425–453](main.cpp#L425-L453).

The success path is deliberately linear:

1. Parse options.
2. If help is requested, print it and return success immediately.
3. Find the directory and list its PNG paths.
4. If listing is requested, print filename stems, one per line.
5. Otherwise select, decode, crop logically, calculate size, print the optional
   title, and render.
6. Flush stdout and return `0` if the stream is healthy, otherwise `1`.

Listing does not decode PNGs or emit artwork color escapes. Normal rendering
retains its escapes even when stdout is redirected; the code does not implement
an automatic plain-text mode.

The `catch (const std::exception &error)` block prints
`megaman-cli: <message>` to stderr and returns `1`.

The decode, visibility, and sizing steps finish **before** the title or artwork
is printed. Thus a corrupt PNG does not leave half an image or a title on stdout.
This is not a general guarantee against partial output if writing itself fails.
The early help return also does not use the final explicit stream-status check.

**Why [INFERENCE]:** one top-level exception handler keeps error formatting out of
the successful rendering steps and gives shell callers a nonzero failure status.

## 4. One image through the whole renderer

Consider the 3 × 3 image used in the transparency regression test. `.` means an
alpha value below 128, regardless of the RGB bytes underneath it:

```text
Source image:
red    .       black
blue   green   .
.      yellow  .
```

Yellow has alpha 128, so it is visible. The bottom-right source pixel has alpha
127, so it is transparent.

Run with `--width 3 --height 2 --no-title` in the test's redirected-output setup:

1. `loadImage` obtains 36 RGBA bytes.
2. `visibleBounds` keeps the whole 3 × 3 rectangle: visible pixels reach all four
   outer edges, even though some positions are transparent.
3. `renderSize` chooses 3 × 3 output pixels, which fit 3 columns × 2 rows and the
   fallback terminal's 288-cell budget.
4. `sample` maps directly to source pixels because source and output sizes agree.
5. `render` emits the following cells:

| Terminal position | Character | What it shows |
| --- | --- | --- |
| Row 1, column 1 | `▀` | Red upper half, blue lower half |
| Row 1, column 2 | `▄` | Default upper half, green lower half |
| Row 1, column 3 | `▀` | Black upper half, default lower half |
| Row 2, column 1 | Space | Default background |
| Row 2, column 2 | `▀` | Yellow upper half, default lower half |
| Row 2, column 3 | Space | Default background |

The final lower halves are transparent because no fourth image row exists.
Foreground and background are reset afterward. This example connects RGBA,
thresholding, odd-height rounding, and half-block output without needing a large
sprite to understand them.

## 5. CMakeLists.txt: building and installing

### 5.1 Project and dependency setup

Source: [lines 1–5](CMakeLists.txt#L1-L5).

```cmake
cmake_minimum_required(VERSION 3.16)
project(megaman-cli VERSION 1.0.0 LANGUAGES CXX)

include(GNUInstallDirs)
find_package(PNG REQUIRED)
```

The first two statements declare the required CMake version, project name,
version, and C++ language. `GNUInstallDirs` supplies standard, configurable
installation locations such as `bin`, `share`, and the documentation directory.
`find_package(PNG REQUIRED)` stops configuration if PNG development support
cannot be found.

**Why [INFERENCE]:** dependency failure at configuration time is clearer than an
unexplained missing-header or linker failure later. Standard directory variables
respect installation-layout overrides.

### 5.2 Executable and compiler settings

Source: [lines 7–13](CMakeLists.txt#L7-L13).

- `add_executable(megaman-cli main.cpp)` creates one executable from one source.
- `target_compile_features(... PRIVATE cxx_std_17)` requires C++17 support.
- `target_link_libraries(... PRIVATE PNG::PNG)` links the discovered PNG target.
- `CXX_EXTENSIONS OFF` requests the standard language dialect rather than compiler
  extensions.
- For GNU or Clang compilers, `-Wall -Wextra -Wpedantic` enable additional warnings;
  these settings do not make every warning an error.

`PRIVATE` means these requirements belong to this target, not an interface for
downstream targets. `PNG::PNG` is an imported CMake target carrying dependency
information such as include paths and link requirements.

**Why [INFERENCE]:** target-scoped settings avoid global compiler flags and
hard-coded libpng paths. Warnings provide feedback without changing runtime
behavior.

### 5.3 Compile the asset locations into the executable

Source: [lines 15–21](CMakeLists.txt#L15-L21).

`file(RELATIVE_PATH ...)` computes the route from the installed binary directory
to the installed sprites directory. `target_compile_definitions` supplies that
route and the two absolute paths as the macros described in section 3.1.

**Example:** with binary directory `/usr/local/bin` and assets under
`/usr/local/share/megaman-cli/sprites`, the relative path is
`../share/megaman-cli/sprites`.

**Why [INFERENCE]:** deriving this path from CMake's directory settings avoids
assuming every installation uses the same prefix or layout. Relative lookup is
also useful when `cmake --install` overrides the prefix after configuration; the
compiled absolute path itself is not rewritten by that installation step.

### 5.4 Installation rules

Source: [lines 23–27](CMakeLists.txt#L23-L27).

The rules install:

1. The runtime executable into the binary directory.
2. The contents of `mm-sprites/pngs/` into the sprites data directory, matching
   `*.png` and `*.PNG`.
3. `README.md` into the documentation directory.

The source directory's trailing slash means copy its contents, not an extra
`pngs` directory level. The installer patterns accept lower- and uppercase PNG
extensions; runtime discovery is more permissive because it folds mixed case too.

The existing installation rule copies **README.md only**. This walkthrough is a
separate source-tree document; the current rule does not install it. The legacy
shell artwork and Git helper are not installed either.

**Why [INFERENCE]:** executable code and image data have different installation
roles. Keeping the README with the package also retains its usage and credits.

### 5.5 Optional test registration

Source: [lines 29–37](CMakeLists.txt#L29-L37).

`include(CTest)` introduces the testing setup, including `BUILD_TESTING` (normally
on). If testing is enabled, CMake quietly looks for a Python 3 interpreter. If
found, it registers one CTest entry called `renderer-edges`.

That entry runs Python with the test script and
`$<TARGET_FILE:megaman-cli>`. This **generator expression** supplies the actual
executable path for the build configuration rather than guessing its location.
If Python is unavailable, the executable can still build; the test is simply not
registered.

**Why [INFERENCE]:** users do not need Python just to render sprites, and tests
can run against the correct compiled binary across build layouts.

## 6. tests/test_renderer.py: checking observable behavior

These are **black-box tests**: they launch the executable and inspect the PNG-to-
terminal result, rather than call private C++ functions. One CTest entry runs
eight Python test methods; some methods contain several subcases.

### 6.1 Imports and the executable argument

Source: [lines 1–18](tests/test_renderer.py#L1-L18).

| Import | Purpose |
| --- | --- |
| `errno` | Recognize Linux pseudo-terminal end-of-stream behavior (`EIO`) |
| `fcntl`, `termios` | Set the pseudo-terminal's reported size |
| `os` | Environment, pseudo-terminal descriptors, descriptor reads and closes |
| `Path` from `pathlib` | Construct paths and write fixture bytes |
| `re` | Split output into ANSI instructions and printable characters |
| `struct` | Pack binary PNG fields and terminal-size fields |
| `select` | Wait for readable terminal output with a timeout |
| `subprocess` | Launch the C++ executable |
| `sys` | Read and remove its path from the test runner's arguments |
| `tempfile` | Create isolated fixture directories |
| `unittest` | Assertions, test discovery, subcases, and cleanup |
| `zlib` | PNG scanline compression and chunk checksums |

```python
BINARY = str(Path(sys.argv.pop(1)).resolve())
```

This consumes the first script argument as the executable path and converts it
to an absolute path. Removing it prevents `unittest` from treating that path as
a test selector. Therefore this script needs a binary argument; it is not meant
to be invoked as just `python3 tests/test_renderer.py`.

**Why [INFERENCE]:** the test suite can exercise any supplied build without
hard-coding `build/megaman-cli` inside the tests.

### 6.2 `write_png` and nested `chunk`: create tiny fixtures

Source: [lines 21–30](tests/test_renderer.py#L21-L30).

Input is a path and rows of RGBA tuples, for example:

```python
write_png(path, [[(255, 0, 0, 255), (0, 0, 255, 255)]])
```

This creates a one-row, two-pixel PNG: red, then blue.

The nested `chunk(kind, data)` builds a PNG chunk:

```text
4-byte data length | chunk type | data | 4-byte CRC checksum
```

`struct.pack(">I", ...)` writes a big-endian unsigned 32-bit integer, as PNG
requires. The CRC covers the chunk type and data.

The remaining statements build:

1. `IHDR`: width, height, 8-bit channels, color type 6 (RGBA), standard compression
   and filtering methods, and no interlacing.
2. Raw rows: a zero filter byte followed by each row's RGBA bytes. Filter byte
   zero means no scanline filter transformation.
3. `IDAT`: the raw rows compressed with `zlib.compress`.
4. The PNG signature, followed by `IHDR`, `IDAT`, and the empty `IEND` chunk.

**Why [INFERENCE]:** a small fixture writer removes the need for Pillow or stored
fixture images. It only writes the simple, valid image shape these tests need;
it is not a replacement for a production PNG encoder or decoder.

### 6.3 `terminal_pixels`: interpret the output like a consumer

Source: [lines 33–68](tests/test_renderer.py#L33-L68).

This helper translates terminal text back into visible top/bottom pixel colors.

#### Tokenize each line

```python
re.findall(r"\x1b\[[0-9;]*m|[^\x1b]", line)
```

The first alternative matches an ANSI color/style instruction; the second
matches an individual non-escape character. `\x1b` is the same escape byte as
C++'s `\033`.

#### Track color instructions

The helper maintains `foreground` and `background`, with `None` meaning default.
It recognizes reset (`0`), default foreground (`39`), default background (`49`),
and RGB foreground/background (`38;2` / `48;2`). Empty reset parameters count as
`0`. Unsupported instructions raise an assertion rather than being silently
ignored.

#### Translate printable characters

| Character | Reconstructed upper/lower pixels |
| --- | --- |
| `▀` | Foreground, background |
| `▄` | Background, foreground |
| `█` | Foreground, foreground |
| Space | Background, background |

The current renderer does not emit `█`, but the consumer helper understands its
meaning. Unexpected characters fail. Each terminal line contributes two pixel
rows, and the helper returns those rows plus the final color state.

**Example:** red foreground + blue background + `▀` becomes an upper red pixel
and lower blue pixel.

**Why [INFERENCE]:** comparing visible colors is less brittle than requiring one
exact escape-string encoding. A renderer may skip redundant escapes while
producing the same image. This helper intentionally models a small output subset,
not a complete terminal emulator.

### 6.4 `RendererEdges.setUp`: isolate each test

Source: [lines 71–75](tests/test_renderer.py#L71-L75).

Each test gets a `TemporaryDirectory`; `addCleanup` registers its deletion even
if an assertion fails. `self.directory` is the corresponding `Path`.

**Why [INFERENCE]:** generated files cannot interfere with another test or depend
on the bundled artwork collection.

### 6.5 `run_cli`: capture non-terminal output

Source: [lines 77–81](tests/test_renderer.py#L77-L81).

The helper launches an argument list containing the binary, temporary sprite
directory, `--no-title`, and the test's extra arguments. It captures stdout and
stderr as UTF-8 text and uses a five-second timeout.

It copies the environment and sets `TERM` and `COLORTERM`. The renderer does not
use those variables to detect color support. Because stdout is captured through
a pipe, this path exercises the 80 × 24 size fallback.

**Why [INFERENCE]:** explicit fixture directories and omitted titles let the test
interpret only artwork. Passing an argument list avoids shell quoting and shell
interpretation of arguments.

### 6.6 `run_terminal`: exercise real terminal-size detection

Source: [lines 83–113](tests/test_renderer.py#L83-L113).

A pseudo-terminal, or PTY, has two ends. The child writes to the **slave** as
though it were a terminal; the test reads those bytes from the **master**.

The blocks perform these steps:

1. `os.openpty()` opens both ends; cleanup is registered for the master.
2. `TIOCSWINSZ` sets the slave's rows and columns. `struct.pack("HHHH", ...)`
   supplies four native unsigned-short fields: rows, columns, and unused pixel
   dimensions.
3. `Popen` connects the child's stdout to the slave and captures stderr.
4. The parent closes its own slave descriptor in `finally`; the child retains
   its stdout connection.
5. `select.select` waits up to five seconds for readable output. `os.read`
   collects available bytes. Empty input or Linux PTY `EIO` ends the read loop;
   other errors are re-raised.
6. `communicate(timeout=5)` finishes process collection; the test checks that it
   exited successfully.
7. A final cleanup kills a still-running child if the operation failed. The
   accumulated output is decoded as UTF-8.

**Example:** `run_terminal(40, 12, "square")` makes the child observe a 40-column,
12-row terminal rather than the pipe fallback.

**Why [INFERENCE]:** setting environment variables alone would not exercise
`isatty` and `TIOCGWINSZ`. A PTY tests the actual OS interface used by the program.
Timeouts and cleanup prevent a broken child from hanging the suite indefinitely.

### 6.7 `test_default_artwork_stays_within_fifteen_percent`

Source: [lines 115–124](tests/test_renderer.py#L115-L124).

The fixture is a solid red 32 × 32 square. Subcases use 80 × 24, 40 × 12, and
120 × 40 pseudo-terminals. The test interprets output, calculates artwork columns
and terminal rows, and checks:

```text
artwork width * artwork rows * 100 <= terminal columns * terminal rows * 15
```

It also checks artwork width and height are smaller than the corresponding
terminal dimensions.

**Why [INFERENCE]:** defaults alone are insufficient to guarantee small artwork
on every terminal. This protects observable output size across several terminal
shapes, rather than pinning an internal scale value.

### 6.8 `test_area_cap_includes_half_block_rounding_and_explicit_sizes`

Source: [lines 126–142](tests/test_renderer.py#L126-L142).

This test supplies large explicit limits (`--width 1000 --height 1000`) and tries
square, very tall, very wide, and narrow-tall source images on different PTYs.
It checks the same area cap and a cross-multiplied aspect-ratio error bound.

The source comment identifies the key rounding case: 27 × 27 pixels would need
27 × 14 terminal cells, or 378 cells, on a 45 × 55 terminal. Its 15% integer
budget is only 371 cells. Treating the height as 13.5 terminal rows would wrongly
accept that size.

The proportion check compares `outputWidth * sourceHeight` with
`visibleOutputHeight * sourceWidth`, allowing an error up to the longer source
axis for integer-pixel rounding. It excludes a transparent final lower half from
visible height.

**Why [INFERENCE]:** this defends two failure boundaries: user-supplied sizes must
not bypass the cap, and a half-used character row still counts as a whole cell.

### 6.9 `test_transparency_black_pixels_and_odd_last_row`

Source: [lines 144–161](tests/test_renderer.py#L144-L161).

This creates the 3 × 3 fixture from section 4. It checks the exact reconstructed
colors, including:

- Opaque black stays black instead of becoming transparent.
- Hidden RGB values in transparent pixels do not appear.
- Alpha 128 is visible; alpha 127 is transparent.
- A missing fourth pixel row becomes transparent lower halves.
- Final foreground and background are default, so subsequent text does not
  inherit sprite colors.

**Why [INFERENCE]:** these are distinct output boundaries that a seemingly small
change to alpha handling or half-block selection could break.

### 6.10 `test_transparent_padding_is_cropped_without_resampling_palette`

Source: [lines 163–174](tests/test_renderer.py#L163-L174).

A 6 × 4 fixture has a transparent border around a 4 × 2 red/blue interior:

```text
. . . . . .
. R R B B .
. R R B B .
. . . . . .
```

With `--width 2 --height 1`, the expected output is one upper row `[red, blue]`
and one transparent lower row.

**Why [INFERENCE]:** retaining the outer border would sample the wrong positions.
Each output footprint covers a uniform color here, so area averaging must retain
exact red and blue. This checks cropping and scaling together.

### 6.11 Downsampling and enlargement regressions

Source: [lines 176–206](tests/test_renderer.py#L176-L206).

- `test_downsampling_retains_detail_between_sample_centers` shrinks a narrow
  blue stripe between red and green in both orientations. Its contribution must
  survive fractional-area averaging, rather than disappearing between centers.
- `test_downsampling_ignores_hidden_rgb_and_preserves_half_coverage` verifies
  that half-covered pixels remain visible, empty footprints stay transparent,
  and hidden green RGB does not tint visible red.
- `test_upscaling_keeps_pixel_art_sharp` enlarges a two-color image by a
  noninteger factor without blending its middle output pixel.

### 6.12 `test_corrupt_png_fails_without_partial_artwork`

Source: [lines 208–213](tests/test_renderer.py#L208-L213).

The test writes `b"not a PNG"` to `broken.png`, runs the CLI, and requires a
nonzero exit status, empty stdout, and an error on stderr.

**Why [INFERENCE]:** extension-based discovery is not content validation. Invalid
image data must fail during decoding without emitting artwork. This case tests
corrupt input; it does not independently test every dimension-limit condition.

### 6.13 The test entry point

Source: [lines 216–217](tests/test_renderer.py#L216-L217).

```python
if __name__ == "__main__":
    unittest.main()
```

When executed as a script, Python discovers the `test_...` methods, runs them,
and reports success or failures. The earlier `BINARY` assignment already consumed
the executable argument.

**Why [INFERENCE]:** the standard runner supplies reporting and process status
without a custom test framework.

## 7. Other project files

### 7.1 `mm-sprites/pngs/`: data, not more renderer code

The directory currently contains 29 PNGs. The program has no per-character
classes or hard-coded sprite registry: filenames are discovered at runtime.

| Group | Filename stems |
| --- | --- |
| Original X poses/armor | `X_1`, `X_2`, `X_fourth_armor`, `X_nova_strike`, `X_nova_strike_blue`, `X_shoot_charged_armor`, `X_shoot_charged_u_armor`, `X_ultimate_armor` |
| Original Zero/Dr. Light | `Zero_1`, `Zero_2`, `zero_x4`, `dr_light` |
| X1 Sigma | `x1_sigma_cape`, `x1_sigma_saber` |
| X1 Chill Penguin | `x1_chill_penguin_idle`, `x1_chill_penguin_jump` |
| X1 Storm Eagle | `x1_storm_eagle_idle`, `x1_storm_eagle_wings` |
| X4 Ultimate Armor | `x4_x_ultimate_idle`, `x4_x_ultimate_dash`, `x4_x_ultimate_nova_strike` |
| X4 Iris | `x4_iris_stand`, `x4_iris_float` |
| X4 Black Zero | `x4_black_zero_idle`, `x4_black_zero_saber`, `x4_black_zero_run` |
| X5 Falcon Armor | `x5_falcon_idle`, `x5_falcon_shoot`, `x5_falcon_flight` |

**Example:** adding `my_pose.png` to the selected directory makes `my_pose`
available without changing C++. Use individual poses rather than a sheet of many
poses; the renderer does not extract animation frames.

PNG alpha determines visibility. The renderer does not infer a background color
to remove, so an opaque blue backdrop remains blue. Historical extraction and
palette details belong to the [README's sprite credits](README.md#sprite-collection-and-credits),
not to runtime image processing. Those credits also explain the artwork rights;
these assets should not be assumed to have an open redistribution license.

**Why [INFERENCE]:** separating data from rendering means new poses do not require
new code or a rebuild, provided the runtime-selected directory contains them.
Installed copies still need updating when source assets change.

### 7.2 The two legacy sprite scripts

Sources: [X_1](mm-sprites/X_1#L1-L25) and
[X_ultimate_armor](mm-sprites/X_ultimate_armor#L1-L25).

Each file is one shell `printf` command containing a multiline string of fixed
spaces, half-block characters, and color escapes. There are no image-decoding,
selection, or scaling functions inside these files.

A shortened illustrative fragment of the same format is:

```bash
printf "\e[38;5;68;48;5;235m▄\e[m\n"
```

- `printf` interprets the escapes in a supporting shell such as Bash.
- `\e` means the escape character in that shell's `printf` format.
- `38;5;68` chooses foreground palette index 68.
- `48;5;235` chooses background palette index 235.
- `▄` shows foreground below background.
- `\e[49m`, used throughout the files, restores the default background.
- `\e[m` resets attributes; `\n` in this illustrative fragment prints a newline.
  The files themselves contain literal line breaks inside their quoted strings.

The repeated numeric sequences are the precomputed artwork itself. These use
**256-color palette indices**, unlike the current renderer's `38;2` / `48;2`
24-bit RGB colors. The closing quote and semicolon end the single command.

The current C++ program neither executes nor reads these scripts. They remain
legacy assets outside the active `pngs/` directory.

**Why [INFERENCE]:** pre-rendered text can be printed without an image decoder,
but fixes size and color encoding in the data. The current PNG pipeline instead
supports runtime sizing and RGB rendering.

### 7.3 `auto_git.sh`: a repository-writing convenience script

Source: [lines 1–9](auto_git.sh#L1-L9).

Its comment describes the purpose: avoid retyping the same Git commands.
The executable statements are:

```sh
git add .
git commit -m  "wooo another commit"
git push -u origin main
```

| Statement | Effect |
| --- | --- |
| `git add .` | Stage additions, modifications, and deletions under the current directory, subject to Git's ignore/tracking rules |
| `git commit -m ...` | Commit the staged changes on the current branch with the fixed message |
| `git push -u origin main` | Push local branch `main` to `origin` and set its upstream on success |

**Important:** the commit uses the current branch, but the push explicitly names
`main`. These need not be the same branch. The script has no shebang selecting
an interpreter and no `set -e` or `&&` chain that stops later commands after an
earlier failure. It operates relative to the caller's working directory; it
does not change into the project directory itself.

This is not a build or renderer dependency. Do not run it merely to learn or
verify rendering: it can commit local work and publish it to a remote.

### 7.4 `.gitignore`: keep build output out of ordinary commits

Source: [line 1](.gitignore#L1).

```gitignore
/build/
```

The leading slash anchors the pattern to the repository root. The trailing slash
marks a directory. It ignores the root build directory and its contents; it does
not ignore every directory named `build` anywhere in the tree, delete files, or
untrack files already committed.

**Why [INFERENCE]:** generated binaries and CMake state are machine/build-specific
outputs, not source files to maintain alongside the renderer.

## 8. README command blocks explained

The README is the usage guide, not another program module. Its runnable blocks
connect to the code above as follows. Commands here assume the repository root
unless stated otherwise.

### 8.1 Dependency installation

The Arch command uses `pacman -S --needed` to install the compiler/build tool
collection, CMake, and libpng without reinstalling up-to-date packages. The
Debian/Ubuntu command uses `apt install` with `build-essential`, `cmake`, and
`libpng-dev`; the `-dev` package supplies development headers/linking support.

`sudo` authorizes system package changes. These are setup commands, not commands
executed by `megaman-cli`.

### 8.2 Configure, build, and run

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
./build/megaman-cli
```

- `-S .`: read the source project here.
- `-B build`: write build-system files into `build/`.
- `-D...=Release`: set the release configuration for a typical single-config
  generator. Multi-config generators select a configuration at build time.
- `--build build`: invoke the configured underlying build tool.
- `--parallel`: allow parallel build work; this project has one C++ source file.
- Running with no arguments selects a random discovered PNG and prints it.

**Why [INFERENCE]:** an out-of-source build separates generated files from source;
CMake's build command avoids tying the instructions to Make or Ninja.

### 8.3 List, select, and control display limits

Runnable examples using the checkout's assets explicitly:

```sh
./build/megaman-cli --sprites-dir mm-sprites/pngs --list
./build/megaman-cli --sprites-dir mm-sprites/pngs --name X_1
./build/megaman-cli --sprites-dir mm-sprites/pngs X_1 --width 12 --height 8 --no-title
./build/megaman-cli --help
```

`--list` prints stems; `--name X_1` and positional `X_1` select the same PNG;
width and height are maximum terminal columns/rows, not forced stretching;
`--no-title` removes the name line. Other named examples in the README use the
same parser branches with different asset names. `--random` explicitly requests
the behavior used when no name is supplied.

### 8.4 Run the existing regression checks

```sh
ctest --test-dir build --output-on-failure
```

CTest uses the tests registered during configuration. `--output-on-failure`
prints captured test output for failures. If Python was not found at configure
time, this test entry will not exist.

The equivalent direct Python invocation, useful for verbose per-method output,
is:

```sh
python3 tests/test_renderer.py ./build/megaman-cli -v
```

The executable must already be built; invoking CTest does not compile it.

### 8.5 Install under your own account

```sh
cmake --install build --prefix "$HOME/.local"
```

This runs the installation rules using a user-local prefix. Quotes keep the home
path as one argument. With the standard layout, the executable goes in
`~/.local/bin` and sprites in `~/.local/share/megaman-cli/sprites`.

This command copies files; it does not update `PATH` or edit shell startup files.
The relative asset lookup explains why the installed binary can run from another
working directory. Copying only the binary does not embed or copy the PNGs.

### 8.6 Bash and Zsh startup guard

```sh
if [[ $- == *i* ]] && [[ -t 1 ]] && command -v megaman-cli >/dev/null 2>&1; then
    megaman-cli --random --no-title
fi
```

- `$-` lists active shell flags; matching `*i*` checks for an interactive shell.
- `[[ -t 1 ]]` checks that stdout is a terminal.
- `command -v` checks whether the command can be found.
- `>/dev/null 2>&1` discards that lookup's stdout and stderr; it does not discard
  the sprite command's output.
- `&&` requires every guard to succeed before executing the body.
- The body prints one random sprite without a title.

**Why [INFERENCE]:** these guards avoid adding artwork to noninteractive or
redirected shell work. The check does not restrict it to the first shell: nested
interactive shells can show artwork too.

### 8.7 Fish startup guard

```fish
if status is-interactive; and isatty stdout; and type -q megaman-cli
    megaman-cli --random --no-title
end
```

This is the same guard expressed in Fish syntax: interactive shell, terminal
stdout, and an available command. `type -q` checks quietly; `end` closes the block.
Use the snippet for your actual shell rather than mixing shell syntaxes.

### 8.8 Custom asset directories

The README shows `--sprites-dir /path/to/poses` and an environment assignment.
Those paths are examples to replace with real directories. A runnable checkout
example of the environment form is:

```sh
MEGAMAN_SPRITES_DIR="$PWD/mm-sprites/pngs" ./build/megaman-cli --list
```

The prefix assignment supplies the variable to this invocation without
permanently changing shell configuration. `--sprites-dir` takes precedence if
both are supplied. Adding a PNG to an installed setup requires placing it in the
installed data directory or installing updated source assets again.

## 9. Quick reference

### Where to look for a behavior

| Question | Relevant block |
| --- | --- |
| Why is a command rejected? | `positiveNumber`, `parseOptions` |
| Which directory supplied this sprite? | `spriteDirectory` |
| Why does a name match or fail? | `foldCase`, `listSprites`, `selectSprite` |
| Why does a PNG fail to decode? | `loadImage` and its libpng diagnostic |
| Why is empty space removed? | `visibleBounds` |
| Why is the artwork smaller than requested? | `renderSize`, especially the 15% budget |
| Why is a partially transparent pixel hidden or fully colored? | Alpha checks in `visibleBounds` and `sample` |
| Why are colors blended only when shrinking? | Area averaging and nearest-neighbor branches in `sample` |
| How do two pixels fit into one character? | `render` and `appendColor` |
| How are installation paths chosen? | CMake definitions and `spriteDirectory` |
| How is terminal-size behavior checked? | Python `run_terminal` and the two area tests |

### Small glossary

- **ANSI escape:** a byte sequence that changes terminal display state rather
  than printing ordinary characters.
- **RGBA:** red, green, blue, and alpha; alpha expresses opacity in the source.
- **Truecolor:** explicit 8-bit red, green, and blue channels, giving 24-bit color.
- **Area averaging:** blend source colors by their overlap with an output pixel's
  footprint, reducing aliasing when shrinking.
- **Nearest neighbor:** choose one existing source pixel instead of blending
  neighboring colors.
- **Exclusive bound:** an edge just after the last included position, so width
  is `right - left`.
- **Sentinel:** a special value outside normal data, such as `-1` for transparent
  rather than any valid packed RGB color.
- **RAII:** automatic cleanup tied to C++ object lifetime.
- **Lambda:** a locally defined function, used here for argument consumption,
  proportional sizing, and the area check.
- **PTY:** pseudo-terminal; an OS-provided terminal connection controlled by
  another program, used here by tests.
- **Black-box test:** a check of inputs and observable outputs without depending
  on private implementation calls.

The central idea is small: **decode once, record visible bounds, choose a fitting
size, sample or average source colors, and print two pixels per terminal character.**
