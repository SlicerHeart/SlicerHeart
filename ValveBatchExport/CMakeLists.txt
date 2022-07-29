#-----------------------------------------------------------------------------
set(MODULE_NAME ValveBatchExport)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  HeartValveBatchAnalysis/__init__
  HeartValveBatchAnalysis/annulus_shape_analysis
  ValveBatchExportRules/__init__
  ValveBatchExportRules/base
  ValveBatchExportRules/QuantificationResults
  ValveBatchExportRules/PapillaryAnalysisResults
  ValveBatchExportRules/AnnulusContourCoordinates
  ValveBatchExportRules/AnnulusContourModel
  ValveBatchExportRules/ValveLandmarkCoordinates
  ValveBatchExportRules/ValveVolume
  ValveBatchExportRules/LeafletSegmentation
  ValveBatchExportRules/ValveLandmarks
  ValveBatchExportRules/ValveLandmarkLabels
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

#-----------------------------------------------------------------------------
if(BUILD_TESTING)

  # Register the unittest subclass in the main script as a ctest.
  # Note that the test will also be available at runtime.
  slicer_add_python_unittest(SCRIPT ${MODULE_NAME}.py)

endif()
