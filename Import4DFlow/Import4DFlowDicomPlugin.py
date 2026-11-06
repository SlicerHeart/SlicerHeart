"""DICOM plugin that loads 4D flow MRI studies (Siemens, GE, Philips) directly as input flow field.

The magnitude series and the 3 velocity component series of an acquisition (identified from their DICOM headers,
see Import4DFlowLib.FlowDicom) are loaded into a magnitude volume sequence and an input flow field (raw velocity,
RAS components in mm/s, see Import4DFlowLogic.createInputFlowFieldFromArrays), the same result as loading the series
as volume sequences with MultiVolumeImporterPlugin and converting them with Import 4D Flow. It is much faster: the
examine step classifies each series from its first file and uses bulk tag queries, and the load step reads the pixel
data directly from the files (uncompressed files; others are read with pydicom).

The plugin offers one loadable per series (so that the series are not loaded as volume sequences too), with a
confidence above MultiVolumeImporterPlugin's, so that 4D flow series are loaded as flow field by default. Loading any
of the loadables loads the whole acquisition. All series of the acquisition must be examined together (selected in
the DICOM browser), otherwise no loadable is offered and the series can be loaded as volume sequences.
"""

import json
import logging
import struct

import numpy as np
import slicer
from DICOMLib import DICOMPlugin, DICOMLoadable
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleTest

from Import4DFlowLib import FlowDicom


def fileValues(filePaths, tag):
    """Values of a DICOM tag of multiple files from the DICOM database (empty string if not found).
    Uses the batch query of DICOMUtils.fileValues (Slicer 5.13 and later), or one query per file."""
    from DICOMLib import DICOMUtils
    if hasattr(DICOMUtils, "fileValues"):
        return DICOMUtils.fileValues(filePaths, tag)
    return [slicer.dicomDatabase.fileValue(filePath, tag) for filePath in filePaths]


class Import4DFlowDicomPluginClass(DICOMPlugin):
    """4D flow MRI interpretation: magnitude + 3 velocity component series -> magnitude sequence + input flow field."""

    # MultiVolumeImporterPlugin offers these series as volume sequences with confidence 1.0, and the DICOM browser selects
    # all loadables of a series that tie for the highest confidence (DICOMUtils.selectHighestConfidenceLoadables), so a
    # value above 1.0 is needed for 4D flow series to be loaded as flow field only, by default (as DICOMImageSequencePlugin
    # in Slicer core does with 1.05 for rotational cine MRI).
    CONFIDENCE = 1.1

    # Uncompressed transfer syntaxes: the pixel data is read directly from the file
    IMPLICIT_VR_LITTLE_ENDIAN = "1.2.840.10008.1.2"
    EXPLICIT_VR_LITTLE_ENDIAN = "1.2.840.10008.1.2.1"

    def __init__(self):
        super().__init__()
        self.loadType = "4D flow"
        self.tags["triggerTime"] = "0018,1060"
        self.tags["position"] = "0020,0032"
        self.tags["instanceUID"] = "0008,0018"
        self.tags["seriesDescription"] = "0008,103E"
        self.tags["seriesNumber"] = "0020,0011"
        self.tags["patientName"] = "0010,0010"
        self.tags["studyDate"] = "0008,0020"

    # ---- examine -----------------------------------------------------------------------------------------------------

    def examineForImport(self, fileLists):
        """One loadable per series of each complete 4D flow acquisition (magnitude and 3 velocity components) among
        the file lists (each list is a series)."""
        self.detailedLogging = self.isDetailedLogging()
        acquisitions = {}  # (study, group key) -> list of images
        for files in fileLists:
            if not files:
                continue
            try:
                image = self._examineSeries(files)
            except Exception as e:
                logging.debug(f"Import4DFlowDicomPlugin: {files[0]} is not examined as 4D flow series: {e}")
                continue
            if image is None:
                continue
            acquisitions.setdefault((image["studyInstanceUID"], image["groupKey"]), []).append(image)
        loadables = []
        for images in acquisitions.values():
            acquisition = self._acquisition(images)
            if acquisition is None:
                continue
            loadables += self._loadables(acquisition)
        return loadables

    def _examineSeries(self, files):
        """Classify a series from its first file (vendor, role, direction, velocity encoding; the velocity tags are the
        same in all files of a series) and group its files into frames (trigger times) and slices (positions along the
        slice normal) with bulk tag queries. Returns None if the series is not a 4D flow magnitude or velocity series."""
        import pydicom

        ds = pydicom.dcmread(files[0], stop_before_pixels=True)
        image = FlowDicom.classifyDataset(ds)
        if image is None:
            return None
        if "ImageOrientationPatient" not in ds or "ImagePositionPatient" not in ds or "PixelSpacing" not in ds:
            logging.debug(f"Import4DFlowDicomPlugin: no image geometry in {files[0]}")
            return None
        if int(ds.get("SamplesPerPixel", 1)) != 1 or int(ds.get("NumberOfFrames", 1)) != 1:
            logging.debug(f"Import4DFlowDicomPlugin: only single-frame grayscale images are supported, skipping {files[0]}")
            return None

        image["files"] = files
        image["heartRateBpm"] = FlowDicom.heartRateBpm(ds)
        image["studyInstanceUID"] = str(ds.StudyInstanceUID).strip()
        image["orientation"] = np.array([float(v) for v in ds.ImageOrientationPatient])
        image["pixelSpacing"] = [float(v) for v in ds.PixelSpacing]
        image["shape"] = (int(ds.Rows), int(ds.Columns))
        image["bitsAllocated"] = int(ds.BitsAllocated)
        image["pixelRepresentation"] = int(ds.PixelRepresentation)
        image["transferSyntax"] = str(ds.file_meta.TransferSyntaxUID) if hasattr(ds, "file_meta") else ""
        # The DICOM reader of Slicer applies the rescale (the velocity scaling of FlowDicom refers to rescaled values)
        image["rescaleSlope"] = float(ds.get("RescaleSlope", 1.0) or 1.0)
        image["rescaleIntercept"] = float(ds.get("RescaleIntercept", 0.0) or 0.0)
        image["patientName"] = ds.PatientName.family_comma_given() if "PatientName" in ds and ds.PatientName else "Unknown"
        image["studyDate"] = str(ds.get("StudyDate", ""))
        image["acquisitionNumber"] = int(ds.get("AcquisitionNumber", 0) or 0)
        image["seriesName"] = self._seriesName(files[0])
        # Non-identifying acquisition metadata (stored in the input flow field, exported with test cases)
        manufacturer = str(ds.get("Manufacturer", "")).strip()
        image["metadata"] = {
            "vendor": manufacturer.split()[0].lower() if manufacturer else "unknown",
            "scanner": " ".join(str(ds.get(tag, "")).strip() for tag in ("Manufacturer", "ManufacturerModelName")).strip(),
            "software_version": str(ds.get("SoftwareVersions", "")).strip(),
            "field_strength_t": float(ds.MagneticFieldStrength) if "MagneticFieldStrength" in ds else None,
        }

        # Frames (trigger times) and slices (sorted along the slice normal)
        normal = np.cross(image["orientation"][:3], image["orientation"][3:])
        triggerTimes = fileValues(files, self.tags["triggerTime"])
        positions = fileValues(files, self.tags["position"])
        frames = {}
        for fileName, triggerTime, position in zip(files, triggerTimes, positions):
            if not triggerTime or not position:
                logging.debug(f"Import4DFlowDicomPlugin: missing trigger time or position in {fileName}")
                return None
            positionLps = np.array([float(v) for v in position.split("\\")])
            frames.setdefault(float(triggerTime), []).append((float(positionLps @ normal), positionLps, fileName))
        if len(frames) < 2:
            logging.debug(f"Import4DFlowDicomPlugin: {image['seriesName']} has a single frame")
            return None
        frameTimes = sorted(frames)
        frameFiles, slicePositions = [], None
        for frameTime in frameTimes:
            slices = sorted(frames[frameTime], key=lambda s: s[0])
            distances = np.array([s[0] for s in slices])
            if len(slices) > 1 and np.min(np.diff(distances)) <= 1e-3 * max(1.0, np.ptp(distances)):
                # Several files at the same position (for example, several velocity components in one series)
                logging.debug(f"Import4DFlowDicomPlugin: {image['seriesName']} has several images at the same position and time")
                return None
            if slicePositions is None:
                slicePositions = np.array([s[1] for s in slices])
            elif len(slices) != len(slicePositions) or np.abs(np.array([s[1] for s in slices]) - slicePositions).max() > 0.01:
                logging.debug(f"Import4DFlowDicomPlugin: {image['seriesName']} has inconsistent slice positions between frames")
                return None
            frameFiles.append([s[2] for s in slices])
        image["frameTimes"] = frameTimes
        image["frameFiles"] = frameFiles
        image["slicePositions"] = slicePositions
        image["normal"] = normal
        return image

    def _seriesName(self, fileName):
        seriesDescription = slicer.dicomDatabase.fileValue(fileName, self.tags["seriesDescription"]) or "Unnamed Series"
        seriesNumber = slicer.dicomDatabase.fileValue(fileName, self.tags["seriesNumber"])
        return f"{seriesNumber}: {seriesDescription}" if seriesNumber else seriesDescription

    @staticmethod
    def _acquisition(images):
        """Complete acquisition (magnitude and the 3 velocity components in RAS order, with the sign convention) from the
        images of one study/group, or None."""
        magnitudes = [image for image in images if image["role"] == "magnitude"]
        velocities = [image for image in images if image["role"] == "velocity"]
        auxiliaries = [image for image in images if image["role"] == "auxiliary"]
        if len(magnitudes) != 1 or len(velocities) < 3:
            return None
        magnitude = magnitudes[0]
        configuration = FlowDicom.componentConfiguration(magnitude["vendor"], [image["directionCode"] for image in velocities])
        if configuration is None:
            logging.debug("Import4DFlowDicomPlugin: no velocity component configuration found for direction codes "
                          f"{[image['directionCode'] for image in velocities]}")
            return None
        components = [next(image for image in velocities if image["directionCode"] == directionCode) for directionCode, _ in configuration]
        invertToRasDirection = [invert for _, invert in configuration]
        # Same voxel grid and frames (auxiliary images that differ are left to the other plugins)
        def sameGrid(image):
            if any(image[key] != magnitude[key] for key in ("shape", "frameTimes")):
                logging.debug(f"Import4DFlowDicomPlugin: {image['seriesName']} and {magnitude['seriesName']} differ in frames or image size")
                return False
            if len(image["slicePositions"]) != len(magnitude["slicePositions"]) or \
                    np.abs(image["slicePositions"] - magnitude["slicePositions"]).max() > 0.01 or \
                    np.abs(image["orientation"] - magnitude["orientation"]).max() > 1e-4:
                logging.debug(f"Import4DFlowDicomPlugin: {image['seriesName']} and {magnitude['seriesName']} differ in geometry")
                return False
            return True
        if not all(sameGrid(image) for image in components):
            return None
        auxiliaries = [image for image in auxiliaries if sameGrid(image)]
        return {"magnitude": magnitude, "components": components, "invertToRasDirection": invertToRasDirection, "auxiliaries": auxiliaries,
                "name": f"{magnitude['patientName']} ({magnitude['studyDate']})"
                        + (f" / {magnitude['acquisitionNumber']}" if magnitude["acquisitionNumber"] > 1 else "")}

    def _loadables(self, acquisition):
        """One loadable per series of the acquisition (so that no other interpretation of the series is selected by
        default); loading any of them loads the whole acquisition."""
        vendorLabel = {"siemens": "Siemens", "ge": "GE", "philips": "Philips"}.get(acquisition["magnitude"]["vendor"], "")
        componentLabels = {"patient_rl": "R/L", "patient_ap": "A/P", "patient_fh": "F/H", "through": "through-plane",
                           "inplane_rl": "in-plane R/L", "inplane_ap": "in-plane A/P", "inplane_fh": "in-plane F/H"}
        auxiliaryLabels = {FlowDicom.COMPLEX_DIFFERENCE_DIRECTION_CODE: "complex difference image"}
        loadables = []
        for image in [acquisition["magnitude"]] + acquisition["components"] + acquisition["auxiliaries"]:
            loadable = DICOMLoadable()
            loadable.files = image["files"]
            if image["role"] == "magnitude":
                role = "magnitude"
            elif image["role"] == "velocity":
                role = f"velocity {componentLabels.get(image['directionCode'], image['directionCode'])}"
            else:
                role = auxiliaryLabels.get(image["directionCode"], image["directionCode"])
            loadable.name = f"{image['seriesName']} - 4D flow {role}"
            loadable.tooltip = (f"4D flow MRI ({vendorLabel}, {len(image['frameTimes'])} frames) loaded as input flow field with the magnitude"
                                " image sequence (and the other images of the acquisition in the same sequence browser). Loading any of"
                                " the series loads the whole acquisition.")
            loadable.selected = True
            loadable.confidence = self.CONFIDENCE
            loadable.flowAcquisition = acquisition
            loadable.flowImage = image
            loadables.append(loadable)
        acquisition["loadables"] = loadables
        return loadables

    # ---- load --------------------------------------------------------------------------------------------------------

    def load(self, loadable):
        """Load the 4D flow acquisition of the loadable (once: the other loadables of the acquisition are loaded by the
        same call). Returns the magnitude volume node (proxy node of the magnitude volume sequence)."""
        acquisition = loadable.flowAcquisition
        loadedNode = slicer.mrmlScene.GetNodeByID(acquisition.get("magnitudeVolumeNodeID", "")) if acquisition.get("magnitudeVolumeNodeID") else None
        if loadedNode is not None:
            # Already loaded with another loadable of this acquisition
            return loadedNode
        import Import4DFlow
        logic = Import4DFlow.Import4DFlowLogic()
        magnitude = acquisition["magnitude"]
        components = acquisition["components"]
        numberOfFrames = len(magnitude["frameTimes"])
        voxelToWorld = self._voxelToWorld(magnitude)
        logging.info(f"Loading 4D flow acquisition {acquisition['name']}: {numberOfFrames} frames, {len(magnitude['slicePositions'])} slices")

        # Magnitude volume sequence (browsed by frame time, as volume sequences imported from DICOM) with its sequence
        # browser, and the auxiliary images of the acquisition (for example, the GE complex difference image) as
        # further sequences of the same browser
        frameTimes = magnitude["frameTimes"]
        browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", magnitude["seriesName"] + " browser")
        sequenceNodes = {}
        for image in [magnitude] + acquisition["auxiliaries"]:
            sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", image["seriesName"])
            sequenceNode.SetIndexName("time")
            sequenceNode.SetIndexUnit("ms")
            sequenceNode.SetIndexType(slicer.vtkMRMLSequenceNode.NumericIndex)
            valueRange = 0.0
            for frameIndex in range(numberOfFrames):
                frame = self._readFrame(image, frameIndex)
                valueRange = max(valueRange, float(frame.max()))
                sequenceNode.SetDataNodeAtValue(logic._volumeNodeFromArray(frame, voxelToWorld), f"{frameTimes[frameIndex]:g}")
            sequenceNode.SetAttribute("MultiVolume.FrameIdentifyingDICOMTagName", "TriggerTime")
            sequenceNode.SetAttribute("MultiVolume.FrameIdentifyingDICOMTagUnits", "ms")
            sequenceNode.SetAttribute("MultiVolume.FrameLabels", ",".join(f"{t:g}" for t in frameTimes))
            sequenceNode.SetAttribute("MultiVolume.NumberOfFrames", str(numberOfFrames))
            sequenceNode.SetAttribute("SlicerHeart.vendor", image["vendor"])
            sequenceNode.SetAttribute("SlicerHeart.directionCode", image["directionCode"])
            if image is magnitude:
                # Siemens magnitude images use a fixed range (see Import4DFlowLogic.magnitudeRange); others are scaled arbitrarily
                magnitudeRange = logic.magnitudeVolumeRange if image["vendor"] == "siemens" else valueRange
                sequenceNode.SetAttribute("SlicerHeart.magnitudeRange", f"{magnitudeRange:g}")
                heartRateBpm = image["heartRateBpm"]
                if not heartRateBpm:
                    heartRateBpm = FlowDicom.heartRateBpmFromFrameTimes(frameTimes)
                    if heartRateBpm:
                        logging.info(f"{image['seriesName']}: heart rate is not in the DICOM header, estimated from the trigger times: {heartRateBpm:.1f} bpm")
                if heartRateBpm:
                    sequenceNode.SetAttribute("SlicerHeart.heartRateBpm", str(heartRateBpm))
                browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())
            else:
                browserNode.AddSynchronizedSequenceNodeID(sequenceNode.GetID())
            # With save changes allowed, the proxy node is updated by shallow copy, which is much faster for large images
            # (as in the volume sequence import of the DICOM module)
            browserNode.SetSaveChanges(sequenceNode, True)
            sequenceNodes[id(image)] = sequenceNode
        slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browserNode)
        for image in [magnitude] + acquisition["auxiliaries"]:
            proxyNode = browserNode.GetProxyNode(sequenceNodes[id(image)])
            proxyNode.CreateDefaultDisplayNodes()
            instanceUIDs = fileValues(image["files"], self.tags["instanceUID"])
            proxyNode.SetAttribute("DICOM.instanceUIDs", " ".join(uid for uid in instanceUIDs if uid))
            imageLoadable = next((l for l in acquisition.get("loadables", []) if l.flowImage is image), loadable)
            self.addSeriesInSubjectHierarchy(imageLoadable, proxyNode)
        magnitudeVolumeNode = browserNode.GetProxyNode(sequenceNodes[id(magnitude)])

        # Input flow field: raw velocity frames (RAS components, mm/s) are read on demand, straight into the flow field
        signs = np.array([-1.0 if invert else 1.0 for invert in acquisition["invertToRasDirection"]])
        vencsMmPerSec = [image["vencCmPerSec"] * 10.0 for image in components]
        maxValues = [image["maxValue"] for image in components]
        scales = [np.float32(vencsMmPerSec[axis] / maxValues[axis] * signs[axis]) for axis in range(3)]
        plugin = self

        class RawVelocityFrames:
            def __getitem__(self, frameIndex):
                frame = None
                for axis in range(3):
                    component = plugin._readFrame(components[axis], frameIndex)
                    if frame is None:
                        frame = np.empty(component.shape + (3,), np.float32)
                    np.multiply(component, scales[axis], out=frame[..., axis], dtype=np.float32)
                return frame

        inputFlowFieldNode = logic.createInputFlowFieldFromArrays(
            RawVelocityFrames(), magnitudeVolumeNode, vencsMmPerSec, np.diag(signs),
            directionCodes=[image["directionCode"] for image in components], componentMaxValues=maxValues, saveChanges=True)
        logic._getSequenceFromProxyNode(inputFlowFieldNode).SetAttribute(logic.ACQUISITION_METADATA_ATTRIBUTE, json.dumps(magnitude["metadata"]))
        for axis, image in enumerate(components):
            inputFlowFieldNode.SetAttribute(f"DICOM.componentInstanceUIDs{axis}",
                                            " ".join(uid for uid in fileValues(image["files"], self.tags["instanceUID"]) if uid))
        # Show the acquisition as the volume sequence import of the DICOM module does: the magnitude images in the slice
        # views (the input flow field is not shown as a volume), the velocity as acquired as glyphs (if the vector field
        # display node is available in this Slicer version), and the sequence browser of the acquisition in the toolbar
        if hasattr(slicer, "vtkMRMLVectorFieldDisplayNode"):
            logic.setFlowFieldVisualizationToDefault(inputFlowFieldNode)
        appLogic = slicer.app.applicationLogic()
        selectionNode = appLogic.GetSelectionNode()
        selectionNode.SetReferenceActiveVolumeID(magnitudeVolumeNode.GetID())
        appLogic.PropagateVolumeSelection()
        sequencesModule = slicer.modules.sequences
        if sequencesModule.autoShowToolBar:
            sequencesModule.setToolBarActiveBrowserNode(browserNode)
            sequencesModule.setToolBarVisible(True)

        acquisition["magnitudeVolumeNodeID"] = magnitudeVolumeNode.GetID()
        acquisition["inputFlowFieldNodeID"] = inputFlowFieldNode.GetID()
        return magnitudeVolumeNode

    @staticmethod
    def _voxelToWorld(image):
        """IJK to RAS matrix (4x4) from the orientation, pixel spacing and sorted slice positions of the image."""
        positions = image["slicePositions"]
        distances = positions @ image["normal"]
        sliceSpacing = float(np.mean(np.diff(distances))) if len(positions) > 1 else 1.0
        if len(positions) > 2:
            nonuniformity = float(np.ptp(np.diff(distances)))
            if nonuniformity > 0.01 * abs(sliceSpacing):
                logging.warning(f"{image['seriesName']}: non-uniform slice spacing (max. deviation {nonuniformity:.3f} mm); the mean spacing is used")
        ijkToLps = np.eye(4)
        ijkToLps[:3, 0] = image["orientation"][:3] * image["pixelSpacing"][1]  # column index (I): row direction cosines, column spacing
        ijkToLps[:3, 1] = image["orientation"][3:] * image["pixelSpacing"][0]  # row index (J)
        ijkToLps[:3, 2] = image["normal"] * sliceSpacing
        ijkToLps[:3, 3] = positions[0]
        return np.diag([-1.0, -1.0, 1.0, 1.0]) @ ijkToLps

    def _readFrame(self, image, frameIndex):
        """Voxel array (k, j, i) of a frame: the slices are read directly from uncompressed files (pixel data is the last
        element of the file and its element header is verified), or with pydicom otherwise. RescaleSlope/RescaleIntercept
        are applied (as the DICOM reader of Slicer does); the array is float32 then, otherwise the stored integer type."""
        rows, columns = image["shape"]
        files = image["frameFiles"][frameIndex]
        pixelBytes = rows * columns * image["bitsAllocated"] // 8
        dtype = {(16, 1): np.int16, (16, 0): np.uint16, (8, 0): np.uint8, (8, 1): np.int8,
                 (32, 1): np.int32, (32, 0): np.uint32}.get((image["bitsAllocated"], image["pixelRepresentation"]))
        rescale = image["rescaleSlope"] != 1.0 or image["rescaleIntercept"] != 0.0
        frame = np.empty((len(files), rows, columns), np.float32 if rescale else dtype)
        expectedHeader = None
        if dtype is not None and image["transferSyntax"] in (self.IMPLICIT_VR_LITTLE_ENDIAN, self.EXPLICIT_VR_LITTLE_ENDIAN):
            explicitVR = image["transferSyntax"] == self.EXPLICIT_VR_LITTLE_ENDIAN
            # (7FE0,0010) element header: tag, VR "OW" with 2 reserved bytes (explicit VR only), 32-bit length
            expectedHeader = b"\xe0\x7f\x10\x00" + (b"OW\x00\x00" if explicitVR else b"") + struct.pack("<I", pixelBytes)
        for sliceIndex, fileName in enumerate(files):
            pixels = None
            if expectedHeader is not None:
                with open(fileName, "rb") as f:
                    f.seek(0, 2)
                    fileSize = f.tell()
                    if fileSize >= pixelBytes + len(expectedHeader):
                        f.seek(fileSize - pixelBytes - len(expectedHeader))
                        if f.read(len(expectedHeader)) == expectedHeader:
                            pixels = np.frombuffer(f.read(pixelBytes), dtype=dtype).reshape(rows, columns)
            if pixels is None:
                import pydicom
                pixels = pydicom.dcmread(fileName).pixel_array
            if rescale:
                np.multiply(pixels, np.float32(image["rescaleSlope"]), out=frame[sliceIndex], dtype=np.float32)
                frame[sliceIndex] += np.float32(image["rescaleIntercept"])
            else:
                frame[sliceIndex] = pixels
        return frame


#
# Import4DFlowDicomPlugin
#

class Import4DFlowDicomPlugin:
    """This class is the 'hook' for slicer to detect and recognize the plugin as a loadable scripted module."""

    def __init__(self, parent):
        parent.title = "4D Flow DICOM Import Plugin"
        parent.categories = ["Developer Tools.DICOM Plugins"]
        parent.dependencies = ["Import4DFlow"]
        parent.contributors = ["Andras Lasso (PerkLab, Queen's University)"]
        parent.helpText = """
Plugin to the DICOM module to load 4D flow MRI studies (Siemens, GE, Philips) directly as input flow field of the
Import 4D Flow module. No module interface here, only in the DICOM module.
"""
        parent.acknowledgementText = """
This file was originally developed by Andras Lasso, PerkLab, Queen's University and was partially funded by
CHOP Frontier Program and SlicerHeart.
"""

        # Don't show this module - it only appears in the DICOM module
        parent.hidden = True

        # Add this extension to the DICOM module's list for discovery when the module is created.
        # Since this module may be discovered before DICOM itself, create the list if it doesn't already exist.
        try:
            slicer.modules.dicomPlugins
        except AttributeError:
            slicer.modules.dicomPlugins = {}
        slicer.modules.dicomPlugins["Import4DFlowDicomPlugin"] = Import4DFlowDicomPluginClass


#
# Import4DFlowDicomPluginTest
#

class Import4DFlowDicomPluginTest(ScriptedLoadableModuleTest):
    """Unit tests of the identification of 4D flow DICOM images (Import4DFlowLib.FlowDicom)."""

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_ClassifyDicomDatasets()
        self.setUp()
        self.test_ComponentConfiguration()

    def test_ClassifyDicomDatasets(self):
        """4D flow magnitude and velocity component images of Siemens, GE, and Philips are identified from their DICOM
        headers (FlowDicom.classifyDataset): role, direction code, velocity encoding, and loaded value scaling."""
        import math
        from pydicom.dataset import Dataset
        from pydicom.sequence import Sequence

        def siemens(**tags):
            ds = Dataset()
            ds.Manufacturer = "SIEMENS"
            ds.AcquisitionNumber = 1
            for key, value in tags.items():
                setattr(ds, key, value)
            return ds

        def ge(flag, venc=2500, scale=795.775):
            ds = Dataset()
            ds.Manufacturer = "GE MEDICAL SYSTEMS"
            ds.SeriesTime = "120313"
            ds.AcquisitionNumber = 1
            ds.add_new((0x0043, 0x0010), "LO", "GEMS_PARM_01")
            ds.add_new((0x0043, 0x1030), "SS", flag)
            ds.add_new((0x0019, 0x0010), "LO", "GEMS_ACQU_01")
            if venc is not None:
                ds.add_new((0x0019, 0x10CC), "SS", venc)
            if scale is not None:
                ds.add_new((0x0019, 0x10E2), "DS", f"{scale:f}")
            return ds

        def philips(componentType, pcVelocity, direction=None, numberOfDirections=None, rescale=True, rescaleType="cm/s"):
            ds = Dataset()
            ds.Manufacturer = "Philips"
            ds.AcquisitionNumber = 37
            ds.ImageType = ["ORIGINAL", "PRIMARY", "VELOCITY MAP", "P", "PCA"] if componentType == "P" else ["ORIGINAL", "PRIMARY", "M_FFE", "M", "FFE"]
            ds.add_new((0x2001, 0x0010), "LO", "Philips Imaging DD 001")
            ds.add_new((0x2001, 0x101A), "FL", pcVelocity)
            if numberOfDirections is not None:
                ds.add_new((0x2001, 0x1016), "SS", numberOfDirections)
            ds.add_new((0x2005, 0x0010), "LO", "Philips MR Imaging DD 001")
            ds.add_new((0x2005, 0x1011), "CS", componentType)
            if direction is not None:
                item = Dataset()
                item.PhaseContrast = "YES"
                item.VelocityEncodingDirection = direction
                ds.add_new((0x2005, 0x140F), "SQ", Sequence([item]))
            if rescale:
                ds.RescaleSlope = "0.09768009768009"
                ds.RescaleIntercept = "-200"
                ds.RescaleType = rescaleType
            return ds

        # Siemens (regression)
        image = FlowDicom.classifyDataset(siemens(SequenceName="fl3d1r2"))
        self.assertEqual((image["vendor"], image["role"], image["directionCode"]), ("siemens", "magnitude", "magnitude"))
        image = FlowDicom.classifyDataset(siemens(SequenceName="fl3d1_v150in"))
        self.assertEqual((image["directionCode"], image["vencCmPerSec"], image["maxValue"], image["groupKey"]), ("through", 150.0, 4096, "1"))
        ds = siemens(SequenceName="fl3d1")
        ds.add_new((0x0021, 0x1129), "UN", b"v120_inplane_ap ")
        image = FlowDicom.classifyDataset(ds)
        self.assertEqual((image["directionCode"], image["vencCmPerSec"]), ("inplane_ap", 120.0))
        self.assertIsNone(FlowDicom.classifyDataset(siemens(SequenceName="tfi2d1")))

        # GE
        image = FlowDicom.classifyDataset(ge(2))
        self.assertEqual((image["vendor"], image["role"], image["directionCode"], image["groupKey"]), ("ge", "magnitude", "magnitude", "120313/1"))
        for flag, directionCode in ((3, "patient_rl"), (4, "patient_ap"), (5, "patient_fh")):
            image = FlowDicom.classifyDataset(ge(flag))
            self.assertEqual((image["role"], image["directionCode"], image["vencCmPerSec"]), ("velocity", directionCode, 250.0))
            self.assertAlmostEqual(image["maxValue"], 795.775 * math.pi, places=3)
        image = FlowDicom.classifyDataset(ge(7))  # complex difference: auxiliary image of the acquisition
        self.assertEqual((image["role"], image["directionCode"], image["vencCmPerSec"]), ("auxiliary", FlowDicom.COMPLEX_DIFFERENCE_DIRECTION_CODE, None))
        self.assertEqual(FlowDicom.classifyDataset(ge(3, scale=None))["maxValue"], 2500.0)  # pixel values in mm/s
        self.assertIsNone(FlowDicom.classifyDataset(ge(3, venc=None)))

        # Philips
        image = FlowDicom.classifyDataset(philips("M", [200.0, 200.0, 200.0], numberOfDirections=3))
        self.assertEqual((image["vendor"], image["role"], image["directionCode"], image["groupKey"]), ("philips", "magnitude", "magnitude", "37"))
        for axis, directionCode in enumerate(["patient_rl", "patient_ap", "patient_fh"]):
            pcVelocity = [0.0, 0.0, 0.0]
            pcVelocity[axis] = 200.0
            direction = [0.0, 0.0, 0.0]
            direction[axis] = 1.0
            image = FlowDicom.classifyDataset(philips("P", pcVelocity, direction))
            self.assertEqual((image["role"], image["directionCode"], image["vencCmPerSec"], image["maxValue"]), ("velocity", directionCode, 200.0, 200.0))
            image = FlowDicom.classifyDataset(philips("P", pcVelocity))  # direction from PC Velocity
            self.assertEqual(image["directionCode"], directionCode)
        self.assertIsNone(FlowDicom.classifyDataset(philips("P", [200.0, 0.0, 0.0], [0.6, 0.8, 0.0])))  # not a patient axis
        self.assertIsNone(FlowDicom.classifyDataset(philips("P", [200.0, 0.0, 0.0], rescale=False)))
        self.assertIsNone(FlowDicom.classifyDataset(philips("M", [200.0, 200.0, 200.0], numberOfDirections=1)))
        ds = Dataset()
        ds.Manufacturer = "Philips"
        ds.ImageType = ["ORIGINAL", "PRIMARY", "M_FFE", "M", "FFE"]
        self.assertIsNone(FlowDicom.classifyDataset(ds))  # not phase contrast

        # Heart rate
        ds = Dataset()
        self.assertIsNone(FlowDicom.heartRateBpm(ds))
        ds.HeartRate = "78"
        self.assertEqual(FlowDicom.heartRateBpm(ds), 78.0)
        ds.NominalInterval = "750"
        self.assertEqual(FlowDicom.heartRateBpm(ds), 80.0)
        self.assertAlmostEqual(FlowDicom.heartRateBpmFromFrameTimes([12.0, 38.0, 64.0, 89.0]), 60000.0 / (77.0 * 4 / 3))
        self.assertIsNone(FlowDicom.heartRateBpmFromFrameTimes([12.0]))
        self.delayDisplay("Classification of DICOM data sets passed")


    def test_ComponentConfiguration(self):
        """The velocity component configuration (RAS order and signs) is found for Siemens (image-relative) and
        patient-axis (GE, Philips) direction codes (FlowDicom.componentConfiguration)."""
        self.assertEqual(FlowDicom.componentConfiguration("siemens", ["inplane_fh", "through", "inplane_ap"]),
                         FlowDicom.SIEMENS_AXIS_CONFIGURATIONS[0])
        self.assertEqual(FlowDicom.componentConfiguration("siemens", ["inplane_rl", "through", "inplane_fh"]),
                         FlowDicom.SIEMENS_AXIS_CONFIGURATIONS[1])
        self.assertIsNone(FlowDicom.componentConfiguration("siemens", ["inplane_rl", "through"]))
        for vendor in ("ge", "philips"):
            self.assertEqual(FlowDicom.componentConfiguration(vendor, ["patient_fh", "patient_rl", "patient_ap"]),
                             FlowDicom.PATIENT_AXIS_CONFIGURATIONS[vendor])
            self.assertIsNone(FlowDicom.componentConfiguration(vendor, ["patient_fh", "patient_rl"]))
        # Patient-axis codes are only valid for vendors with a known sign convention
        self.assertIsNone(FlowDicom.componentConfiguration("siemens", ["patient_fh", "patient_rl", "patient_ap"]))
        self.assertIsNone(FlowDicom.componentConfiguration(None, ["patient_fh", "patient_rl", "patient_ap"]))
        self.delayDisplay("test_ComponentConfiguration passed")

