# Feature tests (they write a markdown report with screenshots, see Import4DFlow/Testing/Python/FlowTestingUtils.py).
# The anonymized clinical data set test is skipped if MRI_4D_FLOW_TEST_DATA is not set.
slicer_add_python_unittest(SCRIPT Analyze4DFlowFeaturesTest.py)
