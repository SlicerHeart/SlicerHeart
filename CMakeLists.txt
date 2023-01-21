cmake_minimum_required(VERSION 3.5)

project(SlicerHeart)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/SlicerHeart/SlicerHeart#readme")
set(EXTENSION_CATEGORY "Cardiac")
set(EXTENSION_CONTRIBUTORS "Andras Lasso (PerkLab, Queen's University), Steve Pieper (Isomics), Adam Rankin (Robarts), Csaba Pinter (Pixel Medical / Ebatinca), Christian Herz (CHOP), Matthew Jolley (CHOP/UPenn)")
set(EXTENSION_DESCRIPTION "Modules for cardiac analysis and intervention planning and guidance")
set(EXTENSION_ICONURL "https://github.com/SlicerHeart/SlicerHeart/raw/master/SlicerHeart.png")
set(EXTENSION_SCREENSHOTURLS "https://github.com/SlicerHeart/SlicerHeart/raw/master/Docs/Image3dApiExample.png https://img.youtube.com/vi/hIxr9OKBvQ8/0.jpg https://raw.githubusercontent.com/SlicerHeart/SlicerHeart/master/ValveQuantification/Resources/MeasurementPreset/MitralValve.png")
set(EXTENSION_STATUS Beta)
set(EXTENSION_DEPENDS SlicerIGT)
set(EXTENSION_BUILD_SUBDIRECTORY inner-build)

set(SUPERBUILD_TOPLEVEL_PROJECT inner)

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})
mark_as_superbuild(Slicer_DIR)

find_package(Git REQUIRED)
mark_as_superbuild(GIT_EXECUTABLE)

# Only build ITK filters if ITK5 is available
# Disable by default, as it is currently not used and may break the build
option(SlicerHeart_BUILD_ITK_FILTERS "Build ITK noise filters." OFF)
message(STATUS "ITK version: ${ITK_VERSION_MAJOR}.${ITK_VERSION_MINOR}.${ITK_VERSION_PATCH}.")
if(${ITK_VERSION_MAJOR}.${ITK_VERSION_MINOR} VERSION_LESS 5.0)
  message(STATUS "ITK version: ${ITK_VERSION_MAJOR}.${ITK_VERSION_MINOR}.${ITK_VERSION_PATCH}. ITK filters are not built.")
  set(SlicerHeart_BUILD_ITK_FILTERS OFF)
endif()
mark_as_superbuild(SlicerHeart_BUILD_ITK_FILTERS)

#-----------------------------------------------------------------------------
# SuperBuild setup
option(${EXTENSION_NAME}_SUPERBUILD "Build ${EXTENSION_NAME} and the projects it depends on." ON)
mark_as_advanced(${EXTENSION_NAME}_SUPERBUILD)
if(${EXTENSION_NAME}_SUPERBUILD)
  include("${CMAKE_CURRENT_SOURCE_DIR}/SuperBuild.cmake")
  return()
endif()

# We do not have compile-time dependency on SlicerIGT therefore
# there is no need for find_package. Uncomment the following lines
# if compile-time dependency is added.
# find_package(SlicerIGT REQUIRED)

#-----------------------------------------------------------------------------
# Extension modules
set(slicerheart_modules
  ValveView
  Philips4dUsDicomPatcher
#   Philips4dUsReader # Disabled until fixing the gdcm build errors
  KretzFileReader
  GeUsMovieReader
  DicomUltrasoundPlugin
  CardiacDeviceSimulator
  AsdVsdDeviceSimulator
  TCAVValveSimulator
  ValveAnnulusAnalysis
  ValveClipDeviceSimulator
  ValvePapillaryAnalysis
  ValveQuantification
  TomTecUcdPlugin
  CartoExport
  BafflePlanner
  ConformalTextureMapping
  Reconstruct4DCineMRI
  EchoVolumeRender
  ValveBatchExport
  LeafletMoldGenerator
  ValveSegmentation
  LeafletAnalysis
  )
if(SlicerHeart_BUILD_ITK_FILTERS)
  list(APPEND slicerheart_modules
    PhaseSymmetryFilter
    )
endif()
if(WIN32)
  # Image3dAPI only works on Windows
  # (see https://github.com/MedicalUltrasound/Image3dAPI)
  list(APPEND slicerheart_modules
    UltrasoundImage3dReader
    )
endif()

# Allow to check if a given SlicerHeart module should be enabled or disabled.
#
# Definitions:
#
# * A SlicerHeart module is a module whose source code is found under one of the
#   "SlicerHeart/*" subdirectories.
#
# * Enabling (or disabling) a module means that it will (or will not) be built.
#
# * Building a module means that the corresponding directory is added using the add_subdirectory
#   CMake command and that the associated CMakeLists.txt is processed.
#
# By default, all SlicerHeart modules are assumed to be enabled. Then, based on
# build options or variables describing the system (e.g WIN32), module may be disabled.
#
# Setting these variables allows to explicitly disable or enable modules
# ignoring effect of the CMake variables or build options:
# * SlicerHeart_MODULES_DISABLED
# * SlicerHeart_MODULES_ENABLED
#
include(SlicerCheckModuleEnabled)
macro(slicerheart_is_module_enabled module_name output_var)
  _slicer_is_module_enabled("SlicerHeart_MODULES" ${module_name} ${output_var})
endmacro()

foreach(module ${slicerheart_modules})
  slicerheart_is_module_enabled(${module} _build_module)
  if(_build_module)
    add_subdirectory(${module})
  endif()
endforeach()

#-----------------------------------------------------------------------------
set(EXTENSION_CPACK_INSTALL_CMAKE_PROJECTS)
if (SlicerHeart_BUILD_ITK_FILTERS)
  list(APPEND EXTENSION_CPACK_INSTALL_CMAKE_PROJECTS "${ITKStrain_DIR};Strain;RuntimeLibraries;/")
  list(APPEND EXTENSION_CPACK_INSTALL_CMAKE_PROJECTS "${ITKPhaseSymmetry_DIR};PhaseSymmetry;RuntimeLibraries;/")
  # Note: no need to install lscm (executable will be installed by the ConformalTextureMapping module)
endif()
set(${EXTENSION_NAME}_CPACK_INSTALL_CMAKE_PROJECTS "${EXTENSION_CPACK_INSTALL_CMAKE_PROJECTS}" CACHE STRING "List of external projects to install" FORCE)
#-----------------------------------------------------------------------------
list(APPEND CPACK_INSTALL_CMAKE_PROJECTS "${CMAKE_BINARY_DIR};${EXTENSION_NAME};ALL;/")
list(APPEND CPACK_INSTALL_CMAKE_PROJECTS "${${EXTENSION_NAME}_CPACK_INSTALL_CMAKE_PROJECTS}")
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
