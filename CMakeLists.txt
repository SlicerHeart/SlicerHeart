cmake_minimum_required(VERSION 2.8.9)

project(HeartValves)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/SlicerHeart")
set(EXTENSION_CATEGORY "Cardiac")
set(EXTENSION_CONTRIBUTORS "Andras Lasso (PerkLab), Steve Pieper (Isomics), Adam Rankin (Robarts), Matthew Jolley (Children's Harvard)")
set(EXTENSION_DESCRIPTION "Modules for cardiac analysis and intervention planning and guidance")
set(EXTENSION_ICONURL "http://www.example.com/Slicer/Extensions/HeartValves.png")
set(EXTENSION_SCREENSHOTURLS "http://www.example.com/Slicer/Extensions/HeartValves/Screenshots/1.png")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(ValveView)
add_subdirectory(DicomPatcher)
add_subdirectory(DicomUltrasoundPlugin)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_CPACK})
