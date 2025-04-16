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

class OverlayWidget(qt.QWidget):

    # Corner enums
    TopLeft = 0
    TopRight = 1
    BottomLeft = 2
    BottomRight = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(qt.Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        if parent:
            parent.installEventFilter(self)
        self.corner = OverlayWidget.TopLeft

    def eventFilter(self, obj, event):
        if event.type() == qt.QEvent.Resize:
            self.resizeEvent(event)
        return False

    def resizeEvent(self, event):
        if self.parent() is None:
            return

        # Superclass resize
        qt.QWidget.resizeEvent(self, event)

        parentRect = self.parent().rect
        if self.corner == OverlayWidget.TopLeft:
            self.move(0, 0)
        elif self.corner == OverlayWidget.TopRight:
            self.move(parentRect.topRight() - self.rect.topRight())
        elif self.corner == OverlayWidget.BottomLeft:
            self.move(parentRect.bottomLeft() - self.rect.bottomLeft())
        elif self.corner == OverlayWidget.BottomRight:
            self.move(parentRect.bottomRight() - self.rect.bottomRight())

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

    measurementNodes: list[slicer.vtkMRMLNode] # Measurement nodes

#
# SimplifiedViewerWidget
#

class SimplifiedViewerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """
    topLeftWidget = None
    bottomLeftWidget = None

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

        if self.topLeftWidget:
            self.topLeftWidget.hide()
            self.topLeftWidget.setParent(None)
            self.topLeftWidget.deleteLater()

        if self.bottomLeftWidget:
            self.bottomLeftWidget.hide()
            self.bottomLeftWidget.setParent(None)
            self.bottomLeftWidget.deleteLater()

        topLeftButtons = []

        self.svToggleButton = qt.QToolButton()
        self.svToggleButton.checkable = True
        self.svToggleButton.connect('clicked(bool)', self.toggleSceneViewPanel)
        topLeftButtons.append(self.svToggleButton)

        self.measurementsToggleButton = qt.QToolButton()
        self.measurementsToggleButton.checkable = True
        self.measurementsToggleButton.connect('clicked(bool)', self.toggleMeasurementPanel)
        topLeftButtons.append(self.measurementsToggleButton)

        self.clippingEnabledAction = qt.QAction("Enable Clipping")
        self.clippingEnabledAction.setCheckable(True)
        self.clippingEnabledAction.connect('toggled(bool)', self.onClippingButtonClicked)
        self.clippingPlaneVisibilityAction = qt.QAction("Show Clipping Plane")
        self.clippingPlaneVisibilityAction.setCheckable(True)
        self.clippingPlaneVisibilityAction.connect('toggled(bool)', self.onClippingPlaneVisibilityButtonClicked)
        self.visibilityMenu = qt.QMenu()
        self.visibilityMenu.addAction(self.clippingEnabledAction)
        self.visibilityMenu.addAction(self.clippingPlaneVisibilityAction)
        self.visibilityButton = qt.QToolButton()
        self.visibilityButton.setMenu(self.visibilityMenu)
        self.visibilityButton.setPopupMode(qt.QToolButton.InstantPopup)
        topLeftButtons.append(self.visibilityButton)

        self.crosshairVisibilityButton = qt.QToolButton()
        self.crosshairVisibilityButton.checkable = True
        self.crosshairVisibilityButton.connect('toggled(bool)', self.onCrosshairVisibilityButtonClicked)
        topLeftButtons.append(self.crosshairVisibilityButton)

        self.fourUpViewAction = qt.QAction("Four Up View")
        self.fourUpViewAction.connect('triggered()', self.onFourUpViewButtonClicked)
        self.conventionalViewAction = qt.QAction("Conventional View")
        self.conventionalViewAction.connect('triggered()', self.onConventionalViewButtonClicked)
        self.layoutsMenu = qt.QMenu()
        self.layoutsMenu.addAction(self.fourUpViewAction)
        self.layoutsMenu.addAction(self.conventionalViewAction)
        self.layoutsButton = qt.QToolButton()
        self.layoutsButton.setMenu(self.layoutsMenu)
        self.layoutsButton.setPopupMode(qt.QToolButton.InstantPopup)
        topLeftButtons.append(self.layoutsButton)

        self.fullSlicerInterfaceAction = qt.QAction("Show full 3D Slicer Interface")
        self.fullSlicerInterfaceAction.setCheckable(True)
        self.fullSlicerInterfaceAction.connect('toggled(bool)', self.setFull3DSlicerInterfaceVisible)
        self.settingsMenu = qt.QMenu()
        self.settingsMenu.addAction(self.fullSlicerInterfaceAction)
        self.settingsButton = qt.QToolButton()
        self.settingsButton.setMenu(self.settingsMenu)
        self.settingsButton.setPopupMode(qt.QToolButton.InstantPopup)
        topLeftButtons.append(self.settingsButton)

        buttonSize = 64
        for button in topLeftButtons:
            button.setFixedSize(buttonSize, buttonSize)

        centralWidget = slicer.util.mainWindow().centralWidget()

        spacing = 3

        self.topLeftWidget = OverlayWidget(centralWidget)
        self.topLeftWidget.setObjectName("buttonWidget")
        self.topLeftWidget.corner = OverlayWidget.TopLeft
        self.topLeftWidget.setLayout(qt.QHBoxLayout())
        self.topLeftWidget.layout().setMargin(0)
        self.topLeftWidget.layout().setContentsMargins(qt.QMargins(0,0,0,0))
        self.topLeftWidget.layout().setSpacing(spacing)
        self.topLeftWidget.layout().addWidget(self.svToggleButton)
        self.topLeftWidget.layout().addWidget(self.measurementsToggleButton)
        self.topLeftWidget.layout().addWidget(self.visibilityButton)
        self.topLeftWidget.layout().addWidget(self.crosshairVisibilityButton)
        self.topLeftWidget.layout().addWidget(self.layoutsButton)
        self.topLeftWidget.layout().addWidget(self.settingsButton)
        self.topLeftWidget.setAttribute(qt.Qt.WA_NoSystemBackground)
        self.topLeftWidget.setAttribute(qt.Qt.WA_TranslucentBackground)
        self.topLeftWidget.setAutoFillBackground(False)
        self.topLeftWidget.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
        self.topLeftWidget.setFixedHeight(buttonSize)
        self.topLeftWidget.setFixedWidth(len(topLeftButtons)*buttonSize + (len(topLeftButtons)-1)*spacing)
        self.topLeftWidget.show()

        self.bottomLeftWidget = OverlayWidget(centralWidget)
        self.bottomLeftWidget.setObjectName("bottomLeftWidget")
        self.bottomLeftWidget.corner = OverlayWidget.BottomLeft
        self.bottomLeftWidget.setLayout(qt.QVBoxLayout())
        self.bottomLeftWidget.layout().setMargin(0)
        self.bottomLeftWidget.layout().setContentsMargins(qt.QMargins(0,0,0,0))
        self.bottomLeftWidget.layout().setSpacing(spacing)
        self.bottomLeftWidget.layout().addWidget(self.ui.sequenceBrowserWidget)

        bottomRightButtons = []
        for button in self.ui.sequenceBrowserWidget.findChildren(qt.QAbstractButton):
            if button.isVisibleTo(self.ui.sequenceBrowserWidget):
                bottomRightButtons.append(button)
                button.setFixedSize(buttonSize, buttonSize)

        self.ui.sequenceBrowserSeekWidget.setFixedHeight(buttonSize/2.0)
        self.bottomLeftWidget.layout().addWidget(self.ui.sequenceBrowserSeekWidget)
        self.bottomLeftWidget.setAttribute(qt.Qt.WA_NoSystemBackground)
        self.bottomLeftWidget.setAttribute(qt.Qt.WA_TranslucentBackground)
        self.bottomLeftWidget.setAutoFillBackground(False)
        self.bottomLeftWidget.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
        self.bottomLeftWidget.setFixedHeight(buttonSize*1.5 + spacing)
        self.bottomLeftWidget.setFixedWidth(len(bottomRightButtons)*buttonSize + (len(bottomRightButtons)-1)*spacing)
        self.bottomLeftWidget.show()

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

        self.ui.clippingNodeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onClippingNodeChanged)
        self.ui.sequenceBrowserSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onSequenceBrowserNodeChanged)

        self.ui.clippingButton.connect('clicked(bool)', self.onClippingButtonClicked)
        self.ui.clippingPlaneVisibilityButton.connect('clicked(bool)', self.onClippingPlaneVisibilityButtonClicked)

        self.ui.newLengthButton.connect('clicked()', self.onNewLengthButtonClicked)
        self.ui.newAreaButton.connect('clicked()', self.onNewAreaButtonClicked)
        self.ui.newCurveButton.connect('clicked()', self.onNewCurveButtonClicked)

        self.ui.measurementsTreeView.connect('currentItemChanged(vtkIdType)', self.updateMeasurementsWidgets)

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
        #slicer.util.setPythonConsoleVisible(visible)

        self.reloadCollapsibleButton.visible = visible
        self.ui.setupCollapsibleButton.visible = visible

        self.topLeftWidget.visible = not visible
        self.bottomLeftWidget.visible = not visible

        # Update widgets with the new display properties
        self.updateViewerWidgets()
        self.updateApplicationPalette()
        self.updateSvgIcons()
        self.updateApplicationStylesheet()
        self.updateGUIFromMRML()

    def toggleSceneViewPanel(self, visible):
        self.measurementsToggleButton.checked = False # BUTTON GROUP
        self.updateSidePanelVisibility()


    def toggleMeasurementPanel(self, visible):
        self.svToggleButton.checked = False # BUTTON GROUP
        self.updateSidePanelVisibility()

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
        # Also https://fonts.google.com/icons
        # Apache license 2.0 https://github.com/google/material-design-icons/blob/master/LICENSE
        widgetPathMap = {
            self.ui.sequenceBrowserWidget.pushButton_VcrFirst:     "Icons/SeekFirst.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrPrevious:  "Icons/SeekPrevious.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrPlayPause: "Icons/SeekPlay.svg" if not playbackActive else "Icons/SeekPause.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrNext:      "Icons/SeekNext.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrLast:      "Icons/SeekLast.svg",
            self.ui.sequenceBrowserWidget.pushButton_VcrLoop:      "Icons/SeekLoop.svg",
            self.svToggleButton:                                   "Icons/SceneViews.svg",
            self.measurementsToggleButton:                         "Icons/Measurements.svg",
            self.visibilityButton:                                 "Icons/Visibility.svg",
            self.crosshairVisibilityButton:                        "Icons/Crosshair.svg",
            self.layoutsButton:                                    "Icons/Layouts.svg",
            self.settingsButton:                                   "Icons/Settings.svg",
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
        self.updateMeasurementsWidgets()
        self.updateSidePanelVisibility()

        self.fullSlicerInterfaceAction.setChecked(self.getFull3DSlicerInterfaceVisible())

    def updateSidePanelVisibility(self):
        full3DSlicerInterfaceVisible = self.getFull3DSlicerInterfaceVisible()
        sidePanelVisible = self.svToggleButton.checked or self.measurementsToggleButton.checked or full3DSlicerInterfaceVisible
        modulePanel = slicer.util.mainWindow().findChildren("QDockWidget", "PanelDockWidget")[0]
        modulePanel.visible = sidePanelVisible
        if not full3DSlicerInterfaceVisible:
            slicer.util.mainWindow().addDockWidget(qt.Qt.RightDockWidgetArea, modulePanel)
        else:
            slicer.util.mainWindow().addDockWidget(qt.Qt.LeftDockWidgetArea, modulePanel)
        self.ui.measurementWidget.visible = self.measurementsToggleButton.checked
        self.ui.sceneViewsWidget.visible = self.svToggleButton.checked
        self.ui.toggleFullInterfaceButton.visible = full3DSlicerInterfaceVisible
        self.ui.viewControlWidget.visible = full3DSlicerInterfaceVisible

    def onNewLengthButtonClicked(self):
        """
        Create a new length measurement
        """
        name = slicer.mrmlScene.GenerateUniqueName("Length")
        measurementNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode", name)
        measurementNode.SetAttribute("SimplifiedViewer", "")
        area = measurementNode.GetMeasurement("length")
        area.SetName("Length")
        area.EnabledOn()
        self._parameterNode.measurementNodes.append(measurementNode)

    def onNewAreaButtonClicked(self):
        """
        Create a new area measurement
        """
        name = slicer.mrmlScene.GenerateUniqueName("Area")
        measurementNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsClosedCurveNode", name)
        measurementNode.SetAttribute("SimplifiedViewer", "")
        area = measurementNode.GetMeasurement("area")
        area.SetName("Area")
        area.EnabledOn()
        self._parameterNode.measurementNodes.append(measurementNode)

    def onNewCurveButtonClicked(self):
        """
        Create a new curve measurement
        """
        name = slicer.mrmlScene.GenerateUniqueName("Curve length")
        measurementNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode", name)
        measurementNode.SetAttribute("SimplifiedViewer", "")
        area = measurementNode.GetMeasurement("length")
        area.SetName("Length")
        area.EnabledOn()
        self._parameterNode.measurementNodes.append(measurementNode)

    def updateMeasurementsWidgets(self):
        shNode = self.ui.measurementsTreeView.subjectHierarchyNode()
        currentItemID = self.ui.measurementsTreeView.currentItem()
        selectedNode = None
        if currentItemID != slicer.vtkMRMLSubjectHierarchyNode.GetInvalidItemID():
            selectedNode = shNode.GetItemDataNode(currentItemID)
        self.ui.markupsPlaceWidget.setCurrentNode(selectedNode)
        self.ui.markupsPlaceWidget.findChild("ctkColorPickerButton", "ColorButton").visible = False
        self.ui.markupsPlaceWidget.findChild("QToolButton", "MoreButton").visible = False

        self.ui.measurementsTreeView.header().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        self.ui.measurementsTreeView.header().setSectionResizeMode(1, qt.QHeaderView.Stretch)
        self.ui.measurementsTreeView.header().setSectionResizeMode(2, qt.QHeaderView.Fixed)
        self.ui.measurementsTreeView.header().setSectionResizeMode(3, qt.QHeaderView.Fixed)


    def updateInputWidgets(self):
        """
        Update the input widgets
        """
        if not self._parameterNode:
            return

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
        sceneViewsLogic = slicer.modules.sceneviews.logic()
        row = 0
        for index in range(sceneViewsLogic.GetNumberOfSceneViews()):
            column = 0

            sceneViewName = sceneViewsLogic.GetNthSceneViewName(index)
            pushButton = qt.QPushButton(sceneViewName)
            pushButton.connect('clicked()', lambda sceneViewName=sceneViewName: self.onSceneViewClicked(sceneViewName))
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

        self.clippingEnabledAction.setChecked(self.logic.getClipping())
        self.clippingPlaneVisibilityAction.setChecked(self.logic.getClippingPlaneVisibility())

        wasBlocking = self.crosshairVisibilityButton.blockSignals(True)
        self.crosshairVisibilityButton.checked = self.logic.getCrosshairVisibility()
        self.crosshairVisibilityButton.blockSignals(wasBlocking)

    def onSceneViewClicked(self, sceneViewName):
        self.logic.restoreSceneView(sceneViewName)
        self.updateGUIFromMRML()

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

    def onClippingButtonClicked(self, visible):
        """
        Update the clipping visibility
        """
        if self._parameterNode and self._parameterNode.clipNode:
            self.logic.setClipping(visible)

    def onClippingPlaneVisibilityButtonClicked(self, visible):
        """
        Update the clipping plane visibility
        """
        if self._parameterNode and self._parameterNode.clipNode:
            self.logic.setClippingPlaneVisibility(visible)

    def onCrosshairVisibilityButtonClicked(self, visible):
        """
        Update the crosshair visibility
        """
        self.logic.setCrosshairVisibility(visible)

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
        clipNode = self.getParameterNode().clipNode
        if not clipNode:
            return False

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

    def setCrosshairVisibility(self, visible: bool):
        crosshairNode = slicer.util.getNode("Crosshair")
        if not crosshairNode:
            return

        crosshairMode = slicer.vtkMRMLCrosshairNode.NoCrosshair
        if visible:
            crosshairMode = slicer.vtkMRMLCrosshairNode.ShowBasic
        crosshairNode.SetCrosshairMode(crosshairMode)

    def getCrosshairVisibility(self):
        crosshairNode = slicer.util.getNode("Crosshair")
        if not crosshairNode:
            return False
        return crosshairNode.GetCrosshairMode() == slicer.vtkMRMLCrosshairNode.ShowBasic

    def restoreSceneView(self, sceneViewName):

        # Preserve clip states
        # TODO: In the future, we may be able to prevent scene views from modifying these nodes
        clipping = self.getClipping()
        planeVisibility = self.getClippingPlaneVisibility()
        crosshairVisibility = self.getCrosshairVisibility()

        with slicer.util.RenderBlocker():
            layoutManager = slicer.app.layoutManager()
            currentLayout = layoutManager.layout

            sceneViewLogic = slicer.modules.sceneviews.logic()
            sceneViewLogic.RestoreSceneView(sceneViewName)

            layoutManager.setLayout(currentLayout)

            # Restore clip states
            self.setClipping(clipping)
            self.setClippingPlaneVisibility(planeVisibility)
            self.setCrosshairVisibility(crosshairVisibility)

            # Restore view background color
            for viewNode in slicer.util.getNodesByClass("vtkMRMLViewNode"):
                viewNode.SetBackgroundColor(0,0,0)
                viewNode.SetBackgroundColor2(0,0,0)
                viewNode.SetBoxVisible(False)

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
