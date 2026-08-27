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
                                  saveMetadata=saveMetadata)
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
        one pixel-data blob per slice, each prefixed with a 4-byte 'MMFD' magic. A project may
        contain several image blocks. (Mimics .mcs only.)
      - In a Mimics project the blocks are named `blob_0` (headers) + `blob_1`, `blob_2`, ...
        (pixels); in a project exported for Mimics Viewer every blob is named with a GUID and
        only the order of the blobs groups a block together.
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
                      saveMetadata=True):
        """Import a Mimics (.mcs) or 3-matic (.mxp) project. Returns
        (volumeNodes, modelNodes, curveNodes, markupsNodes)."""
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
                images = self.importImages(store, blocks)
                volumeNodes = [volumeNode for volumeNode, _meta in images]
                imageMetas = [meta for _volumeNode, meta in images]
                if imageMetas:
                    metadata["images"] = imageMetas
                    # The image of a single-block project stays available under its old key.
                    metadata["image"] = imageMetas[0]
                    for meta in imageMetas:
                        name = meta.get("name", "image")
                        if meta.get("sliceSpacingError"):
                            self.messages.append(
                                ("error", f"{projectName} ({name}): {meta['sliceSpacingError']}"))
                        elif meta.get("sliceSpacingWarning"):
                            self.messages.append(
                                ("warning", f"{projectName} ({name}): {meta['sliceSpacingWarning']}"))
                if len(imageMetas) < len(blocks):
                    metadata["notes"].append(
                        f"{len(blocks) - len(imageMetas)} of {len(blocks)} image block(s) could "
                        "not be reconstructed (unsupported pixel storage).")
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
                # Not loading into the scene: remove the nodes that were created for export.
                counts = (len(volumeNodes), len(modelNodes), len(curveModelNodes), len(markupsNodes))
                for node in volumeNodes + modelNodes + curveModelNodes + markupsNodes:
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
                # Record slice-spacing warnings/errors found during the header analysis.
                if image.get("sliceSpacingError"):
                    self.messages.append(("error", f"{projectName}: {image['sliceSpacingError']}"))
                elif image.get("sliceSpacingWarning"):
                    self.messages.append(("warning", f"{projectName}: {image['sliceSpacingWarning']}"))
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
        blob0 = store.read(block["header"])
        bounds = self._dicomFileBounds(blob0)
        if not bounds:
            return None
        offsets = bounds[:-1]
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

    # Magic that prefixes every per-slice pixel-data blob.
    PIXEL_DATA_MAGIC = b"MMFD"

    # Blob name of the DICOM headers of the single image block of a plain Mimics project.
    _LEGACY_HEADER_BLOB = "blob_0"

    # `blob_0`, `blob_1`, ... - the blob naming of a plain Mimics project.
    _NUMBERED_BLOB_RE = re.compile(r"^blob_(\d+)$")

    # How far into a blob to look for the 'DICM' marker of its first DICOM file.
    _HEADER_SEARCH_LENGTH = 256

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

    def _imageBlocks(self, store):
        """Return the project's image blocks, in the order they are stored.

        Each block is `{"header": name, "pixels": [name, ...]}`: the blob holding the
        concatenated DICOM headers of the block's slices, and one pixel-data blob per slice.
        A plain Mimics project holds a single block (`blob_0` + `blob_1`, `blob_2`, ...); a
        project exported for Mimics Viewer names every blob with a GUID and may hold several
        blocks (for example one per reconstruction), so those are grouped by blob order: a
        header blob starts a block and the pixel blobs that follow it belong to it.

        Only the first bytes of each blob are decompressed, so this is cheap even for projects
        that hold hundreds of megabytes of pixel data.
        """
        def isPixelData(name):
            return store.peek(name, 4) == self.PIXEL_DATA_MAGIC

        def isHeader(name):
            # The first DICOM file of the blob starts 128 bytes (the preamble) before its 'DICM'
            # marker; a few bytes of Mimics' own may precede that preamble.
            return store.peek(name, self._HEADER_SEARCH_LENGTH).find(b"DICM", 128) >= 0

        # Plain Mimics project: a single block, whose pixel blobs are numbered rather than
        # ordered, so they are collected by name.
        if self._LEGACY_HEADER_BLOB in store.names and isHeader(self._LEGACY_HEADER_BLOB):
            numbered = []
            for name in store.names:
                match = self._NUMBERED_BLOB_RE.match(name)
                if match and name != self._LEGACY_HEADER_BLOB and isPixelData(name):
                    numbered.append((int(match.group(1)), name))
            return [{"header": self._LEGACY_HEADER_BLOB,
                     "pixels": [name for _number, name in sorted(numbered)]}]

        blocks = []
        for name in store.orderedNames:
            # Pixel data is recognized first: its magic is unambiguous, while raw pixel bytes
            # could in principle contain a 'DICM' sequence of their own.
            if isPixelData(name):
                if blocks:
                    blocks[-1]["pixels"].append(name)
            elif isHeader(name):
                blocks.append({"header": name, "pixels": []})
        return blocks

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

        Returns (slices, dicomMeta) where `slices` is a list of (instanceNumber, ipp, pixels, ds)
        sorted spatially along the slice normal, or (None, None) if no image data is available.
        """
        try:
            import pydicom
        except ImportError:
            self.addLog("  WARNING: pydicom is not available; skipping image reconstruction.")
            return None, None

        blob0 = store.read(block["header"])
        bounds = self._dicomFileBounds(blob0)
        if not bounds:
            self.addLog("  No DICOM headers found in image data.")
            return None, None

        nHeaders = len(bounds) - 1
        pixelNames = block["pixels"]
        # A block may be followed by extra blobs that are not slices (a downsampled preview of
        # the block, for example); they come after the slices, so pairing by order ignores them.
        if len(pixelNames) < nHeaders:
            self.addLog(f"  WARNING: {nHeaders} DICOM headers but only {len(pixelNames)} pixel "
                        "blobs; pairing by order.")
        nSlices = min(nHeaders, len(pixelNames))
        self.addLog(f"  Reconstructing {nSlices} slices...")

        import io
        slices = []
        dicomMeta = None
        for k in range(nSlices):
            ds = pydicom.dcmread(io.BytesIO(blob0[bounds[k]:bounds[k + 1]]), force=True)
            rows, cols = int(ds.Rows), int(ds.Columns)
            try:
                pixels = self._decodePixels(store.read(pixelNames[k]), rows, cols)
            except ValueError as e:
                # Unsupported pixel storage for this project. Skip image reconstruction rather
                # than producing a wrong volume.
                self.addLog(f"  WARNING: pixel data of slice {k} could not be decoded ({e}); "
                            "skipping image reconstruction.")
                return None, None
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

    def importImages(self, store, blocks=None):
        """Reconstruct every image block of the project.

        Returns a list of (volumeNode, dicomMeta); blocks that cannot be decoded are skipped.
        """
        if blocks is None:
            blocks = self._imageBlocks(store)
        images = []
        for index, block in enumerate(blocks):
            if len(blocks) > 1:
                self.addLog(f"  Image block {index + 1}/{len(blocks)}:")
            volumeNode, dicomMeta = self.importImage(store, block, index, len(blocks))
            if volumeNode is not None:
                images.append((volumeNode, dicomMeta))
        return images

    def importImage(self, store, block=None, index=0, blockCount=1):
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

        imageName = self._imageName(index, blockCount, dicomMeta["modality"])
        dicomMeta["name"] = imageName
        volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        volumeNode.SetName(imageName)
        slicer.util.updateVolumeFromArray(volumeNode, volumeArray)
        vtkMat = vtk.vtkMatrix4x4()
        for r in range(4):
            for c in range(4):
                vtkMat.SetElement(r, c, ijkToRas[r, c])
        volumeNode.SetIJKToRASMatrix(vtkMat)
        volumeNode.CreateDefaultDisplayNodes()

        # Only the geometry is used in the scene; patient/study/series identifiers are not
        # attached to the node (they remain available only for the opt-in metadata/DICOM export).

        self.addLog(f"  Image '{imageName}': "
                    f"{volumeArray.shape[2]}x{volumeArray.shape[1]}x{volumeArray.shape[0]} "
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

    def exportDicomFiles(self, store, outputDir):
        """Reconstruct the complete original DICOM files (headers + pixel data) and save them.

        Files are written to a `dicom` subfolder, one per slice.
        Returns the number of files written.
        """
        import pydicom

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
                try:
                    ds.save_as(path, enforce_file_format=True)
                except TypeError:
                    # pydicom < 3.0
                    ds.save_as(path, write_like_original=False)
            self.addLog(f"  Saved {len(slices)} original DICOM file(s) to {dicomDir}")
            nWritten += len(slices)
        if not nWritten:
            self.addLog("  No DICOM data to export.")
        return nWritten

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
    def _headerBlob(sliceCount, rows, columns, modality, firstZ, leadingBytes):
        import io
        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset
        data = b"\x00" * leadingBytes
        for k in range(sliceCount):
            ds = Dataset()
            ds.file_meta = FileMetaDataset()
            ds.file_meta.MediaStorageSOPClassUID = pydicom.uid.CTImageStorage
            ds.file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
            ds.file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
            ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
            ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
            ds.Modality = modality
            ds.Rows, ds.Columns = rows, columns
            ds.PixelSpacing = [0.5, 0.5]
            ds.SliceThickness = 1.0
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.ImagePositionPatient = [-10.0, -20.0, firstZ + k]
            ds.InstanceNumber = k + 1
            ds.BitsAllocated, ds.BitsStored, ds.PixelRepresentation = 16, 16, 0
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            buffer = io.BytesIO()
            try:
                ds.save_as(buffer, enforce_file_format=True)
            except TypeError:
                ds.save_as(buffer, write_like_original=False)  # pydicom < 3.0
            data += buffer.getvalue()
        return data

    def _writeProject(self, path, blocks, legacyNames):
        """Write a synthetic `.mcs` project holding the given image blocks (lists of slices)."""
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

        for index, (modality, firstZ, volume) in enumerate(blocks):
            sliceCount, rows, columns = volume.shape
            # A Mimics Viewer project prefixes the first DICOM preamble with a few bytes of its
            # own and names every blob with a GUID; a plain project uses `blob_0`, `blob_1`, ...
            header = self._headerBlob(sliceCount, rows, columns, modality, firstZ,
                                      0 if legacyNames else 8)
            slices = [volume[k].tobytes() if k % 2 else self._encodeSlice(volume[k])
                      for k in range(sliceCount)]
            slices = [(ImportMimicsLogic.PIXEL_DATA_MAGIC + s if k % 2 else s)
                      for k, s in enumerate(slices)]
            if legacyNames:
                # Written out of order, to check that numbered blobs are paired by their number.
                for k in reversed(range(sliceCount)):
                    add(f"blob_{k + 1}", slices[k])
                add("blob_0", header)
            else:
                add(f"ImageBlockPngPreview-0x{index:08X}", b"\x00" * 8 + b"\x89PNG")
                add(str(uuid.uuid4()), header)
                for data in slices:
                    add(str(uuid.uuid4()), data)
                # A block is followed by extra blobs that are not slices.
                add(str(uuid.uuid4()), ImportMimicsLogic.PIXEL_DATA_MAGIC + b"\x00" * 999)
        connection.commit()
        connection.close()

    # -------------------------------------------------------------- tests

    def testImportImageBlocks(self):
        """Both blob layouts and both pixel storage variants reconstruct the exact pixels."""
        import tempfile
        try:
            import pydicom  # noqa: F401 - only needed to know whether the test can run
        except ImportError:
            self.delayDisplay("pydicom is not available; skipping the image import test.")
            return

        rng = np.random.default_rng(0)

        def makeVolume(sliceCount, rows, columns):
            # Smooth along the rows so most differences fit in a byte, with jumps that force the
            # decoder through its absolute-value escape as well.
            volume = np.cumsum(rng.integers(-40, 40, size=(sliceCount, rows, columns)), axis=2)
            volume[:, ::5, ::4] += 900
            return np.clip(volume + 1500, 0, 0x3FFF).astype("<u2")

        for legacyNames in (True, False):
            self.setUp()
            self.delayDisplay(f"Importing a synthetic project "
                              f"({'plain Mimics' if legacyNames else 'Mimics Viewer'} layout)")
            blocks = [("CT", 100.0, makeVolume(4, 16, 16))]
            if not legacyNames:
                blocks.append(("MR", 200.0, makeVolume(3, 12, 20)))
            path = os.path.join(tempfile.gettempdir(), "ImportMimicsTest.mcs")
            self._writeProject(path, blocks, legacyNames)

            volumeNodes, _models, _curves, _markups = ImportMimicsLogic().importProject(
                path, loadIntoScene=True, exportDir=None, exportDicom=False, saveMetadata=False)

            self.assertEqual(len(volumeNodes), len(blocks))
            expectedNames = ["image"] if legacyNames else ["image1_CT", "image2_MR"]
            self.assertEqual([node.GetName() for node in volumeNodes], expectedNames)
            for node, (_modality, firstZ, volume) in zip(volumeNodes, blocks):
                self.assertTrue(np.array_equal(slicer.util.arrayFromVolume(node), volume))
                np.testing.assert_allclose(node.GetSpacing(), (0.5, 0.5, 1.0))
                np.testing.assert_allclose(node.GetOrigin(), (10.0, 20.0, firstZ))
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
