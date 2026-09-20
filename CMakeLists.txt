cmake_minimum_required(VERSION 3.16)
project(megaman-cli VERSION 1.0.0 LANGUAGES CXX)

include(GNUInstallDirs)
find_package(PNG REQUIRED)

add_executable(megaman-cli main.cpp)
target_compile_features(megaman-cli PRIVATE cxx_std_17)
target_link_libraries(megaman-cli PRIVATE PNG::PNG)
set_target_properties(megaman-cli PROPERTIES CXX_EXTENSIONS OFF)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(megaman-cli PRIVATE -Wall -Wextra -Wpedantic)
endif()

file(RELATIVE_PATH MEGAMAN_RELATIVE_SPRITE_DIR
    "${CMAKE_INSTALL_FULL_BINDIR}"
    "${CMAKE_INSTALL_FULL_DATADIR}/megaman-cli/sprites")
target_compile_definitions(megaman-cli PRIVATE
    MEGAMAN_SOURCE_SPRITE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/mm-sprites/pngs"
    MEGAMAN_INSTALL_SPRITE_DIR="${CMAKE_INSTALL_FULL_DATADIR}/megaman-cli/sprites"
    MEGAMAN_RELATIVE_SPRITE_DIR="${MEGAMAN_RELATIVE_SPRITE_DIR}")

install(TARGETS megaman-cli RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(FILES LICENSE README.md DESTINATION "${CMAKE_INSTALL_DOCDIR}")
install(FILES docs/images/banner.png
    DESTINATION "${CMAKE_INSTALL_DOCDIR}/docs/images")

# Sprite artwork is not part of this repository: see the "Sprite artwork"
# section of README.md. A local mm-sprites/pngs/ is installed when present, so
# a personal checkout still ships its own assets; without one the executable
# relies on --sprites-dir or MEGAMAN_SPRITES_DIR at runtime.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/mm-sprites/pngs")
    install(DIRECTORY mm-sprites/pngs/
        DESTINATION "${CMAKE_INSTALL_DATADIR}/megaman-cli/sprites"
        FILES_MATCHING PATTERN "*.png" PATTERN "*.PNG")
endif()

include(CTest)
if(BUILD_TESTING)
    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND)
        add_test(NAME renderer-edges
            COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_renderer.py"
                "$<TARGET_FILE:megaman-cli>")
    endif()
endif()
