import json
import logging
import os
import pathlib
import zlib

import numpy as np
import vtk

import qt
import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *


#
# ImportMimics
#


class ImportMimics(ScriptedLoadableModule):
    """Import Materialise Mimics project files (.mcs) into 3D Slicer."""

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Import Mimics")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Cardiac")]
        self.parent.dependencies = []
        self.parent.contributors = ["Andras Lasso (PerkLab, Queen's University)"]
        self.parent.helpText = _("""
This module imports Materialise Mimics project files (<b>.mcs</b>) into 3D Slicer.

A Mimics project is a SQLite database that stores a blob container. This importer extracts:
<ul>
<li><b>Image volume</b> - reconstructed from the embedded DICOM headers (geometry, patient/study
information) combined with the separately stored pixel data.</li>
<li><b>Surface models</b> - segmentation surfaces (3D objects) stored as fixed-point meshes.</li>
<li><b>Metadata</b> - patient/study/series information and a blob inventory, saved as node
attributes and optionally exported to a JSON file.</li>
</ul>

Note: the project's <i>header.xml</i> (object list, colors, analysis data) is stored encrypted by
Mimics and cannot be decoded, so object names/colors are not recovered.
For research use only. Materialise is not affiliated with the development of this module.
""")
        self.parent.acknowledgementText = _("""
This module was developed as part of the SlicerHeart project.
""")


#
# ImportMimicsWidget
#


class ImportMimicsWidget(ScriptedLoadableModuleWidget):

    # All user choices are persisted in the application settings under this prefix.
    SETTINGS_PREFIX = "ImportMimics/"

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.logic = None
        self.loadingInProgress = False
        self._restoringSettings = False
        self._settingCheckBoxes = []
        self._checkBoxDefaults = {}

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/ImportMimics.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = ImportMimicsLogic()
        self.logic.logCallback = self.addLog
        self.logic.progressCallback = self.updateProgress

        # The input may be a single .mcs file or a folder (for batch conversion). No name filter
        # is set: a *.mcs filter would suppress the currentPathChanged signal for folders.
        import ctk
        self.ui.inputPathLineEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Dirs
        # Configure the custom export path selector to pick a folder.
        self.ui.exportPathLineEdit.filters = ctk.ctkPathLineEdit.Dirs

        # (settings key, checkbox) for every persisted checkbox option. The default value for
        # each is whatever the .ui file sets as its initial checked state, captured here before
        # any saved settings are restored.
        self._settingCheckBoxes = [
            ("loadIntoScene", self.ui.loadIntoSceneCheckBox),
            ("importImage", self.ui.importImageCheckBox),
            ("importModels", self.ui.importModelsCheckBox),
            ("importNurbs", self.ui.importNurbsCheckBox),
            ("importPoints", self.ui.importPointsCheckBox),
            ("importDicom", self.ui.importDicomCheckBox),
            ("importMetadata", self.ui.importMetadataCheckBox),
        ]
        self._checkBoxDefaults = {key: checkBox.checked for key, checkBox in self._settingCheckBoxes}

        self.ui.applyButton.connect("clicked(bool)", self.onApplyButton)
        for _key, checkBox in self._settingCheckBoxes:
            checkBox.connect("toggled(bool)", self._onGuiChanged)
        for radioButton in (self.ui.exportNoSaveRadioButton, self.ui.exportSameFolderRadioButton,
                            self.ui.exportCustomFolderRadioButton):
            radioButton.connect("toggled(bool)", self._onGuiChanged)
        self.ui.inputPathLineEdit.connect("currentPathChanged(QString)", self._onGuiChanged)
        self.ui.exportPathLineEdit.connect("currentPathChanged(QString)", self._onGuiChanged)

        self.ui.progressBar.hide()

        self._restoreSettings()
        self._checkCanApply()

    def cleanup(self) -> None:
        pass

    # ------------------------------------------------------------------ settings

    def _onGuiChanged(self, *args) -> None:
        if self._restoringSettings:
            return
        self._saveSettings()
        self._checkCanApply()

    def _saveSettings(self) -> None:
        settings = slicer.app.userSettings()
        prefix = self.SETTINGS_PREFIX
        for key, checkBox in self._settingCheckBoxes:
            settings.setValue(prefix + key, checkBox.checked)
        if self.ui.exportCustomFolderRadioButton.checked:
            outputMode = "custom"
        elif self.ui.exportSameFolderRadioButton.checked:
            outputMode = "same"
        else:
            outputMode = "none"
        settings.setValue(prefix + "outputMode", outputMode)
        settings.setValue(prefix + "inputPath", self.ui.inputPathLineEdit.currentPath)
        settings.setValue(prefix + "customFolder", self.ui.exportPathLineEdit.currentPath)

    def _restoreSettings(self) -> None:
        prefix = self.SETTINGS_PREFIX
        self._restoringSettings = True
        try:
            for key, checkBox in self._settingCheckBoxes:
                checkBox.checked = slicer.util.settingsValue(
                    prefix + key, self._checkBoxDefaults[key], converter=slicer.util.toBool)
            outputMode = slicer.util.settingsValue(prefix + "outputMode", "same")
            if outputMode == "custom":
                self.ui.exportCustomFolderRadioButton.checked = True
            elif outputMode == "none":
                self.ui.exportNoSaveRadioButton.checked = True
            else:
                self.ui.exportSameFolderRadioButton.checked = True
            self.ui.exportPathLineEdit.currentPath = slicer.util.settingsValue(prefix + "customFolder", "")
            self.ui.inputPathLineEdit.currentPath = slicer.util.settingsValue(prefix + "inputPath", "")
        finally:
            self._restoringSettings = False

    def _checkCanApply(self, caller=None, event=None) -> None:
        """Update the output-folder controls and the action button label/enabled state."""
        # Custom output folder path field is only relevant when 'Custom folder' is selected.
        self.ui.exportPathLineEdit.enabled = self.ui.exportCustomFolderRadioButton.checked

        inputPath = self.ui.inputPathLineEdit.currentPath
        hasInput = bool(inputPath)
        isFolder = hasInput and os.path.isdir(inputPath)
        isMcsFile = hasInput and os.path.isfile(inputPath) and inputPath.lower().endswith(".mcs")
        saveToFiles = not self.ui.exportNoSaveRadioButton.checked

        # A folder input is a batch conversion, so loading into the scene does not apply:
        # disable the option and show an explanatory message. No message in any other case.
        label = self.ui.inputWarningLabel
        if isFolder:
            self.ui.loadIntoSceneCheckBox.enabled = False
            label.text = _("Folder selected - batch conversion")
            label.toolTip = _("A folder is selected, so every Mimics project (.mcs) file it "
                              "contains will be converted to files. Loading into the scene does "
                              "not apply to batch conversion.")
            label.styleSheet = "color: gray; font-style: italic;"
            label.visible = True
        else:
            self.ui.loadIntoSceneCheckBox.enabled = True
            label.visible = False

        loadIntoScene = self.ui.loadIntoSceneCheckBox.checked and not isFolder
        # Neither loading nor saving: just report information about the selection.
        inspectMode = not loadIntoScene and not saveToFiles

        if isFolder and saveToFiles:
            self.ui.applyButton.text = _("Batch convert")
        elif inspectMode:
            self.ui.applyButton.text = _("Inspect")
        elif loadIntoScene and saveToFiles:
            self.ui.applyButton.text = _("Convert && Load")
        elif saveToFiles:
            self.ui.applyButton.text = _("Convert")
        else:
            self.ui.applyButton.text = _("Load")
        self.ui.applyButton.enabled = isMcsFile or isFolder

    def clearLog(self):
        self.ui.statusLabel.plainText = ''
        self.ui.progressBar.setValue(0)
        slicer.app.processEvents()

    def addLog(self, text):
        self.ui.statusLabel.appendPlainText(text)
        slicer.app.processEvents()

    def updateProgress(self, percent):
        self.ui.progressBar.setValue(percent)
        slicer.app.processEvents()

    def onApplyButton(self) -> None:
        with slicer.util.tryWithErrorDisplay(_("Failed to import Mimics project."), waitCursor=True):
            try:
                self.clearLog()
                self.logic.messages = []
                inputPath = self.ui.inputPathLineEdit.currentPath
                if not inputPath:
                    raise ValueError("Please specify an input .mcs file or folder")
                isFolder = os.path.isdir(inputPath)

                self.loadingInProgress = True
                self.ui.progressBar.show()
                self.ui.applyButton.enabled = False
                self.ui.inputsCollapsibleButton.enabled = False

                loadImage = self.ui.importImageCheckBox.checked
                loadModels = self.ui.importModelsCheckBox.checked
                loadNurbs = self.ui.importNurbsCheckBox.checked
                loadPoints = self.ui.importPointsCheckBox.checked
                exportDicom = self.ui.importDicomCheckBox.checked
                saveMetadata = self.ui.importMetadataCheckBox.checked
                # A folder input is always a batch conversion (no loading into the scene).
                loadIntoScene = self.ui.loadIntoSceneCheckBox.checked and not isFolder
                saveToFiles = not self.ui.exportNoSaveRadioButton.checked
                if not (loadImage or loadModels or loadNurbs or loadPoints or exportDicom or saveMetadata):
                    raise ValueError("Select at least one content type")

                useCustom = self.ui.exportCustomFolderRadioButton.checked
                customBase = self.ui.exportPathLineEdit.currentPath if useCustom else None
                if saveToFiles and useCustom and not customBase:
                    raise ValueError("Please specify a custom output folder")

                def exportDirFor(mcsPath, perProjectSubfolder):
                    if not saveToFiles:
                        return None
                    projectName = os.path.splitext(os.path.basename(mcsPath))[0]
                    if useCustom:
                        return os.path.join(customBase, projectName) if perProjectSubfolder else customBase
                    # Save next to the .mcs file, inside a subfolder named after the project.
                    return os.path.join(os.path.dirname(os.path.abspath(mcsPath)), projectName)

                commonArgs = dict(loadImage=loadImage, loadModels=loadModels, loadNurbs=loadNurbs,
                                  loadPoints=loadPoints, exportDicom=exportDicom,
                                  saveMetadata=saveMetadata)
                # Neither loading nor saving: only report information about the selection.
                inspectMode = not loadIntoScene and not saveToFiles

                if isFolder:
                    import glob
                    mcsFiles = sorted(glob.glob(os.path.join(inputPath, "*.mcs")))
                    if not mcsFiles:
                        raise ValueError("No .mcs files found in the selected folder")
                    verb = "Inspecting" if inspectMode else "Batch converting"
                    self.addLog(f"{verb} {len(mcsFiles)} Mimics project(s)...")
                    nOk = 0
                    for i, mcsPath in enumerate(mcsFiles):
                        self.addLog(f"[{i + 1}/{len(mcsFiles)}] {os.path.basename(mcsPath)}")
                        try:
                            if inspectMode:
                                self.logic.inspect(mcsPath)
                            else:
                                self.logic.importMcs(mcsPath, loadIntoScene=False,
                                                     exportDir=exportDirFor(mcsPath, True), **commonArgs)
                            nOk += 1
                        except Exception as e:  # noqa: BLE001 - keep going on the rest of the batch
                            self.addLog(f"  ERROR: {e}")
                        self.updateProgress(int((i + 1) / len(mcsFiles) * 100))
                    self.addLog(f"Finished: {nOk}/{len(mcsFiles)} project(s).")
                elif inspectMode:
                    self.logic.inspect(inputPath)
                else:
                    self.logic.importMcs(inputPath, loadIntoScene=loadIntoScene,
                                         exportDir=exportDirFor(inputPath, False), **commonArgs)

                # Show a pop-up at the end if any project reported an error (e.g. >10% non-uniform
                # slice spacing). Warnings are only written to the log above.
                errors = [text for severity, text in self.logic.messages if severity == "error"]
                if errors:
                    slicer.util.errorDisplay("\n\n".join(errors),
                                             windowTitle=_("Import Mimics"))

            finally:
                self.loadingInProgress = False
                self.ui.inputsCollapsibleButton.enabled = True
                self.ui.progressBar.hide()
                self._checkCanApply()


#
# ImportMimicsLogic
#


class ImportMimicsLogic(ScriptedLoadableModuleLogic):
    """Reads Materialise Mimics .mcs project files.

    File format (reverse engineered):
      - The .mcs file is a SQLite database with two tables: `blobs` (blob_id, blob_name,
        number_of_parts) and `blobs_parts` (blob data, optionally zlib-compressed, in parts).
      - `blob_0` contains the original DICOM files concatenated (128-byte preamble + 'DICM' +
        dataset), one per slice, but with the pixel data removed.
      - `blob_1`, `blob_2`, ... are the per-slice pixel data, each prefixed with a 4-byte 'MMFD'
        magic and followed by Rows*Columns*2 bytes of little-endian 16-bit pixels.
      - `Stl{guid}_vertices` and `Stl{guid}_surfaces` store surface models: vertices as int32
        fixed-point coordinates (millimeters * 10000, in LPS/patient coordinate system), and
        surfaces as int32 triangle vertex indices.
      - `header.xml` holds the project structure but is stored encrypted, so it is not decoded.
    """

    # Mimics stores mesh vertex coordinates as integers in units of 0.1 micrometer (mm * 1e4).
    MESH_COORD_SCALE = 1.0e-4

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self.logCallback = None
        self.progressCallback = None
        # Accumulated (severity, text) messages (e.g. non-uniform slice spacing) for the caller
        # to surface as warnings/errors. Reset it before an operation; it accumulates across a
        # batch so all projects' issues can be reported together.
        self.messages = []

    def addLog(self, text):
        logging.info(text)
        if self.logCallback:
            self.logCallback(text)

    def updateProgress(self, percent):
        if self.progressCallback:
            self.progressCallback(percent)

    # ------------------------------------------------------------------ blob store

    @staticmethod
    def _readBlob(cur, blobId):
        """Return the (decompressed, concatenated) bytes of a blob given its id."""
        cur.execute(
            "SELECT is_blob_compressed, blob_part_data FROM blobs_parts "
            "WHERE blob_id=? ORDER BY blob_part_number", (blobId,))
        parts = []
        for compressed, data in cur.fetchall():
            if compressed:
                data = zlib.decompress(data)
            parts.append(data)
        return b"".join(parts)

    @classmethod
    def _blobIndex(cls, con):
        """Return {blob_name: blob_id} for all blobs."""
        cur = con.cursor()
        cur.execute("SELECT blob_name, blob_id FROM blobs")
        return {name: bid for name, bid in cur.fetchall()}

    @staticmethod
    def _inventory(names):
        """Summarize the project contents from blob names alone (no decompression)."""
        stl = sorted(n[len("Stl"):-len("_vertices")]
                     for n in names if n.startswith("Stl{") and n.endswith("}_vertices"))
        nurbs = sorted(n[len("NURBS_"):] for n in names if n.startswith("NURBS_"))
        pointSets = [n for n in names if n.startswith("00007FF")]
        previews = [n for n in names if n.startswith("ImageBlockPngPreview")]
        return {
            "surfaceModelCount": len(stl),
            "surfaceModelGuids": stl,
            "nurbsSurfaceCount": len(nurbs),
            "nurbsSurfaceGuids": nurbs,
            "pointSetCount": len(pointSets),
            "imagePreviewCount": len(previews),
        }

    # ------------------------------------------------------------------ main entry

    def importMcs(self, filename, loadImage=True, loadModels=True, loadNurbs=True,
                  loadPoints=True, loadIntoScene=True, exportDir=None, exportDicom=False,
                  saveMetadata=True):
        import sqlite3

        if not os.path.isfile(filename):
            raise FileNotFoundError(filename)

        self.addLog(f"Importing Mimics project: {filename}")
        self.updateProgress(1)

        # Open read-only so the source project file is never modified.
        try:
            con = sqlite3.connect(f"{pathlib.Path(filename).as_uri()}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            con = sqlite3.connect(filename)
        try:
            names = self._blobIndex(con)
            if "blobs" not in [r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")]:
                raise ValueError("Not a Mimics project file (no 'blobs' table).")

            projectName = os.path.splitext(os.path.basename(filename))[0]
            inventory = self._inventory(names)
            metadata = {
                "sourceFile": os.path.normpath(os.path.abspath(filename)),
                "projectName": projectName,
                "format": "Materialise Mimics project (.mcs)",
                "blobCount": len(names),
                "contents": inventory,
                "notes": [
                    "The project header (object names, colors, analysis data) is stored "
                    "encrypted by Mimics and cannot be decoded; objects are named generically.",
                ],
            }

            volumeNode = None
            dicomMeta = None
            if loadImage:
                volumeNode, dicomMeta = self.importImage(con, names)
                if dicomMeta:
                    metadata["image"] = dicomMeta
                    if dicomMeta.get("sliceSpacingError"):
                        self.messages.append(("error", f"{projectName}: {dicomMeta['sliceSpacingError']}"))
                    elif dicomMeta.get("sliceSpacingWarning"):
                        self.messages.append(("warning", f"{projectName}: {dicomMeta['sliceSpacingWarning']}"))
                elif "blob_0" in names:
                    metadata["notes"].append(
                        "Image data is present but could not be reconstructed "
                        "(unsupported or compressed pixel storage).")
                self.updateProgress(55)

            modelNodes = []
            if loadModels:
                modelNodes = self.importModels(con, names, attachMetadata=saveMetadata)
                metadata["surfaceModels"] = [{
                    "name": m.GetName(),
                    "guid": m.GetAttribute("Mimics.guid"),
                    "points": m.GetPolyData().GetNumberOfPoints(),
                    "triangles": m.GetPolyData().GetNumberOfCells(),
                } for m in modelNodes]
                self.updateProgress(70)

            curveNodes = []
            if loadNurbs and inventory["nurbsSurfaceCount"]:
                curveNodes = self.importNurbsCurves(con, names, attachMetadata=saveMetadata)
                metadata["nurbsCurves"] = [{
                    "name": c.GetName(), "guid": c.GetAttribute("Mimics.guid"),
                } for c in curveNodes]
                self.updateProgress(80)

            pointNodes = []
            if loadPoints and inventory["pointSetCount"]:
                pointNodes = self.importPointSets(con, names, attachMetadata=saveMetadata)
                metadata["pointSets"] = [{
                    "name": p.GetName(), "points": p.GetNumberOfControlPoints(),
                } for p in pointNodes]
                self.updateProgress(85)

            markupsNodes = curveNodes + pointNodes

            if exportDir:
                self._exportFiles(exportDir, volumeNode, modelNodes, markupsNodes, metadata,
                                  saveMetadata)
                if exportDicom:
                    self.exportDicomFiles(con, names, exportDir)
                self.updateProgress(95)

            if loadIntoScene:
                # Nodes are left at the scene top level: no patient/study subject-hierarchy branch
                # is created and no patient information is added - only the geometry is used.
                if volumeNode is not None:
                    slicer.util.setSliceViewerLayers(background=volumeNode, fit=True)
                self.addLog(
                    f"Done. Loaded {'1 volume, ' if volumeNode else ''}{len(modelNodes)} model(s), "
                    f"{len(curveNodes)} curve(s), {len(pointNodes)} point set(s) into the scene.")
            else:
                # Not loading into the scene: remove the nodes that were created for export.
                nVolume = 1 if volumeNode is not None else 0
                counts = (nVolume, len(modelNodes), len(curveNodes), len(pointNodes))
                for node in [volumeNode] + modelNodes + markupsNodes:
                    if node is not None:
                        slicer.mrmlScene.RemoveNode(node)
                volumeNode, modelNodes, markupsNodes = None, [], []
                self.addLog(
                    f"Done. Exported {counts[0]} volume, {counts[1]} model(s), "
                    f"{counts[2]} curve(s), {counts[3]} point set(s) to files.")
            self.updateProgress(100)
            return volumeNode, modelNodes, markupsNodes
        finally:
            con.close()

    def inspect(self, filename):
        """Log a summary of a Mimics project without creating any nodes or writing files."""
        import sqlite3

        if not os.path.isfile(filename):
            raise FileNotFoundError(filename)
        try:
            con = sqlite3.connect(f"{pathlib.Path(filename).as_uri()}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            con = sqlite3.connect(filename)
        try:
            names = self._blobIndex(con)
            if "blobs" not in [r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")]:
                raise ValueError("Not a Mimics project file (no 'blobs' table).")
            inventory = self._inventory(names)
            projectName = os.path.splitext(os.path.basename(filename))[0]
            self.addLog(f"  Project: {projectName}  ({len(names)} blobs)")
            image = self._imageInfo(con, names)
            if image:
                self.addLog(f"  Image: {image['modality']} "
                            f"{image['columns']}x{image['rows']}x{image['sliceCount']}"
                            + (f", spacing {image['pixelSpacing']} mm" if image['pixelSpacing'] else "")
                            + (f" [{image['seriesDescription']}]" if image['seriesDescription'] else ""))
                patientBits = " ".join(x for x in (image['patientName'], image['studyDescription'],
                                                   image['studyDate']) if x)
                if patientBits:
                    self.addLog(f"    {patientBits}")
                # Record slice-spacing warnings/errors found during the header analysis.
                if image.get("sliceSpacingError"):
                    self.messages.append(("error", f"{projectName}: {image['sliceSpacingError']}"))
                elif image.get("sliceSpacingWarning"):
                    self.messages.append(("warning", f"{projectName}: {image['sliceSpacingWarning']}"))
            elif "blob_0" in names:
                self.addLog("  Image: present but could not be read")
            else:
                self.addLog("  Image: none")
            self.addLog(f"  Surface models: {inventory['surfaceModelCount']}, "
                        f"NURBS curves: {inventory['nurbsSurfaceCount']}, "
                        f"point sets: {inventory['pointSetCount']}, "
                        f"image previews: {inventory['imagePreviewCount']}")
            return inventory
        finally:
            con.close()

    def _imageInfo(self, con, names):
        """Return an image summary from the DICOM headers (blob_0), including a slice-spacing
        uniformity check. Only headers are parsed - no pixel data is read."""
        try:
            import pydicom
        except ImportError:
            return None
        if "blob_0" not in names:
            return None
        import io
        blob0 = self._readBlob(con.cursor(), names["blob_0"])
        offsets = []
        start = 0
        while True:
            i = blob0.find(b"DICM", start)
            if i < 0:
                break
            offsets.append(i - 128)
            start = i + 1
        offsets = [o for o in offsets if o >= 0]
        if not offsets:
            return None
        bounds = offsets + [len(blob0)]
        ds = pydicom.dcmread(io.BytesIO(blob0[bounds[0]:bounds[1]]), force=True)
        info = {
            "modality": str(ds.get("Modality", "")),
            "rows": int(ds.get("Rows", 0)),
            "columns": int(ds.get("Columns", 0)),
            "sliceCount": len(offsets),
            "pixelSpacing": [float(x) for x in ds.get("PixelSpacing", [])],
            "seriesDescription": str(ds.get("SeriesDescription", "")),
            "patientName": str(ds.get("PatientName", "")),
            "studyDescription": str(ds.get("StudyDescription", "")),
            "studyDate": str(ds.get("StudyDate", "")),
        }
        # Slice-spacing uniformity check from the per-slice ImagePositionPatient.
        try:
            if len(offsets) >= 3 and "ImageOrientationPatient" in ds and "ImagePositionPatient" in ds:
                iop = np.array([float(x) for x in ds.ImageOrientationPatient], dtype=float)
                ipps = []
                for k in range(len(offsets)):
                    dk = ds if k == 0 else pydicom.dcmread(
                        io.BytesIO(blob0[bounds[k]:bounds[k + 1]]), force=True,
                        specific_tags=["ImagePositionPatient"])
                    ipps.append([float(x) for x in dk.ImagePositionPatient])
                ipps = np.array(ipps, dtype=float)
                normal = np.cross(iop[0:3], iop[3:6])
                order = np.argsort(ipps @ normal)
                sortedSlices = [(0, ipps[o], None, None) for o in order]
                self._checkSliceSpacingUniformity(sortedSlices, info)
        except Exception:  # noqa: BLE001 - spacing check is best-effort during inspection
            pass
        return info

    # ------------------------------------------------------------------ image

    def _reconstructSlices(self, con, names):
        """Split blob_0 into per-slice DICOM headers, pair with MMFD pixel blobs and decode pixels.

        Returns (slices, dicomMeta) where `slices` is a list of (instanceNumber, ipp, pixels, ds)
        sorted spatially along the slice normal, or (None, None) if no image data is available.
        """
        try:
            import pydicom
        except ImportError:
            self.addLog("  WARNING: pydicom is not available; skipping image reconstruction.")
            return None, None

        if "blob_0" not in names:
            self.addLog("  No image data found (blob_0 missing).")
            return None, None

        cur = con.cursor()
        blob0 = self._readBlob(cur, names["blob_0"])

        # Split concatenated DICOM files: each starts 128 bytes before its 'DICM' marker.
        headerChunks = []
        start = 0
        while True:
            i = blob0.find(b"DICM", start)
            if i < 0:
                break
            headerChunks.append(i - 128)
            start = i + 1
        headerChunks = [o for o in headerChunks if o >= 0]
        if not headerChunks:
            self.addLog("  No DICOM headers found in image data.")
            return None, None
        bounds = headerChunks + [len(blob0)]

        # Collect per-slice pixel data blobs (prefixed with 'MMFD').
        pixelBlobs = []
        for name, bid in names.items():
            if name == "blob_0" or not (name.startswith("blob_") and name[5:].isdigit()):
                continue
            data = self._readBlob(cur, bid)
            if data[:4] == b"MMFD":
                pixelBlobs.append((int(name[5:]), data[4:]))
        pixelBlobs.sort()

        nHeaders = len(headerChunks)
        if len(pixelBlobs) != nHeaders:
            self.addLog(f"  WARNING: {nHeaders} DICOM headers but {len(pixelBlobs)} pixel blobs; "
                        "pairing by order.")
        nSlices = min(nHeaders, len(pixelBlobs))
        self.addLog(f"  Reconstructing {nSlices} slices...")

        import io
        slices = []
        dicomMeta = None
        for k in range(nSlices):
            ds = pydicom.dcmread(io.BytesIO(blob0[bounds[k]:bounds[k + 1]]), force=True)
            rows, cols = int(ds.Rows), int(ds.Columns)
            body = pixelBlobs[k][1]
            if len(body) != rows * cols * 2:
                # Unsupported pixel storage for this project (e.g. compressed or a variant
                # layout). Skip image reconstruction rather than producing a wrong volume.
                self.addLog(f"  WARNING: unexpected pixel data size for slice {k} "
                            f"({len(body)} bytes, expected {rows * cols * 2}); "
                            "skipping image reconstruction.")
                return None, None
            pixels = np.frombuffer(body, dtype="<u2").reshape(rows, cols)
            ipp = np.array([float(x) for x in ds.ImagePositionPatient], dtype=float)
            instanceNumber = int(getattr(ds, "InstanceNumber", k + 1))
            slices.append((instanceNumber, ipp, pixels, ds))
            if dicomMeta is None:
                iop = [float(x) for x in ds.ImageOrientationPatient]
                ps = [float(x) for x in ds.PixelSpacing]
                dicomMeta = {
                    "patientName": str(getattr(ds, "PatientName", "")),
                    "patientID": str(getattr(ds, "PatientID", "")),
                    "patientSex": str(getattr(ds, "PatientSex", "")),
                    "patientBirthDate": str(getattr(ds, "PatientBirthDate", "")),
                    "studyDescription": str(getattr(ds, "StudyDescription", "")),
                    "studyDate": str(getattr(ds, "StudyDate", "")),
                    "studyInstanceUID": str(getattr(ds, "StudyInstanceUID", "")),
                    "seriesDescription": str(getattr(ds, "SeriesDescription", "")),
                    "seriesNumber": str(getattr(ds, "SeriesNumber", "")),
                    "seriesInstanceUID": str(getattr(ds, "SeriesInstanceUID", "")),
                    "modality": str(getattr(ds, "Modality", "")),
                    "manufacturer": str(getattr(ds, "Manufacturer", "")),
                    "manufacturerModelName": str(getattr(ds, "ManufacturerModelName", "")),
                    "rows": rows, "columns": cols,
                    "pixelSpacing": ps,
                    "imageOrientationPatient": iop,
                    "imagePositionPatientFirst": [float(x) for x in ds.ImagePositionPatient],
                    "sliceThickness": float(getattr(ds, "SliceThickness", 0) or 0),
                }

        # Order slices spatially by projection onto the slice normal.
        iop = np.array(dicomMeta["imageOrientationPatient"], dtype=float)
        rowDir = iop[0:3]   # direction of increasing column index (i)
        colDir = iop[3:6]   # direction of increasing row index (j)
        sliceNormal = np.cross(rowDir, colDir)
        slices.sort(key=lambda s: np.dot(s[1], sliceNormal))
        return slices, dicomMeta

    def importImage(self, con, names):
        """Reconstruct the image volume from DICOM headers (blob_0) + MMFD pixel blobs."""
        slices, dicomMeta = self._reconstructSlices(con, names)
        if not slices:
            return None, None
        nSlices = len(slices)

        rowDir = np.array(dicomMeta["imageOrientationPatient"][0:3], dtype=float)
        colDir = np.array(dicomMeta["imageOrientationPatient"][3:6], dtype=float)
        sliceNormal = np.cross(rowDir, colDir)

        volumeArray = np.stack([s[2] for s in slices])  # (k, rows=j, cols=i)

        ippFirst = slices[0][1]
        ippLast = slices[-1][1]
        ps = dicomMeta["pixelSpacing"]
        colSpacing = ps[1]  # spacing between columns (along rowDir)
        rowSpacing = ps[0]  # spacing between rows (along colDir)
        if nSlices > 1:
            sliceVec = ippLast - ippFirst
            sliceSpacing = np.linalg.norm(sliceVec) / (nSlices - 1)
            sliceDir = sliceVec / np.linalg.norm(sliceVec)
            self._checkSliceSpacingUniformity(slices, dicomMeta)
        else:
            sliceSpacing = dicomMeta["sliceThickness"] or 1.0
            sliceDir = sliceNormal

        dicomMeta["sliceCount"] = int(nSlices)
        dicomMeta["sliceSpacing"] = float(sliceSpacing)

        # Build IJK->RAS (LPS negated in x,y).
        lpsToRas = np.diag([-1.0, -1.0, 1.0])
        ijkToRas = np.eye(4)
        ijkToRas[0:3, 0] = lpsToRas @ (rowDir * colSpacing)
        ijkToRas[0:3, 1] = lpsToRas @ (colDir * rowSpacing)
        ijkToRas[0:3, 2] = lpsToRas @ (sliceDir * sliceSpacing)
        ijkToRas[0:3, 3] = lpsToRas @ ippFirst

        volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        volumeNode.SetName("image")
        slicer.util.updateVolumeFromArray(volumeNode, volumeArray)
        vtkMat = vtk.vtkMatrix4x4()
        for r in range(4):
            for c in range(4):
                vtkMat.SetElement(r, c, ijkToRas[r, c])
        volumeNode.SetIJKToRASMatrix(vtkMat)
        volumeNode.CreateDefaultDisplayNodes()

        # Only the geometry is used in the scene; patient/study/series identifiers are not
        # attached to the node (they remain available only for the opt-in metadata/DICOM export).

        self.addLog(f"  Image: {volumeArray.shape[2]}x{volumeArray.shape[1]}x{volumeArray.shape[0]} "
                    f"({dicomMeta['modality']}, spacing "
                    f"{colSpacing:.3g}x{rowSpacing:.3g}x{sliceSpacing:.3g} mm)")
        return volumeNode, dicomMeta

    def _checkSliceSpacingUniformity(self, slices, dicomMeta):
        """Warn/error when the slice-to-slice distances contain outliers.

        A single average spacing is used for the reconstructed volume, so any non-uniformity
        makes the geometry inaccurate. Outliers are slice-to-slice distances that differ from
        the median by more than 1%. If the worst outlier is within 10% of the median it is a
        warning; beyond 10% it is an error (which the caller shows in a pop-up at the end).
        Each distinct outlier value is reported with how many times it occurs.
        """
        import collections

        ippArray = np.array([s[1] for s in slices], dtype=float)
        gaps = np.linalg.norm(np.diff(ippArray, axis=0), axis=1)
        median = float(np.median(gaps))
        if median <= 0:
            return
        relativeDeviation = np.abs(gaps - median) / median
        dicomMeta["sliceSpacingMedian"] = round(median, 4)
        dicomMeta["sliceSpacingMaxDeviationPercent"] = round(float(relativeDeviation.max()) * 100.0, 2)

        outlierMask = relativeDeviation > 0.01
        if not outlierMask.any():
            return

        # Count how many times each distinct outlier spacing occurs.
        counts = collections.Counter(round(float(g), 3) for g in gaps[outlierMask])
        outlierText = ", ".join(f"{value:g} mm occurred {count}x"
                                for value, count in sorted(counts.items()))
        dicomMeta["sliceSpacingOutliers"] = {f"{value:g}": count
                                             for value, count in sorted(counts.items())}
        base = (f"Non-uniform slice spacing: the median spacing is {round(median, 3):g} mm, "
                f"but the following outlier spacings (differing by more than 1% from the median) "
                f"were found: {outlierText}.")
        if float(relativeDeviation.max()) > 0.10:
            message = (base + " The reconstructed volume uses a single average spacing, so its "
                       "geometry is likely inaccurate.")
            self.addLog(f"  ERROR: {message}")
            dicomMeta["sliceSpacingError"] = message
        else:
            message = base + " The volume uses the average spacing."
            self.addLog(f"  WARNING: {message}")
            dicomMeta["sliceSpacingWarning"] = message

    def exportDicomFiles(self, con, names, outputDir):
        """Reconstruct the complete original DICOM files (headers + pixel data) and save them.

        Files are written to a `dicom` subfolder, one per slice.
        Returns the number of files written.
        """
        import pydicom

        slices, dicomMeta = self._reconstructSlices(con, names)
        if not slices:
            self.addLog("  No DICOM data to export.")
            return 0

        dicomDir = os.path.join(outputDir, "dicom")
        os.makedirs(dicomDir, exist_ok=True)
        for instanceNumber, ipp, pixels, ds in slices:
            # Mimics stores the DICOM headers with the pixel data removed (and, for compressed
            # source images, leaves a compressed transfer syntax on the header). Complete each
            # file: inject the raw pixels, use a matching uncompressed transfer syntax, and set
            # the Pixel Data VR according to the bit depth.
            ds.PixelData = pixels.tobytes()
            ds["PixelData"].VR = "OW" if int(getattr(ds, "BitsAllocated", 16)) > 8 else "OB"
            ds.file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
            path = os.path.join(dicomDir, f"slice_{instanceNumber:04d}.dcm")
            ds.save_as(path, enforce_file_format=True)
        self.addLog(f"  Saved {len(slices)} original DICOM file(s) to {dicomDir}")
        return len(slices)

    # ------------------------------------------------------------------ models

    def importModels(self, con, names, attachMetadata=True):
        """Create model nodes from Stl{guid}_vertices / _surfaces blobs."""
        cur = con.cursor()
        guids = []
        for name in names:
            if name.startswith("Stl{") and name.endswith("}_vertices"):
                guids.append(name[len("Stl"):-len("_vertices")])

        modelNodes = []
        colorPalette = [
            (0.9, 0.5, 0.5), (0.5, 0.7, 0.9), (0.6, 0.9, 0.6),
            (0.9, 0.8, 0.5), (0.8, 0.6, 0.9), (0.5, 0.9, 0.85),
        ]
        for idx, guid in enumerate(sorted(guids)):
            vName = f"Stl{guid}_vertices"
            sName = f"Stl{guid}_surfaces"
            if sName not in names:
                self.addLog(f"  Skipping {guid}: no surfaces blob.")
                continue

            vertexBytes = self._readBlob(cur, names[vName])
            surfaceBytes = self._readBlob(cur, names[sName])
            vertices = np.frombuffer(vertexBytes, dtype="<i4").reshape(-1, 3).astype(np.float64)
            vertices *= self.MESH_COORD_SCALE  # -> millimeters (LPS)
            # LPS -> RAS
            vertices[:, 0] *= -1.0
            vertices[:, 1] *= -1.0
            triangles = np.frombuffer(surfaceBytes, dtype="<i4").reshape(-1, 3)

            polyData = self._buildPolyData(vertices, triangles)
            modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")
            modelNode.SetName(f"object{idx + 1}")
            modelNode.SetAndObservePolyData(polyData)
            modelNode.CreateDefaultDisplayNodes()
            displayNode = modelNode.GetDisplayNode()
            displayNode.SetColor(*colorPalette[idx % len(colorPalette)])
            displayNode.SetVisibility2D(True)
            if attachMetadata:
                modelNode.SetAttribute("Mimics.guid", guid)
            modelNodes.append(modelNode)
            self.addLog(f"  Model {idx + 1}: {len(vertices)} points, {len(triangles)} triangles "
                        f"(guid {guid})")
        return modelNodes

    @staticmethod
    def _buildPolyData(vertices, triangles):
        points = vtk.vtkPoints()
        points.SetNumberOfPoints(len(vertices))
        for i, (x, y, z) in enumerate(vertices):
            points.SetPoint(i, x, y, z)

        cells = vtk.vtkCellArray()
        idList = vtk.vtkIdList()
        for tri in triangles:
            idList.Reset()
            idList.InsertNextId(int(tri[0]))
            idList.InsertNextId(int(tri[1]))
            idList.InsertNextId(int(tri[2]))
            cells.InsertNextCell(idList)

        polyData = vtk.vtkPolyData()
        polyData.SetPoints(points)
        polyData.SetPolys(cells)

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(polyData)
        normals.SplittingOff()
        normals.ConsistencyOn()
        normals.Update()
        return normals.GetOutput()

    @staticmethod
    def _lpsToRas(points):
        """Convert an (N,3) array of LPS/patient coordinates to Slicer RAS (in place)."""
        points[:, 0] *= -1.0
        points[:, 1] *= -1.0
        return points

    # ------------------------------------------------------------------ NURBS curves

    @staticmethod
    def _parseNurbs(data):
        """Parse a NURBS_{guid} blob into (controlPoints Nx3, knots, degree).

        Layout: N weighted control points (x, y, z, w) as float64, followed by the
        knot vector (float64). Weights are 1.0 in the observed files.
        """
        values = np.frombuffer(data[:len(data) // 8 * 8], dtype="<f8")
        ncp = 0
        while ncp * 4 + 3 < len(values) and abs(values[ncp * 4 + 3] - 1.0) < 1e-9:
            ncp += 1
        if ncp < 4:
            return None, None, None
        cps = values[:ncp * 4].reshape(-1, 4)[:, :3].astype(np.float64)
        knots = values[ncp * 4:].astype(np.float64)
        degree = len(knots) - ncp - 1
        if degree < 1 or len(knots) < 2 * (degree + 1):
            return None, None, None
        return cps, knots, degree

    @staticmethod
    def _evalBSpline(cps, knots, degree, nSamples):
        """Evaluate a B-spline curve over its valid domain using de Boor's algorithm.

        Returns an (nSamples, 3) array. For the periodic/unclamped knot vectors used by
        Mimics the evaluated curve is closed (first sample == last), so the caller drops
        the duplicated final sample when building a closed curve.
        """
        n = len(cps)
        u0, u1 = knots[degree], knots[n]
        us = np.linspace(u0, u1, nSamples, endpoint=True)
        out = np.empty((nSamples, 3))
        for si, u in enumerate(us):
            # find knot span k with knots[k] <= u < knots[k+1]
            if u >= knots[n]:
                k = n - 1
            else:
                k = degree
                while k < n and not (knots[k] <= u < knots[k + 1]):
                    k += 1
                k = min(max(k, degree), n - 1)
            d = [cps[j].copy() for j in range(k - degree, k + 1)]
            for r in range(1, degree + 1):
                for j in range(degree, r - 1, -1):
                    i = k - degree + j
                    denom = knots[i + degree - r + 1] - knots[i]
                    a = 0.0 if denom == 0 else (u - knots[i]) / denom
                    d[j] = (1.0 - a) * d[j - 1] + a * d[j]
            out[si] = d[degree]
        return out

    def importNurbsCurves(self, con, names, attachMetadata=True):
        """Create closed markups curve nodes from NURBS_{guid} blobs (e.g. valve annuli)."""
        cur = con.cursor()
        guids = sorted(n[len("NURBS_"):] for n in names if n.startswith("NURBS_"))
        curveNodes = []
        for idx, guid in enumerate(guids):
            cps, knots, degree = self._parseNurbs(self._readBlob(cur, names["NURBS_" + guid]))
            if cps is None:
                self.addLog(f"  Skipping NURBS {guid}: unsupported layout.")
                continue
            # Sample the true B-spline at the original control-point density (on the curve),
            # dropping the duplicated closing sample. A closed markups curve with spline
            # interpolation through these on-curve points reproduces the annulus faithfully.
            nSamples = len(cps) + 1
            curvePoints = self._evalBSpline(cps, knots, degree, nSamples)[:-1]
            self._lpsToRas(curvePoints)

            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsClosedCurveNode")
            node.SetName(f"curve{idx + 1}")
            slicer.util.updateMarkupsControlPointsFromArray(node, curvePoints)
            if attachMetadata:
                node.SetAttribute("Mimics.guid", guid)
                node.SetAttribute("Mimics.type", "NURBS")
            node.CreateDefaultDisplayNodes()
            node.GetDisplayNode().SetPointLabelsVisibility(False)
            curveNodes.append(node)
            self.addLog(f"  NURBS curve {idx + 1}: cubic, {len(cps)} control points (guid {guid})")
        return curveNodes

    # ------------------------------------------------------------------ point sets

    def importPointSets(self, con, names, attachMetadata=True):
        """Create markups point-list nodes from the float64 point-set blobs."""
        cur = con.cursor()
        pointBlobs = sorted(n for n in names if n.startswith("00007FF"))
        pointNodes = []
        for idx, name in enumerate(pointBlobs):
            data = self._readBlob(cur, names[name])
            npts = len(data) // 24
            if npts < 1:
                continue
            pts = np.frombuffer(data[:npts * 24], dtype="<f8").reshape(-1, 3).astype(np.float64)
            self._lpsToRas(pts)

            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
            node.SetName(f"points{idx + 1}")
            slicer.util.updateMarkupsControlPointsFromArray(node, pts)
            if attachMetadata:
                node.SetAttribute("Mimics.type", "PointSet")
            node.CreateDefaultDisplayNodes()
            node.GetDisplayNode().SetPointLabelsVisibility(False)
            pointNodes.append(node)
            self.addLog(f"  Point set {idx + 1}: {npts} points")
        return pointNodes

    # ------------------------------------------------------------------ organization / export

    def _exportFiles(self, exportDir, volumeNode, modelNodes, markupsNodes, metadata,
                     saveMetadata=True):
        # Files are written to a subfolder named after the project, so node names (and hence
        # file names) do not repeat the project name.
        os.makedirs(exportDir, exist_ok=True)
        if volumeNode:
            path = os.path.join(exportDir, "image.nrrd")
            slicer.util.saveNode(volumeNode, path)
            self.addLog(f"  Saved {path}")
        for modelNode in modelNodes:
            path = os.path.join(exportDir, f"{modelNode.GetName()}.ply")
            slicer.util.saveNode(modelNode, path)
            self.addLog(f"  Saved {path}")
        for markupsNode in markupsNodes:
            path = os.path.join(exportDir, f"{markupsNode.GetName()}.mrk.json")
            slicer.util.saveNode(markupsNode, path)
            self.addLog(f"  Saved {path}")
        # The metadata JSON may contain patient information, so it is only written on request.
        if saveMetadata:
            jsonPath = os.path.join(exportDir, "metadata.json")
            with open(jsonPath, "w") as f:
                json.dump(metadata, f, indent=2, default=str)
            self.addLog(f"  Saved {jsonPath}")


#
# ImportMimicsFileReader
#


class ImportMimicsFileReader:
    """File reader plugin so that .mcs projects can be opened directly (File > Add Data,
    drag-and-drop). The project is loaded into the scene only; no converted files are written.
    Registered automatically because the class is named <ModuleName>FileReader.
    """

    def __init__(self, parent):
        self.parent = parent

    def description(self):
        return _("Materialise Mimics project")

    def fileType(self):
        return "MimicsProject"

    def extensions(self):
        return [_("Materialise Mimics project") + " (*.mcs)"]

    def canLoadFileConfidence(self, filePath):
        # Must have the .mcs extension...
        if not self.parent.supportedNameFilters(filePath):
            return 0.0
        # ...and be a SQLite database (that is how Mimics stores .mcs projects).
        try:
            with open(filePath, "rb") as f:
                if f.read(16).startswith(b"SQLite format 3"):
                    return 0.9
        except OSError:
            pass
        return 0.0

    def load(self, properties):
        try:
            filePath = properties["fileName"]
            logic = ImportMimicsLogic()
            # Load into the scene only; never write converted files to a folder.
            volumeNode, modelNodes, markupsNodes = logic.importMcs(
                filePath, loadIntoScene=True, exportDir=None, exportDicom=False)
            # Surface any warnings/errors (e.g. non-uniform slice spacing) to the user.
            for severity, text in logic.messages:
                event = vtk.vtkCommand.ErrorEvent if severity == "error" else vtk.vtkCommand.WarningEvent
                self.parent.userMessages().AddMessage(event, text)
            loadedNodes = ([volumeNode] if volumeNode else []) + modelNodes + markupsNodes
            if not loadedNodes:
                raise ValueError("No data could be loaded from the Mimics project.")
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.parent.userMessages().AddMessage(
                vtk.vtkCommand.ErrorEvent, f"Failed to read Mimics project: {e}")
            return False

        self.parent.loadedNodes = [n.GetID() for n in loadedNodes]
        return True


#
# ImportMimicsTest
#


class ImportMimicsTest(ScriptedLoadableModuleTest):

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.delayDisplay("ImportMimics has no automated test (requires a sample .mcs file).")
        self.delayDisplay("Test passed")
