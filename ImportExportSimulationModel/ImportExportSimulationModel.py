import logging
import os
import re

import vtk

import ctk
import qt
import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *

from ImportExportSimulationModelLib import MeshArrays, MeshConversion, MeshWriting
from ImportExportSimulationModelLib.Units import (
    COORDINATE_SYSTEMS, quantityWithLengthExponent, SCENE_COORDINATE_SYSTEM, SCENE_UNIT_SYSTEM,
    UNIT_SYSTEMS,
)
from ImportExportSimulationModelLib.OperationMonitor import OperationMonitor
from ImportExportSimulationModelLib.MeshReduction import (
    DEFAULT_DECIMATION_BOUNDARY_WEIGHT, DEFAULT_DECIMATION_CELL_COUNT_THRESHOLD,
    DEFAULT_DECIMATION_TARGET_REDUCTION, DEFAULT_RESAMPLE_SPACING_MM,
)
from ImportExportSimulationModelLib.MeshReading import (
    APPROXIMATE_RANGE_CELL_COUNT_THRESHOLD, MeshFileReader,
)
from ImportExportSimulationModelLib.MeshWriting import (
    SIMULATION_MODEL_FILE_FORMATS, simulationModelFileFormatById,
)
from ImportExportSimulationModelLib.ModelImport import SimulationModelImporter
from ImportExportSimulationModelLib.WidgetUtils import FileDropEventFilter, OperationProgress
from ImportExportSimulationModelLib.ArrayInfoTable import ArrayInfoTable


# Files of ImportExportSimulationModelLib, in the order they have to be reloaded: a file only uses the files before it.
LIBRARY_SUBMODULE_NAMES = [
    "Units", "MeshArrays", "OperationMonitor", "MeshConversion", "MeshReduction", "MeshReading",
    "MeshWriting", "ModelImport", "WidgetUtils", "ArrayInfoTable",
]


#
# ImportExportSimulationModel
#


class ImportExportSimulationModel(ScriptedLoadableModule):
    """Import and export simulation meshes, converting between coordinate and unit systems."""

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Import/export simulation model")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Cardiac")]
        self.parent.dependencies = ["Sequences"]
        self.parent.contributors = ["Andras Lasso (PerkLab, Queen's University)"]
        self.parent.helpText = _("""
This module imports simulation meshes (surface or volumetric) into the scene and exports models
from the scene, converting between coordinate systems and unit systems. Several files can be
imported at once, and several models can be selected for export in the subject hierarchy tree:
each of them is written to a separate file in the output folder, named after the model.
<p>See the <a href="https://github.com/SlicerHeart/SlicerHeart/blob/master/Docs/ImportExportSimulationModel.md">module documentation</a>
for details on unit guessing, conversion rules, stored unit information, and supported file formats.</p>

<b>Coordinate system:</b> models are always stored in the scene in <b>RAS</b>. If the file uses
<b>LPS</b> (the default assumption, unless the file specifies the coordinate system) then the
first two axes are negated, and every array is rotated accordingly:
<ul>
<li><b>Point coordinates and vectors</b> (velocity, displacement, WSS, ...): the x and y
components are negated. A 2-component array is considered a vector if its quantity is recognized
from its name.</li>
<li><b>Tensors</b> stored as 6-component (symmetric) or 9-component arrays: the components that
mix the third axis with one of the first two are negated (yz, xz, and for a full tensor zy, zx),
which is the T -&gt; R*T*R' rotation of the tensor.</li>
<li><b>Single tensor components</b> stored in an array of their own, named after the component
(Stress_xz, Strain_yz, sigma_xz, ...): negated if that component is negated.</li>
<li><b>Invariants and other scalars</b> (pressure, von Mises stress and strain, principal
stresses and strains, Jacobian, Q-criterion even if stored in several components, ...) and
integer arrays: left unchanged, because they do not depend on the coordinate system.</li>
</ul>
The tooltip of each array name in the table shows how that array is transformed.

<b>Unit system:</b> models are always stored in the scene in the <b>mm-g-s</b> system, because
Slicer works in mm. Values read from a file in the <b>CGS</b> (cm-g-s) system are scaled by
10<sup>e</sup>, where <i>e</i> is the length exponent of the quantity (for example, x10 for a
velocity in cm/s, x0.1 for a pressure in dyn/cm2, x0.001 for a density in g/cm3). The mass (g)
and time (s) units are the same in both systems, so the length exponent alone determines the
conversion factor.

The quantity of each array is guessed from the array name and can be corrected in the arrays
table before importing. Any prefix and any suffix of the name is ignored, so the quantity is
recognized wherever it is in the name: <i>Stress</i>, <i>Stress_xx</i>, <i>solid_Stress_1</i>,
and <i>VonMisesStress</i> are all recognized as a stress. The unit and the length exponent of the point coordinates and of every
array are stored in the imported model as node attributes (visible in the Data module), and are
used when the model is exported again.

<b>Merge duplicate points:</b> simulation results often store a separate copy of a point for each
cell that uses it. By default, copies at the same position with exactly the same values in all
point data arrays are merged on import, which can reduce the memory use several-fold without
changing any value. The option is in the Advanced section of the import section.

<b>Decimate large meshes:</b> by default, tetrahedral meshes with more cells than a threshold are
decimated on import. The shape of the boundary is preserved and data arrays are transferred to the
result, but this reduces the resolution of the data, unlike merging duplicate points. The threshold,
the target reduction, and the boundary weight can be set in the Advanced section.

<b>Resample uniformly:</b> optionally, volumetric meshes are replaced on import by cubes of the
chosen size, aligned with the axes. The volume is preserved, but the boundary becomes a staircase
and details smaller than a cube are lost. Decimation is not used for meshes that are resampled.

<b>First time point, keep 1 of every N time points:</b> the Advanced section can also reduce the
number of time points that are loaded from a VTKHDF file. By default, all of them are loaded.

<b>Approximate scalar ranges:</b> by default, a large VTKHDF file is listed in the arrays table
without reading all of its data, so that adding the file takes seconds. The range of the point
coordinates remains exact, but the ranges of data arrays are computed from a sample of the file,
they are marked with ~ and can be much narrower than the true ranges. This does not affect the import.

<b>Cancelling:</b> a progress bar is shown in the Status section during import and export, with a
Cancel button. The file that is being processed is abandoned and the files that have been completed
are kept. Some steps cannot be interrupted (a decimation pass, for example), they are finished first.
A file is added to the input file list when it has been read. Reading can be cancelled the same
way, the files that have not been read by then are not added.

<b>Supported file formats:</b> .vtu, .vtp, .vtk, .vtkhdf, .vtkhdf5, .vti, .stl, .ply, and .obj can
be read. A .vtkhdf or .vtkhdf5 file with several time points is loaded as a sequence of models with
a sequence browser, each time point converted the same way. A .vti file is loaded as a volume, with
its origin and spacing converted to the coordinate and unit system of the scene. For writing,
the format is selected by name and the extension follows from the mesh: <b>VTK (XML)</b> writes a
surface mesh to .vtp and a volumetric mesh to .vtu, <b>VTK (classic)</b> writes both to .vtk, and
<b>PLY</b>, <b>OBJ</b>, and <b>STL</b> store a surface only, without data arrays.
""")
        self.parent.acknowledgementText = _("""
This file was originally developed by Andras Lasso (PerkLab, Queen's University).
""")


#
# ImportExportSimulationModelWidget
#


class ImportExportSimulationModelWidget(ScriptedLoadableModuleWidget):

    SETTINGS_PREFIX = "ImportExportSimulationModel/"
    # Reading of input files is often immediate, its progress is shown only if it takes longer than this (seconds).
    PROGRESS_DISPLAY_DELAY = 0.5

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.logic = None
        # Runs the operations of the logic, showing their progress and log in the Status section
        self._progress = None
        # Arrays of the input files and of the models that are selected for export
        self._importTable = None
        self._exportTable = None
        self._updatingGui = False
        self._updatingSections = False
        self._dropEventFilter = None

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/ImportExportSimulationModel.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = ImportExportSimulationModelLogic()
        self._progress = OperationProgress(
            self.logic.monitor, self.ui.progressBar, self.ui.cancelButton, self.ui.statusTextEdit,
            self.ui.statusCollapsibleButton)
        self.logic.logCallback = self._progress.addLog

        for comboBox in (self.ui.inputCoordinateSystemComboBox, self.ui.outputCoordinateSystemComboBox):
            for coordinateSystem in COORDINATE_SYSTEMS:
                comboBox.addItem(coordinateSystem, coordinateSystem)
        for comboBox in (self.ui.inputUnitSystemComboBox, self.ui.outputUnitSystemComboBox):
            for unitSystem, properties in UNIT_SYSTEMS.items():
                comboBox.addItem(properties["name"], unitSystem)

        # Import scales the values from the unit system of the file to the one of the scene,
        # export scales them the other way round.
        self._importTable = ArrayInfoTable(self.ui.importTableWidget, _("Scale to Slicer"), unitsEditable=True)
        self._exportTable = ArrayInfoTable(self.ui.exportTableWidget, _("Scale from Slicer"))

        # Files can be dropped on the file list. Virtual method overrides of Qt classes are not
        # available in Python, therefore drag and drop is implemented in an event filter.
        # The files are read after the drop is completed, so that the application that the files
        # were dragged from does not have to wait for it.
        self._dropEventFilter = FileDropEventFilter(
            ImportExportSimulationModelLogic.READ_FILE_EXTENSIONS,
            lambda filePaths: qt.QTimer.singleShot(0, lambda: self.addInputFiles(filePaths)))
        self.ui.inputFilesListWidget.installEventFilter(self._dropEventFilter)

        # Several models can be selected for export. Selecting a folder exports everything in it.
        treeView = self.ui.exportModelTreeView
        treeView.nodeTypes = ["vtkMRMLModelNode"]
        treeView.multiSelection = True
        treeView.setColumnHidden(treeView.model().transformColumn, True)
        treeView.setColumnHidden(treeView.model().idColumn, True)

        self.ui.outputFolderPathLineEdit.filters = ctk.ctkPathLineEdit.Dirs
        for index, fileFormat in enumerate(SIMULATION_MODEL_FILE_FORMATS):
            self.ui.outputFileFormatComboBox.addItem(fileFormat.name, fileFormat.formatId)
            self.ui.outputFileFormatComboBox.setItemData(
                index, _("File extension: {extensions}").format(
                    extensions=", ".join(fileFormat.extensions)), qt.Qt.ToolTipRole)

        self.ui.addFilesButton.connect("clicked(bool)", self.onAddFilesButton)
        self.ui.removeFilesButton.connect("clicked(bool)", self.onRemoveFilesButton)
        self.ui.inputCoordinateSystemComboBox.connect("currentIndexChanged(int)", self._onImportConversionChanged)
        self.ui.inputUnitSystemComboBox.connect("currentIndexChanged(int)", self._onImportConversionChanged)
        self.ui.mergeDuplicatePointsCheckBox.connect("toggled(bool)", self._onImportOptionChanged)
        self.ui.decimateCheckBox.connect("toggled(bool)", self._onDecimateToggled)
        self.ui.decimationThresholdSpinBox.connect("valueChanged(int)", self._onImportOptionChanged)
        self.ui.decimationTargetReductionSpinBox.connect("valueChanged(int)", self._onImportOptionChanged)
        self.ui.decimationBoundaryWeightSpinBox.connect("valueChanged(double)", self._onImportOptionChanged)
        self.ui.firstTimePointIndexSpinBox.connect("valueChanged(int)", self._onImportOptionChanged)
        self.ui.keepEveryNthTimePointSpinBox.connect("valueChanged(int)", self._onImportOptionChanged)
        self.ui.resampleCheckBox.connect("toggled(bool)", self._onResampleToggled)
        self.ui.resampleSpacingSpinBox.connect("valueChanged(double)", self._onImportOptionChanged)
        self.ui.approximateRangesCheckBox.connect("toggled(bool)", self._onApproximateRangesToggled)
        self.ui.importButton.connect("clicked(bool)", self.onImportButton)

        self.ui.exportModelTreeView.connect("currentItemsChanged(QList<vtkIdType>)",
                                            self._onExportModelChanged)
        self.ui.outputCoordinateSystemComboBox.connect("currentIndexChanged(int)", self._onExportOptionChanged)
        self.ui.outputUnitSystemComboBox.connect("currentIndexChanged(int)", self._onExportOptionChanged)
        self.ui.outputFileFormatComboBox.connect("currentIndexChanged(int)", self._onExportOptionChanged)
        self.ui.outputFolderPathLineEdit.connect("currentPathChanged(QString)", self._onExportOptionChanged)
        self.ui.exportButton.connect("clicked(bool)", self.onExportButton)

        # Importing and exporting are separate tasks, so only one section is open at a time.
        self.ui.importCollapsibleButton.connect(
            "contentsCollapsed(bool)",
            lambda collapsed: self._onSectionCollapsed(collapsed, self.ui.exportCollapsibleButton))
        self.ui.exportCollapsibleButton.connect(
            "contentsCollapsed(bool)",
            lambda collapsed: self._onSectionCollapsed(collapsed, self.ui.importCollapsibleButton))

        self._restoreSettings()
        self._updateImportTable()
        self._updateExportTable()

    def onReload(self) -> None:
        """Reload the module, including the files of its library (for development)."""
        import importlib
        import sys
        for submoduleName in LIBRARY_SUBMODULE_NAMES:
            submodule = sys.modules.get("ImportExportSimulationModelLib." + submoduleName)
            if submodule is not None:
                importlib.reload(submodule)
        ScriptedLoadableModuleWidget.onReload(self)

    def cleanup(self) -> None:
        """Release everything that keeps a reference to this widget, to the scene, or to the
        meshes that were read.

        This is called when the module is unloaded, which may happen after the widgets have
        already been destroyed, and it may be called more than once.
        """
        try:
            if self._dropEventFilter is not None:
                self.ui.inputFilesListWidget.removeEventFilter(self._dropEventFilter)
            if self._progress is not None:
                self._progress.disconnect()
            # The tree view observes the scene, release it so that the scene can be destroyed.
            self.ui.exportModelTreeView.setMRMLScene(None)
        except (ValueError, RuntimeError):
            # The widgets have already been destroyed, so they hold nothing any more.
            pass
        if self._dropEventFilter is not None:
            self._dropEventFilter.onFilesDropped = None
            self._dropEventFilter = None
        if self.logic is not None:
            self.logic.logCallback = None
            self.logic.clearCache()
        self._progress = None
        for table in (self._importTable, self._exportTable):
            if table is not None:
                table.arrayInfos = []

    def _onSectionCollapsed(self, collapsed, otherSection) -> None:
        """Close the other section when a section is opened, so only one of them is open.

        Closing a section does not open the other one: the user may want to see neither.
        """
        if collapsed or self._updatingGui or self._updatingSections:
            return
        self._updatingSections = True
        try:
            otherSection.collapsed = True
        finally:
            self._updatingSections = False
        self._saveSettings()

    # ------------------------------------------------------------------ settings

    def _saveSettings(self) -> None:
        settings = slicer.app.userSettings()
        settings.setValue(self.SETTINGS_PREFIX + "inputCoordinateSystem", self.inputCoordinateSystem)
        settings.setValue(self.SETTINGS_PREFIX + "inputUnitSystem", self.inputUnitSystem)
        settings.setValue(self.SETTINGS_PREFIX + "mergeDuplicatePoints",
                          self.ui.mergeDuplicatePointsCheckBox.checked)
        settings.setValue(self.SETTINGS_PREFIX + "decimate", self.ui.decimateCheckBox.checked)
        settings.setValue(self.SETTINGS_PREFIX + "decimationThreshold",
                          self.ui.decimationThresholdSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "decimationTargetReductionPercent",
                          self.ui.decimationTargetReductionSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "decimationBoundaryWeight",
                          self.ui.decimationBoundaryWeightSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "resample", self.ui.resampleCheckBox.checked)
        settings.setValue(self.SETTINGS_PREFIX + "resampleSpacing", self.ui.resampleSpacingSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "firstTimePointIndex",
                          self.ui.firstTimePointIndexSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "keepEveryNthTimePoint",
                          self.ui.keepEveryNthTimePointSpinBox.value)
        settings.setValue(self.SETTINGS_PREFIX + "approximateRanges",
                          self.ui.approximateRangesCheckBox.checked)
        settings.setValue(self.SETTINGS_PREFIX + "outputCoordinateSystem", self.outputCoordinateSystem)
        settings.setValue(self.SETTINGS_PREFIX + "outputUnitSystem", self.outputUnitSystem)
        settings.setValue(self.SETTINGS_PREFIX + "outputFileFormat", self.outputFileFormat)
        settings.setValue(self.SETTINGS_PREFIX + "outputFolder",
                          self.ui.outputFolderPathLineEdit.currentPath)
        if not self.ui.importCollapsibleButton.collapsed:
            openSection = "import"
        elif not self.ui.exportCollapsibleButton.collapsed:
            openSection = "export"
        else:
            openSection = "none"
        settings.setValue(self.SETTINGS_PREFIX + "openSection", openSection)

    def _restoreSettings(self) -> None:
        self._updatingGui = True
        try:
            # LPS and CGS are the most common conventions in simulation software, therefore they
            # are the defaults.
            self._setComboBoxValue(self.ui.inputCoordinateSystemComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "inputCoordinateSystem", "LPS"))
            self._setComboBoxValue(self.ui.inputUnitSystemComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "inputUnitSystem", "cgs"))
            self.ui.mergeDuplicatePointsCheckBox.checked = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "mergeDuplicatePoints", True, converter=slicer.util.toBool)
            self.ui.decimateCheckBox.checked = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "decimate", True, converter=slicer.util.toBool)
            self.ui.decimationThresholdSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "decimationThreshold", DEFAULT_DECIMATION_CELL_COUNT_THRESHOLD,
                converter=int)
            self.ui.decimationTargetReductionSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "decimationTargetReductionPercent",
                int(DEFAULT_DECIMATION_TARGET_REDUCTION * 100), converter=int)
            self.ui.decimationBoundaryWeightSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "decimationBoundaryWeight", DEFAULT_DECIMATION_BOUNDARY_WEIGHT,
                converter=float)
            self.ui.resampleCheckBox.checked = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "resample", False, converter=slicer.util.toBool)
            self.ui.resampleSpacingSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "resampleSpacing", DEFAULT_RESAMPLE_SPACING_MM, converter=float)
            self._updateDecimationWidgets()
            self.ui.firstTimePointIndexSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "firstTimePointIndex", 0, converter=int)
            self.ui.keepEveryNthTimePointSpinBox.value = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "keepEveryNthTimePoint", 1, converter=int)
            self.ui.approximateRangesCheckBox.checked = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "approximateRanges", True, converter=slicer.util.toBool)
            self._setComboBoxValue(self.ui.outputCoordinateSystemComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "outputCoordinateSystem", "LPS"))
            self._setComboBoxValue(self.ui.outputUnitSystemComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "outputUnitSystem", "cgs"))
            self._setComboBoxValue(self.ui.outputFileFormatComboBox, slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "outputFileFormat", "vtkxml"))
            self.ui.outputFolderPathLineEdit.currentPath = slicer.util.settingsValue(
                self.SETTINGS_PREFIX + "outputFolder", "")
            openSection = slicer.util.settingsValue(self.SETTINGS_PREFIX + "openSection", "import")
            self.ui.importCollapsibleButton.collapsed = (openSection != "import")
            self.ui.exportCollapsibleButton.collapsed = (openSection != "export")
        finally:
            self._updatingGui = False

    @staticmethod
    def _setComboBoxValue(comboBox, value) -> None:
        index = comboBox.findData(value)
        if index >= 0:
            comboBox.currentIndex = index

    # ------------------------------------------------------------------ current GUI state

    @property
    def inputCoordinateSystem(self):
        return self.ui.inputCoordinateSystemComboBox.currentData

    @property
    def inputUnitSystem(self):
        return self.ui.inputUnitSystemComboBox.currentData

    @property
    def outputCoordinateSystem(self):
        return self.ui.outputCoordinateSystemComboBox.currentData

    @property
    def outputUnitSystem(self):
        return self.ui.outputUnitSystemComboBox.currentData

    @property
    def outputFileFormat(self):
        return self.ui.outputFileFormatComboBox.currentData

    @property
    def selectedExportModelNodes(self):
        """Model nodes selected in the tree view, including the contents of selected folders."""
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        if subjectHierarchyNode is None:
            return []
        selectedItemIds = vtk.vtkIdList()
        self.ui.exportModelTreeView.currentItems(selectedItemIds)

        # Selecting a folder (or the scene) means exporting every model in it.
        itemIds = []
        for index in range(selectedItemIds.GetNumberOfIds()):
            itemId = selectedItemIds.GetId(index)
            itemIds.append(itemId)
            childItemIds = vtk.vtkIdList()
            subjectHierarchyNode.GetItemChildren(itemId, childItemIds, True)
            for childIndex in range(childItemIds.GetNumberOfIds()):
                itemIds.append(childItemIds.GetId(childIndex))

        modelNodes = []
        for itemId in itemIds:
            node = subjectHierarchyNode.GetItemDataNode(itemId)
            if node is not None and node.IsA("vtkMRMLModelNode") and node not in modelNodes:
                modelNodes.append(node)
        # The selection order is the order in which the items were clicked, sort by name so that
        # the exported files are listed and reported in a predictable order.
        modelNodes.sort(key=lambda node: node.GetName())
        return modelNodes

    @property
    def inputFilePaths(self):
        listWidget = self.ui.inputFilesListWidget
        return [listWidget.item(row).data(qt.Qt.UserRole) for row in range(listWidget.count)]

    # ------------------------------------------------------------------ input file list

    def addInputFiles(self, filePaths) -> None:
        """Add files to the input file list, skipping files that are already in the list.

        Each file is added to the list when it has been read, so that the list never contains
        a file that is not taken into account in the arrays table. If reading of a file fails or
        the user cancels it, then that file and the files after it are not added.
        """
        existingFilePaths = self.inputFilePaths
        addedFilePaths = []
        for filePath in filePaths:
            filePath = os.path.normpath(filePath)
            if filePath in existingFilePaths or filePath in addedFilePaths:
                continue
            addedFilePaths.append(filePath)
        if not addedFilePaths:
            return

        def onFileCompleted(filePath, arrayInfos) -> None:
            if filePath not in addedFilePaths:
                return
            item = qt.QListWidgetItem(os.path.basename(filePath))
            item.setData(qt.Qt.UserRole, filePath)
            item.setToolTip(filePath)
            self.ui.inputFilesListWidget.addItem(item)
            # The files that were already in the list are processed before the added ones,
            # so this is the array information of the files that are in the list now.
            self._updateImportTable(arrayInfos)

        self._readArrayInfos(existingFilePaths + addedFilePaths, onFileCompleted)

    def onAddFilesButton(self) -> None:
        lastDirectory = slicer.util.settingsValue(self.SETTINGS_PREFIX + "lastInputDirectory", "")
        filePaths = qt.QFileDialog.getOpenFileNames(
            self.parent, _("Select simulation mesh files"), lastDirectory,
            ImportExportSimulationModelLogic.readFileNameFilter())
        if not filePaths:
            return
        slicer.app.userSettings().setValue(
            self.SETTINGS_PREFIX + "lastInputDirectory", os.path.dirname(filePaths[0]))
        self.addInputFiles(filePaths)

    def onRemoveFilesButton(self) -> None:
        listWidget = self.ui.inputFilesListWidget
        selectedItems = listWidget.selectedItems()
        if not selectedItems:
            listWidget.clear()
        else:
            for item in selectedItems:
                listWidget.takeItem(listWidget.row(item))
        self._updateImportTable()

    # ------------------------------------------------------------------ import table

    def _onImportOptionChanged(self, *unused) -> None:
        if self._updatingGui:
            return
        self._saveSettings()

    def _onImportConversionChanged(self, *unused) -> None:
        """The coordinate system or the unit system of the input files is changed."""
        if self._updatingGui:
            return
        self._saveSettings()
        # Only the displayed units, scales, and negated components change, the arrays themselves
        # do not, therefore the input files do not have to be read again.
        self._importTable.setConversion(
            self.inputUnitSystem, SCENE_UNIT_SYSTEM, self.inputCoordinateSystem != SCENE_COORDINATE_SYSTEM)

    def _onApproximateRangesToggled(self, *unused) -> None:
        if self._updatingGui:
            return
        self._saveSettings()
        if self._updateImportTable():
            # Cancelled: the option is restored, the files have already been read with that.
            wasUpdatingGui = self._updatingGui
            self._updatingGui = True
            self.ui.approximateRangesCheckBox.checked = not self.ui.approximateRangesCheckBox.checked
            self._updatingGui = wasUpdatingGui
            self._saveSettings()
            self._updateImportTable()

    def _onDecimateToggled(self, *unused) -> None:
        self._updateDecimationWidgets()
        self._onImportOptionChanged()

    def _onResampleToggled(self, *unused) -> None:
        self._updateDecimationWidgets()
        self._onImportOptionChanged()

    def _updateDecimationWidgets(self) -> None:
        # Every mesh that could be decimated is resampled instead, if resampling is enabled.
        resample = self.ui.resampleCheckBox.checked
        self.ui.label_decimate.enabled = not resample
        self.ui.decimateCheckBox.enabled = not resample
        enabled = self.ui.decimateCheckBox.checked and not resample
        for widget in (self.ui.label_decimationThreshold, self.ui.decimationThresholdSpinBox,
                       self.ui.label_decimationTargetReduction, self.ui.decimationTargetReductionSpinBox,
                       self.ui.label_decimationBoundaryWeight, self.ui.decimationBoundaryWeightSpinBox):
            widget.enabled = enabled
        self.ui.label_resampleSpacing.enabled = resample
        self.ui.resampleSpacingSpinBox.enabled = resample

    def _readArrayInfos(self, filePaths, fileCompletedCallback=None):
        """Read the coordinates and data arrays of files, showing the progress if it takes long.

        :param fileCompletedCallback: called when a file has been processed, with the file path
            and the array information of the files that have been processed by then.
        :return: list of array information (None if reading failed or it was cancelled), and
            True if the user cancelled reading.
        """
        if not filePaths:
            return [], False
        result = {"arrayInfos": None}

        def readArrayInfos() -> None:
            result["arrayInfos"] = self.logic.getArrayInfosFromFiles(
                filePaths,
                APPROXIMATE_RANGE_CELL_COUNT_THRESHOLD if self.ui.approximateRangesCheckBox.checked else None,
                fileCompletedCallback)

        # Files that have been read before are not read again: the progress is not shown then,
        # and the log of the previous operation is kept.
        wasCancelled = self._progress.run(
            readArrayInfos, _("Failed to read input files."), _("Reading of the input files was cancelled."),
            clearLog=False, displayDelay=self.PROGRESS_DISPLAY_DELAY)
        return result["arrayInfos"], wasCancelled

    def _updateImportTable(self, arrayInfos=None) -> bool:
        """Show the coordinates and data arrays of the input files in the table.

        :param arrayInfos: array information of the input files, if they have been read already.
            By default the files are read.
        :return: True if the user cancelled reading of the files. The table is empty then.
        """
        filePaths = self.inputFilePaths
        wasCancelled = False
        if arrayInfos is None:
            arrayInfos, wasCancelled = self._readArrayInfos(filePaths)
        self._importTable.setArrayInfos(
            arrayInfos or [], self.inputUnitSystem, SCENE_UNIT_SYSTEM,
            self.inputCoordinateSystem != SCENE_COORDINATE_SYSTEM)

        self.ui.importButton.enabled = bool(filePaths) and bool(self._importTable.arrayInfos)
        return wasCancelled

    def onImportButton(self) -> None:
        self._progress.run(
            lambda: self._importFiles(), _("Failed to import simulation model."), _("Import was cancelled."))

    def _importFiles(self) -> None:
        # The units that the user chose in the table
        quantities = {arrayInfo.key: arrayInfo.simulationUnit.quantity
                      for arrayInfo in self._importTable.arrayInfos}
        importedNodes = self.logic.importFiles(
            self.inputFilePaths, self.inputCoordinateSystem, self.inputUnitSystem, quantities,
            self.ui.mergeDuplicatePointsCheckBox.checked,
            self.ui.decimationThresholdSpinBox.value if self.ui.decimateCheckBox.checked else None,
            self.ui.decimationTargetReductionSpinBox.value / 100.0,
            self.ui.decimationBoundaryWeightSpinBox.value,
            self.ui.keepEveryNthTimePointSpinBox.value,
            self.ui.firstTimePointIndexSpinBox.value,
            self.ui.resampleSpacingSpinBox.value if self.ui.resampleCheckBox.checked else None)
        # Only models can be exported, volumes that were imported from images cannot.
        modelNodes = [node for node in importedNodes if node.IsA("vtkMRMLModelNode")]
        if modelNodes:
            # Preselect the imported models for export.
            itemIds = vtk.vtkIdList()
            subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            if subjectHierarchyNode is not None:
                for modelNode in modelNodes:
                    itemIds.InsertNextId(subjectHierarchyNode.GetItemByDataNode(modelNode))
                self.ui.exportModelTreeView.setCurrentItems(itemIds)

    # ------------------------------------------------------------------ export table

    def _onExportModelChanged(self, *unused) -> None:
        self._updateExportTable()

    def _onExportOptionChanged(self, *unused) -> None:
        if self._updatingGui:
            return
        self._saveSettings()
        self._updateExportTable()

    def _updateExportTable(self) -> None:
        """Show the coordinates and data arrays of all selected models in the export table.

        An array that several models have is listed once, with the value range covering all of
        them, the same way as arrays of several input files are listed in the import table.
        """
        modelNodes = self.selectedExportModelNodes
        # Models are normally all in the scene unit system and coordinate system, but a model may
        # have been changed by hand.
        arrayInfos, arrayUnitSystems = self.logic.getArrayInfosFromModels(modelNodes)
        flipFirstTwoComponents = any(
            self.outputCoordinateSystem != self.logic.getModelCoordinateSystem(modelNode)
            for modelNode in modelNodes)
        # Units are not editable here: they are the units stored in the model at import time.
        self._exportTable.setArrayInfos(
            arrayInfos, arrayUnitSystems, self.outputUnitSystem, flipFirstTwoComponents)

        self.ui.exportButton.text = (_("Export {count} models").format(count=len(modelNodes))
                                     if len(modelNodes) > 1 else _("Export"))
        self.ui.exportButton.enabled = (bool(modelNodes)
                                        and bool(self.ui.outputFolderPathLineEdit.currentPath))

    def onExportButton(self) -> None:
        self._progress.run(
            lambda: self._exportModels(), _("Failed to export simulation model."), _("Export was cancelled."))

    def _exportModels(self) -> None:
        self.logic.exportModels(
            self.selectedExportModelNodes,
            self.ui.outputFolderPathLineEdit.currentPath,
            self.outputFileFormat,
            self.outputCoordinateSystem, self.outputUnitSystem)


#
# ImportExportSimulationModelLogic
#


class ImportExportSimulationModelLogic(ScriptedLoadableModuleLogic):
    """Imports simulation mesh files into the scene and exports models into simulation mesh files,
    converting between coordinate systems and unit systems.

    These are the features that other modules can use:

    - importFiles: read files (meshes, time series, images), convert them, and add them to the scene.
    - exportModels, exportModel: convert models and write them into files.
    - getArrayInfosFromFiles, getArrayInfosFromModels, getArrayInfosFromModel: list the point
      coordinates and data arrays of files and of models, with their units.
    - getModelUnitSystem, getModelCoordinateSystem: what a model in the scene is stored in.
    - readMesh, writeMesh, convertMesh: read, write, and convert a mesh without using the scene.
    - monitor: reports the progress of these operations and lets them be cancelled, see OperationMonitor.
    - logCallback: called with each message that describes what is being done.

    The implementation is in the files of ImportExportSimulationModelLib: units and descriptions
    of arrays (Units.py, MeshArrays.py), operations on meshes that do not use the scene
    (MeshReading.py, MeshWriting.py, MeshConversion.py, MeshReduction.py), and import of a file
    into the scene (ModelImport.py).
    """

    # Prefix of the node attributes that store the units of a model, see MeshArrays.py.
    ATTRIBUTE_PREFIX = MeshArrays.ATTRIBUTE_PREFIX
    READ_FILE_EXTENSIONS = MeshFileReader.READ_FILE_EXTENSIONS
    WRITE_FILE_EXTENSIONS = MeshWriting.WRITE_FILE_EXTENSIONS

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self.logCallback = None
        self.monitor = OperationMonitor()
        # Reads the input files and keeps their meshes until they are imported.
        self.reader = MeshFileReader(self.addLog, self.monitor)

    def addLog(self, text) -> None:
        logging.info(text)
        if self.logCallback:
            self.logCallback(text)

    # ------------------------------------------------------------------ import

    def importFiles(self, filePaths, coordinateSystem, unitSystem, arrayQuantities=None,
                    mergeDuplicatePoints=True,
                    decimationCellCountThreshold=DEFAULT_DECIMATION_CELL_COUNT_THRESHOLD,
                    decimationTargetReduction=DEFAULT_DECIMATION_TARGET_REDUCTION,
                    decimationBoundaryWeight=DEFAULT_DECIMATION_BOUNDARY_WEIGHT,
                    keepEveryNthTimePoint=1, firstTimePointIndex=0, resampleSpacing=None):
        """Load mesh and image files into the scene.

        A mesh is loaded as a model node. A VTKHDF file with several time points is loaded as a
        sequence of models with a sequence browser. A .vti image is loaded as a volume node.

        :param coordinateSystem: coordinate system of the files (RAS or LPS). Nodes are always
            loaded into the scene in RAS.
        :param unitSystem: unit system of the files. Nodes are always loaded into the scene in
            the mm-g-s system.
        :param arrayQuantities: (location, name) -> quantity name. Arrays that are not in the
            dictionary get their unit guessed from the array name.
        :param mergeDuplicatePoints: merge the points of meshes that have the same position and the
            same values, see MeshReduction.mergeDuplicatePoints.
        :param decimationCellCountThreshold: tetrahedral meshes that have more cells than this are
            decimated, see TetrahedralMeshDecimator. None disables decimation.
        :param decimationTargetReduction: fraction of the cells to remove from a decimated mesh.
        :param decimationBoundaryWeight: how strongly the boundary of a decimated mesh is preserved.
        :param keepEveryNthTimePoint: load only the first of every N time points of a time series.
        :param firstTimePointIndex: index of the first time point to load from a time series,
            starting from 0.
        :param resampleSpacing: replace the cells of volumetric meshes with cubes of this size, in
            mm, instead of decimating them. None to not resample.
        :return: list of the created model nodes (the proxy model node of a sequence) and volume
            nodes.
        :raises OperationCancelledError: if the import was cancelled, see OperationMonitor. The file
            that was being imported is not loaded, the files imported before it remain in the scene.
        """
        self.monitor.reset()
        if not filePaths:
            raise ValueError(_("No input file is specified"))
        importer = SimulationModelImporter(
            self.reader, coordinateSystem, unitSystem, arrayQuantities, mergeDuplicatePoints,
            decimationCellCountThreshold, decimationTargetReduction, decimationBoundaryWeight,
            keepEveryNthTimePoint, firstTimePointIndex, resampleSpacing, self.addLog, self.monitor)

        importedNodes = []
        for filePath in filePaths:
            self.monitor.check()
            importedNodes.extend(importer.importFile(filePath))

        # Simulation meshes can be very large (hundreds of MB), therefore the meshes that were
        # read for populating the arrays table are released as soon as they have been imported.
        # The arrays table remains valid, it does not need the meshes any more.
        self.reader.clearCache()

        self.addLog(_("Imported {count} node(s).").format(count=len(importedNodes)))
        return importedNodes

    # ------------------------------------------------------------------ export

    @staticmethod
    def fileNameFromNodeName(nodeName):
        """File name (without extension) for a model, safe to use on any file system."""
        fileName = re.sub(r'[\\\\/:*?"<>|]+', "_", nodeName).strip(" .")
        return fileName or "model"

    def exportModels(self, modelNodes, outputDirectory, fileFormatId,
                     coordinateSystem, unitSystem):
        """Write each model to a separate file in the output folder, named after the model.

        The file extension is determined by the file format and by the mesh of each model: a
        surface mesh and a volumetric mesh are written to different file types by the VTK
        formats (.vtp and .vtu for VTK (XML), for example).

        :return: list of the written file paths.
        :raises OperationCancelledError: if the export was cancelled, see OperationMonitor. The file
            that was being written is removed, the files written before it are kept.
        """
        self.monitor.reset()
        if not modelNodes:
            raise ValueError(_("No model is selected"))
        if not outputDirectory:
            raise ValueError(_("No output folder is specified"))
        fileFormat = simulationModelFileFormatById(fileFormatId)
        if fileFormat is None:
            raise ValueError(_("Unsupported file format: {fileFormatId}").format(
                fileFormatId=fileFormatId))
        if not os.path.isdir(outputDirectory):
            os.makedirs(outputDirectory)

        filePaths = []
        usedFileNames = set()
        for modelNode in modelNodes:
            self.monitor.check()
            fileName = self.fileNameFromNodeName(modelNode.GetName())
            extension = fileFormat.extension(modelNode.GetMesh())
            # Two nodes may have the same name; make sure that they do not overwrite each other.
            uniqueFileName = fileName
            index = 1
            while (uniqueFileName + extension).lower() in usedFileNames:
                index += 1
                uniqueFileName = "%s_%d" % (fileName, index)
            usedFileNames.add((uniqueFileName + extension).lower())
            filePath = os.path.join(outputDirectory, uniqueFileName + extension)
            self.exportModel(modelNode, filePath, coordinateSystem, unitSystem)
            filePaths.append(filePath)

        self.addLog(_("Exported {count} model(s) to {outputDirectory}").format(
            count=len(filePaths), outputDirectory=outputDirectory))
        return filePaths

    def exportModel(self, modelNode, filePath, coordinateSystem, unitSystem):
        """Write a model to file, converting it to the given coordinate and unit system."""
        if modelNode is None:
            raise ValueError(_("No model is selected"))
        if not filePath:
            raise ValueError(_("No output file is specified"))
        if coordinateSystem not in COORDINATE_SYSTEMS:
            raise ValueError(_("Invalid coordinate system: {coordinateSystem}").format(
                coordinateSystem=coordinateSystem))
        if unitSystem not in UNIT_SYSTEMS:
            raise ValueError(_("Invalid unit system: {unitSystem}").format(unitSystem=unitSystem))
        mesh = modelNode.GetMesh()
        if mesh is None:
            raise ValueError(_("The selected model contains no mesh"))

        modelUnitSystem = MeshArrays.getModelUnitSystem(modelNode)
        modelCoordinateSystem = MeshArrays.getModelCoordinateSystem(modelNode)
        flipFirstTwoComponents = (coordinateSystem != modelCoordinateSystem)

        arrayInfos = MeshArrays.getArrayInfosFromModel(modelNode)
        # Units that are not known by this module (custom units read from the model node) have no
        # quantity name, so their length exponent is passed to the conversion using a temporary
        # quantity that has the same exponent.
        quantities = {}
        for arrayInfo in arrayInfos:
            simulationUnit = arrayInfo.simulationUnit
            quantity = simulationUnit.quantity
            if quantity is None:
                quantity = quantityWithLengthExponent(simulationUnit.lengthExponent)
            quantities[arrayInfo.key] = quantity

        self.addLog(_("Exporting {name} to {filePath}").format(
            name=modelNode.GetName(), filePath=filePath))
        convertedMesh = MeshConversion.convertMesh(mesh, quantities, flipFirstTwoComponents,
                                                   modelUnitSystem, unitSystem)
        self.monitor.check()
        self.writeMesh(convertedMesh, filePath)
        for description in MeshArrays.conversionDescriptions(
                arrayInfos, modelUnitSystem, unitSystem, flipFirstTwoComponents):
            self.addLog("  " + description)

    # ------------------------------------------------------------------ arrays and their units

    def getArrayInfosFromFiles(self, filePaths, approximateRangeCellCountThreshold=None,
                               fileCompletedCallback=None):
        """Coordinates and data arrays of files, merged into a single list of MeshArrayInfo.

        The meshes that are read are kept until the files are imported, so that importing does
        not have to read the files again. See MeshFileReader.getArrayInfosFromFiles.

        :raises OperationCancelledError: if the operation was cancelled, see OperationMonitor.
        """
        return self.reader.getArrayInfosFromFiles(
            filePaths, approximateRangeCellCountThreshold, fileCompletedCallback)

    @staticmethod
    def getArrayInfosFromModel(modelNode):
        """Coordinates and data arrays of a model, with the units stored in the model node."""
        return MeshArrays.getArrayInfosFromModel(modelNode)

    @staticmethod
    def getArrayInfosFromModels(modelNodes):
        """Coordinates and data arrays of several models, merged into a single list.

        An array that several models have is listed once, with the value range covering all of
        them, the same way as the arrays of several files are listed by getArrayInfosFromFiles.

        :return: list of MeshArrayInfo, and the unit system that each listed array is stored in.
            Models are normally all in the scene unit system, but a model may have been changed
            by hand.
        """
        arrayInfos = []
        arrayUnitSystems = []
        arrayInfosByKey = {}
        for modelNode in modelNodes:
            modelUnitSystem = MeshArrays.getModelUnitSystem(modelNode)
            for arrayInfo in MeshArrays.getArrayInfosFromModel(modelNode):
                existingArrayInfo = arrayInfosByKey.get(arrayInfo.key)
                if existingArrayInfo is None:
                    arrayInfosByKey[arrayInfo.key] = arrayInfo
                    arrayInfos.append(arrayInfo)
                    arrayUnitSystems.append(modelUnitSystem)
                else:
                    existingArrayInfo.mergeRanges(arrayInfo)
        return arrayInfos, arrayUnitSystems

    @staticmethod
    def getModelUnitSystem(modelNode):
        """Unit system that the model is stored in, mm-g-s if it is not specified in the model."""
        return MeshArrays.getModelUnitSystem(modelNode)

    @staticmethod
    def getModelCoordinateSystem(modelNode):
        """Coordinate system that the model is stored in, RAS if it is not specified in the model."""
        return MeshArrays.getModelCoordinateSystem(modelNode)

    # ------------------------------------------------------------------ meshes, without the scene

    @staticmethod
    def readFileNameFilter():
        """File name filter of the files that can be imported, for file selection dialogs."""
        return MeshFileReader.readFileNameFilter()

    def readMesh(self, filePath):
        """Read a mesh (or an image, from a .vti file) from file, without any conversion."""
        return self.reader.readMesh(filePath)

    def writeMesh(self, mesh, filePath):
        """Write a mesh to file, without any conversion."""
        MeshWriting.writeMesh(mesh, filePath, self.addLog, self.monitor)

    @staticmethod
    def convertMesh(mesh, arrayQuantities, flipFirstTwoComponents, fromUnitSystem, toUnitSystem):
        """Return a copy of a mesh or image, converted between unit and coordinate systems.

        See MeshConversion.convertMesh.
        """
        return MeshConversion.convertMesh(
            mesh, arrayQuantities, flipFirstTwoComponents, fromUnitSystem, toUnitSystem)

    def clearCache(self) -> None:
        """Release the meshes of the input files that were read for listing their arrays."""
        self.reader.clearCache()


#
# ImportExportSimulationModelTest
#


class ImportExportSimulationModelTest(ScriptedLoadableModuleTest):
    """Basic test of the module. The detailed tests are in the Testing/Python folder of the module."""

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_ImportExport()

    def test_ImportExport(self):
        self.delayDisplay("Starting import/export test")

        import tempfile

        # Create a test mesh in LPS, in the CGS unit system: a single point at (1, 2, 3) cm with
        # a velocity of (1, 2, 3) cm/s and a pressure of 1 dyn/cm2.
        points = vtk.vtkPoints()
        points.InsertNextPoint(1.0, 2.0, 3.0)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)
        vertices = vtk.vtkCellArray()
        vertices.InsertNextCell(1)
        vertices.InsertCellPoint(0)
        mesh.SetVerts(vertices)
        velocity = vtk.vtkDoubleArray()
        velocity.SetName("Velocity")
        velocity.SetNumberOfComponents(3)
        velocity.InsertNextTuple3(1.0, 2.0, 3.0)
        mesh.GetPointData().AddArray(velocity)
        pressure = vtk.vtkDoubleArray()
        pressure.SetName("Pressure")
        pressure.InsertNextTuple1(1.0)
        mesh.GetPointData().AddArray(pressure)

        temporaryDirectory = tempfile.mkdtemp()
        inputFilePath = os.path.join(temporaryDirectory, "testMesh.vtp")
        logic = ImportExportSimulationModelLogic()
        logic.writeMesh(mesh, inputFilePath)

        modelNodes = logic.importFiles([inputFilePath], "LPS", "cgs")
        self.assertEqual(len(modelNodes), 1)
        modelNode = modelNodes[0]
        importedMesh = modelNode.GetMesh()

        # Coordinates: x10 (cm -> mm), first two components negated (LPS -> RAS).
        self.assertEqual(list(importedMesh.GetPoint(0)), [-10.0, -20.0, 30.0])
        # Velocity: x10 (cm/s -> mm/s), first two components negated.
        importedVelocity = list(importedMesh.GetPointData().GetArray("Velocity").GetTuple3(0))
        self.assertEqual(importedVelocity, [-10.0, -20.0, 30.0])
        # Pressure: x0.1 (dyn/cm2 -> g/(mm*s2)), 1 component so it is not negated.
        self.assertAlmostEqual(importedMesh.GetPointData().GetArray("Pressure").GetTuple1(0), 0.1)

        # Units are stored in the model node.
        prefix = ImportExportSimulationModelLogic.ATTRIBUTE_PREFIX
        self.assertEqual(modelNode.GetAttribute(prefix + "UnitSystem"), "mmgs")
        self.assertEqual(modelNode.GetAttribute(prefix + "CoordinateSystem"), "RAS")
        self.assertEqual(modelNode.GetAttribute(prefix + "Position.Unit"), "mm")
        self.assertEqual(modelNode.GetAttribute(prefix + "Position.LengthExponent"), "1")
        self.assertEqual(modelNode.GetAttribute(prefix + "PointArray.Velocity.Unit"), "mm/s")
        self.assertEqual(modelNode.GetAttribute(prefix + "PointArray.Velocity.LengthExponent"), "1")
        self.assertEqual(modelNode.GetAttribute(prefix + "PointArray.Pressure.Unit"), "g/(mm*s2)")
        self.assertEqual(modelNode.GetAttribute(prefix + "PointArray.Pressure.LengthExponent"), "-1")

        # Arrays of several models are listed once, with the unit system that they are stored in.
        secondModelNode = logic.importFiles([inputFilePath], "LPS", "cgs")[0]
        secondPressure = secondModelNode.GetMesh().GetPointData().GetArray("Pressure")
        secondPressure.SetTuple1(0, 5.0)
        secondPressure.Modified()
        arrayInfos, arrayUnitSystems = logic.getArrayInfosFromModels([modelNode, secondModelNode])
        self.assertEqual([arrayInfo.name for arrayInfo in arrayInfos], ["Position", "Velocity", "Pressure"])
        self.assertEqual(arrayUnitSystems, ["mmgs", "mmgs", "mmgs"])
        self.assertEqual(arrayInfos[2].simulationUnit.unit("mmgs"), "g/(mm*s2)")
        self.assertAlmostEqual(arrayInfos[2].componentRanges[0][0], 0.1)
        self.assertAlmostEqual(arrayInfos[2].componentRanges[0][1], 5.0)

        # Exporting back to LPS/CGS must restore the original values.
        outputFilePath = os.path.join(temporaryDirectory, "exportedMesh.vtp")
        logic.exportModel(modelNode, outputFilePath, "LPS", "cgs")
        exportedMesh = logic.readMesh(outputFilePath)
        exportedPoint = list(exportedMesh.GetPoint(0))
        for value, expectedValue in zip(exportedPoint, [1.0, 2.0, 3.0]):
            self.assertAlmostEqual(value, expectedValue)
        exportedVelocity = list(exportedMesh.GetPointData().GetArray("Velocity").GetTuple3(0))
        for value, expectedValue in zip(exportedVelocity, [1.0, 2.0, 3.0]):
            self.assertAlmostEqual(value, expectedValue)
        self.assertAlmostEqual(exportedMesh.GetPointData().GetArray("Pressure").GetTuple1(0), 1.0)

        # Exporting to RAS/mm-g-s must write the values as they are stored in the scene.
        outputFilePath2 = os.path.join(temporaryDirectory, "exportedMeshRas.vtp")
        logic.exportModel(modelNode, outputFilePath2, "RAS", "mmgs")
        exportedMesh2 = logic.readMesh(outputFilePath2)
        self.assertEqual(list(exportedMesh2.GetPoint(0)), [-10.0, -20.0, 30.0])

        self.delayDisplay("Import/export test passed")
