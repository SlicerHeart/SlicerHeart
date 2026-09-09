import json
import logging
import os
import pathlib
import re
import struct
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
    """Import Materialise Mimics (.mcs) and 3-matic (.mxp) project files into 3D Slicer."""

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Import Mimics")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Cardiac")]
        self.parent.dependencies = []
        self.parent.contributors = ["Andras Lasso (PerkLab, Queen's University)"]
        self.parent.helpText = _("""
This module imports Materialise <b>Mimics</b> (<b>.mcs</b>) and <b>3-matic</b> (<b>.mxp</b>)
project files into 3D Slicer. It can load a single project into the scene, convert projects to
standard files, or batch-convert a whole folder.
<p>See the <a href="https://github.com/SlicerHeart/SlicerHeart/blob/master/Docs/ImportMimics.md">module documentation</a>
for supported formats, usage, and limitations.</p>

<b>What is imported:</b>
<ul>
<li><b>Surface models</b> - segmentation surfaces / 3D objects.</li>
<li><b>Curves</b> - contours and wireframes (mainly from 3-matic projects).</li>
<li><b>Image volumes</b> - the CT/MR image(s) the project contains; a project may hold several
image blocks, and each is imported as its own volume (Mimics projects only; 3-matic projects
contain no image).</li>
<li><b>NURBS surfaces and point sets</b> - imported as markups (Mimics projects).</li>
<li><b>Metadata</b> - patient/study/series information, optionally saved to a JSON file.</li>
</ul>

<b>Limitations:</b> object names, colors, and analysis measurements are stored encrypted in the
project and cannot be recovered, so imported objects are named generically (object1, curve1, ...).
The module is experimental and not guaranteed to be correct for all projects.

<b>Patient information:</b> Mimics projects embed the original DICOM headers, so the optional
<i>DICOM files</i> and <i>Metadata</i> outputs may contain patient identifiers (name, ID, dates);
both are off by default. The image, model, and markups outputs contain only geometry.

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

        # The input may be a single .mcs / .mxp file or a folder (for batch conversion). No name
        # filter is set: a name filter would suppress the currentPathChanged signal for folders.
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
            ("loadWithDicom", self.ui.loadWithDicomCheckBox),
            ("hardenAcquisitionTransform", self.ui.hardenAcquisitionTransformCheckBox),
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
        # The acquisition transform only exists when the image is loaded with the DICOM module.
        self.ui.hardenAcquisitionTransformCheckBox.enabled = (
            self.ui.importImageCheckBox.checked and self.ui.loadWithDicomCheckBox.checked)

        inputPath = self.ui.inputPathLineEdit.currentPath
        hasInput = bool(inputPath)
        isFolder = hasInput and os.path.isdir(inputPath)
        isProjectFile = (hasInput and os.path.isfile(inputPath)
                         and inputPath.lower().endswith((".mcs", ".mxp")))
        saveToFiles = not self.ui.exportNoSaveRadioButton.checked

        # A folder input is a batch conversion, so loading into the scene does not apply:
        # disable the option and show an explanatory message. No message in any other case.
        label = self.ui.inputWarningLabel
        if isFolder:
            self.ui.loadIntoSceneCheckBox.enabled = False
            label.text = _("Folder selected - batch conversion")
            label.toolTip = _("A folder is selected, so every Mimics (.mcs) and 3-matic (.mxp) "
                              "project file it contains will be converted to files. Loading into "
                              "the scene does not apply to batch conversion.")
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
        self.ui.applyButton.enabled = isProjectFile or isFolder

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
        with slicer.util.tryWithErrorDisplay(_("Failed to import project."), waitCursor=True):
            try:
                self.clearLog()
                self.logic.messages = []
                inputPath = self.ui.inputPathLineEdit.currentPath
                if not inputPath:
                    raise ValueError("Please specify an input .mcs / .mxp file or folder")
                isFolder = os.path.isdir(inputPath)

                self.loadingInProgress = True
                self.ui.progressBar.show()
                self.ui.applyButton.enabled = False
                self.ui.inputsCollapsibleButton.enabled = False

                loadImage = self.ui.importImageCheckBox.checked
                useDicomReader = self.ui.loadWithDicomCheckBox.checked
                hardenAcquisitionTransform = self.ui.hardenAcquisitionTransformCheckBox.checked
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

                def exportDirFor(projectPath, perProjectSubfolder):
                    if not saveToFiles:
                        return None
                    projectName = os.path.splitext(os.path.basename(projectPath))[0]
                    if useCustom:
                        return os.path.join(customBase, projectName) if perProjectSubfolder else customBase
                    # Save next to the project file, inside a subfolder named after the project.
                    return os.path.join(os.path.dirname(os.path.abspath(projectPath)), projectName)

                commonArgs = dict(loadImage=loadImage, loadModels=loadModels, loadNurbs=loadNurbs,
                                  loadPoints=loadPoints, exportDicom=exportDicom,
                                  saveMetadata=saveMetadata, useDicomReader=useDicomReader,
                                  hardenAcquisitionTransform=hardenAcquisitionTransform)
                # Neither loading nor saving: only report information about the selection.
                inspectMode = not loadIntoScene and not saveToFiles

                if isFolder:
                    import glob
                    projectFiles = sorted(glob.glob(os.path.join(inputPath, "*.mcs"))
                                          + glob.glob(os.path.join(inputPath, "*.mxp")))
                    if not projectFiles:
                        raise ValueError("No .mcs or .mxp files found in the selected folder")
                    verb = "Inspecting" if inspectMode else "Batch converting"
                    self.addLog(f"{verb} {len(projectFiles)} project(s)...")
                    nOk = 0
                    for i, projectPath in enumerate(projectFiles):
                        self.addLog(f"[{i + 1}/{len(projectFiles)}] {os.path.basename(projectPath)}")
                        try:
                            if inspectMode:
                                self.logic.inspect(projectPath)
                            else:
                                self.logic.importProject(projectPath, loadIntoScene=False,
                                                         exportDir=exportDirFor(projectPath, True), **commonArgs)
                            nOk += 1
                        except Exception as e:  # noqa: BLE001 - keep going on the rest of the batch
                            self.addLog(f"  ERROR: {e}")
                        self.updateProgress(int((i + 1) / len(projectFiles) * 100))
                    self.addLog(f"Finished: {nOk}/{len(projectFiles)} project(s).")
                elif inspectMode:
                    self.logic.inspect(inputPath)
                else:
                    self.logic.importProject(inputPath, loadIntoScene=loadIntoScene,
                                             exportDir=exportDirFor(inputPath, False), **commonArgs)

                # Show a pop-up at the end if any project reported a geometry problem (slices
                # that are not parallel, non-uniform slice spacing, ...); all messages are in
                # the log above as well.
                errors = [text for severity, text in self.logic.messages if severity == "error"]
                warnings = [text for severity, text in self.logic.messages if severity == "warning"]
                if errors:
                    slicer.util.errorDisplay("\n\n".join(errors + warnings),
                                             windowTitle=_("Import Mimics"))
                elif warnings:
                    slicer.util.warningDisplay("\n\n".join(warnings),
                                               windowTitle=_("Import Mimics"))

            finally:
                self.loadingInProgress = False
                self.ui.inputsCollapsibleButton.enabled = True
                self.ui.progressBar.hide()
                self._checkCanApply()


#
# Blob stores
#


class _SqliteBlobStore:
    """Access to the named blobs of a Materialise Mimics `.mcs` project.

    A `.mcs` file is a SQLite database with two tables: `blobs` (blob_id, blob_name,
    number_of_parts) and `blobs_parts` (per-part data, optionally zlib-compressed). A blob is the
    concatenation of its parts in order.
    """

    def __init__(self, filename):
        import sqlite3
        # Open read-only so the source project file is never modified.
        try:
            self._con = sqlite3.connect(f"{pathlib.Path(filename).as_uri()}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            self._con = sqlite3.connect(filename)
        tables = [r[0] for r in self._con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        if "blobs" not in tables:
            self._con.close()
            raise ValueError("Not a Mimics project file (no 'blobs' table).")
        cur = self._con.cursor()
        cur.execute("SELECT blob_name, blob_id FROM blobs ORDER BY blob_id")
        blobs = cur.fetchall()
        self._ids = dict(blobs)
        # Blob names in the order they were written. Mimics writes each image block as a header
        # blob immediately followed by the block's per-slice pixel blobs, and the blob names
        # themselves carry no ordering, so this order is what groups a block together.
        self.orderedNames = [name for name, _bid in blobs]
        self.names = set(self._ids.keys())

    def read(self, name):
        """Return the decompressed bytes of the named blob."""
        cur = self._con.cursor()
        cur.execute(
            "SELECT is_blob_compressed, blob_part_data FROM blobs_parts "
            "WHERE blob_id=? ORDER BY blob_part_number", (self._ids[name],))
        parts = []
        for compressed, data in cur.fetchall():
            if compressed:
                data = zlib.decompress(data)
            parts.append(data)
        return b"".join(parts)

    def peek(self, name, size):
        """Return (at most) the first `size` decompressed bytes of the named blob.

        Only the first part is inspected, which is enough to identify a blob from its magic
        without paying for decompressing hundreds of megabytes of pixel data.
        """
        cur = self._con.cursor()
        cur.execute(
            "SELECT is_blob_compressed, blob_part_data FROM blobs_parts "
            "WHERE blob_id=? ORDER BY blob_part_number LIMIT 1", (self._ids[name],))
        row = cur.fetchone()
        if row is None:
            return b""
        compressed, data = row
        if not compressed:
            return bytes(data[:size])
        return zlib.decompressobj().decompress(bytes(data), size)

    def close(self):
        self._con.close()


class _MxpBlobStore:
    """Access to the named blobs of a Materialise 3-matic `.mxp` project.

    A `.mxp` file is a ZIP archive in which the usual 'PK' signatures are replaced with 'MT'
    (Materialise); each member is stored with a standard 30-byte local file header and raw
    DEFLATE (or 'store') compression, and members are read by seeking to the recorded data
    offset.

    The members are taken from the trailing central directory. 3-matic writes its members with
    a data descriptor (general purpose flag 0x08), which leaves the sizes in the local file
    headers set to zero, so the local headers alone cannot be walked. Files that have no usable
    central directory fall back to walking the local headers.
    """

    LOCAL_HEADER_SIGNATURE = b"MT\x03\x04"
    CENTRAL_HEADER_SIGNATURE = b"MT\x01\x02"
    END_RECORD_SIGNATURE = b"MT\x05\x06"

    # Largest possible end-of-central-directory record: the fixed part plus its comment.
    _MAX_END_RECORD_SIZE = 22 + 0xFFFF

    # A size of 0xFFFFFFFF means the real value is in a ZIP64 extra field, which is not read.
    _ZIP64_SIZE = 0xFFFFFFFF

    def __init__(self, filename):
        self._filename = filename
        # name -> (compression_method, data_offset, compressed_size)
        with open(filename, "rb") as f:
            self._members = self._readCentralDirectory(f) or self._walkLocalHeaders(f)
        if not self._members:
            raise ValueError("Not a 3-matic project file (no 'MT' archive entries).")
        self.orderedNames = list(self._members.keys())
        self.names = set(self._members.keys())

    @classmethod
    def _readCentralDirectory(cls, f):
        """Return the members listed in the archive's central directory, or None if unreadable."""
        f.seek(0, os.SEEK_END)
        fileSize = f.tell()
        searchLength = min(fileSize, cls._MAX_END_RECORD_SIZE)
        f.seek(fileSize - searchLength)
        tail = f.read(searchLength)
        end = tail.rfind(cls.END_RECORD_SIGNATURE)
        if end < 0 or len(tail) - end < 22:
            return None
        (_disk, _startDisk, _entriesOnDisk, entryCount,
         _size, directoryOffset, _commentLen) = struct.unpack("<HHHHIIH", tail[end + 4:end + 22])

        entries = []
        f.seek(directoryOffset)
        for _ in range(entryCount):
            header = f.read(46)
            if len(header) < 46 or header[:4] != cls.CENTRAL_HEADER_SIGNATURE:
                return None
            (_madeBy, _needed, _flags, method, _mtime, _mdate, _crc, csize, _usize,
             nameLen, extraLen, commentLen, _disk, _internal, _external,
             localHeaderOffset) = struct.unpack("<HHHHHHIIIHHHHHII", header[4:46])
            name = f.read(nameLen).decode("utf-8", "replace")
            f.seek(extraLen + commentLen, 1)
            if csize == cls._ZIP64_SIZE or localHeaderOffset == cls._ZIP64_SIZE:
                return None
            entries.append((name, method, csize, localHeaderOffset))

        # The name and extra field of a local header may differ in length from the central
        # directory entry, so where the data starts can only be read from the local header.
        members = {}
        for name, method, csize, localHeaderOffset in entries:
            f.seek(localHeaderOffset)
            header = f.read(30)
            if len(header) < 30 or header[:4] != cls.LOCAL_HEADER_SIGNATURE:
                return None
            nameLen, extraLen = struct.unpack("<HH", header[26:30])
            members[name] = (method, localHeaderOffset + 30 + nameLen + extraLen, csize)
        return members

    @classmethod
    def _walkLocalHeaders(cls, f):
        """Return the members found by walking the local file headers from the start of the file.

        Only usable for archives that record the compressed size in the local header.
        """
        members = {}
        f.seek(0)
        while True:
            header = f.read(30)
            if len(header) < 30 or header[:4] != cls.LOCAL_HEADER_SIGNATURE:
                break
            (_ver, _flags, method, _mtime, _mdate, _crc, csize, _usize,
             nameLen, extraLen) = struct.unpack("<HHHHHIIIHH", header[4:30])
            name = f.read(nameLen).decode("utf-8", "replace")
            f.seek(extraLen, 1)
            dataOffset = f.tell()
            f.seek(csize, 1)
            members[name] = (method, dataOffset, csize)
        return members

    def read(self, name):
        """Return the decompressed bytes of the named member."""
        method, dataOffset, csize = self._members[name]
        with open(self._filename, "rb") as f:
            f.seek(dataOffset)
            data = f.read(csize)
        if method == 8:  # DEFLATE (raw, no zlib header)
            return zlib.decompress(data, -15)
        if method == 0:  # stored uncompressed
            return data
        raise ValueError(f"Unsupported compression method {method} for member '{name}'.")

    def peek(self, name, size):
        """Return (at most) the first `size` decompressed bytes of the named member."""
        method, dataOffset, csize = self._members[name]
        with open(self._filename, "rb") as f:
            f.seek(dataOffset)
            # Read more compressed bytes than requested: even an incompressible member needs
            # only a little more than `size` bytes to yield `size` bytes of output.
            data = f.read(min(csize, max(4 * size, 4096)))
        if method == 8:
            return zlib.decompressobj(-15).decompress(data, size)
        if method == 0:
            return data[:size]
        return b""

    def close(self):
        pass


#
# ImportMimicsLogic
#


class ImportMimicsLogic(ScriptedLoadableModuleLogic):
    """Reads Materialise Mimics (.mcs) and 3-matic (.mxp) project files.

    Both formats are containers of named, individually zlib/deflate-compressed binary blobs; only
    the container differs (see the blob-store classes below), while the blob contents are shared:
      - An image block is a header blob holding the original DICOM files concatenated (128-byte
        preamble + 'DICM' + dataset), one per slice but with the pixel data removed, followed by
        one pixel-data blob per slice, each prefixed with a 4-byte 'MMFD' magic. Older projects
        store one header blob per slice instead. A project may contain several image blocks,
        and the headers of a block are stored twice. (Mimics .mcs only.)
      - In a Mimics project the blobs are named `blob_N` and the numbers give the slice order;
        in a project exported for Mimics Viewer every blob is named with a GUID and only the
        order of the blobs groups a block together. See `_imageBlocks`.
      - Pixel data is stored either as Rows*Columns*2 bytes of little-endian 16-bit pixels, or
        row-compressed (see `_decodeCompressedPixels`).
      - `Stl{guid}_vertices` / `Stl(N)_vertices` store vertices as int32 fixed-point coordinates
        (millimeters * 10000, in LPS/patient coordinate system).
      - `Stl..._surfaces` store triangle vertex indices as int32 triplets (surface meshes).
      - `Stl..._curves` store a polyline as an ordered list of int32 vertex indices into the
        object's own `_vertices` (contours/wireframes; 3-matic .mxp).
      - `NURBS_{guid}` store closed B-spline curves (valve annuli; .mcs only).
      - `header.xml` holds the project structure but is stored encrypted, so it is not decoded.
    """

    # Materialise stores mesh vertex coordinates as integers in units of 0.1 micrometer (mm * 1e4).
    MESH_COORD_SCALE = 1.0e-4

    # Matches both id styles used for mesh/curve objects: `Stl{guid}_part` and `Stl(N)_part`.
    # Group 1 is the id including its delimiters ('{guid}' or '(N)'); group 2 is the part name.
    _STL_RE = re.compile(r"^Stl(\{[0-9a-fA-F-]+\}|\(\d+\))_(vertices|surfaces|curves)$")

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
    def openStore(filename):
        """Open a Mimics/3-matic project and return a blob store, chosen from the file's magic.

        A `.mcs` file is a SQLite database; a `.mxp` file is a ZIP-like archive with 'MT'
        signatures. The extension is used only as a fallback when the magic is inconclusive.
        """
        if not os.path.isfile(filename):
            raise FileNotFoundError(filename)
        with open(filename, "rb") as f:
            magic = f.read(16)
        if magic.startswith(b"SQLite format 3"):
            return _SqliteBlobStore(filename)
        if magic.startswith(_MxpBlobStore.LOCAL_HEADER_SIGNATURE):
            return _MxpBlobStore(filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".mcs":
            return _SqliteBlobStore(filename)
        if ext == ".mxp":
            return _MxpBlobStore(filename)
        raise ValueError("Unrecognized file (not a Mimics .mcs or 3-matic .mxp project).")

    @classmethod
    def _stlObjects(cls, names):
        """Return {objectId: set(parts)} for every Stl mesh/curve object in the blob names.

        objectId includes its delimiters, e.g. '{6543...}' or '(18)'; parts is a subset of
        {'vertices', 'surfaces', 'curves'}.
        """
        objects = {}
        for name in names:
            match = cls._STL_RE.match(name)
            if match:
                objects.setdefault(match.group(1), set()).add(match.group(2))
        return objects

    @staticmethod
    def _stlSortKey(objectId):
        """Order integer ids '(N)' numerically and before guid ids '{...}' (ordered lexically)."""
        if objectId.startswith("("):
            return (0, int(objectId[1:-1]), "")
        return (1, 0, objectId)

    @classmethod
    def _inventory(cls, names):
        """Summarize the project contents from blob names alone (no decompression)."""
        objects = cls._stlObjects(names)
        surfaces = sorted((i for i, p in objects.items() if "surfaces" in p), key=cls._stlSortKey)
        curves = sorted((i for i, p in objects.items() if "curves" in p), key=cls._stlSortKey)
        pointClouds = sorted((i for i, p in objects.items() if p == {"vertices"}), key=cls._stlSortKey)
        nurbs = sorted(n[len("NURBS_"):] for n in names if n.startswith("NURBS_"))
        pointSets = [n for n in names if n.startswith("00007FF")]
        previews = [n for n in names if n.startswith("ImageBlockPngPreview")]
        return {
            "surfaceModelCount": len(surfaces),
            "surfaceModelIds": surfaces,
            "curveCount": len(curves),
            "curveIds": curves,
            "pointCloudCount": len(pointClouds),
            "pointCloudIds": pointClouds,
            "nurbsSurfaceCount": len(nurbs),
            "nurbsSurfaceGuids": nurbs,
            "pointSetCount": len(pointSets),
            "imagePreviewCount": len(previews),
        }

    # ------------------------------------------------------------------ main entry

    def importProject(self, filename, loadImage=True, loadModels=True, loadNurbs=True,
                      loadPoints=True, loadIntoScene=True, exportDir=None, exportDicom=False,
                      saveMetadata=True, useDicomReader=False, hardenAcquisitionTransform=True):
        """Import a Mimics (.mcs) or 3-matic (.mxp) project. Returns
        (volumeNodes, modelNodes, curveNodes, markupsNodes).

        With `useDicomReader` the image volumes are loaded by Slicer's DICOM scalar volume
        plugin from the reconstructed DICOM files (see `_loadImageWithDicomPlugin`). A volume
        whose slice positions are irregular gets an acquisition transform, which is applied to
        the image (`hardenAcquisitionTransform`) or kept as its parent transform node."""
        isMxp = os.path.splitext(filename)[1].lower() == ".mxp"
        self.addLog(f"Importing {'3-matic' if isMxp else 'Mimics'} project: {filename}")
        self.updateProgress(1)

        store = self.openStore(filename)
        try:
            names = store.names
            projectName = os.path.splitext(os.path.basename(filename))[0]
            inventory = self._inventory(names)
            metadata = {
                "sourceFile": os.path.normpath(os.path.abspath(filename)),
                "projectName": projectName,
                "format": ("Materialise 3-matic project (.mxp)" if isMxp
                           else "Materialise Mimics project (.mcs)"),
                "blobCount": len(names),
                "contents": inventory,
                "notes": [
                    "The project header (object names, colors, analysis data) is stored "
                    "encrypted by Materialise and cannot be decoded; objects are named generically.",
                ],
            }

            volumeNodes = []
            if loadImage:
                blocks = self._imageBlocks(store)
                images = self.importImages(store, blocks, useDicomReader, hardenAcquisitionTransform)
                volumeNodes = [volumeNode for volumeNode, _meta in images if volumeNode is not None]
                imageMetas = [meta for _volumeNode, meta in images]
                if imageMetas:
                    metadata["images"] = imageMetas
                    # The image of a single-block project stays available under its old key.
                    metadata["image"] = imageMetas[0]
                    messageCount = len(self.messages)
                    for meta in imageMetas:
                        self._collectGeometryMessages(meta, f"{projectName} ({meta.get('name', 'image')})")
                    if len(self.messages) > messageCount and not useDicomReader:
                        self.messages.append(("warning", (
                            f"{projectName}: Enable 'Load image using DICOM module' in the Import "
                            "Mimics module to load the image with Slicer's DICOM reader, which "
                            "places every slice at its true position with an acquisition "
                            "transform when the slice spacing or the in-plane position is "
                            "irregular.")))
                if len(volumeNodes) < len(blocks):
                    metadata["notes"].append(
                        f"{len(blocks) - len(volumeNodes)} of {len(blocks)} image block(s) could "
                        "not be reconstructed (unsupported pixel storage or slices of different "
                        "sizes).")
                self.updateProgress(50)

            modelNodes = []
            if loadModels:
                modelNodes = self.importModels(store, attachMetadata=saveMetadata)
                metadata["surfaceModels"] = [{
                    "name": m.GetName(),
                    "id": m.GetAttribute("Mimics.id"),
                    "points": m.GetPolyData().GetNumberOfPoints(),
                    "triangles": m.GetPolyData().GetNumberOfCells(),
                } for m in modelNodes]
                self.updateProgress(70)

            curveModelNodes = []
            if loadModels and inventory["curveCount"]:
                curveModelNodes = self.importCurves(store, attachMetadata=saveMetadata)
                metadata["curves"] = [{
                    "name": c.GetName(), "id": c.GetAttribute("Mimics.id"),
                    "points": c.GetPolyData().GetNumberOfPoints(),
                } for c in curveModelNodes]
                self.updateProgress(78)

            nurbsNodes = []
            if loadNurbs and inventory["nurbsSurfaceCount"]:
                nurbsNodes = self.importNurbsCurves(store, attachMetadata=saveMetadata)
                metadata["nurbsCurves"] = [{
                    "name": c.GetName(), "guid": c.GetAttribute("Mimics.guid"),
                } for c in nurbsNodes]
                self.updateProgress(84)

            pointNodes = []
            if loadPoints and inventory["pointSetCount"]:
                pointNodes = self.importPointSets(store, attachMetadata=saveMetadata)
                metadata["pointSets"] = [{
                    "name": p.GetName(), "points": p.GetNumberOfControlPoints(),
                } for p in pointNodes]
                self.updateProgress(88)

            markupsNodes = nurbsNodes + pointNodes

            if exportDir:
                self._exportFiles(exportDir, volumeNodes, modelNodes, curveModelNodes,
                                  markupsNodes, metadata, saveMetadata)
                if exportDicom:
                    self.exportDicomFiles(store, exportDir)
                self.updateProgress(95)

            if loadIntoScene:
                # Nodes are left at the scene top level: no patient/study subject-hierarchy branch
                # is created and no patient information is added - only the geometry is used.
                if volumeNodes:
                    slicer.util.setSliceViewerLayers(background=volumeNodes[0], fit=True)
                self.addLog(
                    f"Done. Loaded {len(volumeNodes)} volume(s), {len(modelNodes)} model(s), "
                    f"{len(curveModelNodes)} curve(s), {len(nurbsNodes)} NURBS, "
                    f"{len(pointNodes)} point set(s) into the scene.")
            else:
                # Not loading into the scene: remove the nodes that were created for export
                # (including the acquisition transforms of the volumes).
                counts = (len(volumeNodes), len(modelNodes), len(curveModelNodes), len(markupsNodes))
                transformNodes = [v.GetParentTransformNode() for v in volumeNodes]
                for node in volumeNodes + modelNodes + curveModelNodes + markupsNodes + transformNodes:
                    if node is not None:
                        slicer.mrmlScene.RemoveNode(node)
                volumeNodes, modelNodes, curveModelNodes, markupsNodes = [], [], [], []
                self.addLog(
                    f"Done. Exported {counts[0]} volume(s), {counts[1]} model(s), "
                    f"{counts[2]} curve(s), {counts[3]} markup(s) to files.")
            self.updateProgress(100)
            return volumeNodes, modelNodes, curveModelNodes, markupsNodes
        finally:
            store.close()

    # Backwards-compatible alias (the module historically exposed importMcs).
    importMcs = importProject

    def _collectGeometryMessages(self, imageMeta, prefix):
        """Add the geometry errors/warnings recorded in an image's metadata to `self.messages`."""
        for message in imageMeta.get("geometryErrors", []):
            self.messages.append(("error", f"{prefix}: {message}"))
        for message in imageMeta.get("geometryWarnings", []):
            self.messages.append(("warning", f"{prefix}: {message}"))

    def inspect(self, filename):
        """Log a summary of a project without creating any nodes or writing files."""
        store = self.openStore(filename)
        try:
            names = store.names
            inventory = self._inventory(names)
            projectName = os.path.splitext(os.path.basename(filename))[0]
            self.addLog(f"  Project: {projectName}  ({len(names)} blobs)")
            blocks = self._imageBlocks(store)
            images = [self._imageInfo(store, block) for block in blocks]
            images = [image for image in images if image]
            for image in images:
                self.addLog(f"  Image: {image['modality']} "
                            f"{image['columns']}x{image['rows']}x{image['sliceCount']}"
                            + (f", spacing {image['pixelSpacing']} mm" if image['pixelSpacing'] else "")
                            + (f" [{image['seriesDescription']}]" if image['seriesDescription'] else ""))
                patientBits = " ".join(x for x in (image['patientName'], image['studyDescription'],
                                                   image['studyDate']) if x)
                if patientBits:
                    self.addLog(f"    {patientBits}")
                # Record the geometry warnings/errors found during the header analysis.
                self._collectGeometryMessages(image, projectName)
            if not images:
                self.addLog("  Image: present but could not be read" if blocks else "  Image: none")
            self.addLog(f"  Surface models: {inventory['surfaceModelCount']}, "
                        f"curves: {inventory['curveCount']}, "
                        f"point clouds: {inventory['pointCloudCount']}, "
                        f"NURBS curves: {inventory['nurbsSurfaceCount']}, "
                        f"point sets: {inventory['pointSetCount']}")
            return inventory
        finally:
            store.close()

    def _imageInfo(self, store, block):
        """Return a summary of one image block from its DICOM headers, including a slice-spacing
        uniformity check. Only headers are parsed - no pixel data is read."""
        try:
            import pydicom
        except ImportError:
            return None
        import io
        blob0 = b"".join(store.read(name) for name in block["header"])
        bounds = self._dicomFileBounds(blob0)
        if not bounds:
            return None
        offsets = bounds[:-1]
        ds = pydicom.dcmread(io.BytesIO(blob0[bounds[0]:bounds[1]]), force=True)
        geometry = self._sliceGeometry(ds)
        info = {
            "modality": str(ds.get("Modality", "")),
            "rows": int(ds.get("Rows", 0)),
            "columns": int(ds.get("Columns", 0)),
            "sliceCount": len(offsets),
            "pixelSpacing": geometry["pixelSpacing"] if geometry else [],
            "seriesDescription": str(ds.get("SeriesDescription", "")),
            "patientName": str(ds.get("PatientName", "")),
            "studyDescription": str(ds.get("StudyDescription", "")),
            "studyDate": str(ds.get("StudyDate", "")),
        }
        # Geometry check (parallel slices, uniform spacing, ...) from the per-slice headers.
        try:
            if geometry:
                geometries, shapes = [], []
                for k in range(len(offsets)):
                    dk = ds if k == 0 else pydicom.dcmread(
                        io.BytesIO(blob0[bounds[k]:bounds[k + 1]]), force=True,
                        specific_tags=["ImagePositionPatient", "ImageOrientationPatient",
                                       "PixelSpacing", "Rows", "Columns",
                                       "SharedFunctionalGroupsSequence",
                                       "PerFrameFunctionalGroupsSequence"])
                    geometries.append(self._sliceGeometry(dk))
                    shapes.append((int(dk.get("Rows", 0)), int(dk.get("Columns", 0))))
                order = self._sliceOrder(geometries)
                self._checkSliceGeometry([geometries[k] for k in order],
                                         [shapes[k] for k in order], info)
        except Exception:  # noqa: BLE001 - the geometry check is best-effort during inspection
            pass
        return info

    # ------------------------------------------------------------------ image

    # Magic that prefixes every per-slice pixel-data blob.
    PIXEL_DATA_MAGIC = b"MMFD"

    # `blob_0`, `blob_1`, ... - the blob naming of a plain Mimics project.
    _NUMBERED_BLOB_RE = re.compile(r"^blob_(\d+)$")

    # How far into a blob to look for the 'DICM' marker of its first DICOM file.
    _HEADER_SEARCH_LENGTH = 256

    # How many bytes after the 'DICM' marker identify a DICOM file (the file meta information
    # with the media storage SOP instance UID fits in there).
    _DICOM_FILE_KEY_LENGTH = 512

    @classmethod
    def _blobNumber(cls, name):
        """Return N for a blob named `blob_N`, None for any other name."""
        match = cls._NUMBERED_BLOB_RE.match(name)
        return int(match.group(1)) if match else None

    @staticmethod
    def _dicomFileBounds(blob):
        """Return the offsets that split a blob of concatenated DICOM files into single files.

        Each file starts 128 bytes (the preamble) before its 'DICM' marker. The returned list
        holds the start offset of every file plus the end of the blob, so file `k` occupies
        `blob[bounds[k]:bounds[k + 1]]`; it is empty if the blob holds no DICOM files.
        """
        offsets = []
        start = 0
        while True:
            i = blob.find(b"DICM", start)
            if i < 0:
                break
            if i >= 128:
                offsets.append(i - 128)
            start = i + 1
        return offsets + [len(blob)] if offsets else []

    @classmethod
    def _dicomFileKeys(cls, blob, bounds):
        """Return a content key for each DICOM file in a header blob, to recognize the same file
        stored again in another blob. The key is the file meta information right after the
        'DICM' marker (it carries the SOP instance UID), so it does not depend on whatever
        Mimics puts between the files."""
        return [blob[start + 128:start + 128 + cls._DICOM_FILE_KEY_LENGTH]
                for start in bounds[:-1]]

    def _imageBlocks(self, store):
        """Return the project's image blocks, in the order they are stored.

        Each block is `{"header": [name, ...], "pixels": [name, ...]}`: the blob(s) holding the
        DICOM headers of the block's slices (one blob with all the headers concatenated, or -
        in projects written by older Mimics versions - one single-header blob per slice), and
        one pixel-data blob per slice, in slice order.

        How the blobs are grouped was worked out from a few hundred projects:

        - A header blob starts a block and the pixel blobs that come after it belong to it. A
          run of consecutive single-header blobs is one header set (the per-slice layout).
        - Mimics stores the headers of a block twice: in the order the DICOM files were
          imported and again later on. The second copy holds the same files, so it is
          recognized by content and folded into its block instead of becoming a block of its
          own (it may be followed by a downsampled preview slice, which is not a slice).
        - In a plain Mimics project every blob is named `blob_N`, and the numbers give the
          order: the pixel blobs of a block are numbered consecutively after its header, in
          slice order. The order of the blobs in the file is not reliable, as Mimics rewrites
          individual blobs on a later save (keeping their names), which moves them to the end.
          A block's pixel blobs may also be numbered in several runs, when other blobs got
          the numbers in between. So a numbered project is walked in number order: a pixel
          blob belongs to the most recent block that does not yet have a blob for every one
          of its headers. Projects exported for Mimics Viewer name their blobs with GUIDs and
          are walked in the order the blobs are stored.

        Every header blob is decompressed (to count its files and to recognize copies), but
        only the first bytes of the pixel blobs, so this costs a second or two even for
        projects that hold hundreds of megabytes of pixel data.
        """
        def isPixelData(name):
            return store.peek(name, 4) == self.PIXEL_DATA_MAGIC

        def isHeader(name):
            # The first DICOM file of the blob starts 128 bytes (the preamble) before its 'DICM'
            # marker; a few bytes of Mimics' own may precede that preamble.
            return store.peek(name, self._HEADER_SEARCH_LENGTH).find(b"DICM", 128) >= 0

        # Header sets and pixel blobs, in the order they are stored.
        headerSets = []  # {"names", "keys", "pixels", "position"}
        pixelNames = []  # (position, name)
        lastWasSingleHeader = False
        for position, name in enumerate(store.orderedNames):
            # Pixel data is recognized first: its magic is unambiguous, while raw pixel bytes
            # could in principle contain a 'DICM' sequence of their own.
            if isPixelData(name):
                pixelNames.append((position, name))
                lastWasSingleHeader = False
            elif isHeader(name):
                blob = store.read(name)
                keys = self._dicomFileKeys(blob, self._dicomFileBounds(blob))
                # A single-header blob continues the current per-slice header set - unless it
                # holds a header that set already has, which means a second copy starts here.
                if len(keys) == 1 and lastWasSingleHeader and keys[0] not in headerSets[-1]["keys"]:
                    headerSets[-1]["names"].append(name)
                    headerSets[-1]["keys"].extend(keys)
                else:
                    headerSets.append({"names": [name], "keys": keys, "pixels": [],
                                       "position": position})
                lastWasSingleHeader = len(keys) == 1
        if not headerSets:
            return []

        # Walk header sets and pixel blobs in number order (plain project) or storage order
        # (Mimics Viewer export) and hand every pixel blob to a header set.
        allNames = [name for headerSet in headerSets for name in headerSet["names"]]
        allNames += [name for _position, name in pixelNames]
        numbered = all(self._blobNumber(name) is not None for name in allNames)

        def sortKey(position, name):
            return self._blobNumber(name) if numbered else position

        pixelKeys = {name: sortKey(position, name) for position, name in pixelNames}
        items = [(min(sortKey(headerSet["position"], name) for name in headerSet["names"]),
                  0, headerSet) for headerSet in headerSets]
        items += [(pixelKeys[name], 1, name) for _position, name in pixelNames]
        opened = []
        for _key, kind, item in sorted(items, key=lambda item: item[:2]):
            if kind == 0:
                opened.append(item)
            elif opened:
                target = next((headerSet for headerSet in reversed(opened)
                               if len(headerSet["pixels"]) < len(headerSet["keys"])), opened[-1])
                target["pixels"].append(item)

        # Fold the copies of a header set into one block, which gets the pixel blobs of all its
        # copies (a copy may have picked up a slice whose number got past the block's own
        # header copy, or a preview slice, which comes after the real ones and is ignored).
        blocks = {}
        for headerSet in headerSets:
            block = blocks.setdefault(frozenset(headerSet["keys"]), {
                "header": headerSet["names"], "pixels": [], "position": headerSet["position"]})
            block["pixels"] += headerSet["pixels"]
        return [{"header": block["header"],
                 "pixels": sorted(block["pixels"], key=lambda name: pixelKeys[name])}
                for block in sorted(blocks.values(), key=lambda block: block["position"])
                if block["pixels"]]

    @staticmethod
    def _sliceGeometry(ds):
        """Return the geometry of a single-frame DICOM dataset as a dict with
        `imageOrientationPatient`, `imagePositionPatient`, `pixelSpacing` and `sliceThickness`,
        or None if the dataset has no image geometry. Enhanced (multi-frame) objects keep the
        geometry in their functional groups; the first frame is used for those."""
        def functionalGroup(sequenceName):
            for groups in ("SharedFunctionalGroupsSequence", "PerFrameFunctionalGroupsSequence"):
                if groups in ds and len(ds[groups].value) and sequenceName in ds[groups].value[0]:
                    return ds[groups].value[0][sequenceName].value[0]
            return None

        def read(tagName, sequenceName):
            if tagName in ds:
                return ds[tagName].value
            group = functionalGroup(sequenceName)
            return group[tagName].value if group is not None and tagName in group else None

        iop = read("ImageOrientationPatient", "PlaneOrientationSequence")
        ipp = read("ImagePositionPatient", "PlanePositionSequence")
        if iop is None or ipp is None or len(iop) != 6 or len(ipp) != 3:
            return None
        pixelSpacing = read("PixelSpacing", "PixelMeasuresSequence")
        sliceThickness = read("SliceThickness", "PixelMeasuresSequence")
        return {
            "imageOrientationPatient": [float(x) for x in iop],
            "imagePositionPatient": [float(x) for x in ipp],
            "pixelSpacing": [float(x) for x in pixelSpacing] if pixelSpacing else [1.0, 1.0],
            "sliceThickness": float(sliceThickness or 0),
        }

    @staticmethod
    def _recoverSliceOrder(stack, window=48, maxPasses=60):
        """Return the order (an index array into `stack`) that makes the slices of a stack
        most similar to their neighbours, letting every slice move at most `window` positions
        (and at most half the stack).

        Projects exported for Mimics Viewer name their pixel blobs with GUIDs and store them
        in the order they were written, which is not the slice order: the slices appear to be
        compressed by a pool of threads and written as they complete, so every slice ends up
        near its true position, displaced by up to about the number of threads (32 seen), and
        the record of the true order is in the encrypted project header. The order is
        therefore recovered from the images: the sum of the mean absolute differences between
        consecutive slices (on a downsampled copy) is minimized over the orders that keep every
        slice within `window` of its stored position. A slice that is out of place by two or
        more positions shows as a jump in that difference well above the level between true
        neighbours, so the search moves single slices to where they fit best, reverses runs,
        and at the largest remaining jumps also reverses or relocates the whole run that
        starts or ends there (the move that a shuffled or reversed stretch needs). The window
        rules out far-away matches; the direction of the stack, which the differences cannot
        tell, is taken from the stored order. On correctly ordered stacks the result is the
        identity apart from, at most, swaps of near-identical neighbours.
        """
        n = stack.shape[0]
        if n < 3:
            return np.arange(n)
        factor = max(1, min(stack.shape[1:]) // 128)
        flat = stack[:, ::factor, ::factor].reshape(n, -1).astype(np.float32)
        # A slice never needs to cross the middle of the stack; without that cap the two ends
        # of a small stack could be joined (a near-black end slice fits at either end, and a
        # rotating MIP series is cyclic), which shifts the whole volume by a slice.
        W = max(1, min(window, n // 2))
        # band[k, off + W] = distance between stored slices k and k + off
        band = np.full((n, 2 * W + 1), np.inf, dtype=np.float32)
        for off in range(1, W + 1):
            d = np.mean(np.abs(flat[:-off] - flat[off:]), axis=1)
            band[:-off, off + W] = d
            band[off:, W - off] = d

        def dist(i, j):
            if i is None or j is None:
                return 0.0
            off = j - i
            return float(band[i, off + W]) if -W <= off <= W else np.inf

        def fits(segment, first):
            # every slice of the segment stays within the window when placed from `first`
            return all(abs(s - (first + i)) <= W for i, s in enumerate(segment))

        def bestPlacement(order, start, end):
            """The best relocation or reversal of the run order[start:end + 1]: returns
            (gain, insertion slot in the order without the run, reversed)."""
            segment = order[start:end + 1]
            left = order[start - 1] if start > 0 else None
            right = order[end + 1] if end < n - 1 else None
            removal = dist(left, segment[0]) + dist(segment[-1], right) - dist(left, right)
            best = (1e-6, None, False)
            if fits(segment[::-1], start):
                gain = removal - (dist(left, segment[-1]) + dist(segment[0], right) - dist(left, right))
                if gain > best[0]:
                    best = (gain, start, True)
            rest = order[:start] + order[end + 1:]
            for u in range(max(0, min(segment) - W), min(len(rest), max(segment) + W) + 1):
                if u == start:
                    continue
                newLeft = rest[u - 1] if u > 0 else None
                newRight = rest[u] if u < len(rest) else None
                for reversed_ in (False, True):
                    placed = segment[::-1] if reversed_ else segment
                    if not fits(placed, u):
                        continue
                    gain = removal - (dist(newLeft, placed[0]) + dist(placed[-1], newRight)
                                      - dist(newLeft, newRight))
                    if gain > best[0]:
                        best = (gain, u, reversed_)
            return best

        def relocate(order, start, end, u, reversed_):
            segment = order[start:end + 1]
            rest = order[:start] + order[end + 1:]
            placed = segment[::-1] if reversed_ else segment
            order[:] = rest[:u] + placed + rest[u:]

        order = list(range(n))
        for _pass in range(maxPasses):
            improved = False
            # Move single slices to the slot where they fit best.
            for t in range(n):
                gain, u, reversed_ = bestPlacement(order, t, t)
                if u is not None:
                    relocate(order, t, t, u, reversed_)
                    improved = True
            # Reverse runs when that lowers the sum.
            for a in range(n - 1):
                for b in range(a + 1, min(n, a + W)):
                    segment = order[a:b + 1]
                    left = order[a - 1] if a > 0 else None
                    right = order[b + 1] if b < n - 1 else None
                    if (dist(left, segment[-1]) + dist(segment[0], right)
                            < dist(left, segment[0]) + dist(segment[-1], right) - 1e-6
                            and fits(segment[::-1], a)):
                        order[a:b + 1] = segment[::-1]
                        improved = True
            if improved:
                continue
            # No single-slice move or reversal helps: at the largest jumps between
            # neighbours, try reversing or relocating the whole run that starts or ends there.
            gaps = np.array([dist(order[t], order[t + 1]) for t in range(n - 1)])
            threshold = 1.3 * float(np.median(gaps))
            for t in np.argsort(gaps)[::-1][:10]:
                if gaps[t] < threshold:
                    break
                best = (1e-6, None)
                for start, end in ([(t + 1, t + L) for L in range(2, W + 1)]
                                   + [(t - L + 1, t) for L in range(2, W + 1)]):
                    if start < 0 or end > n - 1:
                        continue
                    gain, u, reversed_ = bestPlacement(order, start, end)
                    if u is not None and gain > best[0]:
                        best = (gain, (start, end, u, reversed_))
                if best[1] is not None:
                    relocate(order, *best[1])
                    improved = True
                    break
            if not improved:
                break
        order = np.array(order)
        # The differences cannot tell a stack from its mirror image; keep the stored direction.
        if np.corrcoef(order, np.arange(n))[0, 1] < 0:
            order = order[::-1]
        return order

    @staticmethod
    def _sliceOrder(geometries):
        """Return the indices of the headers of a block in slice order.

        Mimics stores the pixel blobs of a block in slice order (sorted by position along the
        slice normal), but the headers in the order the DICOM files were imported, which
        usually is the same but not always (the files may have been imported in file name
        order, for example). The headers are therefore sorted by position along the normal;
        the direction is the overall direction of the import order, which is what the sort
        has to preserve so that an import order that is already sorted stays as it is.
        """
        n = len(geometries)
        if n < 3 or any(g is None for g in geometries):
            return list(range(n))
        iop = np.array(geometries[0]["imageOrientationPatient"], dtype=float)
        normal = np.cross(iop[0:3], iop[3:6])
        positions = np.array([np.dot(g["imagePositionPatient"], normal) for g in geometries])
        direction = np.sign(np.dot(np.arange(n) - (n - 1) / 2.0, positions - positions.mean()))
        if direction == 0:
            return list(range(n))
        return sorted(range(n), key=lambda k: direction * positions[k])

    @classmethod
    def _decodePixels(cls, data, rows, columns):
        """Decode a pixel-data blob into a (rows, columns) array of 16-bit pixels."""
        if data[:4] != cls.PIXEL_DATA_MAGIC:
            raise ValueError(f"not pixel data (magic is {data[:4]!r})")
        body = data[4:]
        if len(body) == rows * columns * 2:
            return np.frombuffer(body, dtype="<u2").reshape(rows, columns)
        return cls._decodeCompressedPixels(body, rows, columns)

    @staticmethod
    def _decodeCompressedPixels(body, rows, columns):
        """Decode the row-compressed pixel-data variant into a (rows, columns) uint16 array.

        Mimics stores a slice either uncompressed or, when that is smaller, row-compressed:
        a table of `rows` little-endian uint16 compressed row lengths followed by the rows
        themselves. A row is a sequence of 16-bit big-endian tokens whose top two bits select
        the token type:

        - `00` / `01` - one pixel, stored as the absolute value in the remaining 14 bits (used
          wherever the difference from the previous pixel does not fit in a signed byte);
        - `10` - a run of N pixels (N = the remaining 14 bits) follows as N bytes, each a
          signed 8-bit difference from the preceding pixel;
        - `11` - a control token holding a column index in its remaining 14 bits. A row starts
          with two of them: the first column it covers (pixels before it stay 0) and the last.

        A row always starts with an absolute value, so no state carries over between rows.
        """
        if len(body) < 2 * rows:
            raise ValueError("compressed pixel data is truncated")
        rowLengths = np.frombuffer(body, dtype="<u2", count=rows, offset=0).astype(np.int64)
        image = np.zeros((rows, columns), dtype=np.uint16)
        # Reused across rows to keep the per-row work to a few small array operations.
        differences = np.zeros(columns, dtype=np.int64)
        offset = 2 * rows
        for r in range(rows):
            row = body[offset:offset + int(rowLengths[r])]
            offset += int(rowLengths[r])
            differences[:] = 0
            absoluteColumns = [0]
            absoluteValues = [0]
            pos = 0
            column = 0
            firstColumnSeen = False
            while pos + 1 < len(row):
                token = (row[pos] << 8) | row[pos + 1]
                pos += 2
                tag = token >> 14
                if tag == 0b11:
                    # The first control token is the row's first column; the second one is its
                    # last column, which the pixel count below already verifies.
                    if not firstColumnSeen:
                        column = token & 0x3FFF
                        firstColumnSeen = True
                elif tag == 0b10:
                    count = token & 0x3FFF
                    if pos + count > len(row) or column + count > columns:
                        raise ValueError(f"row {r} overruns its data")
                    differences[column:column + count] = np.frombuffer(
                        row, dtype=np.int8, count=count, offset=pos)
                    pos += count
                    column += count
                else:
                    if column >= columns:
                        raise ValueError(f"row {r} overruns its data")
                    absoluteColumns.append(column)
                    absoluteValues.append(token & 0x3FFF)
                    column += 1
            if column != columns:
                raise ValueError(f"row {r} decoded to {column} pixels instead of {columns}")
            # Every pixel is its last preceding absolute value plus the differences in between.
            running = np.cumsum(differences)
            segment = np.zeros(columns, dtype=np.int64)
            segment[absoluteColumns] = np.arange(len(absoluteColumns))
            np.maximum.accumulate(segment, out=segment)
            starts = np.array(absoluteColumns, dtype=np.int64)[segment]
            image[r] = (running - running[starts]
                        + np.array(absoluteValues, dtype=np.int64)[segment]).astype(np.uint16)
        return image

    def _reconstructSlices(self, store, block):
        """Split an image block's header blob into per-slice DICOM headers, pair them with the
        block's pixel blobs and decode the pixels.

        Returns (slices, dicomMeta) where `slices` is a list of (instanceNumber, ipp, pixels, ds,
        geometry) sorted spatially along the slice normal, or (None, None) if no image data is
        available.
        """
        try:
            import pydicom
        except ImportError:
            self.addLog("  WARNING: pydicom is not available; skipping image reconstruction.")
            return None, None

        import io
        blob0 = b"".join(store.read(name) for name in block["header"])
        bounds = self._dicomFileBounds(blob0)
        if not bounds:
            self.addLog("  No DICOM headers found in image data.")
            return None, None

        headers = [pydicom.dcmread(io.BytesIO(blob0[bounds[k]:bounds[k + 1]]), force=True)
                   for k in range(len(bounds) - 1)]
        geometries = [self._sliceGeometry(ds) for ds in headers]
        if any(geometry is None for geometry in geometries):
            self.addLog("  WARNING: the DICOM headers carry no image geometry; "
                        "skipping image reconstruction.")
            return None, None
        # The pixel blobs are in slice order; the headers may not be (see _sliceOrder).
        order = self._sliceOrder(geometries)
        if order != list(range(len(order))):
            self.addLog("  The DICOM headers are not stored in slice order; sorted them by position.")

        nHeaders = len(headers)
        pixelNames = block["pixels"]
        # A block may be followed by extra blobs that are not slices (a downsampled preview of
        # the block, for example); they come after the slices, so pairing by order ignores them.
        if len(pixelNames) < nHeaders:
            self.addLog(f"  WARNING: {nHeaders} DICOM headers but only {len(pixelNames)} pixel "
                        "blobs; pairing by order.")
        nSlices = min(nHeaders, len(pixelNames))
        self.addLog(f"  Reconstructing {nSlices} slices...")

        pixelArrays = []
        for k in range(nSlices):
            ds = headers[order[k]]
            try:
                pixelArrays.append(self._decodePixels(store.read(pixelNames[k]),
                                                      int(ds.Rows), int(ds.Columns)))
            except ValueError as e:
                # Unsupported pixel storage for this project. Skip image reconstruction rather
                # than producing a wrong volume.
                self.addLog(f"  WARNING: pixel data of slice {k} could not be decoded ({e}); "
                            "skipping image reconstruction.")
                return None, None

        # In a plain project the blob numbers give the slice order of the pixel blobs. In a
        # project exported for Mimics Viewer nothing does: the blobs are stored in the order
        # they were written, which is only roughly the slice order (see _recoverSliceOrder).
        recoveredOrder = None
        if (not all(self._blobNumber(name) is not None for name in pixelNames)
                and len({pixels.shape for pixels in pixelArrays}) == 1):
            recoveredOrder = self._recoverSliceOrder(np.stack(pixelArrays))
            if np.array_equal(recoveredOrder, np.arange(nSlices)):
                recoveredOrder = None
            else:
                pixelArrays = [pixelArrays[k] for k in recoveredOrder]

        slices = []
        dicomMeta = None
        for k in range(nSlices):
            ds, geometry, pixels = headers[order[k]], geometries[order[k]], pixelArrays[k]
            rows, cols = int(ds.Rows), int(ds.Columns)
            ipp = np.array(geometry["imagePositionPatient"], dtype=float)
            instanceNumber = int(getattr(ds, "InstanceNumber", k + 1))
            slices.append((instanceNumber, ipp, pixels, ds, geometry))
            if dicomMeta is None:
                iop = geometry["imageOrientationPatient"]
                ps = geometry["pixelSpacing"]
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
                    "imagePositionPatientFirst": geometry["imagePositionPatient"],
                    "sliceThickness": geometry["sliceThickness"],
                }

        if recoveredOrder is not None:
            displacement = np.abs(recoveredOrder - np.arange(nSlices))
            moved = int(np.sum(displacement > 0))
            message = (f"The pixel data of {moved} of the {nSlices} slices was stored out of "
                       "order (the blobs carry no slice numbers). The slice order was recovered "
                       "from the similarity of neighbouring slices, moving slices by up to "
                       f"{int(displacement.max())} positions; please verify the image.")
            self.addLog(f"  WARNING: {message}")
            dicomMeta.setdefault("geometryWarnings", []).append(message)
            dicomMeta["sliceOrderRecovered"] = {"movedSlices": moved,
                                                "maxDisplacement": int(displacement.max())}

        # Order slices spatially by projection onto the slice normal.
        iop = np.array(dicomMeta["imageOrientationPatient"], dtype=float)
        rowDir = iop[0:3]   # direction of increasing column index (i)
        colDir = iop[3:6]   # direction of increasing row index (j)
        sliceNormal = np.cross(rowDir, colDir)
        slices.sort(key=lambda s: np.dot(s[1], sliceNormal))
        return slices, dicomMeta

    @staticmethod
    def _imageName(index, blockCount, modality):
        """Node (and exported file) name of an image block.

        A project with a single image block keeps the plain `image` name it always had; when a
        project holds several blocks they are numbered and tagged with their modality so that
        they can be told apart (the block names in the project header are encrypted).
        """
        if blockCount <= 1:
            return "image"
        modality = re.sub(r"[^A-Za-z0-9]", "", modality)
        return f"image{index + 1}_{modality}" if modality else f"image{index + 1}"

    def importImages(self, store, blocks=None, useDicomReader=False, hardenAcquisitionTransform=True):
        """Reconstruct every image block of the project.

        Returns a list of (volumeNode, dicomMeta). Blocks that cannot be decoded are skipped;
        a block whose slices do not form a volume is listed with volumeNode None, so that its
        metadata (with the geometry errors) is still available.
        """
        if blocks is None:
            blocks = self._imageBlocks(store)
        images = []
        for index, block in enumerate(blocks):
            if len(blocks) > 1:
                self.addLog(f"  Image block {index + 1}/{len(blocks)}:")
            volumeNode, dicomMeta = self.importImage(store, block, index, len(blocks), useDicomReader,
                                                     hardenAcquisitionTransform)
            if volumeNode is not None or dicomMeta is not None:
                images.append((volumeNode, dicomMeta))
        return images

    def importImage(self, store, block=None, index=0, blockCount=1, useDicomReader=False,
                    hardenAcquisitionTransform=True):
        """Reconstruct one image block into a volume node.

        Returns (volumeNode, dicomMeta), or (None, None) if the block cannot be decoded.
        """
        if block is None:
            blocks = self._imageBlocks(store)
            if not blocks:
                self.addLog("  No image data found.")
                return None, None
            block, blockCount = blocks[0], len(blocks)
        slices, dicomMeta = self._reconstructSlices(store, block)
        if not slices:
            return None, None
        nSlices = len(slices)
        imageName = self._imageName(index, blockCount, dicomMeta["modality"])
        dicomMeta["name"] = imageName

        # Report every deviation from a regular volume; slices of different sizes cannot be
        # reconstructed at all (the caller still gets the metadata, with the error messages).
        if not self._checkSliceGeometry([s[4] for s in slices], [s[2].shape for s in slices],
                                        dicomMeta):
            return None, dicomMeta

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

        volumeNode = None
        if useDicomReader:
            try:
                volumeNode = self._loadImageWithDicomPlugin(slices, dicomMeta, imageName,
                                                            hardenAcquisitionTransform)
            except Exception as e:  # noqa: BLE001 - fall back to the direct reconstruction
                message = (f"The image could not be loaded with the DICOM module ({e}); "
                           "it was reconstructed directly instead.")
                self.addLog(f"  WARNING: {message}")
                dicomMeta.setdefault("geometryWarnings", []).append(message)
        if volumeNode is None:
            volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
            volumeNode.SetName(imageName)
            slicer.util.updateVolumeFromArray(volumeNode, volumeArray)
            vtkMat = vtk.vtkMatrix4x4()
            for r in range(4):
                for c in range(4):
                    vtkMat.SetElement(r, c, ijkToRas[r, c])
            volumeNode.SetIJKToRASMatrix(vtkMat)
            volumeNode.CreateDefaultDisplayNodes()
            dicomMeta["loadedWith"] = "direct reconstruction"

        # Only the geometry is used in the scene; patient/study/series identifiers are not
        # attached to the node (they remain available only for the opt-in metadata/DICOM export).

        dimensions = volumeNode.GetImageData().GetDimensions()
        self.addLog(f"  Image '{imageName}': {dimensions[0]}x{dimensions[1]}x{dimensions[2]} "
                    f"({dicomMeta['modality']}, spacing "
                    f"{colSpacing:.3g}x{rowSpacing:.3g}x{sliceSpacing:.3g} mm, "
                    f"{dicomMeta['loadedWith']})")
        return volumeNode, dicomMeta

    def _loadImageWithDicomPlugin(self, slices, dicomMeta, imageName, hardenAcquisitionTransform):
        """Load a block's slices the way the DICOM module does, with the DICOM scalar volume
        plugin.

        The complete DICOM files of the slices are written to a temporary folder and indexed
        into a temporary DICOM database, which replaces the application's database while the
        plugin examines and loads them (the plugin looks the slices up in the database: their
        instance UIDs, and their geometry for the acquisition transform); the application's
        database is restored afterwards and the temporary one is cleared, so the files - which
        carry patient information - never enter the user's database. The result is what the
        DICOM module loads from the exported files: the rescale slope/intercept of the headers
        is applied, and when the slice positions are irregular the plugin adds a grid transform
        (the acquisition transform) that moves every slice to its true position; with
        `hardenAcquisitionTransform` it is applied to the image (resampled), otherwise it stays
        as the volume's parent transform. The reader and this regularization are fixed here,
        so the result does not depend on the DICOM module settings. The patient/study subject
        hierarchy items the plugin creates are removed again.

        Returns the volume node, or raises if the plugin could not load the files.
        """
        import shutil
        import tempfile
        import DICOMScalarVolumePlugin
        from DICOMLib import DICOMUtils

        class ScalarVolumePlugin(DICOMScalarVolumePlugin.DICOMScalarVolumePluginClass):
            """The scalar volume plugin with the acquisition geometry regularization decided
            here instead of by the DICOM module settings."""

            def acquisitionGeometryRegularizationEnabled(self):
                return True

            def hardenAcquisitionGeometryRegularization(self):
                return hardenAcquisitionTransform

        plugin = ScalarVolumePlugin()
        volumeNodesBefore = {node.GetID() for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")}
        dicomDir = tempfile.mkdtemp(prefix="ImportMimics-")
        # The database files cannot be deleted while the application runs, so one temporary
        # database folder is reused (it is emptied every time it is opened).
        databaseDir = os.path.join(slicer.app.temporaryPath, "ImportMimicsDICOMDatabase")
        try:
            files = self._writeDicomSlices(slices, dicomDir)
            with DICOMUtils.TemporaryDICOMDatabase(databaseDir) as database:
                if not DICOMUtils.importDicom(dicomDir, database):
                    raise ValueError("the DICOM files could not be indexed")
                loadables = plugin.examineFiles(files)
                loadables = [loadable for loadable in loadables if loadable.selected] or loadables
                if not loadables:
                    raise ValueError("the DICOM module found nothing to load")
                loadable = max(loadables, key=lambda loadable: loadable.confidence)
                if loadable.warning:
                    self.addLog(f"  DICOM module: {loadable.warning}")
                self.addLog(f"  Loading {len(loadable.files)} slices with the DICOM module...")
                try:
                    volumeNode = plugin.load(loadable, readerApproach="GDCM with DCMTK fallback")
                except AttributeError:
                    volumeNode = self._completeAcquisitionTransform(plugin, volumeNodesBefore)
        finally:
            shutil.rmtree(dicomDir, ignore_errors=True)
        if volumeNode is None:
            raise ValueError("the DICOM reader failed")

        volumeNode.SetName(imageName)
        dicomMeta["loadedWith"] = "DICOM module"
        sliceCount = volumeNode.GetImageData().GetDimensions()[2]
        if sliceCount != len(slices):
            message = (f"The DICOM reader loaded {sliceCount} of the {len(slices)} slices (it "
                       "leaves out slices whose orientation differs from the first slice, for "
                       "example).")
            self.addLog(f"  WARNING: {message}")
            dicomMeta.setdefault("geometryWarnings", []).append(message)

        modeling = getattr(plugin, "acquisitionModeling", None)
        maxError = None
        if (modeling is not None and modeling.originalCorners is not None
                and modeling.targetCorners is not None):
            maxError = float(np.abs(modeling.originalCorners - modeling.targetCorners).max())
            dicomMeta["acquisitionGeometryMaxErrorMm"] = round(maxError, 4)
        transformNode = volumeNode.GetParentTransformNode()
        if transformNode is not None:
            transformNode.SetName(f"{imageName}_acquisitionTransform")
            dicomMeta["acquisitionTransform"] = transformNode.GetName()
            self.addLog(f"  Irregular slice positions (up to {maxError:.3g} mm): the DICOM module "
                        f"added the acquisition transform '{transformNode.GetName()}'.")
        elif maxError is not None and maxError > modeling.cornerEpsilon:
            dicomMeta["acquisitionTransform"] = "hardened"
            self.addLog(f"  Irregular slice positions (up to {maxError:.3g} mm): the acquisition "
                        "transform was applied to the image.")

        # The plugin files the volume under patient/study subject hierarchy items that carry
        # patient information; only the geometry is used here, so the nodes are moved to the
        # scene top level and the items removed (unless something else is filed under them).
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        for node in (volumeNode, transformNode):
            if node is None:
                continue
            item = shNode.GetItemByDataNode(node)
            parent = shNode.GetItemParent(item)
            shNode.SetItemParent(item, shNode.GetSceneItemID())
            while (parent and parent != shNode.GetSceneItemID()
                   and shNode.GetNumberOfItemChildren(parent) == 0):
                grandParent = shNode.GetItemParent(parent)
                shNode.RemoveItem(parent)
                parent = grandParent
        return volumeNode

    @staticmethod
    def _completeAcquisitionTransform(plugin, volumeNodesBefore):
        """Finish a `plugin.load()` that failed while filling the acquisition transform.

        Up to Slicer 5.13 the plugin fails there when the volume is not shown in a slice view
        (batch conversion, or no main window): it fills the transform through
        `slicer.util.arrayFromGridTransform`, which reads the node's transform from the parent,
        and that - the inverse of the stored grid, computed on demand - has no displacement
        grid until it is updated. At that point the volume is loaded, the transform node is
        created and attached to it, and the plugin's acquisition modeling holds the slice
        corners; so the transform is updated and filled here (and hardened if requested).
        Returns the volume node; raises if the failure was another.
        """
        newVolumeNodes = [node for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
                          if node.GetID() not in volumeNodesBefore]
        modeling = getattr(plugin, "acquisitionModeling", None)
        volumeNode = newVolumeNodes[0] if len(newVolumeNodes) == 1 else None
        transformNode = volumeNode.GetParentTransformNode() if volumeNode is not None else None
        if transformNode is None or modeling is None or modeling.targetCorners is None:
            for node in newVolumeNodes:
                slicer.mrmlScene.RemoveNode(node)
            raise
        transformNode.GetTransformFromParent().Update()
        displacements = slicer.util.arrayFromGridTransform(transformNode)
        displacements[:] = modeling.targetCorners - modeling.originalCorners
        slicer.util.arrayFromGridTransformModified(transformNode)
        if plugin.hardenAcquisitionGeometryRegularization():
            volumeNode.HardenTransform()
            slicer.mrmlScene.RemoveNode(transformNode)
        return volumeNode

    def _checkSliceGeometry(self, geometries, shapes, dicomMeta):
        """Check that the slices of a block form a regular volume and record every problem
        found in `dicomMeta["geometryWarnings"]` / `dicomMeta["geometryErrors"]` (the caller
        shows them to the user at the end).

        `geometries` are the per-slice geometry dicts (see `_sliceGeometry`) and `shapes` the
        per-slice (rows, columns), both in slice order. The reconstructed volume takes the
        orientation, pixel spacing and matrix size of the first slice, and places the slices
        at a uniform spacing along the line from the first to the last slice, so every
        deviation from that is reported: slices that differ in size (an error - the block
        cannot be reconstructed at all), in pixel spacing or in orientation (not parallel),
        an in-plane offset that grows along the stack (a sheared volume, which the volume's
        non-orthogonal axes do represent, but which not every tool handles), irregular
        in-plane offsets, and a non-uniform slice spacing. Small deviations (up to 1%, or 1
        degree for the orientation) are warnings, larger ones errors.

        Returns True if the block can be reconstructed (the slices have one size).
        """
        import collections

        errors = dicomMeta.setdefault("geometryErrors", [])
        warnings = dicomMeta.setdefault("geometryWarnings", [])

        def report(message, deviation, warningLevel, errorLevel):
            if deviation > errorLevel:
                self.addLog(f"  ERROR: {message}")
                errors.append(message)
            elif deviation > warningLevel:
                self.addLog(f"  WARNING: {message}")
                warnings.append(message)

        def angleDegrees(a, b):
            return float(np.degrees(np.arccos(np.clip(np.dot(a, b), -1.0, 1.0))))

        n = len(geometries)
        first = geometries[0]

        # Matrix size: the slices cannot even be stacked if it differs.
        counts = collections.Counter(shapes)
        if len(counts) > 1:
            report("The slices differ in size: "
                   + ", ".join(f"{rows}x{columns} ({count} slices)"
                               for (rows, columns), count in sorted(counts.items(),
                                                                    key=lambda item: -item[1]))
                   + ". The image cannot be reconstructed.", 1.0, 0.0, 0.0)
            return False

        # Pixel spacing.
        spacing0 = np.array(first["pixelSpacing"], dtype=float)
        spacings = np.array([g["pixelSpacing"] for g in geometries], dtype=float)
        if spacing0.min() > 0:
            deviation = float(np.abs(spacings - spacing0).max() / spacing0.min())
            report(f"The pixel spacing differs between slices by up to {deviation * 100:.2g}% "
                   f"(the first slice has {spacing0[0]:g} x {spacing0[1]:g} mm, which the "
                   "reconstructed image uses for all slices).", deviation, 0.001, 0.01)

        # Orientation: both in-plane directions must match (a rotation about the normal would
        # keep the normal but still misalign the slices).
        iop0 = np.array(first["imageOrientationPatient"], dtype=float)
        rowDir, colDir = iop0[0:3], iop0[3:6]
        normal = np.cross(rowDir, colDir)
        maxAngle = 0.0
        for g in geometries:
            iop = np.array(g["imageOrientationPatient"], dtype=float)
            maxAngle = max(maxAngle, angleDegrees(rowDir, iop[0:3]), angleDegrees(colDir, iop[3:6]))
        report(f"The slices are not parallel: their orientation differs by up to "
               f"{maxAngle:.3g} degrees. The reconstructed image uses the orientation of the "
               "first slice for all slices, so its geometry is inaccurate.", maxAngle, 0.05, 1.0)

        if n < 2:
            return True
        ipps = np.array([g["imagePositionPatient"] for g in geometries], dtype=float)
        gaps = np.linalg.norm(np.diff(ipps, axis=0), axis=1)
        median = float(np.median(gaps))
        dicomMeta["sliceSpacingMedian"] = round(median, 4)
        if median <= 0:
            report("Several slices are at the same position; the reconstructed image cannot "
                   "place them correctly.", 1.0, 0.0, 0.0)
            return True

        # Slice axis: the line from the first to the last slice. If it is tilted from the
        # slice normal, the volume is sheared (its axes are not orthogonal).
        sliceVec = (ipps[-1] - ipps[0]) / (n - 1)
        sliceDir = sliceVec / np.linalg.norm(sliceVec) if np.linalg.norm(sliceVec) > 0 else normal
        shearAngle = angleDegrees(sliceDir, normal)
        shearAngle = min(shearAngle, 180.0 - shearAngle)
        dicomMeta["sliceAxisTiltDegrees"] = round(shearAngle, 4)
        report(f"The slices are shifted within the image plane along the stack (the slice axis "
               f"is tilted {shearAngle:.3g} degrees from the slice normal). The reconstructed "
               "image is sheared accordingly; its axes are not orthogonal.", shearAngle, 0.05, 90.0)

        # Irregular in-plane offsets: what remains of each slice position after removing the
        # uniform progression along the slice axis, measured within the image plane.
        residuals = ipps - (ipps[0] + np.outer(np.arange(n), sliceVec))
        inPlane = np.hypot(residuals @ rowDir, residuals @ colDir)
        maxShift = float(inPlane.max())
        dicomMeta["sliceInPlaneShiftMax"] = round(maxShift, 4)
        report(f"The slices are shifted irregularly within the image plane, by up to "
               f"{maxShift:.3g} mm from their expected position, which the reconstructed image "
               "cannot represent.", maxShift / median, 0.01, 0.10)

        # Slice spacing: a single average spacing is used, so outliers (slice-to-slice
        # distances differing from the median by more than 1%) make the geometry inaccurate.
        relativeDeviation = np.abs(gaps - median) / median
        dicomMeta["sliceSpacingMaxDeviationPercent"] = round(float(relativeDeviation.max()) * 100.0, 2)
        outlierMask = relativeDeviation > 0.01
        if outlierMask.any():
            # Count how many times each distinct outlier spacing occurs.
            counts = collections.Counter(round(float(g), 3) for g in gaps[outlierMask])
            outlierText = ", ".join(f"{value:g} mm occurred {count}x"
                                    for value, count in sorted(counts.items()))
            dicomMeta["sliceSpacingOutliers"] = {f"{value:g}": count
                                                 for value, count in sorted(counts.items())}
            report(f"Non-uniform slice spacing: the median spacing is {round(median, 3):g} mm, "
                   f"but the following outlier spacings (differing by more than 1% from the "
                   f"median) were found: {outlierText}. The reconstructed image uses a single "
                   "average spacing.", float(relativeDeviation.max()), 0.01, 0.10)
        return True

    def exportDicomFiles(self, store, outputDir):
        """Reconstruct the complete original DICOM files (headers + pixel data) and save them.

        Files are written to a `dicom` subfolder, one per slice.
        Returns the number of files written.
        """
        blocks = self._imageBlocks(store)
        nWritten = 0
        for index, block in enumerate(blocks):
            slices, dicomMeta = self._reconstructSlices(store, block)
            if not slices:
                continue
            # Each image block gets its own subfolder, since instance numbers repeat between
            # blocks; a project with a single block keeps the plain `dicom` folder.
            dicomDir = os.path.join(outputDir, "dicom")
            if len(blocks) > 1:
                dicomDir = os.path.join(dicomDir,
                                        self._imageName(index, len(blocks), dicomMeta["modality"]))
            files = self._writeDicomSlices(slices, dicomDir)
            self.addLog(f"  Saved {len(files)} original DICOM file(s) to {dicomDir}")
            nWritten += len(files)
        if not nWritten:
            self.addLog("  No DICOM data to export.")
        return nWritten

    @staticmethod
    def _writeDicomSlices(slices, dicomDir):
        """Write the complete DICOM file (header + pixel data) of every slice of a block into
        `dicomDir` (created if needed), one file per slice, and return the file paths."""
        import pydicom

        os.makedirs(dicomDir, exist_ok=True)
        files = []
        for instanceNumber, _ipp, pixels, ds, _geometry in slices:
            # Mimics stores the DICOM headers with the pixel data removed (and, for compressed
            # source images, leaves a compressed transfer syntax on the header). Complete each
            # file: inject the raw pixels, use a matching uncompressed transfer syntax, and set
            # the Pixel Data VR according to the bit depth.
            ds.PixelData = pixels.tobytes()
            ds["PixelData"].VR = "OW" if int(getattr(ds, "BitsAllocated", 16)) > 8 else "OB"
            ds.file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
            path = os.path.join(dicomDir, f"slice_{instanceNumber:04d}.dcm")
            try:
                ds.save_as(path, enforce_file_format=True)
            except TypeError:
                # pydicom < 3.0
                ds.save_as(path, write_like_original=False)
            files.append(path)
        return files

    # ------------------------------------------------------------------ models

    # A small palette so consecutive objects get distinguishable colors (names/colors from the
    # project header are encrypted and unavailable).
    _COLOR_PALETTE = [
        (0.9, 0.5, 0.5), (0.5, 0.7, 0.9), (0.6, 0.9, 0.6),
        (0.9, 0.8, 0.5), (0.8, 0.6, 0.9), (0.5, 0.9, 0.85),
    ]

    def _readVerticesRas(self, store, objectId):
        """Read an object's `_vertices` blob and return its points as an (N,3) RAS array."""
        vertices = np.frombuffer(store.read(f"Stl{objectId}_vertices"),
                                 dtype="<i4").reshape(-1, 3).astype(np.float64)
        vertices *= self.MESH_COORD_SCALE  # fixed-point -> millimeters (LPS)
        return self._lpsToRas(vertices)

    def importModels(self, store, attachMetadata=True):
        """Create model nodes from Stl objects that have a `_surfaces` blob (triangle meshes).

        Objects that have `_vertices` but neither surfaces nor curves are imported as point-cloud
        models. Both id styles (`Stl{guid}_...` and `Stl(N)_...`) are supported.
        """
        names = store.names
        objects = self._stlObjects(names)
        modelNodes = []
        for objectId in sorted(objects, key=self._stlSortKey):
            parts = objects[objectId]
            if f"Stl{objectId}_vertices" not in names:
                continue
            hasSurfaces = "surfaces" in parts
            # Curve-only objects are handled by importCurves; skip them here.
            if not hasSurfaces and "curves" in parts:
                continue

            vertices = self._readVerticesRas(store, objectId)
            if len(vertices) == 0:
                # Empty placeholder object (0 vertices); nothing to import.
                self.addLog(f"  Skipping empty object (id {objectId})")
                continue
            if hasSurfaces:
                triangles = np.frombuffer(store.read(f"Stl{objectId}_surfaces"),
                                          dtype="<i4").reshape(-1, 3)
                polyData = self._buildPolyData(vertices, triangles)
                detail = f"{len(vertices)} points, {len(triangles)} triangles"
            else:
                # Vertices only: represent as a point cloud (glyphable vertex cells).
                polyData = self._buildPointCloud(vertices)
                detail = f"{len(vertices)} points (point cloud)"

            idx = len(modelNodes)  # consecutive object numbering (curve-only objects are skipped)
            modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")
            modelNode.SetName(f"object{idx + 1}")
            modelNode.SetAndObservePolyData(polyData)
            modelNode.CreateDefaultDisplayNodes()
            displayNode = modelNode.GetDisplayNode()
            displayNode.SetColor(*self._COLOR_PALETTE[idx % len(self._COLOR_PALETTE)])
            displayNode.SetVisibility2D(True)
            if attachMetadata:
                modelNode.SetAttribute("Mimics.id", objectId)
            modelNodes.append(modelNode)
            self.addLog(f"  Model {idx + 1}: {detail} (id {objectId})")
        return modelNodes

    def importCurves(self, store, attachMetadata=True):
        """Create polyline model nodes from Stl objects that have a `_curves` blob.

        A `_curves` blob is an ordered list of int32 vertex indices into the object's own
        `_vertices`, defining a contour/wireframe. If the first and last index coincide the
        polyline is closed. The result is a model node holding a single polyline (dense sampled
        points, so a lightweight polyline model rather than an editable markups curve).
        """
        names = store.names
        objects = self._stlObjects(names)
        curveNodes = []
        idx = 0
        for objectId in sorted(objects, key=self._stlSortKey):
            if "curves" not in objects[objectId] or f"Stl{objectId}_vertices" not in names:
                continue
            vertices = self._readVerticesRas(store, objectId)
            if len(vertices) == 0:
                continue
            indices = np.frombuffer(store.read(f"Stl{objectId}_curves"), dtype="<i4")
            # Keep only valid indices into this object's vertices.
            indices = indices[(indices >= 0) & (indices < len(vertices))]
            if len(indices) < 2:
                continue
            closed = bool(indices[0] == indices[-1]) and len(indices) > 2
            if closed:
                indices = indices[:-1]
            # Drop consecutive duplicate indices (zero-length segments).
            keep = np.ones(len(indices), dtype=bool)
            keep[1:] = indices[1:] != indices[:-1]
            indices = indices[keep]
            if len(indices) < 2:
                continue
            curvePoints = vertices[indices]

            polyData = self._buildPolyLine(curvePoints, closed)
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")
            node.SetName(f"curve{idx + 1}")
            node.SetAndObservePolyData(polyData)
            node.CreateDefaultDisplayNodes()
            displayNode = node.GetDisplayNode()
            displayNode.SetColor(1.0, 1.0, 0.4)
            displayNode.SetLineWidth(3)
            displayNode.SetVisibility2D(True)
            if attachMetadata:
                node.SetAttribute("Mimics.id", objectId)
                node.SetAttribute("Mimics.type", "Curve")
            curveNodes.append(node)
            self.addLog(f"  Curve {idx + 1}: {len(curvePoints)} points, "
                        f"{'closed' if closed else 'open'} (id {objectId})")
            idx += 1
        return curveNodes

    @staticmethod
    def _buildPolyData(vertices, triangles):
        """Build a triangulated vtkPolyData from (N,3) float points and (M,3) int triangle indices.

        Points and cells are set from numpy in bulk (meshes can have millions of triangles, so a
        per-cell Python loop would be prohibitively slow)."""
        from vtk.util import numpy_support

        points = vtk.vtkPoints()
        points.SetData(numpy_support.numpy_to_vtk(
            np.ascontiguousarray(vertices, dtype=np.float64), deep=True))

        nCells = len(triangles)
        connectivity = np.empty((nCells, 4), dtype=np.int64)
        connectivity[:, 0] = 3
        connectivity[:, 1:] = triangles
        cells = vtk.vtkCellArray()
        cells.SetCells(nCells, numpy_support.numpy_to_vtkIdTypeArray(
            connectivity.ravel(), deep=True))

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
    def _buildPolyLine(points, closed):
        """Build a vtkPolyData holding a single polyline through the given (N,3) points."""
        from vtk.util import numpy_support

        arr = np.ascontiguousarray(points, dtype=np.float64)
        if closed:
            arr = np.vstack([arr, arr[0]])
        vtkPoints = vtk.vtkPoints()
        vtkPoints.SetData(numpy_support.numpy_to_vtk(arr, deep=True))

        nPoints = len(arr)
        connectivity = np.empty(nPoints + 1, dtype=np.int64)
        connectivity[0] = nPoints
        connectivity[1:] = np.arange(nPoints, dtype=np.int64)
        lines = vtk.vtkCellArray()
        lines.SetCells(1, numpy_support.numpy_to_vtkIdTypeArray(connectivity, deep=True))

        polyData = vtk.vtkPolyData()
        polyData.SetPoints(vtkPoints)
        polyData.SetLines(lines)
        return polyData

    @staticmethod
    def _buildPointCloud(points):
        """Build a vtkPolyData holding vertex cells for the given (N,3) points."""
        from vtk.util import numpy_support

        arr = np.ascontiguousarray(points, dtype=np.float64)
        vtkPoints = vtk.vtkPoints()
        vtkPoints.SetData(numpy_support.numpy_to_vtk(arr, deep=True))

        nPoints = len(arr)
        connectivity = np.empty((nPoints, 2), dtype=np.int64)
        connectivity[:, 0] = 1
        connectivity[:, 1] = np.arange(nPoints, dtype=np.int64)
        verts = vtk.vtkCellArray()
        verts.SetCells(nPoints, numpy_support.numpy_to_vtkIdTypeArray(
            connectivity.ravel(), deep=True))

        polyData = vtk.vtkPolyData()
        polyData.SetPoints(vtkPoints)
        polyData.SetVerts(verts)
        return polyData

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

    def importNurbsCurves(self, store, attachMetadata=True):
        """Create closed markups curve nodes from NURBS_{guid} blobs (e.g. valve annuli)."""
        guids = sorted(n[len("NURBS_"):] for n in store.names if n.startswith("NURBS_"))
        curveNodes = []
        for idx, guid in enumerate(guids):
            cps, knots, degree = self._parseNurbs(store.read("NURBS_" + guid))
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

    def importPointSets(self, store, attachMetadata=True):
        """Create markups point-list nodes from the float64 point-set blobs."""
        pointBlobs = sorted(n for n in store.names if n.startswith("00007FF"))
        pointNodes = []
        for idx, name in enumerate(pointBlobs):
            data = store.read(name)
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

    def _exportFiles(self, exportDir, volumeNodes, modelNodes, curveNodes, markupsNodes, metadata,
                     saveMetadata=True):
        # Files are written to a subfolder named after the project, so node names (and hence
        # file names) do not repeat the project name.
        os.makedirs(exportDir, exist_ok=True)
        for volumeNode in volumeNodes:
            path = os.path.join(exportDir, f"{volumeNode.GetName()}.nrrd")
            slicer.util.saveNode(volumeNode, path)
            self.addLog(f"  Saved {path}")
            # A volume loaded with the DICOM module may carry an acquisition transform that
            # puts its slices at their true positions; it belongs with the image.
            transformNode = volumeNode.GetParentTransformNode()
            if transformNode is not None:
                path = os.path.join(exportDir, f"{transformNode.GetName()}.h5")
                slicer.util.saveNode(transformNode, path)
                self.addLog(f"  Saved {path}")
        for modelNode in modelNodes:
            path = os.path.join(exportDir, f"{modelNode.GetName()}.ply")
            slicer.util.saveNode(modelNode, path)
            self.addLog(f"  Saved {path}")
        # Curve models hold polylines; .ply cannot store lines, so use .vtp (XML PolyData).
        for curveNode in curveNodes:
            path = os.path.join(exportDir, f"{curveNode.GetName()}.vtp")
            slicer.util.saveNode(curveNode, path)
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
    """File reader plugin so that .mcs / .mxp projects can be opened directly (File > Add Data,
    drag-and-drop). The project is loaded into the scene only; no converted files are written.
    Registered automatically because the class is named <ModuleName>FileReader.
    """

    def __init__(self, parent):
        self.parent = parent

    def description(self):
        return _("Materialise Mimics/3-matic project")

    def fileType(self):
        return "MimicsProject"

    def extensions(self):
        return [_("Materialise Mimics/3-matic project") + " (*.mcs *.mxp)"]

    def canLoadFileConfidence(self, filePath):
        # Must have a supported extension (.mcs / .mxp)...
        if not self.parent.supportedNameFilters(filePath):
            return 0.0
        # ...and be a SQLite database (.mcs) or an 'MT' archive (.mxp).
        try:
            with open(filePath, "rb") as f:
                magic = f.read(16)
            if magic.startswith(b"SQLite format 3") or magic.startswith(b"MT\x03\x04"):
                return 0.9
        except OSError:
            pass
        return 0.0

    def load(self, properties):
        try:
            filePath = properties["fileName"]
            logic = ImportMimicsLogic()
            # Load into the scene only; never write converted files to a folder.
            volumeNodes, modelNodes, curveNodes, markupsNodes = logic.importProject(
                filePath, loadIntoScene=True, exportDir=None, exportDicom=False)
            # Surface any warnings/errors (e.g. non-uniform slice spacing) to the user.
            for severity, text in logic.messages:
                event = vtk.vtkCommand.ErrorEvent if severity == "error" else vtk.vtkCommand.WarningEvent
                self.parent.userMessages().AddMessage(event, text)
            loadedNodes = volumeNodes + modelNodes + curveNodes + markupsNodes
            if not loadedNodes:
                raise ValueError("No data could be loaded from the project.")
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.parent.userMessages().AddMessage(
                vtk.vtkCommand.ErrorEvent, f"Failed to read Materialise project: {e}")
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
        self.testImportImageBlocks()
        self.testRecoveredSliceOrder()
        self.testGeometryIssues()
        self.testMxpArchiveLayouts()
        self.delayDisplay("Test passed")

    # -------------------------------------------------------------- synthetic project builder

    @staticmethod
    def _encodeRow(values):
        """Encode one row of pixels the way Mimics does, to test the decoder against."""
        out = bytearray([0xC0, 0x00])                                    # first column
        out += bytes([0xC0 | ((len(values) - 1) >> 8), (len(values) - 1) & 0xFF])  # last column
        run = bytearray()

        def flushRun():
            if run:
                out.extend([0x80 | (len(run) >> 8), len(run) & 0xFF])
                out.extend(run)
                run.clear()

        previous = None
        for value in values:
            difference = None if previous is None else int(value) - int(previous)
            if difference is not None and -128 <= difference <= 127:
                run.append(difference & 0xFF)
            else:
                flushRun()
                out += bytes([(int(value) >> 8) & 0x3F, int(value) & 0xFF])
            previous = value
        flushRun()
        return bytes(out)

    @classmethod
    def _encodeSlice(cls, image):
        rows = [cls._encodeRow(image[r]) for r in range(image.shape[0])]
        table = np.array([len(row) for row in rows], dtype="<u2").tobytes()
        return ImportMimicsLogic.PIXEL_DATA_MAGIC + table + b"".join(rows)

    @staticmethod
    def _dicomFiles(sliceCount, rows, columns, modality, firstZ, geometry=None):
        """Return the DICOM file (preamble + 'DICM' + dataset, no pixel data) of every slice.

        `geometry(k)` may return a dict with any of `position`, `orientation`, `pixelSpacing`
        to override the regular geometry of slice k (used to build irregular volumes)."""
        import io
        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset
        files = []
        # Identification that the DICOM database needs to index the files (the DICOM module
        # loading route indexes them into a temporary database).
        studyInstanceUID = pydicom.uid.generate_uid()
        seriesInstanceUID = pydicom.uid.generate_uid()
        for k in range(sliceCount):
            override = geometry(k) if geometry else {}
            ds = Dataset()
            ds.PatientName = "ImportMimics^Test"
            ds.PatientID = "ImportMimicsTest"
            ds.StudyInstanceUID = studyInstanceUID
            ds.SeriesInstanceUID = seriesInstanceUID
            ds.StudyID = "1"
            ds.SeriesNumber = 1
            ds.StudyDate = "20260101"
            ds.SeriesDescription = f"{modality} test series"
            ds.file_meta = FileMetaDataset()
            ds.file_meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
            ds.file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
            ds.file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
            ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
            ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
            ds.Modality = modality
            ds.Rows, ds.Columns = rows, columns
            ds.PixelSpacing = override.get("pixelSpacing", [0.5, 0.5])
            ds.SliceThickness = 1.0
            ds.ImageOrientationPatient = override.get("orientation", [1, 0, 0, 0, 1, 0])
            ds.ImagePositionPatient = override.get("position", [-10.0, -20.0, firstZ + k])
            ds.InstanceNumber = k + 1
            ds.BitsAllocated, ds.BitsStored, ds.PixelRepresentation = 16, 16, 0
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            buffer = io.BytesIO()
            try:
                ds.save_as(buffer, enforce_file_format=True)
            except TypeError:
                ds.save_as(buffer, write_like_original=False)  # pydicom < 3.0
            files.append(buffer.getvalue())
        return files

    @staticmethod
    def _importOrder(sliceCount):
        """A DICOM file import order that is not the slice order (two slices swapped), as
        happens when the files were imported in file name order."""
        order = list(range(sliceCount))
        order[1], order[2] = order[2], order[1]
        return order

    def _writeProject(self, path, blocks, layout):
        """Write a synthetic `.mcs` project holding the given image blocks (lists of slices) in
        one of the blob layouts Mimics uses:

        - `viewer`: a project exported for Mimics Viewer - every blob named with a GUID, a
          header blob (with a few bytes of Mimics' own before the first DICOM preamble)
          followed by the pixel blobs of the block (in the order given as the block's fifth
          element, if any) and an extra blob that is not a slice;
        - `plain`: a plain Mimics project - `blob_N` names, the headers stored in import order
          (which is not the slice order) and again in slice order, the pixel blobs numbered in
          slice order after the header but stored out of order (one of them was rewritten on
          a later save, so it comes last), the numbers of the second block's pixel blobs split
          around those of the first block;
        - `perSlice`: a plain project of an older Mimics version - one header blob per slice.
        """
        import sqlite3
        import uuid
        if os.path.exists(path):
            os.remove(path)
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE blobs (blob_id INTEGER PRIMARY KEY, "
                           "blob_name VARCHAR(128) NOT NULL UNIQUE, number_of_parts INT NOT NULL)")
        connection.execute("CREATE TABLE blobs_parts (blob_part_id INTEGER PRIMARY KEY, "
                           "blob_id INTEGER NOT NULL, blob_part_number INTEGER NOT NULL, "
                           "blob_part_size INT NOT NULL, is_blob_compressed INT NOT NULL, "
                           "orig_size INT, blob_part_data BLOB NOT NULL)")
        blobId = [0]

        def add(name, data):
            blobId[0] += 1
            payload = zlib.compress(data)
            connection.execute("INSERT INTO blobs VALUES (?,?,1)", (blobId[0], name))
            connection.execute("INSERT INTO blobs_parts VALUES (?,?,0,?,1,?,?)",
                               (blobId[0], blobId[0], len(data), len(data), sqlite3.Binary(payload)))

        def lengthPrefixed(files):
            # Mimics stores a 4-byte length before each DICOM file.
            return b"".join(struct.pack("<I", len(f)) + f for f in files)

        deferred = []  # (name, data) of blobs rewritten on a later save: they come last
        nextNumber = [0]

        def numbers(count):
            first = nextNumber[0]
            nextNumber[0] += count
            return list(range(first, first + count))

        for index, block in enumerate(blocks):
            modality, firstZ, volume = block[:3]
            sliceCount, rows, columns = volume.shape
            files = self._dicomFiles(sliceCount, rows, columns, modality, firstZ,
                                     block[3] if len(block) > 3 else None)
            # The order in which the pixel blobs are stored (viewer layout): slice order unless
            # the block says otherwise.
            storedOrder = block[4] if len(block) > 4 else range(sliceCount)
            slices = [volume[k].tobytes() if k % 2 else self._encodeSlice(volume[k])
                      for k in range(sliceCount)]
            slices = [(ImportMimicsLogic.PIXEL_DATA_MAGIC + s if k % 2 else s)
                      for k, s in enumerate(slices)]
            importOrder = self._importOrder(sliceCount)
            if layout == "viewer":
                add(f"ImageBlockPngPreview-0x{index:08X}", b"\x00" * 8 + b"\x89PNG")
                add(str(uuid.uuid4()), b"\x00" * 8 + b"".join(files))
                for k in storedOrder:
                    add(str(uuid.uuid4()), slices[k])
                # A block is followed by extra blobs that are not slices.
                add(str(uuid.uuid4()), ImportMimicsLogic.PIXEL_DATA_MAGIC + b"\x00" * 999)
            elif layout == "plain":
                if index == 0:
                    # Mimics hands out the lowest free numbers: leave the first ones for the
                    # second block's header and first two pixel blobs (see below), then two for
                    # the header copies.
                    reserved = numbers(3)
                    copyNumbers = numbers(2)
                    headerNumber, = numbers(1)
                    pixelNumbers = numbers(sliceCount)
                else:
                    headerNumber = reserved[0]
                    pixelNumbers = reserved[1:] + numbers(sliceCount - 2)
                add(f"blob_{headerNumber}", lengthPrefixed([files[k] for k in importOrder]))
                for k in range(sliceCount):
                    if k == 1:
                        deferred.append((f"blob_{pixelNumbers[k]}", slices[k]))
                    else:
                        add(f"blob_{pixelNumbers[k]}", slices[k])
                # The headers again, in slice order, and a blob that is neither.
                deferred.append((f"blob_{copyNumbers[index]}", lengthPrefixed(files)))
                deferred.append((f"blob_{nextNumber[0] + 10 + index}", b"\x00" * 64))
            elif layout == "perSlice":
                for number, k in enumerate(importOrder):
                    add(f"blob_{number}", lengthPrefixed([files[k]]))
                for k in range(sliceCount):
                    add(f"blob_{sliceCount + k}", slices[k])
                add(f"blob_{2 * sliceCount}", b"\x00" * 64)
                for k in range(sliceCount):
                    add(f"blob_{2 * sliceCount + 3 + k}", lengthPrefixed([files[k]]))
        for name, data in deferred:
            add(name, data)
        connection.commit()
        connection.close()

    # -------------------------------------------------------------- tests

    def testImportImageBlocks(self):
        """Every blob layout and both pixel storage variants reconstruct the exact pixels."""
        import tempfile
        try:
            import pydicom  # noqa: F401 - only needed to know whether the test can run
        except ImportError:
            self.delayDisplay("pydicom is not available; skipping the image import test.")
            return

        rng = np.random.default_rng(0)

        def makeVolume(sliceCount, rows, columns):
            # Smooth along the rows so most differences fit in a byte, with jumps that force the
            # decoder through its absolute-value escape as well; every slice is the previous one
            # shifted by a column, so that neighbouring slices resemble each other (the slice
            # order of a Mimics Viewer project is recovered from that resemblance).
            base = np.cumsum(rng.integers(-40, 40, size=(rows, columns)), axis=1)
            base[::5, ::4] += 900
            volume = np.stack([np.roll(base, k, axis=1) + 7 * k for k in range(sliceCount)])
            return np.clip(volume + 1500, 0, 0x3FFF).astype("<u2")

        for layout in ("viewer", "plain", "perSlice"):
            self.setUp()
            self.delayDisplay(f"Importing a synthetic project ({layout} layout)")
            blocks = [("CT", 100.0, makeVolume(4, 16, 16))]
            if layout != "perSlice":
                blocks.append(("MR", 200.0, makeVolume(3, 12, 20)))
            path = os.path.join(tempfile.gettempdir(), "ImportMimicsTest.mcs")
            self._writeProject(path, blocks, layout)

            volumeNodes, _models, _curves, _markups = ImportMimicsLogic().importProject(
                path, loadIntoScene=True, exportDir=None, exportDicom=False, saveMetadata=False)

            self.assertEqual(len(volumeNodes), len(blocks))
            expectedNames = ["image"] if len(blocks) == 1 else ["image1_CT", "image2_MR"]
            self.assertEqual([node.GetName() for node in volumeNodes], expectedNames)
            for node, (_modality, firstZ, volume) in zip(volumeNodes, blocks):
                self.assertTrue(np.array_equal(slicer.util.arrayFromVolume(node), volume))
                np.testing.assert_allclose(node.GetSpacing(), (0.5, 0.5, 1.0))
                np.testing.assert_allclose(node.GetOrigin(), (10.0, 20.0, firstZ))
            os.remove(path)

    def testRecoveredSliceOrder(self):
        """A Mimics Viewer project whose pixel blobs are stored out of order (as written by a
        thread pool) is reconstructed with the slices back in place."""
        import tempfile
        try:
            import pydicom  # noqa: F401 - only needed to know whether the test can run
        except ImportError:
            self.delayDisplay("pydicom is not available; skipping the slice order test.")
            return
        rng = np.random.default_rng(2)
        # Slices that resemble their neighbours more than any other slice: a blob that drifts
        # along the stack and an intensity ramp (nothing periodic).
        sliceCount, size = 24, 32
        y, x = np.mgrid[0:size, 0:size]
        volume = np.stack([1000 + 800 * np.exp(-((x - 8 - k * 0.6) ** 2 + (y - 12 - k * 0.3) ** 2) / 40.0)
                           + 25 * k + rng.integers(0, 20, (size, size))
                           for k in range(sliceCount)]).astype("<u2")
        # Stored order: completion order of a pool of 6 threads.
        stored = np.argsort(np.arange(sliceCount) + rng.uniform(0, 6, sliceCount))
        self.assertGreater(np.abs(stored - np.arange(sliceCount)).max(), 1)

        self.setUp()
        self.delayDisplay("Importing a Mimics Viewer project with scrambled pixel blobs")
        path = os.path.join(tempfile.gettempdir(), "ImportMimicsTest.mcs")
        self._writeProject(path, [("CT", 100.0, volume, None, stored)], "viewer")
        logic = ImportMimicsLogic()
        volumeNodes, _models, _curves, _markups = logic.importProject(
            path, loadIntoScene=True, exportDir=None, exportDicom=False, saveMetadata=False)
        self.assertEqual(len(volumeNodes), 1)
        self.assertTrue(np.array_equal(slicer.util.arrayFromVolume(volumeNodes[0]), volume))
        self.assertTrue(any("stored out of order" in text for _s, text in logic.messages),
                        logic.messages)
        os.remove(path)

    def testGeometryIssues(self):
        """Irregular slice geometry is reported, and loading with the DICOM module adds an
        acquisition transform that puts the slices back at their true positions."""
        import math
        import tempfile
        try:
            import pydicom  # noqa: F401 - only needed to know whether the test can run
        except ImportError:
            self.delayDisplay("pydicom is not available; skipping the geometry test.")
            return

        rng = np.random.default_rng(1)
        volume = np.clip(np.cumsum(rng.integers(-40, 40, size=(6, 16, 16)), axis=2) + 1500,
                         0, 0x3FFF).astype("<u2")
        tilt = math.radians(2.0)
        axial, tiltedAboutX = [1, 0, 0, 0, 1, 0], [1, 0, 0, 0, math.cos(tilt), math.sin(tilt)]
        tiltedAboutY, coronal = [math.cos(tilt), 0, -math.sin(tilt), 0, 1, 0], [1, 0, 0, 0, 0, -1]
        # name -> (geometry override of slice k, expected severity, expected words, whether the
        # DICOM module needs an acquisition transform to place the slices correctly, the slices
        # the DICOM reader loads - it leaves out slices whose orientation differs from the
        # first - and whether the direct reconstruction still holds every slice's pixels)
        cases = {
            "nonUniformSpacing": (
                lambda k: {"position": [-10.0, -20.0, 100.0 + k + (1.0 if k >= 4 else 0.0)]},
                "error", "Non-uniform slice spacing", True, 6, True),
            "inPlaneShift": (
                lambda k: {"position": [-10.0 + (0.3 if k == 3 else 0.0), -20.0, 100.0 + k]},
                "error", "shifted irregularly within the image plane", True, 6, True),
            "shear": (
                lambda k: {"position": [-10.0 + 0.2 * k, -20.0, 100.0 + k]},
                "warning", "slice axis is tilted", False, 6, True),
            "nonParallel": (
                lambda k: {"orientation": tiltedAboutX if k == 4 else axial},
                "error", "not parallel", False, 5, True),
            "twoTiltedSlices": (
                lambda k: {"orientation": {1: tiltedAboutX, 4: tiltedAboutY}.get(k, axial)},
                "error", "not parallel", False, 4, True),
            # Two stacks of different orientation in one block (the slices are not a volume).
            "twoOrientations": (
                lambda k: {"orientation": axial if k < 3 else coronal,
                           "position": [-10.0, -20.0, 100.0 + k] if k < 3
                           else [-10.0, -17.0 + k, 100.0]},
                "error", "orientation differs by up to 90 degrees", False, 3, False),
            "pixelSpacing": (
                lambda k: {"pixelSpacing": [0.52, 0.52] if k == 2 else [0.5, 0.5]},
                "error", "pixel spacing differs", True, 6, True),
        }

        for name, (geometry, severity, words, needsTransform, dicomSliceCount,
                   pixelsIntact) in cases.items():
            path = os.path.join(tempfile.gettempdir(), "ImportMimicsTest.mcs")
            self._writeProject(path, [("CT", 100.0, volume, geometry)], "plain")
            truePositions = np.array([geometry(k).get("position", [-10.0, -20.0, 100.0 + k])
                                      for k in range(6)]) * [-1, -1, 1]  # LPS -> RAS

            # (loaded with the DICOM module, acquisition transform hardened)
            for useDicomReader, harden in ((False, False), (True, False), (True, True)):
                self.setUp()
                self.delayDisplay(f"Importing a project with {name} ("
                                  + ("DICOM module, hardened" if harden else
                                     "DICOM module" if useDicomReader else "direct") + ")")
                logic = ImportMimicsLogic()
                exportDir = os.path.join(tempfile.gettempdir(), "ImportMimicsTestExport")
                volumeNodes, _models, _curves, _markups = logic.importProject(
                    path, loadIntoScene=True, exportDir=exportDir, exportDicom=False,
                    saveMetadata=False, useDicomReader=useDicomReader,
                    hardenAcquisitionTransform=harden)
                self.assertEqual(len(volumeNodes), 1)
                volumeNode = volumeNodes[0]
                transformNode = volumeNode.GetParentTransformNode()
                if useDicomReader and dicomSliceCount < 6:
                    self.assertEqual(volumeNode.GetImageData().GetDimensions()[2], dicomSliceCount)
                    self.assertTrue(any(f"loaded {dicomSliceCount} of the 6 slices" in text
                                        for _s, text in logic.messages), logic.messages)
                    continue
                if pixelsIntact and not (harden and needsTransform):
                    self.assertTrue(np.array_equal(slicer.util.arrayFromVolume(volumeNode), volume),
                                    f"{name}: pixels differ (DICOM module: {useDicomReader})")

                # The problem is reported, and the DICOM module is recommended unless it
                # was used already.
                self.assertTrue(any(s == severity and words in text
                                    for s, text in logic.messages), logic.messages)
                self.assertEqual(any("Load image using DICOM module" in text
                                     for _s, text in logic.messages), not useDicomReader)

                if not useDicomReader or not needsTransform:
                    self.assertIsNone(transformNode, name)
                    continue
                if harden:
                    # The transform has been applied to the image: no transform node, and the
                    # image spans the true slice positions.
                    self.assertIsNone(transformNode, name)
                    bounds = [0.0] * 6
                    volumeNode.GetRASBounds(bounds)
                    self.assertLess(bounds[4], truePositions[:, 2].min() + 0.01, name)
                    self.assertGreater(bounds[5], truePositions[:, 2].max() - 0.01, name)
                    continue
                self.assertIsNotNone(transformNode, name)
                # With the transform, every slice origin lands on its true position, also
                # after the transform has been saved next to the image and loaded back.
                ijkToRas = vtk.vtkMatrix4x4()
                volumeNode.GetIJKToRASMatrix(ijkToRas)
                transformPath = os.path.join(exportDir, f"{transformNode.GetName()}.h5")
                self.assertTrue(os.path.exists(transformPath))
                loadedTransformNode = slicer.util.loadTransform(transformPath)
                for node in (transformNode, loadedTransformNode):
                    volumeNode.SetAndObserveTransformNodeID(node.GetID())
                    for k in range(6):
                        origin = ijkToRas.MultiplyPoint([0, 0, k, 1])[:3]
                        world = [0.0, 0.0, 0.0]
                        volumeNode.TransformPointToWorld(origin, world)
                        distances = np.linalg.norm(truePositions - np.array(world), axis=1)
                        self.assertLess(distances.min(), 1e-3,
                                        f"{name}: slice {k} is off with {node.GetName()}")
            os.remove(path)

    @staticmethod
    def _writeMxp(path, members, withCentralDirectory):
        """Write a synthetic `.mxp` archive holding `members` (a name -> bytes mapping).

        With `withCentralDirectory`, the members are written the way 3-matic writes them: the
        local headers carry no sizes (general purpose flag 0x08) and a data descriptor follows
        each member, so the sizes are only in the central directory. Otherwise the sizes go in
        the local headers and no central directory is written, which is the fallback layout.
        """
        import binascii
        entries = []
        out = bytearray()
        for name, content in members.items():
            deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
            data = deflate.compress(content) + deflate.flush()
            crc = binascii.crc32(content) & 0xFFFFFFFF
            encodedName = name.encode("utf-8")
            flags = 0x08 if withCentralDirectory else 0x00
            entries.append((encodedName, data, crc, len(content), flags, len(out)))
            out += _MxpBlobStore.LOCAL_HEADER_SIGNATURE
            out += struct.pack("<HHHHHIIIHH", 20, flags, 8, 0, 0,
                               0 if withCentralDirectory else crc,
                               0 if withCentralDirectory else len(data),
                               0 if withCentralDirectory else len(content),
                               len(encodedName), 0)
            out += encodedName + data
            if withCentralDirectory:
                out += b"PK\x07\x08" + struct.pack("<III", crc, len(data), len(content))

        if withCentralDirectory:
            directoryOffset = len(out)
            for encodedName, data, crc, size, flags, localHeaderOffset in entries:
                out += _MxpBlobStore.CENTRAL_HEADER_SIGNATURE
                out += struct.pack("<HHHHHHIIIHHHHHII", 20, 20, flags, 8, 0, 0, crc, len(data),
                                   size, len(encodedName), 0, 0, 0, 0, 0, localHeaderOffset)
                out += encodedName
            directorySize = len(out) - directoryOffset
            out += _MxpBlobStore.END_RECORD_SIGNATURE
            out += struct.pack("<HHHHIIH", 0, 0, len(entries), len(entries),
                               directorySize, directoryOffset, 0)

        with open(path, "wb") as f:
            f.write(bytes(out))

    def testMxpArchiveLayouts(self):
        """Members are found both when the sizes are in the central directory and when they are
        in the local headers."""
        import tempfile
        members = {
            "preview_256x256": b"",
            "log_data": b"Project created in Mimics Medical 26.0.0\n" * 40,
            "Stl{00000000-0000-0000-0000-000000000001}_vertices":
                np.arange(90, dtype="<i4").tobytes(),
            "Stl{00000000-0000-0000-0000-000000000001}_surfaces":
                np.arange(30, dtype="<i4").tobytes(),
        }
        path = os.path.join(tempfile.gettempdir(), "ImportMimicsTest.mxp")
        for withCentralDirectory in (True, False):
            self.delayDisplay("Reading a synthetic .mxp archive "
                              f"({'central directory' if withCentralDirectory else 'local headers'})")
            self._writeMxp(path, members, withCentralDirectory)
            store = ImportMimicsLogic.openStore(path)
            try:
                self.assertEqual(store.names, set(members))
                self.assertEqual(store.orderedNames, list(members))
                for name, content in members.items():
                    self.assertEqual(store.read(name), content)
                    self.assertEqual(store.peek(name, 16), content[:16])
            finally:
                store.close()
        os.remove(path)
