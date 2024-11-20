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
    clipNode: slicer.vtkMRMLNode # Clip node

#
# SimplifiedViewerWidget
#

class SimplifiedViewerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """
    sequenceWidget = None

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
        labels = self.ui.sequenceBrowserSeekWidget.findChildren("QLabel")
        for label in labels:
            label.hide()

        self.ui.sequenceBrowserWidget.pushButton_VcrRecord.hide()
        self.ui.sequenceBrowserWidget.pushButton_Snapshot.hide()

        if self.sequenceWidget:
            self.sequenceWidget.hide()
            self.sequenceWidget.setParent(None)
            self.sequenceWidget.deleteLater()

        self.sequenceWidget = qt.QWidget()
        self.sequenceWidget.setObjectName("sequenceWidget")
        self.sequenceWidget.setLayout(qt.QVBoxLayout())
        self.sequenceWidget.layout().setMargin(0)
        self.sequenceWidget.layout().setContentsMargins(qt.QMargins(0,0,0,0))
        self.sequenceWidget.layout().setSpacing(0)
        self.sequenceWidget.layout().addWidget(self.ui.sequenceBrowserWidget)
        self.sequenceWidget.layout().addWidget(self.ui.sequenceBrowserSeekWidget)
        self.sequenceWidget.setAttribute(qt.Qt.WA_NoSystemBackground)
        self.sequenceWidget.setAttribute(qt.Qt.WA_TranslucentBackground)
        self.sequenceWidget.setAutoFillBackground(False)

        centralWidget = slicer.util.mainWindow().centralWidget()
        self.sequenceWidget.setParent(centralWidget)
        self.sequenceWidget.show()

        self.ui.conventionalViewButton.text = ""
        self.ui.conventionalViewButton.icon = qt.QIcon(self.resourcePath("Icons/LayoutConventionalView.png"))

        self.ui.fourUpViewButton.text = ""
        self.ui.fourUpViewButton.icon = qt.QIcon(self.resourcePath("Icons/LayoutFourUpView.png"))

        self.ui.resetViewsButton.visible = False
        self.ui.clippingButton.visible = self.clippingAvailable
        self.ui.clippingPlaneVisibilityButton.visible = self.clippingAvailable

        # Connections
        self.ui.toggleFullInterfaceButton.connect('clicked(bool)', self.toggleFull3DSlicerInterfaceVisible)
        self.ui.loadSampleDataButton.connect('clicked(bool)', self.onLoadSampleDataButtonClicked)
        self.ui.resetViewsButton.connect('clicked()', self.onResetViewsButtonClicked)
        self.ui.conventionalViewButton.connect('clicked(bool)', self.onConventionalViewButtonClicked)
        self.ui.fourUpViewButton.connect('clicked(bool)', self.onFourUpViewButtonClicked)
        self.ui.sequenceBrowserWidget.pushButton_VcrPlayPause.connect('clicked(bool)', self.updateSvgIcons)

        self.ui.checkableNodeComboBox.connect('checkedNodesChanged()', self.onSelectedNodesChanged)
        self.ui.clippingNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onClippingNodeChanged)
        self.ui.sequenceBrowserSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onSequenceBrowserNodeChanged)

        self.ui.clippingButton.connect('clicked(bool)', self.onClippingButtonClicked)
        self.ui.clippingPlaneVisibilityButton.connect('clicked(bool)', self.onClippingPlaneVisibilityButtonClicked)

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

        # Update widgets with the new display properties
        self.updateViewerWidgets()
        self.updateApplicationPalette()
        self.updateSvgIcons()
        self.updateApplicationStylesheet()

        self.sequenceWidget.adjustSize()
        

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
        self.updateClippingWidgets()

    def updateInputWidgets(self):
        """
        Update the input widgets
        """
        if not self._parameterNode:
            return

        wasBlocking = self.ui.checkableNodeComboBox.blockSignals(True)
        for node in self.ui.checkableNodeComboBox.uncheckedNodes():
            self.ui.checkableNodeComboBox.setCheckState(node, qt.Qt.Checked if node in self._parameterNode.selectedNodes else qt.Qt.Unchecked)
        for node in self.ui.checkableNodeComboBox.checkedNodes():
            self.ui.checkableNodeComboBox.setCheckState(node, qt.Qt.Checked if node in self._parameterNode.selectedNodes else qt.Qt.Unchecked)
        self.ui.checkableNodeComboBox.blockSignals(wasBlocking)

        wasBlocking = self.ui.clippingNodeSelector.blockSignals(True)
        self.ui.clippingNodeSelector.setCurrentNode(self._parameterNode.clipNode)
        self.ui.clippingNodeSelector.blockSignals(wasBlocking)

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
        sceneViewNodes = slicer.util.getNodesByClass("vtkMRMLSceneViewNode")
        row = 0
        for sceneViewNode in sceneViewNodes:
            column = 0

            pushButton = qt.QPushButton(sceneViewNode.GetName())
            pushButton.connect('clicked()', lambda sceneViewNode=sceneViewNode: self.onSceneViewClicked(sceneViewNode))
            self.ui.selectedNodeWidget.layout().addWidget(pushButton, row, column)
            column += 1

            row += 1
    
    def updateClippingWidgets(self):
        if not self._parameterNode:
            return
        
        wasBlocking = self.ui.clippingButton.blockSignals(True)
        self.ui.clippingButton.checked = self.logic.getClipping()
        self.ui.clippingButton.blockSignals(wasBlocking)

        wasBlocking = self.ui.clippingPlaneVisibilityButton.blockSignals(True)
        self.ui.clippingPlaneVisibilityButton.checked = self.logic.getClippingPlaneVisibility()
        self.ui.clippingPlaneVisibilityButton.blockSignals(wasBlocking)
    
    def onSceneViewClicked(self, sceneViewNode):
        self.logic.restoreSceneView(sceneViewNode)
        self.updateGUIFromMRML()

    def onSelectedNodesChanged(self):
        """
        Update the selected nodes in the parameter node
        """
        selectedNodes = self.ui.checkableNodeComboBox.checkedNodes()
        self._parameterNode.selectedNodes = selectedNodes

    def onClippingNodeChanged(self):
        """
        Update the clipping node in the parameter node
        """
        self._parameterNode.clipNode = self.ui.clippingNodeSelector.currentNode()

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
    
    def onClippingButtonClicked(self):
        """
        Update the clipping visibility
        """
        if self._parameterNode and self._parameterNode.clipNode:
            self.logic.setClipping(self.ui.clippingButton.checked)
    
    def onClippingPlaneVisibilityButtonClicked(self):
        """
        Update the clipping plane visibility
        """
        if self._parameterNode and self._parameterNode.clipNode:
            self.logic.setClippingPlaneVisibility(self.ui.clippingPlaneVisibilityButton.checked)

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
    
    def getClipping(self):
        clipNode = self.getParameterNode().clipNode
        if not clipNode:
            return False
        
        displayNodes = slicer.util.getNodesByClass("vtkMRMLDisplayNode")
        for displayNode in displayNodes:
            if displayNode.GetClipNode() == clipNode and displayNode.GetClipping():
                return True
        return False


    def setClipping(self, enabled: bool):
        clipNode = self.getParameterNode().clipNode
        if not clipNode:
            return
        
        displayNodes = slicer.util.getNodesByClass("vtkMRMLDisplayNode")
        for displayNode in displayNodes:
            if displayNode.GetClipNode() != clipNode:
                continue
            displayNode.SetClipping(enabled)

            if displayNode.IsA("vtkMRMLModelDisplayNode") or displayNode.IsA("vtkMRMLSegmentationDisplayNode"):
                displayNode.ClippingCapSurfaceOn()
                displayNode.ClippingOutlineOn()

    def getClippingPlaneVisibility(self):
        numberOfClippingNodes = self.getParameterNode().clipNode.GetNumberOfClippingNodes()
        for index in range(numberOfClippingNodes):
            clippingNode = self.getParameterNode().clipNode.GetNthClippingNode(index)
            if clippingNode and clippingNode.IsA("vtkMRMLMarkupsNode"):
                return clippingNode.GetDisplayVisibility()
        return False
    
    def setClippingPlaneVisibility(self, visible: bool):
        clipNode = self.getParameterNode().clipNode
        if not clipNode:
            return

        for index in range(clipNode.GetNumberOfClippingNodes()):
            clippingNode = clipNode.GetNthClippingNode(index)
            if not clippingNode or not clippingNode.IsA("vtkMRMLMarkupsNode"):
                continue
            clippingNode.SetDisplayVisibility(visible)

    def restoreSceneView(self, sceneViewNode):

        # Preserve clip states
        # TODO: In the future, we may be able to prevent scene views from modifying these nodes
        clipping = self.getClipping()
        planeVisibility = self.getClippingPlaneVisibility()

        with slicer.util.RenderBlocker():
            layoutManager = slicer.app.layoutManager()
            currentLayout = layoutManager.layout
            sceneViewNode.RestoreScene()
            layoutManager.setLayout(currentLayout)

            # Restore clip states
            self.setClipping(clipping)
            self.setClippingPlaneVisibility(planeVisibility)

        slicer.util.forceRenderAllViews()

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
