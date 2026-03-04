if(DEFINED slicersources_SOURCE_DIR AND NOT DEFINED Slicer_SOURCE_DIR)
  # Explicitly setting "Slicer_SOURCE_DIR" when only "slicersources_SOURCE_DIR"
  # is defined is required to successfully complete configuration in an empty
  # build directory
  #
  # Indeed, in that case, Slicer sources have been downloaded by they have not been
  # added using "add_subdirectory()" and the variable "Slicer_SOURCE_DIR" is not yet in
  # in the CACHE.
  set(Slicer_SOURCE_DIR ${slicersources_SOURCE_DIR})
endif()

# Set list of dependencies to ensure the custom application bundling this
# extension does NOT automatically collect the project list and attempt to
# build external projects conditionally enabled.
set(SlicerHeart_EXTERNAL_PROJECT_DEPENDENCIES
  lscm
  )
if(NOT DEFINED SlicerHeart_BUILD_ITK_FILTERS)
  set(SlicerHeart_BUILD_ITK_FILTERS OFF)
endif()
if(SlicerHeart_BUILD_ITK_FILTERS)
  list(APPEND SlicerHeart_BUILD_ITK_FILTERS
    ITKPhaseSymmetry
    ITKStrain
    )
endif()
message(STATUS "SlicerHeart_EXTERNAL_PROJECT_DEPENDENCIES:${SlicerHeart_EXTERNAL_PROJECT_DEPENDENCIES}")


if(NOT DEFINED Slicer_SOURCE_DIR)
  # Extension is built standalone

  # NA

else()
  # Extension is bundled in a custom application

  # Additional external project dependencies
  if(SlicerHeart_BUILD_ITK_FILTERS)
    ExternalProject_Add_Dependencies(ITKPhaseSymmetry
      DEPENDS
        ITK
      )
    ExternalProject_Add_Dependencies(ITKStrain
      DEPENDS
        ITK
      )
  endif()
endif()
