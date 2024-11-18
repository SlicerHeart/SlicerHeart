import logging
import os
from typing import Annotated, Optional

import vtk, qt, ctk, slicer

from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)

#
# SimplifiedViewer
#


class SimplifiedViewer(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Simplified Viewer")
        # TODO: set categories (folders where the module shows up in the module selector)
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Examples")]
        self.parent.dependencies = []
        self.parent.contributors = ["Kyle Sunderland (PerkLab)", "Andras Lasso (PerkLab)"]
        self.parent.helpText = _("Simplified viewer module for SlicerHeart.")
        # TODO: replace with organization, grant and thanks
        self.parent.acknowledgementText = _("This file was originally developed by Kyle Sunderland (PerkLab), Andras Lasso (PerkLab).")


#
# SimplifiedViewerParameterNode
#


@parameterNodeWrapper
class SimplifiedViewerParameterNode:
    """
    The parameters needed by the module.
    """
    selectedNodes: list[slicer.vtkMRMLNode] # Selected nodes to display
    sequenceBrowserNode: slicer.vtkMRMLSequenceBrowserNode # Sequence browser node
    clipNode: slicer.vtkMRMLClipNode # Clip node
    clipPlaneNode: slicer.vtkMRMLMarkupsPlaneNode # Clip plane node

#
# SimplifiedViewerWidget
#

class SimplifiedViewerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None
        self.clippingAvailable = False

    def setup(self) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.setup(self)

        try:
            slicer.vtkMRMLClipNode
            self.clippingAvailable = True
        except:
            self.clippingAvailable = False
        logging.info(f"Clipping available: {self.clippingAvailable}")

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/SimplifiedViewer.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = SimplifiedViewerLogic()

        # Widget updates
        playbackSpinBox = self.ui.sequenceBrowserWidget.findChild("QDoubleSpinBox", "doubleSpinBox_VcrPlaybackRate")
        playbackSpinBox.visible = False

        self.ui.sequenceBrowserSeekWidget.label_IndexName.hide()
        # change widget margins
        self.ui.sequenceBrowserWidget.layout().setContentsMargins(0, 0, 0, 0)
        self.ui.sequenceBrowserSeekWidget.layout().setContentsMargins(0, 0, 0, 0)

        self.ui.sequenceBrowserWidget.pushButton_VcrRecord.hide()
        self.ui.sequenceBrowserWidget.pushButton_Snapshot.hide()

        self.ui.conventionalViewButton.text = ""
        self.ui.conventionalViewButton.icon = qt.QIcon(self.resourcePath("Icons/LayoutConventionalView.png"))

        self.ui.fourUpViewButton.text = ""
        self.ui.fourUpViewButton.icon = qt.QIcon(self.resourcePath("Icons/LayoutFourUpView.png"))

        # Connections
        self.ui.toggleFullInterfaceButton.connect('clicked(bool)', self.toggleFull3DSlicerInterfaceVisible)
        self.ui.loadSampleDataButton.connect('clicked(bool)', self.onLoadSampleDataButtonClicked)
        self.ui.resetViewsButton.connect('clicked()', self.onResetViewsButtonClicked)
        self.ui.conventionalViewButton.connect('clicked(bool)', self.onConventionalViewButtonClicked)
        self.ui.fourUpViewButton.connect('clicked(bool)', self.onFourUpViewButtonClicked)
        self.ui.sequenceBrowserWidget.pushButton_VcrPlayPause.connect('clicked(bool)', self.updateSvgIcons)

        self.ui.checkableNodeComboBox.connect('checkedNodesChanged()', self.onSelectedNodesChanged)
        self.ui.sequenceBrowserSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onSequenceBrowserNodeChanged)

        self.ui.redSliceClipCheckBox.connect('toggled(bool)', self.onClippingSliceChanged)
        self.ui.greenSliceClipCheckBox.connect('toggled(bool)', self.onClippingSliceChanged)
        self.ui.yellowSliceClipCheckBox.connect('toggled(bool)', self.onClippingSliceChanged)

        layoutManager = slicer.app.layoutManager()
        layoutManager.connect('layoutChanged(int)', self.onLayoutChanged)

        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()

        if self.parent.isEntered:
            self.enter()

    def cleanup(self) -> None:
        """Called when the application closes and the module widget is destroyed."""
        self.removeObservers()

    def enter(self) -> None:
        """Called each time the user opens this module."""
        # Make sure parameter node exists and observed
        self.initializeParameterNode()
        self.setFull3DSlicerInterfaceVisible(self.getFull3DSlicerInterfaceVisible())
        self.updateSequenceBrowserWidgets()

    def exit(self) -> None:
        """Called each time the user opens a different module."""
        # Do not react to parameter node changes (GUI will be updated when the user enters into the module)
        self.removeObservers(self.onParameterNodeModified)

    def onParameterNodeModified(self, caller, event) -> None:
        """Called when the parameter node is modified."""
        self.updateGUIFromMRML()

    def onSceneStartClose(self, caller, event) -> None:
        """Called just before the scene is closed."""
        # Parameter node will be reset, do not use it anymore
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        """Called just after the scene is closed."""
        # If this module is shown while the scene is closed then recreate a new parameter node immediately
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        """Ensure parameter node exists and observed."""
        # Parameter node stores all user choices in parameter values, node selections, etc.
        # so that when the scene is saved and reloaded, these settings are restored.

        self.setParameterNode(self.logic.getParameterNode())

        if self.clippingAvailable:
            if self._parameterNode.clipNode is None:
                self._parameterNode.clipNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLClipNode", "SimplifiedViewerClip")

            sliceNodes = [
                slicer.mrmlScene.GetNodeByID("vtkMRMLSliceNodeRed"),
                slicer.mrmlScene.GetNodeByID("vtkMRMLSliceNodeGreen"),
                slicer.mrmlScene.GetNodeByID("vtkMRMLSliceNodeYellow")]
            for sliceNode in sliceNodes:
                if self._parameterNode.clipNode.HasClippingNodeID(sliceNode.GetID()):
                    continue
                self._parameterNode.clipNode.AddAndObserveClippingNodeID(sliceNode.GetID())
                self._parameterNode.clipNode.SetClippingNodeState(sliceNode, slicer.vtkMRMLClipNode.ClipOff)                

            if self._parameterNode.clipPlaneNode is None:
                self._parameterNode.clipPlaneNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "SimplifiedViewerClippingPlane")
                self._parameterNode.clipPlaneNode.SetNormal(0, 1.0, 0)
                self._parameterNode.clipPlaneNode.SetOrigin(0, 0, 0)
                self._parameterNode.clipPlaneNode.CreateDefaultDisplayNodes()
                self._parameterNode.clipPlaneNode.SetDisplayVisibility(False)
                self._parameterNode.clipNode.AddAndObserveClippingNodeID(self._parameterNode.clipPlaneNode.GetID())

    def setParameterNode(self, inputParameterNode: Optional[SimplifiedViewerParameterNode]) -> None:
        """
        Set and observe parameter node.
        Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
        """
        oldParameterNode = self._parameterNode
        self._parameterNode = inputParameterNode
        self.removeObservers(self.onParameterNodeModified)
        if self._parameterNode:
            self.addObserver(inputParameterNode, vtk.vtkCommand.ModifiedEvent, self.onParameterNodeModified)
        if oldParameterNode != self._parameterNode:
            self.onParameterNodeModified(None, None)

    def toggleFull3DSlicerInterfaceVisible(self):
        # Toggle the full 3D Slicer interface
        self.setFull3DSlicerInterfaceVisible(not self.getFull3DSlicerInterfaceVisible())

    def setFull3DSlicerInterfaceVisible(self, visible: bool):
        settings = qt.QSettings()
        settings.setValue('SimplifiedViewer/FullInterfaceVisible', visible)

        # Set the full 3D Slicer interface visibility
        slicer.util.setToolbarsVisible(visible)
        slicer.util.setMenuBarsVisible(visible)
        slicer.util.setApplicationLogoVisible(visible)
        slicer.util.setModuleHelpSectionVisible(visible)
        slicer.util.setModulePanelTitleVisible(visible)
        slicer.util.setDataProbeVisible(visible)
        slicer.util.setStatusBarVisible(visible)
        slicer.util.setPythonConsoleVisible(visible)

        self.reloadCollapsibleButton.visible = visible
        self.ui.setupCollapsibleButton.visible = visible

        self.ui.clippingControlWidget.visible = self.clippingAvailable

        # Update widgets with the new display properties
        self.updateViewerWidgets()
        self.updateApplicationPalette()
        self.updateSvgIcons()
        self.updateApplicationStylesheet()

    def updateSvgIcons(self):
        """
        Update the SVG icons for the sequence browser playback buttons
        """
        playbackActive = False
        if self.ui.sequenceBrowserWidget.pushButton_VcrPlayPause.isChecked():
            playbackActive = True

        palette = slicer.app.palette()
        sizePx = 32
        color = palette.color(qt.QPalette.Text)

        # Vectors and icons by Css.gg: https://github.com/astrit/css.gg?ref=svgrepo.com
        # MIT License via https://www.svgrepo.com
        widgetPathMap = {
            self.ui.sequenceBrowserWidget.pushButton_VcrFirst:     "Icons/SeekFirst.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrPrevious:  "Icons/SeekPrevious.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrPlayPause: "Icons/SeekPlay.svg" if not playbackActive else "Icons/SeekPause.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrNext:      "Icons/SeekNext.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrLast:      "Icons/SeekLast.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrLoop:      "Icons/SeekLoop.svg",
        }
        for widget, iconPath in widgetPathMap.items():
            icon = self.loadSvg(self.resourcePath(iconPath), sizePx, color)
            widget.setIcon(qt.QIcon(icon))
            widget.setIconSize(qt.QSize(sizePx, sizePx))

    def loadSvg(self, svg_filename: str, size: int, color: qt.QColor) -> qt.QIcon:
        """
        https://stackoverflow.com/questions/75440429/qt-render-svg-with-custom-color/75443894#75443894
        """
        # Load the SVG file into string
        with open(svg_filename, 'r') as file:
            svg_data = file.read()

        # Replace #000000 with the desired color
        svg_data = svg_data.replace("#000000", color.name())
        svg_data = svg_data.replace('width="24"', f'width="{size}"')
        svg_data = svg_data.replace('height="24"', f'height="{size}"')

        # Create a QIcon from the QPixmap
        pixmap = qt.QPixmap(500,500)
        pixmap.loadFromData(svg_data.encode())
        return qt.QIcon(pixmap.scaledToHeight(size, qt.Qt.SmoothTransformation))

    def getFull3DSlicerInterfaceVisible(self):
        return slicer.util.settingsValue('SimplifiedViewer/FullInterfaceVisible', False, converter=slicer.util.toBool)

    def updateApplicationStylesheet(self):
        stylesheet = ""
        if not self.getFull3DSlicerInterfaceVisible():
            stylesheetPath = self.resourcePath("Stylesheet/SimplifiedViewer.qss")
            with open(stylesheetPath, 'r') as f:
                stylesheet = f.read()
        slicer.app.setStyleSheet(stylesheet)

    def updateApplicationPalette(self):
        palette = qt.QPalette()
        if not self.getFull3DSlicerInterfaceVisible():
            base = "#0c0c14"
            alternateBase = "#000000"
            button = "#3c94b4"
            light = "#d5e8ec"
            midLight = "#8cbccb"
            mid = "#2F738C"
            dark = "#215163"
            paletteColors = {
                qt.QPalette.Window : base,
                qt.QPalette.WindowText : light,
                qt.QPalette.Base : base,
                qt.QPalette.AlternateBase : alternateBase,
                qt.QPalette.ToolTipBase : light,
                qt.QPalette.ToolTipText : alternateBase,
                #qt.QPalette.PlaceholderText : light, # Qt 6.0
                qt.QPalette.Text : light,
                qt.QPalette.Button : button,
                qt.QPalette.ButtonText : light,
                qt.QPalette.BrightText : midLight,

                qt.QPalette.Light : light,
                qt.QPalette.Midlight : midLight,
                qt.QPalette.Mid : mid,
                qt.QPalette.Dark : dark,
                qt.QPalette.Shadow : base,

                qt.QPalette.Highlight : midLight,
                #qt.QPalette.Accent : button, # Qt 6.6
                qt.QPalette.HighlightedText : dark,

                qt.QPalette.Link : midLight,
                qt.QPalette.LinkVisited : dark,
            }
            for role, color in paletteColors.items():
                palette.setColor(role, qt.QColor(color))
        slicer.app.setPalette(palette)

    def updateViewerWidgets(self):
        """
        Update the viewer widgets to match the current full 3D Slicer interface visibility.
        Customizes the appearance of the viewers.
        """
        import HeartValveLib
        full3DSlicerInterfaceVisible = self.getFull3DSlicerInterfaceVisible()
        layoutManager = slicer.app.layoutManager()
        for viewWidget in layoutManager.viewWidgets():
            if isinstance(viewWidget, slicer.qMRMLSliceWidget):
                viewWidget.setSliceOffsetSliderOrientation(qt.Qt.Vertical if not full3DSlicerInterfaceVisible else qt.Qt.Horizontal)
                viewWidget.sliceController().setVisible(full3DSlicerInterfaceVisible)
                sliceLogic = viewWidget.sliceLogic()
                sliceViewNode = sliceLogic.GetSliceNode()
                HeartValveLib.HeartValves.setHeartOrientationmarker(sliceViewNode.GetID())
            elif isinstance(viewWidget, slicer.qMRMLThreeDWidget):
                viewWidget.threeDController().setVisible(full3DSlicerInterfaceVisible)
                if not full3DSlicerInterfaceVisible:
                    viewNode = viewWidget.mrmlViewNode()
                    viewNode.SetBackgroundColor(0,0,0)
                    viewNode.SetBackgroundColor2(0,0,0)
                    viewNode.SetBoxVisible(False)
                    HeartValveLib.HeartValves.setHeartOrientationmarker(viewNode.GetID())

        # Disable slice annotations
        if not full3DSlicerInterfaceVisible:
            if slicer.modules.DataProbeInstance.infoWidget:
                sliceAnnotations = slicer.modules.DataProbeInstance.infoWidget.sliceAnnotations
                sliceAnnotations.sliceViewAnnotationsEnabled = False
                sliceAnnotations.updateSliceViewFromGUI()

    def onLayoutChanged(self):
        """
        Called when the layout is changed. This is used to update the viewer widgets
        """
        self.updateViewerWidgets()

    def onLoadSampleDataButtonClicked(self):
        """
        Load sample data
        """
        with slicer.util.RenderBlocker():
            slicer.mrmlScene.Clear()
            import SampleData
            SampleData.SampleDataLogic().downloadSample("Mitral")

            volumeNode = slicer.util.getNode("Mitral_US_1")
            volumeRenderingLogic = slicer.modules.volumerendering.logic()
            displayNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(volumeNode)
            displayNode.GetVolumePropertyNode().Copy(volumeRenderingLogic.GetPresetByName("US-Red-Tinge"))

            self._parameterNode.selectedNodes = [volumeNode]
            browserNode = slicer.util.getNode("Mitral_US_1 browser")
            self._parameterNode.sequenceBrowserNode = browserNode

            self.onResetViewsButtonClicked()

    def updateGUIFromMRML(self):
        """
        Update the GUI from the parameter node
        """
        self.updateInputWidgets()
        self.updateSelectedNodeWidget()
        self.updateSequenceBrowserWidgets()

    def updateInputWidgets(self):
        """
        Update the input widgets
        """
        wasBlocking = self.ui.checkableNodeComboBox.blockSignals(True)
        for node in self.ui.checkableNodeComboBox.uncheckedNodes():
            self.ui.checkableNodeComboBox.setCheckState(node, qt.Qt.Checked if node in self._parameterNode.selectedNodes else qt.Qt.Unchecked)
        for node in self.ui.checkableNodeComboBox.checkedNodes():
            self.ui.checkableNodeComboBox.setCheckState(node, qt.Qt.Checked if node in self._parameterNode.selectedNodes else qt.Qt.Unchecked)
        self.ui.checkableNodeComboBox.blockSignals(wasBlocking)

        wasBlocking = self.ui.sequenceBrowserSelector.blockSignals(True)
        self.ui.sequenceBrowserSelector.setCurrentNode(self._parameterNode.sequenceBrowserNode)
        self.ui.sequenceBrowserSelector.blockSignals(wasBlocking)

    def updateSequenceBrowserWidgets(self):
        sequenceBrowserNode = self._parameterNode.sequenceBrowserNode if self._parameterNode else None
        wasBlocking = self.ui.sequenceBrowserSelector.blockSignals(True)
        self.ui.sequenceBrowserSelector.setCurrentNode(sequenceBrowserNode)
        self.ui.sequenceBrowserSelector.blockSignals(wasBlocking)
        self.ui.sequenceBrowserWidget.setMRMLSequenceBrowserNode(sequenceBrowserNode)
        self.ui.sequenceBrowserWidget.visible = sequenceBrowserNode is not None
        self.ui.sequenceBrowserSeekWidget.setMRMLSequenceBrowserNode(sequenceBrowserNode)
        self.ui.sequenceBrowserSeekWidget.visible = sequenceBrowserNode is not None

    def updateSelectedNodeWidget(self):
        """
        Update the selected node widget
        """
        # remove existing widgets from selectedNodeWidget
        if self.ui.selectedNodeWidget.layout():
          for i in range(self.ui.selectedNodeWidget.layout().count()):
              item = self.ui.selectedNodeWidget.layout().itemAt(i)
              if item:
                  item.widget().deleteLater()
        else:
            self.ui.selectedNodeWidget.setLayout(qt.QGridLayout())

        if not self._parameterNode:
            return

        # add new widgets to selectedNodeWidget grid layout
        row = 0
        for node in self._parameterNode.selectedNodes:
            nodeID = node.GetID()
            displayNode = node.GetDisplayNode()

            column = 0

            label = qt.QLabel(node.GetName())
            self.ui.selectedNodeWidget.layout().addWidget(label, row, column)
            column += 1

            visibilityCheckBox = qt.QCheckBox("Visibility")            
            visibilityCheckBox.connect('toggled(bool)', lambda checked, nodeID=nodeID: self.onVisibilityChanged(checked, nodeID))
            visibilityCheckBox.checked = node.GetDisplayVisibility()
            self.ui.selectedNodeWidget.layout().addWidget(visibilityCheckBox, row, column)
            column += 1

            if self.clippingAvailable:
                clippingCheckBox = qt.QCheckBox("Clipping")
                clippingCheckBox.checked = displayNode.GetClipping() if displayNode else False
                clippingCheckBox.connect('toggled(bool)', lambda checked, nodeID=nodeID: self.onClippingChanged(checked, nodeID))

                self.ui.selectedNodeWidget.layout().addWidget(clippingCheckBox, row, column)
                column += 1

            row += 1
    
    def onVisibilityChanged(self, checked: bool, nodeID: str):
        """
        Update the visibility of the node
        """
        node = slicer.mrmlScene.GetNodeByID(nodeID)
        for i in range(node.GetNumberOfDisplayNodes()):
            displayNode = node.GetNthDisplayNode(i)
            displayNode.SetVisibility(checked)

    def onClippingChanged(self, checked: bool, nodeID: str):
        """
        Update the clipping of the node
        """
        node = slicer.mrmlScene.GetNodeByID(nodeID)
        for i in range(node.GetNumberOfDisplayNodes()):
            displayNode = node.GetNthDisplayNode(i)
            displayNode.SetClipping(checked)
            if checked and displayNode.GetClipNode() is None:
                displayNode.SetAndObserveClipNodeID(self._parameterNode.clipNode.GetID())
            if displayNode.IsA("vtkMRMLVolumeRenderingDisplayNode"):
                displayNode.SetClippingSoftEdgeVoxels(2.0)
            if displayNode.IsA("vtkMRMLModelDisplayNode") or displayNode.IsA("vtkMRMLSegmentationDisplayNode"):
                displayNode.SetClippingCapSurface(checked)

    def onSelectedNodesChanged(self):
        """
        Update the selected nodes in the parameter node
        """
        selectedNodes = self.ui.checkableNodeComboBox.checkedNodes()
        self._parameterNode.selectedNodes = selectedNodes

    def onSequenceBrowserNodeChanged(self):
        """
        Update the sequence browser node in the parameter node
        """
        self._parameterNode.sequenceBrowserNode = self.ui.sequenceBrowserSelector.currentNode()

    def onResetViewsButtonClicked(self):
        """
        Reset the view position and orientation
        """
        slicer.app.layoutManager().resetThreeDViews()
        slicer.app.layoutManager().resetSliceViews()

    def onConventionalViewButtonClicked(self):
        """
        Set the layout to the conventional view
        """
        layoutManager = slicer.app.layoutManager()
        layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)

    def onFourUpViewButtonClicked(self):
        """
        Set the layout to the four up view
        """
        layoutManager = slicer.app.layoutManager()
        layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    
    def onClippingSliceChanged(self):
        """
        Update the clipping visibility
        """
        clipNode = self._parameterNode.clipNode
        redSlice = slicer.mrmlScene.GetNodeByID("vtkMRMLSliceNodeRed")
        clipNode.SetClippingNodeState(redSlice, slicer.vtkMRMLClipNode.ClipNegativeSpace if self.ui.redSliceClipCheckBox.checked else slicer.vtkMRMLClipNode.ClipOff)
        greenSlice = slicer.mrmlScene.GetNodeByID("vtkMRMLSliceNodeGreen")
        clipNode.SetClippingNodeState(greenSlice, slicer.vtkMRMLClipNode.ClipNegativeSpace if self.ui.greenSliceClipCheckBox.checked else slicer.vtkMRMLClipNode.ClipOff)
        yellowSlice = slicer.mrmlScene.GetNodeByID("vtkMRMLSliceNodeYellow")
        clipNode.SetClippingNodeState(yellowSlice, slicer.vtkMRMLClipNode.ClipNegativeSpace if self.ui.yellowSliceClipCheckBox.checked else slicer.vtkMRMLClipNode.ClipOff)

#
# SimplifiedViewerLogic
#


class SimplifiedViewerLogic(ScriptedLoadableModuleLogic):
    """This class should implement all the actual
    computation done by your module.  The interface
    should be such that other python code can import
    this class and make use of the functionality without
    requiring an instance of the Widget.
    Uses ScriptedLoadableModuleLogic base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self) -> None:
        """Called when the logic class is instantiated. Can be used for initializing member variables."""
        ScriptedLoadableModuleLogic.__init__(self)

    def getParameterNode(self):
        return SimplifiedViewerParameterNode(super().getParameterNode())

    def updateNodeVisibility(self):
        pass

#
# SimplifiedViewerTest
#


class SimplifiedViewerTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        """Do whatever is needed to reset the state - typically a scene clear will be enough."""
        slicer.mrmlScene.Clear()

    def runTest(self):
        """Run as few or as many tests as needed here."""
        self.setUp()
