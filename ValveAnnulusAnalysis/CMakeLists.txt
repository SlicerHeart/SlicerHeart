#-----------------------------------------------------------------------------
set(MODULE_NAME ValveAnnulusAnalysis)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  HeartValveLib/__init__
  HeartValveLib/util
  HeartValveLib/helpers
  HeartValveLib/HeartValves
  HeartValveLib/HeartValvesSubjectHierarchyPlugin
  HeartValveLib/ValveRoi
  HeartValveLib/LeafletModel
  HeartValveLib/ValveModel
  HeartValveLib/PapillaryModel
  HeartValveLib/CoaptationModel
  HeartValveLib/Constants
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/Icons/CAVC.png
  Resources/Icons/Mitral.png
  Resources/Icons/PDA.png
  Resources/Icons/Tricuspid.png
  Resources/UI/${MODULE_NAME}.ui
  Resources/VrPresets/CT-EndoVascular.png
  Resources/VrPresets/US-Green.png
  Resources/VrPresets/US-Grey.png
  Resources/VrPresets/US-InverseGreen.png
  Resources/VrPresets/US-Ocean.png
  Resources/VrPresets/US-Red.png
  Resources/VrPresets/US-Red-Tinge.png
  Resources/VrPresets/US-Silver.png
  Resources/VrPresets/US-VrPresets.mrml
  Resources/HeartOrientationMarker.vtp
  Resources/SlicerHeartSegmentationCategoryTypeModifier.json
  Resources/SlicerHeartPDAVesselsCategoryTypeModifier_A_Normal.jpg
  Resources/SlicerHeartPDAVesselsCategoryTypeModifier_A_Normal.json
  Resources/SlicerHeartPDAVesselsCategoryTypeModifier_B_CommonBrachioBicephalicTrunk.jpg
  Resources/SlicerHeartPDAVesselsCategoryTypeModifier_B_CommonBrachioBicephalicTrunk.json
  Resources/SlicerHeartPDAVesselsCategoryTypeModifier_C_RightAorticArch.jpg
  Resources/SlicerHeartPDAVesselsCategoryTypeModifier_C_RightAorticArch.json
  Resources/SlicerHeartPDAVesselsCategoryTypeModifier_Other.png # From https://www.shareicon.net/dialogue-box-slider-navigation-multimedia-chat-conversation-658180
  Resources/SlicerHeartPDAVesselsCategoryTypeModifier_Other.json
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

  # Additional build-time testing
  add_subdirectory(Testing)
endif()
