cmake_minimum_required(VERSION 3.20)
project(lina_identity_service VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find GMP
find_package(PkgConfig REQUIRED)
pkg_check_modules(GMP REQUIRED gmp gmpxx)

# Paths to sibling modules — use the shared build tree
set(VALUE_ENGINE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../value_engine")
set(VALUE_ENGINE_BUILD_DIR "${CMAKE_BINARY_DIR}/value_engine")
set(MEMORY_MODULE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../memory")
set(MEMORY_MODULE_BUILD_DIR "${CMAKE_BINARY_DIR}/memory")

add_executable(identity_service_test
    identity_service.cpp
    main_identity.cpp
)

target_include_directories(identity_service_test PRIVATE
    ${GMP_INCLUDE_DIRS}
    ${VALUE_ENGINE_DIR}
    ${MEMORY_MODULE_DIR}
    .
)

target_link_libraries(identity_service_test PRIVATE
    ${GMP_LIBRARIES}
    "${VALUE_ENGINE_BUILD_DIR}/liblina_value_engine.a"
    "${MEMORY_MODULE_BUILD_DIR}/liblina_memory_module.a"
)

target_compile_options(identity_service_test PRIVATE -Wall -Wextra -Wpedantic)

# Add a library target for later integration
add_library(lina_identity_service STATIC
    identity_service.cpp
)
target_include_directories(lina_identity_service PUBLIC
    ${GMP_INCLUDE_DIRS}
    ${VALUE_ENGINE_DIR}
    ${MEMORY_MODULE_DIR}
    .
)
target_link_libraries(lina_identity_service PUBLIC
    ${GMP_LIBRARIES}
    "${VALUE_ENGINE_BUILD_DIR}/liblina_value_engine.a"
    "${MEMORY_MODULE_BUILD_DIR}/liblina_memory_module.a"
)
target_compile_options(lina_identity_service PRIVATE -fPIC)

# ── Shared library (C ABI) ─────────────────────────────────────────────────
add_library(lina_service_abi SHARED
    service_abi.cpp
)

target_include_directories(lina_service_abi PRIVATE
    ${GMP_INCLUDE_DIRS}
    ${VALUE_ENGINE_DIR}
    ${MEMORY_MODULE_DIR}
    .
)

target_link_libraries(lina_service_abi PRIVATE
    ${GMP_LIBRARIES}
    "${VALUE_ENGINE_BUILD_DIR}/liblina_value_engine_abi.so"
    "${MEMORY_MODULE_BUILD_DIR}/liblina_memory_module_abi.so"
    "${CMAKE_BINARY_DIR}/service/liblina_identity_service.a"
)

# Set soname and visibility for shared library
target_compile_options(lina_service_abi PRIVATE -fPIC -fvisibility=hidden)

# Set output directory for easy discovery
set_target_properties(lina_service_abi PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/service"
)