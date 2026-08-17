cmake_minimum_required(VERSION 3.20)
project(lina_cpp_modules LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory(value_engine)
add_subdirectory(memory)
add_subdirectory(service)