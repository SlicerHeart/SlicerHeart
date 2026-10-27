"""Identification of 4D flow MRI DICOM images (magnitude and velocity component images) from their headers, for the
supported vendors (Siemens, GE, Philips): role of the image, direction code of the encoded velocity component, velocity
encoding (venc), the loaded voxel value that corresponds to venc, heart rate. Only pydicom is used (no Slicer), so the
classification can be tested without loading images.

Direction codes:
- Siemens: relative to the image: "through", "inplane_rl", "inplane_ap", "inplane_fh"; mapped to RAS axes by
  Import4DFlowLogic.axisForDirectionCodes (depends on the acquisition orientation).
- GE, Philips: along patient axes: "patient_rl", "patient_ap", "patient_fh" (RAS axes R, A, S, independent of the
  image orientation), with the signs in PATIENT_AXIS_CONFIGURATIONS.

Velocity scaling: a loaded voxel value v (after the DICOM reader of Slicer applied RescaleSlope/RescaleIntercept, if
any) gives the velocity (mm/s) along the encoded direction as v * vencMmPerSec / maxValue, where maxValue is the loaded
value that corresponds to the velocity encoding:
- Siemens CS 4D flow: phase in [-4096, 4096) (rescaled), maxValue = 4096
- GE: no rescale tags, int16 pixel = phase * (0019,10E2) [Velocity Encode Scale = venc/pi, mm/s per radian], so
  maxValue = (0019,10E2) * pi (= venc mm/s: the pixel values are velocity in mm/s)
- Philips: RescaleSlope/RescaleIntercept convert the stored value to cm/s (RescaleType "cm/s"), so maxValue = venc cm/s

Vendor conventions were verified on sample data sets, see Docs/Import4DFlow.md "Vendor DICOM conventions".
"""

import logging
import math
import re

SIEMENS_DIRECTION_CODES = ("through", "inplane_rl", "inplane_ap", "inplane_fh")
PATIENT_DIRECTION_CODES = ("patient_rl", "patient_ap", "patient_fh")  # RAS axes R, A, S
MAGNITUDE_DIRECTION_CODE = "magnitude"
# Auxiliary images of an acquisition (neither magnitude nor velocity component), loaded as additional image sequences
COMPLEX_DIFFERENCE_DIRECTION_CODE = "complex_difference"  # GE: angiogram-like complex difference image
AUXILIARY_DIRECTION_CODES = (COMPLEX_DIFFERENCE_DIRECTION_CODE,)

# Siemens CS 4D flow component images store the phase in the range of [-4096, 4096)
SIEMENS_PHASE_MAX_VALUE = 4096

# Patient-axis velocity encoding (GE, Philips): for each RAS axis (R, A, S), (directionCode, invertToRasDirection).
# invertToRasDirection is True if a positive stored velocity points to the negative RAS direction (that is, to L or P).
# The sign convention is not in the DICOM headers; it was verified on sample data sets with the encoding direction
# check (divergence of the time-averaged velocity, slicerheart_4dflow.encoding_check) and the physiological flow
# direction in the great vessels (see Docs/Import4DFlow.md "Vendor DICOM conventions").
PATIENT_AXIS_CONFIGURATIONS = {
    # Philips: (0018,9090) Velocity Encoding Direction is given in the patient (LPS) coordinate system; positive velocity
    # points to L, P, S (Philips Ingenia Ambition X, software 12.3, classic DICOM export)
    "philips": [("patient_rl", True), ("patient_ap", True), ("patient_fh", False)],
    # GE: (0043,1030) Vas collapse flag gives the encoded patient axis (L/R, A/P, S/I); positive velocity points to
    # L, P, S (GE DISCOVERY MR750, software 27, mm4dflow sequence)
    "ge": [("patient_rl", True), ("patient_ap", True), ("patient_fh", False)],
}

# Image-relative velocity encoding (Siemens): the possible (directionCode, invertToRasDirection) triplets for the RAS
# axes R, A, S, in the order of preference (the first configuration that has all 3 components is used).
SIEMENS_AXIS_CONFIGURATIONS = [
    [("through", True), ("inplane_ap", True), ("inplane_fh", False)],
    [("inplane_rl", False), ("through", True), ("inplane_fh", False)],
    # We have not encountered the following configuration yet, but based on the first two cases (observed in real data
    # sets) it seems possible. Need to verify the invertToRasDirection flags.
    [("inplane_rl", True), ("inplane_ap", True), ("through", False)],
]


def componentConfiguration(vendorName, directionCodes):
    """Velocity component configuration for the available direction codes: list of (directionCode, invertToRasDirection)
    for the RAS axes R, A, S (the image-relative configurations of Siemens are tried first, then the patient-axis
    configuration of the vendor), or None if no configuration has all 3 components."""
    configurations = list(SIEMENS_AXIS_CONFIGURATIONS)
    if vendorName in PATIENT_AXIS_CONFIGURATIONS:
        configurations.append(PATIENT_AXIS_CONFIGURATIONS[vendorName])
    for configuration in configurations:
        if all(directionCode in directionCodes for directionCode, _ in configuration):
            return configuration
    return None


# Direction code in the SequenceName DICOM field (for example, "in" in "fl3d1_v150in") to direction code used in the
# Siemens private tag (for example, "through" in "v150_through").
SIEMENS_SEQUENCE_NAME_DIRECTION_CODES = {"in": "through", "rl": "inplane_rl", "ap": "inplane_ap", "fh": "inplane_fh"}

# Velocity encoding and direction code at the end of SequenceName, for example "150" and "in" in "fl3d1_v150in"
_SIEMENS_SEQUENCE_NAME_PATTERN = r"_v(\d+(?:\.\d+)?)(in|rl|ap|fh)$"

# GE (0043,1030) Vas collapse flag: role of the image
_GE_VAS_COLLAPSE_FLAGS = {
    2: MAGNITUDE_DIRECTION_CODE,  # magnitude
    3: "patient_rl",  # left/right (4D flow) or slice (2D PC) velocity
    4: "patient_ap",  # anterior/posterior velocity
    5: "patient_fh",  # inferior/superior velocity
    7: COMPLEX_DIFFERENCE_DIRECTION_CODE,  # 5th series with nonnegative values (complex difference), auxiliary image
    # 8-11: same as 2-5, "oblique orientation" (not encountered yet, the convention is unverified)
    8: MAGNITUDE_DIRECTION_CODE,
    9: "patient_rl",
    10: "patient_ap",
    11: "patient_fh",
}


def _stringValue(value):
    """DICOM element value as stripped string (private tags may be stored as raw bytes, VR UN)."""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return str(value).strip()


def _floatValue(ds, tag, default=None):
    """Numeric element value as float (the first value of a multi-valued element), or default if the element is missing
    or not numeric."""
    if tag not in ds:
        return default
    try:
        value = ds[tag].value
        if not isinstance(value, (str, bytes)) and hasattr(value, "__len__"):
            value = value[0]
        return float(_stringValue(value) if isinstance(value, (str, bytes)) else value)
    except (TypeError, ValueError, IndexError):
        return default


def _floatList(ds, tag):
    """Multi-valued numeric element as list of floats (empty if missing)."""
    if tag not in ds:
        return []
    value = ds[tag].value
    try:
        if isinstance(value, (str, bytes)):
            return [float(v) for v in _stringValue(value).replace("\\", " ").split()]
        return [float(v) for v in value] if hasattr(value, "__iter__") else [float(value)]
    except (TypeError, ValueError):
        return []


def vendor(ds):
    """Vendor identifier from the Manufacturer tag: "siemens", "ge", "philips", or None if unknown."""
    manufacturer = _stringValue(ds.get("Manufacturer", "")).upper()
    for prefix, name in (("SIEMENS", "siemens"), ("GE", "ge"), ("PHILIPS", "philips")):
        if manufacturer.startswith(prefix):
            return name
    return None


def heartRateBpm(ds):
    """Heart rate (bpm) from the DICOM header: from NominalInterval (RR interval, ms), or from HeartRate; None if neither
    is available."""
    nominalIntervalMs = _floatValue(ds, "NominalInterval")
    if nominalIntervalMs and nominalIntervalMs > 0:
        return 60000.0 / nominalIntervalMs
    heartRate = _floatValue(ds, "HeartRate")
    if heartRate and heartRate > 0:
        return heartRate
    return None


def heartRateBpmFromFrameTimes(frameTimesMs):
    """Heart rate (bpm) estimated from the trigger times of the frames (ms): the RR interval is the frame interval times
    the number of frames. None if there are fewer than 2 frames."""
    times = [float(t) for t in frameTimesMs]
    if len(times) < 2 or times[-1] <= times[0]:
        return None
    rrMs = (times[-1] - times[0]) * len(times) / (len(times) - 1)
    return 60000.0 / rrMs


def classifyDataset(ds):
    """Identify a 4D flow magnitude or velocity component image from its DICOM header.

    Returns None if the image is not a 4D flow image of a supported vendor, otherwise a dictionary:
    - vendor: "siemens", "ge", or "philips"
    - role: "magnitude", "velocity", or "auxiliary" (other image of the acquisition, for example the GE complex
      difference image, see AUXILIARY_DIRECTION_CODES)
    - directionCode: "magnitude", the direction code of the encoded velocity component (see the module docstring), or
      the auxiliary image code
    - vencCmPerSec: velocity encoding (cm/s) of the component (None for other images)
    - maxValue: loaded voxel value that corresponds to the velocity encoding (None for other images)
    - groupKey: identifies the acquisition within the study (images of one 4D flow acquisition have the same key)
    """
    vendorName = vendor(ds)
    classifiers = {"siemens": _classifySiemens, "ge": _classifyGE, "philips": _classifyPhilips}
    if vendorName in classifiers:
        return classifiers[vendorName](ds)
    # Unknown or missing manufacturer (for example, after de-identification): try all vendors
    for classify in classifiers.values():
        result = classify(ds)
        if result:
            return result
    return None


def _result(vendorName, directionCode, vencCmPerSec=None, maxValue=None, groupKey=None):
    if directionCode == MAGNITUDE_DIRECTION_CODE:
        role = "magnitude"
    elif directionCode in AUXILIARY_DIRECTION_CODES:
        role = "auxiliary"
    else:
        role = "velocity"
    return {
        "vendor": vendorName,
        "role": role,
        "directionCode": directionCode,
        "vencCmPerSec": vencCmPerSec,
        "maxValue": maxValue,
        "groupKey": groupKey,
    }


def _acquisitionNumberKey(ds):
    return str(ds.get("AcquisitionNumber", 0) or 0)


def _classifySiemens(ds):
    """Siemens CS 4D flow: velocity component images have the venc and direction code in a private tag
    ((0051,1014) on Avanto, (0021,1129) on Avanto Fit, for example 'v150_through') or at the end of SequenceName
    (for example 'fl3d1_v150in'); magnitude images have SequenceName 'fl3d1r2' or 'fl3d1r3'."""
    groupKey = _acquisitionNumberKey(ds)
    for tag in [(0x0051, 0x1014), (0x0021, 0x1129)]:
        if tag in ds:
            # The tag contains speed and direction, for example: 'v150_through', 'v150_inplane_ap', 'v150_inplane_fh'
            speedAndDirectionCode = _stringValue(ds[tag].value)
            try:
                vencInput, directionCode = speedAndDirectionCode.split("_", 1)
                vencCmPerSec = float(vencInput[1:])
            except ValueError:
                logging.debug(f"Siemens speed and direction code is not recognized: {speedAndDirectionCode}")
                return None
            return _result("siemens", directionCode.strip(), vencCmPerSec, SIEMENS_PHASE_MAX_VALUE, groupKey)
    sequenceName = _stringValue(ds.get("SequenceName", ""))
    match = re.search(_SIEMENS_SEQUENCE_NAME_PATTERN, sequenceName)
    if match:
        # Examples: 'fl3d1_v150in', 'fl3d1_v150ap', 'fl3d1_v150fh', 'WIP_f_v150fh'
        # In free-running flow sequences, all the directions may be under the same series
        directionCode = SIEMENS_SEQUENCE_NAME_DIRECTION_CODES[match.group(2)]
        return _result("siemens", directionCode, float(match.group(1)), SIEMENS_PHASE_MAX_VALUE, groupKey)
    if "fl3d1r2" in sequenceName or "fl3d1r3" in sequenceName:
        # Examples: '*fl3d1r2' or 'fl3d1r2' or 'WIP_fl3d1r2' or 'WIP_fl3d1r3'
        return _result("siemens", MAGNITUDE_DIRECTION_CODE, groupKey=groupKey)
    return None


def _classifyGE(ds):
    """GE 4D flow (mm4dflow / 4DFLOW sequences): the role of each series is in the private tag (0043,1030)
    Vas collapse flag (2: magnitude, 3/4/5: L/R, A/P, S/I velocity, 7: complex difference image), the velocity encoding
    (mm/s) in (0019,10CC),
    and the stored value scaling in (0019,10E2) Velocity Encode Scale (venc/pi): pixel = phase * scale, so the pixel
    values are velocity in mm/s. The series of one acquisition share the SeriesTime."""
    flag = _floatValue(ds, (0x0043, 0x1030))
    if flag is None:
        return None
    flag = int(flag)
    directionCode = _GE_VAS_COLLAPSE_FLAGS.get(flag)
    if directionCode is None:
        logging.debug(f"GE image with Vas collapse flag {flag} is not a 4D flow magnitude or velocity image - skip")
        return None
    if flag >= 8:
        logging.warning(f"GE image with Vas collapse flag {flag} (oblique velocity encoding): the direction convention"
                        " has not been verified on such images")
    seriesTime = _stringValue(ds.get("SeriesTime", "")) or _stringValue(ds.get("AcquisitionTime", ""))
    groupKey = f"{seriesTime}/{_acquisitionNumberKey(ds)}"
    if directionCode == MAGNITUDE_DIRECTION_CODE or directionCode in AUXILIARY_DIRECTION_CODES:
        return _result("ge", directionCode, groupKey=groupKey)
    vencMmPerSec = _floatValue(ds, (0x0019, 0x10CC))
    if not vencMmPerSec or vencMmPerSec <= 0:
        logging.warning("GE velocity image has no velocity encoding in (0019,10CC) - skip")
        return None
    velocityEncodeScale = _floatValue(ds, (0x0019, 0x10E2))
    if velocityEncodeScale and velocityEncodeScale > 0:
        # pixel = phase (rad) * scale, and velocity = phase / pi * venc, so the pixel value at venc is scale * pi
        maxValue = velocityEncodeScale * math.pi
        if abs(maxValue - vencMmPerSec) > 0.01 * vencMmPerSec:
            logging.warning(f"GE Velocity Encode Scale (0019,10E2) {velocityEncodeScale:g} does not match"
                            f" venc/pi ({vencMmPerSec / math.pi:g}); using the scale")
    else:
        maxValue = vencMmPerSec  # pixel values are velocity in mm/s
    return _result("ge", directionCode, vencMmPerSec / 10.0, maxValue, groupKey)


def _philipsVelocityDirection(ds, pcVelocity):
    """Encoded patient axis (0, 1, 2 for L/R, A/P, F/H) of a Philips velocity image: from (0018,9090) Velocity Encoding
    Direction (in the (2005,140F) sequence), from the nonzero element of (2001,101A) PC Velocity, or from the series
    description (RL, AP, FH). None if not determined or not along a patient axis."""
    axis = None
    if (0x2005, 0x140F) in ds:
        try:
            item = ds[(0x2005, 0x140F)].value[0]
            direction = [abs(float(v)) for v in item.VelocityEncodingDirection] if "VelocityEncodingDirection" in item else []
        except (IndexError, TypeError, ValueError, AttributeError):
            direction = []
        if len(direction) == 3 and max(direction) > 0:
            axis = direction.index(max(direction))
            if sum(1 for v in direction if v > 0.01 * max(direction)) != 1:
                logging.warning(f"Philips velocity encoding direction {direction} is not along a patient axis - skip")
                return None
    if axis is None:
        nonzero = [i for i, v in enumerate(pcVelocity) if abs(v) > 0]
        if len(nonzero) == 1:
            axis = nonzero[0]
    if axis is None:
        seriesDescription = _stringValue(ds.get("SeriesDescription", "")).upper()
        axis = {"RL": 0, "LR": 0, "AP": 1, "PA": 1, "FH": 2, "HF": 2}.get(seriesDescription)
    return axis


def _classifyPhilips(ds):
    """Philips 4D flow (classic DICOM export): velocity images have ImageType 'VELOCITY MAP' (private (2005,1011) 'P'),
    the velocity encoding (cm/s) in (2001,101A) PC Velocity (one nonzero element, the encoded patient axis), the
    encoding direction in (0018,9090) in the (2005,140F) sequence, and RescaleSlope/RescaleIntercept that convert the
    stored values to cm/s. The magnitude image has (2005,1011) 'M' and (2001,1016) Number of PC directions 3."""
    pcVelocity = _floatList(ds, (0x2001, 0x101A))
    if not pcVelocity or max(abs(v) for v in pcVelocity) <= 0:
        return None
    imageType = [_stringValue(v).upper() for v in ds.get("ImageType", [])]
    componentType = _stringValue(ds[(0x2005, 0x1011)].value).upper() if (0x2005, 0x1011) in ds else ""
    if not componentType and len(imageType) > 3:
        componentType = imageType[3]
    groupKey = _acquisitionNumberKey(ds)
    if "VELOCITY MAP" in imageType or componentType == "P":
        axis = _philipsVelocityDirection(ds, pcVelocity)
        if axis is None:
            logging.warning("Philips velocity image: the encoding direction cannot be determined - skip")
            return None
        vencCmPerSec = abs(pcVelocity[axis]) if axis < len(pcVelocity) and pcVelocity[axis] else max(abs(v) for v in pcVelocity)
        if "RescaleSlope" not in ds or "RescaleIntercept" not in ds:
            logging.warning("Philips velocity image has no RescaleSlope/RescaleIntercept - skip")
            return None
        rescaleType = _stringValue(ds.get("RescaleType", "")).lower()
        if rescaleType and rescaleType not in ("cm/s", "cm/sec"):
            logging.warning(f"Philips velocity image rescale type is '{rescaleType}', expected cm/s - skip")
            return None
        # The DICOM reader applies the rescale, so the loaded voxel values are in cm/s
        return _result("philips", PATIENT_DIRECTION_CODES[axis], vencCmPerSec, vencCmPerSec, groupKey)
    if componentType == "M" or "M" in imageType[2:]:
        numberOfDirections = _floatValue(ds, (0x2001, 0x1016))
        if numberOfDirections is not None and int(numberOfDirections) < 3:
            logging.debug("Philips magnitude image with fewer than 3 velocity encoding directions - skip")
            return None
        return _result("philips", MAGNITUDE_DIRECTION_CODE, groupKey=groupKey)
    return None
