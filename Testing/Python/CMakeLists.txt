#-----------------------------------------------------------------------------
# Extension-wide Python tests: the end-to-end workflow and the interactive module journeys.
# They use the HeartValveTestLib fixtures of ValveAnnulusAnalysis/Testing/Python.

slicer_add_python_unittest(SCRIPT HeartValveWorkflowTest.py)
slicer_add_python_unittest(SCRIPT HeartValveInteractiveTest.py)
