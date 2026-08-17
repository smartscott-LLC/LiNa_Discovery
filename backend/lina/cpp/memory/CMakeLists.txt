cmake_minimum_required(VERSION 3.20)
project(lina_memory_module VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find GMP
find_package(PkgConfig REQUIRED)
pkg_check_modules(GMP REQUIRED gmp gmpxx)

# Path to value_engine library — use the shared build tree
set(VALUE_ENGINE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../value_engine")
set(VALUE_ENGINE_BUILD_DIR "${CMAKE_BINARY_DIR}/value_engine")

add_executable(memory_module_test
    memory_module.cpp
    main_memory.cpp
)

target_include_directories(memory_module_test PRIVATE
    ${GMP_INCLUDE_DIRS}
    ${VALUE_ENGINE_DIR}
    .
)

# Link to value_engine static library (built separately)
target_link_libraries(memory_module_test PRIVATE
    ${GMP_LIBRARIES}
    "${VALUE_ENGINE_BUILD_DIR}/liblina_value_engine.a"
)

# Enable warnings
target_compile_options(memory_module_test PRIVATE -Wall -Wextra -Wpedantic)

# Add a library target for later integration
add_library(lina_memory_module STATIC
    memory_module.cpp
)
target_include_directories(lina_memory_module PUBLIC
    ${GMP_INCLUDE_DIRS}
    ${VALUE_ENGINE_DIR}
    .
)
target_link_libraries(lina_memory_module PUBLIC
    ${GMP_LIBRARIES}
    "${VALUE_ENGINE_BUILD_DIR}/liblina_value_engine.a"
)
target_compile_options(lina_memory_module PRIVATE -fPIC)

# Shared library for C ABI
add_library(lina_memory_module_abi SHARED
    memory_module_abi.cpp
)
target_include_directories(lina_memory_module_abi PUBLIC
    ${GMP_INCLUDE_DIRS}
    ${VALUE_ENGINE_DIR}
    .
)
target_link_libraries(lina_memory_module_abi PRIVATE
    ${GMP_LIBRARIES}
    lina_memory_module
    "${VALUE_ENGINE_BUILD_DIR}/liblina_value_engine.a"
)
set_target_properties(lina_memory_module_abi PROPERTIES
    VERSION 0.1.0
    SOVERSION 0
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
)