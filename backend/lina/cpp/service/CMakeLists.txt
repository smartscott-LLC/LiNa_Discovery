cmake_minimum_required(VERSION 3.20)
project(lina_identity_service VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find GMP
find_package(PkgConfig REQUIRED)
pkg_check_modules(GMP REQUIRED gmp gmpxx)

# Paths to sibling modules
set(VALUE_ENGINE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../value_engine")
set(VALUE_ENGINE_BUILD_DIR "${VALUE_ENGINE_DIR}/build")
set(MEMORY_MODULE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../memory")
set(MEMORY_MODULE_BUILD_DIR "${MEMORY_MODULE_DIR}/build")

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