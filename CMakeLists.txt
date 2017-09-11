cmake_minimum_required(VERSION 3.5)

project(SlicerHeart)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "http://www.slicer.org/slicerWiki/index.php/Documentation/Nightly/Extensions/SlicerHeart")
set(EXTENSION_CATEGORY "Cardiac")
set(EXTENSION_CONTRIBUTORS "Andras Lasso (PerkLab), Steve Pieper (Isomics), Adam Rankin (Robarts), Matthew Jolley (CHOP)")
set(EXTENSION_DESCRIPTION "Modules for cardiac analysis and intervention planning and guidance")
set(EXTENSION_ICONURL "http://www.slicer.org/slicerWiki/images/f/ff/SlicerHeart_Logo_128x128.png")
set(EXTENSION_SCREENSHOTURLS "http://www.slicer.org/slicerWiki/images/a/ae/BasicHeartView.png")
set(EXTENSION_DEPENDS "Sequences")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(ValveView)
add_subdirectory(Philips4dUsDicomPatcher)
add_subdirectory(DicomUltrasoundPlugin)
add_subdirectory(KretzFileReader)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_CPACK})
