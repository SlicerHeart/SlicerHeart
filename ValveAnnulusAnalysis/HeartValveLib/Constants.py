from collections import OrderedDict

PROBE_POSITION_UNKNOWN = 'UNKNOWN'
PROBE_POSITION_TTE_APICAL = 'TTE_APICAL'
PROBE_POSITION_TTE_APICAL_NONSTANDARD_DOT_AT_9OCLOCK = 'TTE_APICAL_NONSTANDARD_DOT_AT_9OCLOCK'
PROBE_POSITION_TTE_SUBCOSTAL = 'TTE_SUBCOSTAL'
PROBE_POSITION_TTE_SUBCOSTAL_NONSTANDARD_DOT_AT_12OCLOCK = 'TTE_SUBCOSTAL_NONSTANDARD_DOT_AT_12OCLOCK'
PROBE_POSITION_TEE_APICAL = 'TEE_APICAL'
PROBE_POSITION_PATIENT_ANATOMICAL_AXES = 'PATIENT_ANATOMICAL_AXES'
VALVE_MASK_SEGMENT_ID = 'ValveMask'

# axialSliceToRasTransformMatrix defines axial slice directions in RAS coordinate system
# so that:
#   Slice view X axis = patient L
#   Slice view Y axis = patient S
# axialSliceToOrtho1SliceRotationsDeg and axialSliceToOrtho2SliceRotationsDeg
# defines 3 rotations to apply to the axial slice to orient ortho1 (yellow) and ortho2 (green) slices.
PROBE_POSITION_PRESETS = OrderedDict([
  (PROBE_POSITION_UNKNOWN, {
    'name': 'unknown',
    'description': 'Probe position is unknown.',
    'probeToRasTransformMatrix': '1 0 0 0  0 1 0 0  0 0 1 0  0 0 0 1',
    'axialSliceToRasTransformMatrix': '-1 0 0 0  0 0 1 0  0 1 0 0  0 0 0 1',
    'axialSliceToOrtho1SliceRotationsDeg': [0, -90, 0],
    'axialSliceToOrtho2SliceRotationsDeg': [-90, 0, 0]
  }),
  (PROBE_POSITION_TTE_APICAL, {
    'name': 'TTE apical',
    'description': "Apical view using transthoracic probe. Dot on the probe is at 3 o'clock direction.",
    'probeToRasTransformMatrix': '-0.939693 -0.296198 0.17101 0 0.07111 -0.658272 -0.749414 0 0.334546 -0.692058 0.639636 0 0 0 0 1',
    'axialSliceToRasTransformMatrix': '-0.939693 0.296198 -0.17101 0 0.07111 0.658272 0.749414 0 0.334546 0.692058 -0.639636 0 0 0 0 1',
    'axialSliceToOrtho1SliceRotationsDeg': [-90, -90, 0],
    'axialSliceToOrtho2SliceRotationsDeg': [-90, 0, 0]
  }),
  (PROBE_POSITION_TTE_APICAL_NONSTANDARD_DOT_AT_9OCLOCK, {
    'name': "TTE apical (non-standard 9 o'clock)",
    'description': "Apical view using transthoracic probe. Dot on the probe is at (non-standard) 9 o'clock direction.",
    'probeToRasTransformMatrix': '0.939693 0.296198 0.17101 0 -0.07111 0.658272 -0.749414 0 -0.334546 0.692058 0.639636 0 0 0 0 1',
    'axialSliceToRasTransformMatrix': '-0.939693 0.296198 -0.17101 0 0.07111 0.658272 0.749414 0 0.334546 0.692058 -0.639636 0 0 0 0 1',
    'axialSliceToOrtho1SliceRotationsDeg': [-90, -90, 0],
    'axialSliceToOrtho2SliceRotationsDeg': [-90, 0, 0]
  }),
  (PROBE_POSITION_TTE_SUBCOSTAL, {
    'name': 'TTE sub-costal short-axis',
    'description': "Sub-costal view, dot at 6 o'clock.",
    'probeToRasTransformMatrix': '-0.796091 -0.37075 0.478313 0 0.340335 -0.927818 -0.152728 0 0.500412 0.0412014 0.864807 0 0 0 0 1',
    'axialSliceToRasTransformMatrix': '-0.796091 0.37075 -0.478313 0 0.340335 0.927818 0.152728 0 0.500412 -0.0412014 -0.864807 0 0 0 0 1',
    'axialSliceToOrtho1SliceRotationsDeg': [-90, -90, 0],
    'axialSliceToOrtho2SliceRotationsDeg': [-90, 0, 0]
  }),
  (PROBE_POSITION_TTE_SUBCOSTAL_NONSTANDARD_DOT_AT_12OCLOCK, {
    'name': "TTE sub-costal short-axis (non-standard 12 o'clock)",
    'description': "Sub-costal view. Dot on the probe is at (non-standard) 12 o'clock direction.",
    'probeToRasTransformMatrix': '0.796091 0.37075 0.478313 0 -0.340335 0.927818 -0.152728 0 -0.500412 -0.0412014 0.864807 0 0 0 0 1',
    'axialSliceToRasTransformMatrix': '-0.796091 0.37075 -0.478313 0 0.340335 0.927818 0.152728 0 0.500412 -0.0412014 -0.864807 0 0 0 0 1',
    'axialSliceToOrtho1SliceRotationsDeg': [-90, -90, 0],
    'axialSliceToOrtho2SliceRotationsDeg': [-90, 0, 0]
  }),
  (PROBE_POSITION_TEE_APICAL, {
    'name': 'TEE mid-esophageal',
    'description': 'TEE probe at mid-esophageal position.',
    'probeToRasTransformMatrix': '-0.939693 0 0.34202 0 0.34202 0 0.939693 0 0 1 0 0 0 0 0 1',
    'axialSliceToRasTransformMatrix': '-0.939693 0 0.34202 0 0.34202 0 0.939693 0 0 1 0 0 0 0 0 1',
    'axialSliceToOrtho1SliceRotationsDeg': [-90, -90, -90],
    'axialSliceToOrtho2SliceRotationsDeg': [-90, 0, 0]
  }),
  (PROBE_POSITION_PATIENT_ANATOMICAL_AXES, {
    'name': 'Patient anatomical axes',
    'description': "Image axes are aligned with patient anatomical axes (right-anterior-superior). Typical for CT and MRI acquisitions.",
    'probeToRasTransformMatrix': '0.587785 0.809017 0 -85.1289 -0.809017 0.587785 0 -107.865 0 0 1 -1185.5 0 0 0 1',
    'axialSliceToRasTransformMatrix': '1 0 0 0 0 -1 0 0 0 0 -1 0 0 0 0 1',
    'axialSliceToOrtho1SliceRotationsDeg': [-90, -90, 0],
    'axialSliceToOrtho2SliceRotationsDeg': [-90, 0, 0]
  })
])

# approximateFlowDirection: Defines approximate blood flow direction through the valve.
#   It is used for determining sign of annulus contour plane normal. "anterior" means towards heart anterior (towards apex) direction.
#   For unknown valves, plane normal will be approximately point to anterior direction, which will be correct for mitral and tricuspid valves.
# phaseComparePointLabels: during phase compare, these labels will be used to split up the contour to segments. If not specified then all
#   point labels will be used that present in both of the compared valves.
VALVE_TYPE_PRESETS = OrderedDict([
  ("unknown", {
    "shortname": "UN",
    "approximateFlowDirection": "anterior",
    "papillaryNames": ["papillary1", "papillary2", "papillary3", "papillary4"],
    "papillaryShortNames": ["P1", "P2", "P3", "P4"],
    "phaseComparePointLabels": None
  }),
  ("mitral", {
    "shortname": "MV",
    "approximateFlowDirection": "anterior",
    "papillaryNames": ["antero-lateral", "postero-medial"],
    "papillaryShortNames": ["AL", "PM"],
    "phaseComparePointLabels": ["A", "P", "PM", "AL"],
  }),
  ("tricuspid", {
    "shortname": "TV",
    "approximateFlowDirection": "anterior",
    "papillaryNames": ["anterior", "posterior", "septal"],
    "papillaryShortNames": ["A", "P", "S"],
    "phaseComparePointLabels": ["A", "P", "S", "L"],
  }),
  ("aortic", {
    "shortname": "AV",
    "approximateFlowDirection": "posterior",
    "papillaryNames": ["papillary1", "papillary2", "papillary3"],
    "papillaryShortNames": ["P1", "P2", "P3"],
    "phaseComparePointLabels": None
  }),
  ("pulmonary", {
    "shortname": "PV",
    "approximateFlowDirection": "posterior",
    "papillaryNames": ["papillary1", "papillary2", "papillary3"],
    "papillaryShortNames": ["P1", "P2", "P3"],
    "phaseComparePointLabels": None
  }),
 ("cavc", {
    "shortname": "CAVC",
    "approximateFlowDirection": "anterior",
    "papillaryNames": ["anterior", "posterior", "superior-lateral", "inferior-lateral"],
    "papillaryShortNames": ["P1", "P2", "P3", "P4"],
    "phaseComparePointLabels": ['R', 'MA', 'L', 'MP']
  }),
  ("lavv", {
    "shortname": "LAVV",
    "approximateFlowDirection": "anterior",
    "papillaryNames": ["superior-lateral", "inferior-lateral"],
    "papillaryShortNames": ["P1", "P2"],
    "phaseComparePointLabels": ['PMC', 'ALC', 'SIC']
  }),
  ("tri-leaflet aortic valve", {
    "shortname": "triAV",
    "approximateFlowDirection": "posterior",
    "papillaryNames": ["papillary1", "papillary2", "papillary3"],
    "papillaryShortNames": ["P1", "P2", "P3"],
    "phaseComparePointLabels": None
  }),
  ("bi-commissural aortic valve", {
    "shortname": "bicomAV",
    "approximateFlowDirection": "posterior",
    "papillaryNames": ["papillary1", "papillary2", "papillary3", "papillary4"],
    "papillaryShortNames": ["P1", "P2", "P3", "P4"],
    "phaseComparePointLabels": None
  }),
  ("tri-leaflet truncal valve", {
    "shortname": "triTruncV",
    "approximateFlowDirection": "posterior",
    "papillaryNames": ["papillary1", "papillary2", "papillary3"],
    "papillaryShortNames": ["P1", "P2", "P3"],
    "phaseComparePointLabels": None
  }),
  ("quadracuspid truncal valve", {
    "shortname": "quadTruncV",
    "approximateFlowDirection": "posterior",
    "papillaryNames": ["papillary1", "papillary2", "papillary3", "papillary4"],
    "papillaryShortNames": ["P1", "P2", "P3", "P4"],
    "phaseComparePointLabels": None
  })
])

PAPILLARY_MUSCLE_POINT_LABELS = ["muscle base", "muscle tip", "chordal insertion"]

CARDIAC_CYCLE_PHASE_PRESETS = OrderedDict([
  ("unknown", {
    "color": [0.3, 0.3, 1.0],
    "shortname": "UN"
  }),
  ("mid-systole",  {
    "color": [1.0, 0.0, 0.0],
    "shortname": "MS"
  }),
  ("end-systole",  {
    "color": [1.0, 1.0, 0.0],
    "shortname": "ES"
  }),
  ("mid-diastole", {
    "color": [0.0, 0.0, 1.0],
    "shortname": "MD"
  }),
  ("end-diastole", {
    "color": [0.0, 1.0, 1.0],
    "shortname": "ED"
  }),
  ("custom-systolic", {
    "color": [0.82, 0.09, 0.81],
    "shortname": "CS"
  }),
  ("custom-transition", {
    "color": [1.0, 0.56, 0.18],
    "shortname": "CT"
  }),
  ("custom-diastolic", {
    "color": [0.02, 0.76, 0.04],
    "shortname": "CD"
  }),
  ("custom1", {
    "color": [0.0, 1.0, 0.0],
    "shortname": "P1"
  }),
  ("custom2", {
    "color": [1.0, 0.0, 1.0],
    "shortname": "P2"
  }),
  ("custom3", {
    "color": [0.5, 0.5, 1.0],
    "shortname": "P3"
  }),
  ("custom4",  {
    "color": [1.0, 0.5, 0.5],
    "shortname": "P4"
  })
])