
#slicer_add_python_unittest(SCRIPT ${MODULE_NAME}ModuleTest.py)

# Feature tests (they write a markdown report with screenshots, see FlowTestingUtils.py).
# The anonymized clinical data set test is skipped if MRI_4D_FLOW_TEST_DATA is not set.
slicer_add_python_unittest(SCRIPT Import4DFlowFeaturesTest.py)
