#include <png.h>

#include <algorithm>
#include <charconv>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include <sys/ioctl.h>
#include <unistd.h>

#ifndef MEGAMAN_SOURCE_SPRITE_DIR
#define MEGAMAN_SOURCE_SPRITE_DIR ""
#endif
#ifndef MEGAMAN_INSTALL_SPRITE_DIR
#define MEGAMAN_INSTALL_SPRITE_DIR ""
#endif
#ifndef MEGAMAN_RELATIVE_SPRITE_DIR
#define MEGAMAN_RELATIVE_SPRITE_DIR "../share/megaman-cli/sprites"
#endif

namespace {
namespace fs = std::filesystem;

struct Options {
    std::string name;
    fs::path directory;
    int width = 28;
    int height = 14;
    bool random = false;
    bool list = false;
    bool help = false;
    bool title = true;
};

int positiveNumber(std::string_view value, std::string_view option) {
    int result = 0;
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
    if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || result < 1 ||
        result > 1000) {
        throw std::runtime_error(std::string(option) + " expects an integer from 1 to 1000");
    }
    return result;
}

Options parseOptions(int argc, char *argv[]) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg = argv[i];
        const auto value = [&]() -> std::string_view {
            if (++i == argc || argv[i][0] == '\0') {
                throw std::runtime_error(std::string(arg) + " requires a value");
            }
            return argv[i];
        };
        if (arg == "--help" || arg == "-h") {
            options.help = true;
        } else if (arg == "--list" || arg == "-l") {
            options.list = true;
        } else if (arg == "--random" || arg == "-r") {
            options.random = true;
        } else if (arg == "--name" || arg == "-n") {
            if (!options.name.empty()) {
                throw std::runtime_error("select only one sprite");
            }
            options.name = value();
        } else if (arg == "--width" || arg == "-w") {
            options.width = positiveNumber(value(), arg);
        } else if (arg == "--height") {
            options.height = positiveNumber(value(), arg);
        } else if (arg == "--sprites-dir") {
            options.directory = value();
        } else if (arg == "--no-title") {
            options.title = false;
        } else if (!arg.empty() && arg.front() != '-') {
            if (!options.name.empty()) {
                throw std::runtime_error("select only one sprite");
            }
            options.name = arg;
        } else {
            throw std::runtime_error("unknown option: " + std::string(arg));
        }
    }
    if (!options.help && ((options.random && !options.name.empty()) ||
                          (options.list && (options.random || !options.name.empty())))) {
        throw std::runtime_error("use only one of --list, --random, or --name");
    }
    return options;
}

void printHelp() {
    std::cout << "megaman-cli - Mega Man pixel art in your terminal\n\n"
                 "Usage: megaman-cli [NAME | --random | --list] [OPTIONS]\n\n"
                 "With no arguments, display a random sprite and exit.\n\n"
                 "  -r, --random            Display a random sprite\n"
                 "  -n, --name NAME         Display a PNG filename without its extension\n"
                 "  -l, --list              List available sprite names\n"
                 "  -w, --width COLUMNS     Maximum artwork width (default: 28)\n"
                 "      --height ROWS       Maximum artwork height (default: 14)\n"
                 "      --no-title          Display only the artwork\n"
                 "      --sprites-dir DIR   Use PNGs from this directory\n"
                 "  -h, --help              Show this help\n\n"
                 "Sizes preserve aspect ratio; artwork uses at most 15% of terminal cells.\n"
                 "Size limits cannot override this cap. Unknown terminal size uses 80x24.\n"
                 "Requires a UTF-8 terminal with ANSI 24-bit color support.\n"
                 "MEGAMAN_SPRITES_DIR sets the asset directory unless --sprites-dir is used.\n";
}

fs::path spriteDirectory(const Options &options, const char *program) {
    fs::path override = options.directory;
    if (override.empty()) {
        if (const char *value = std::getenv("MEGAMAN_SPRITES_DIR"); value && *value) {
            override = value;
        }
    }
    if (!override.empty()) {
        if (!fs::is_directory(override)) {
            throw std::runtime_error("sprite directory does not exist: " + override.string());
        }
        return override;
    }

    std::error_code error;
    fs::path executable = fs::read_symlink("/proc/self/exe", error);
    if (error) {
        executable = fs::absolute(program);
    }
    std::vector<fs::path> candidates = {
        executable.parent_path() / MEGAMAN_RELATIVE_SPRITE_DIR,
        executable.parent_path() / "mm-sprites/pngs",
        fs::path(MEGAMAN_INSTALL_SPRITE_DIR),
        fs::path(MEGAMAN_SOURCE_SPRITE_DIR),
        fs::path("mm-sprites/pngs"),
    };
    for (const auto &path : candidates) {
        if (!path.empty() && fs::is_directory(path, error)) {
            return path;
        }
    }
    throw std::runtime_error(
        "cannot locate sprites; install the assets or set --sprites-dir /path/to/pngs");
}

std::string foldCase(std::string value) {
    for (char &ch : value) {
        if (ch >= 'A' && ch <= 'Z') {
            ch = static_cast<char>(ch - 'A' + 'a');
        }
    }
    return value;
}

std::vector<fs::path> listSprites(const fs::path &directory) {
    std::vector<fs::path> paths;
    for (const auto &entry : fs::directory_iterator(directory)) {
        if (entry.is_regular_file() && foldCase(entry.path().extension().string()) == ".png") {
            paths.push_back(entry.path());
        }
    }
    std::sort(paths.begin(), paths.end());
    if (paths.empty()) {
        throw std::runtime_error("no PNG sprites found in " + directory.string());
    }
    return paths;
}

const fs::path &selectSprite(const std::vector<fs::path> &paths, const std::string &name) {
    if (name.empty()) {
        std::mt19937 generator(std::random_device{}());
        return paths[std::uniform_int_distribution<std::size_t>(0, paths.size() - 1)(generator)];
    }
    const fs::path *match = nullptr;
    const std::string folded = foldCase(name);
    bool ambiguous = false;
    for (const auto &path : paths) {
        const std::string stem = path.stem().string();
        if (stem == name) {
            return path;
        }
        if (foldCase(stem) == folded) {
            ambiguous = match != nullptr;
            match = &path;
        }
    }
    if (ambiguous) {
        throw std::runtime_error("ambiguous sprite name; use the exact spelling from --list");
    }
    if (!match) {
        throw std::runtime_error("unknown sprite: " + name + "; use --list to see available names");
    }
    return *match;
}

struct Image {
    int width;
    int height;
    std::vector<unsigned char> pixels;

    const unsigned char *at(int x, int y) const {
        return pixels.data() + (static_cast<std::size_t>(y) * width + x) * 4;
    }
};

Image loadImage(const fs::path &path) {
    struct PngHandle {
        png_image image{};
        ~PngHandle() { png_image_free(&image); }
    } handle;
    png_image &png = handle.image;
    png.version = PNG_IMAGE_VERSION;
    if (!png_image_begin_read_from_file(&png, path.c_str())) {
        throw std::runtime_error("cannot read " + path.filename().string() + ": " + png.message);
    }
    // Bound the decoded allocation before trusting dimensions supplied by a PNG.
    if (png.width == 0 || png.height == 0 || png.width > 8192 || png.height > 8192 ||
        static_cast<std::uint64_t>(png.width) * png.height > 16 * 1024 * 1024) {
        throw std::runtime_error("PNG exceeds the 8192-axis / 16-megapixel limit: " +
                                 path.string());
    }
    png.format = PNG_FORMAT_RGBA;
    Image image{static_cast<int>(png.width), static_cast<int>(png.height),
                std::vector<unsigned char>(PNG_IMAGE_SIZE(png))};
    if (!png_image_finish_read(&png, nullptr, image.pixels.data(), 0, nullptr)) {
        throw std::runtime_error("cannot decode " + path.filename().string() + ": " + png.message);
    }
    return image;
}

struct Bounds {
    int left;
    int top;
    int right;
    int bottom;
};

Bounds visibleBounds(const Image &image) {
    Bounds bounds{image.width, image.height, 0, 0};
    for (int y = 0; y < image.height; ++y) {
        for (int x = 0; x < image.width; ++x) {
            // ANSI cells have no alpha channel: threshold instead of adding a matte.
            if (image.at(x, y)[3] >= 128) {
                bounds.left = std::min(bounds.left, x);
                bounds.top = std::min(bounds.top, y);
                bounds.right = std::max(bounds.right, x + 1);
                bounds.bottom = std::max(bounds.bottom, y + 1);
            }
        }
    }
    if (bounds.right <= bounds.left || bounds.bottom <= bounds.top) {
        throw std::runtime_error("sprite has no visible pixels");
    }
    return bounds;
}

struct Size {
    int width;
    int height;
};

Size renderSize(const Bounds &bounds, const Options &options) {
    int terminalColumns = 80;
    int terminalRows = 24;
    winsize terminal{};
    if (isatty(STDOUT_FILENO) && ioctl(STDOUT_FILENO, TIOCGWINSZ, &terminal) == 0) {
        if (terminal.ws_col > 0) {
            terminalColumns = terminal.ws_col;
        }
        if (terminal.ws_row > 0) {
            terminalRows = terminal.ws_row;
        }
    }
    // Leave one column to avoid delayed autowrap, plus title/prompt rows.
    const int columns = std::min(options.width, std::max(1, terminalColumns - 1));
    const int rows =
        std::min(options.height, std::max(1, terminalRows - (options.title ? 2 : 1)));
    const auto cellBudget = static_cast<std::int64_t>(terminalColumns) * terminalRows * 15 / 100;
    if (cellBudget == 0) {
        throw std::runtime_error("terminal too small to display a sprite within the 15% area limit");
    }
    const int width = bounds.right - bounds.left;
    const int height = bounds.bottom - bounds.top;
    const int longest = std::max(width, height);
    const auto sizeAt = [&](int pixels) -> Size {
        return {std::max(1, pixels * width / longest),
                std::max(1, pixels * height / longest)};
    };
    const auto fits = [&](const Size &size) {
        // Count the last half-block as a full terminal row, even for odd heights.
        return static_cast<std::int64_t>(size.width) * ((size.height + 1) / 2) <= cellBudget;
    };
    int low = 1;
    int high = std::min(columns * longest / width, rows * 2 * longest / height);
    const Size maximum = sizeAt(high);
    if (fits(maximum)) {
        return maximum;
    }
    // Find the largest proportional integer-pixel size within the cell budget.
    while (low < high) {
        const int middle = low + (high - low + 1) / 2;
        if (fits(sizeAt(middle))) {
            low = middle;
        } else {
            high = middle - 1;
        }
    }
    return sizeAt(low);
}

int sample(const Image &image, const Bounds &bounds, const Size &size, int x, int y) {
    if (y >= size.height) {
        return -1;
    }
    // Sample pixel centers; nearest-neighbor keeps palette colors and sharp edges.
    const int sourceX =
        bounds.left +
        static_cast<int>((static_cast<std::int64_t>(2 * x + 1) * (bounds.right - bounds.left)) /
                         (2 * size.width));
    const int sourceY =
        bounds.top +
        static_cast<int>((static_cast<std::int64_t>(2 * y + 1) * (bounds.bottom - bounds.top)) /
                         (2 * size.height));
    const unsigned char *pixel = image.at(sourceX, sourceY);
    if (pixel[3] < 128) {
        return -1;
    }
    return (static_cast<int>(pixel[0]) << 16) | (static_cast<int>(pixel[1]) << 8) | pixel[2];
}

void appendColor(std::string &output, int color, bool foreground, int &previous) {
    if (color == previous) {
        return;
    }
    previous = color;
    if (color < 0) {
        output += foreground ? "\033[39m" : "\033[49m";
        return;
    }
    output += foreground ? "\033[38;2;" : "\033[48;2;";
    char number[3];
    for (int shift : {16, 8, 0}) {
        const auto converted =
            std::to_chars(number, number + sizeof(number), (color >> shift) & 255);
        output.append(number, converted.ptr);
        output += shift == 0 ? 'm' : ';';
    }
}

void render(const Image &image, const Bounds &bounds, const Size &size) {
    std::string line;
    line.reserve(static_cast<std::size_t>(size.width) * 48 + 16);
    for (int y = 0; y < size.height; y += 2) {
        line = "\033[0m";
        int foreground = -1;
        int background = -1;
        for (int x = 0; x < size.width; ++x) {
            const int upper = sample(image, bounds, size, x, y);
            const int lower = sample(image, bounds, size, x, y + 1);
            if (upper < 0 && lower < 0) {
                appendColor(line, -1, false, background);
                line += ' ';
            } else if (upper < 0) {
                appendColor(line, lower, true, foreground);
                appendColor(line, -1, false, background);
                line += "▄";
            } else {
                appendColor(line, upper, true, foreground);
                appendColor(line, lower, false, background);
                line += "▀";
            }
        }
        line += "\033[0m\n";
        std::cout << line;
    }
}

} // namespace

int main(int argc, char *argv[]) {
    try {
        const Options options = parseOptions(argc, argv);
        if (options.help) {
            printHelp();
            return 0;
        }
        const auto sprites = listSprites(spriteDirectory(options, argv[0]));
        if (options.list) {
            for (const auto &path : sprites) {
                std::cout << path.stem().string() << '\n';
            }
        } else {
            const fs::path &path = selectSprite(sprites, options.name);
            const Image image = loadImage(path);
            const Bounds bounds = visibleBounds(image);
            const Size size = renderSize(bounds, options);
            if (options.title) {
                std::cout << path.stem().string() << '\n';
            }
            render(image, bounds, size);
        }
        std::cout.flush();
        return std::cout ? 0 : 1;
    } catch (const std::exception &error) {
        std::cerr << "megaman-cli: " << error.what() << '\n';
        return 1;
    }
}
