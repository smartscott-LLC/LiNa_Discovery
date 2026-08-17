cmake_minimum_required(VERSION 3.20)
project(lina_value_engine VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find GMP
find_package(PkgConfig REQUIRED)
pkg_check_modules(GMP REQUIRED gmp gmpxx)

# ── Test executable ─────────────────────────────────────────────────────────
add_executable(value_engine_test
    value_engine.cpp
    main.cpp
)

target_include_directories(value_engine_test PRIVATE ${GMP_INCLUDE_DIRS} .)
target_link_libraries(value_engine_test PRIVATE ${GMP_LIBRARIES})
target_compile_options(value_engine_test PRIVATE -Wall -Wextra -Wpedantic)

# ── Static library (for internal C++ linking) ───────────────────────────────
add_library(lina_value_engine STATIC
    value_engine.cpp
)
target_include_directories(lina_value_engine PUBLIC ${GMP_INCLUDE_DIRS} .)
target_link_libraries(lina_value_engine PUBLIC ${GMP_LIBRARIES})
target_compile_options(lina_value_engine PRIVATE -fPIC)

# ── Shared library with C ABI (for ctypes / Python bridge) ──────────────────
add_library(lina_value_engine_abi SHARED
    value_engine.cpp
    value_engine_abi.cpp
)
target_include_directories(lina_value_engine_abi PUBLIC ${GMP_INCLUDE_DIRS} .)
target_link_libraries(lina_value_engine_abi PUBLIC ${GMP_LIBRARIES})
target_compile_options(lina_value_engine_abi PRIVATE -Wall -Wextra -Wpedantic)

# Remove C++ ABI symbols from the public interface — only extern "C" remain
set_target_properties(lina_value_engine_abi PROPERTIES
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
    POSITION_INDEPENDENT_CODE ON
    SOVERSION 0.1.0
)