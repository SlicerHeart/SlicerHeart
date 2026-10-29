#-----------------------------------------------------------------------------
# Extension-wide Python tests: the end-to-end workflow and the interactive module journeys.
# They use the HeartValveTestLib fixtures of ValveAnnulusAnalysis/Testing/Python.

# The workflow test does not need the GUI. It runs without the main window: with the views present,
# the application does not exit after this test (leaked model display pipelines of
# vtkMRMLModelDisplayableManager keep OpenGL objects alive past the render windows).
slicer_add_python_unittest(SCRIPT HeartValveWorkflowTest.py SLICER_ARGS --no-main-window)
slicer_add_python_unittest(SCRIPT HeartValveInteractiveTest.py)
