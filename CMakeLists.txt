cmake_minimum_required(VERSION 2.8.9)

project(HeartValves)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "http://www.example.com/Slicer/Extensions/HeartValves")
set(EXTENSION_CATEGORY "Heart Valves")
set(EXTENSION_CONTRIBUTORS "Andras Lasso (PerkLab)")
set(EXTENSION_DESCRIPTION "Modules for analyzing heart valves")
set(EXTENSION_ICONURL "http://www.example.com/Slicer/Extensions/HeartValves.png")
set(EXTENSION_SCREENSHOTURLS "http://www.example.com/Slicer/Extensions/HeartValves/Screenshots/1.png")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(ValveView)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_CPACK})
