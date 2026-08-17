cmake_minimum_required(VERSION 3.20)
project(lina_value_engine VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find GMP
find_package(PkgConfig REQUIRED)
pkg_check_modules(GMP REQUIRED gmp gmpxx)

add_executable(value_engine_test
    value_engine.cpp
    main.cpp
)

target_include_directories(value_engine_test PRIVATE ${GMP_INCLUDE_DIRS} .)
target_link_libraries(value_engine_test PRIVATE ${GMP_LIBRARIES})

# Enable warnings
target_compile_options(value_engine_test PRIVATE -Wall -Wextra -Wpedantic)

# Add a library target for later integration
add_library(lina_value_engine STATIC
    value_engine.cpp
)
target_include_directories(lina_value_engine PUBLIC ${GMP_INCLUDE_DIRS} .)
target_link_libraries(lina_value_engine PUBLIC ${GMP_LIBRARIES})