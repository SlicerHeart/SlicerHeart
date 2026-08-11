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
        self.parent.dependencies = ["UserStatistics"]
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

class ResizeFilter(qt.QObject):
    """
    A filter that detects resize events.
    """
    def __init__(self, parent=None, moduleWidget=None):
        super().__init__(parent)
        if parent:
            parent.installEventFilter(self)
        self.moduleWidget = moduleWidget

    def eventFilter(self, obj, event):
        if event.type() != qt.QEvent.Resize:
            return False

        if self.moduleWidget is None and self.moduleWidget.parent.isEntered:
            return False
        self.moduleWidget.onResizeEvent()
        return False

class IdleCloseWarningDialog(qt.QDialog):

  def __init__(self, parent):
    qt.QDialog.__init__(self, parent)

    flags = self.windowFlags() | qt.Qt.FramelessWindowHint | qt.Qt.WindowStaysOnTopHint
    self.setWindowFlags(flags)

    layout = qt.QVBoxLayout()
    self.setLayout(layout)

    self.setWindowTitle("Idle Close Warning")
    self.setAttribute(qt.Qt.WA_DeleteOnClose)

    self.updateTimer = qt.QTimer(self)
    self.updateTimer.setInterval(1000) # Update every second
    self.updateTimer.setSingleShot(False)
    self.updateTimer.timeout.connect(self.updateLabel)
    self.updateTimer.start()
    self.startTime = qt.QTime.currentTime()

    self.warningLabel = qt.QLabel("")
    layout.addWidget(self.warningLabel)
    self.updateLabel()

  def updateLabel(self):
    """
    Update the warning label with the remaining time.
    """
    elapsedTime = self.startTime.secsTo(qt.QTime.currentTime())
    remainingTime = SimplifiedViewerWidget.getIdleCloseSeconds() - elapsedTime
    if remainingTime <= 0.0:
        # Close slicer
        slicer.util.quit()
        return
    labelText = f"You have been idle for a while. The application will be closed in {remainingTime:.0f} seconds."
    logging.info(f"Shutdown in {remainingTime} seconds")
    self.warningLabel.setText(labelText)

class BlockGUIStateSaver(qt.QObject):
    def eventFilter(self, obj, event):
        if event.type() != qt.QEvent.Close:
            # Only handle close events
            return False

        if obj is not slicer.util.mainWindow():
            # Only act if the main window is being closed
            return False

        if slicer.modules.simplifiedviewer.widgetRepresentation().self().getFull3DSlicerInterfaceVisible():
            # Do not block GUI state saver if the full 3D Slicer interface is visible
            return False

        slicer.util.quit()
        return True  # Block the close event

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
        self.buttonSize = 64
        self.spacing = 3

    def setup(self) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.setup(self)

        self.resizeFilter = ResizeFilter(slicer.util.mainWindow(), self)
        self.idleCloseWarningDialog = None

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

        self.setupDicomBrowser()

        if self.topLeftWidget:
            self.topLeftWidget.hide()
            self.topLeftWidget.setParent(None)
            self.topLeftWidget.deleteLater()

        if self.bottomLeftWidget:
            self.bottomLeftWidget.hide()
            self.bottomLeftWidget.setParent(None)
            self.bottomLeftWidget.deleteLater()

        topLeftButtons = []

        self.dicomBrowserButton = qt.QToolButton()
        self.dicomBrowserButton.setToolTip("Open DICOM browser")
        self.dicomBrowserButton.checkable = True
        self.dicomBrowserButton.connect('clicked(bool)', self.toggleDicomBrowser)
        topLeftButtons.append(self.dicomBrowserButton)

        self.svToggleButton = qt.QToolButton()
        self.svToggleButton.setToolTip("Toggle scene views panel")
        self.svToggleButton.checkable = True
        self.svToggleButton.connect('clicked(bool)', self.toggleSceneViewPanel)
        topLeftButtons.append(self.svToggleButton)

        self.measurementsToggleButton = qt.QToolButton()
        self.measurementsToggleButton.setToolTip("Toggle measurements panel")
        self.measurementsToggleButton.checkable = True
        self.measurementsToggleButton.connect('clicked(bool)', self.toggleMeasurementPanel)
        topLeftButtons.append(self.measurementsToggleButton)

        self.crosshairVisibilityButton = qt.QToolButton()
        self.crosshairVisibilityButton.setToolTip("Toggle crosshair visibility")
        self.crosshairVisibilityButton.checkable = True
        self.crosshairVisibilityButton.connect('toggled(bool)', self.onCrosshairVisibilityButtonClicked)
        topLeftButtons.append(self.crosshairVisibilityButton)

        self.mprVisibilityButton = qt.QToolButton()
        self.mprVisibilityButton.setToolTip("Toggle slice intersections")
        self.mprVisibilityButton.checkable = True
        self.mprVisibilityButton.connect('toggled(bool)', self.onMprVisibilityButtonClicked)
        topLeftButtons.append(self.mprVisibilityButton)

        self.fourUpViewAction = qt.QAction("Four Up View")
        self.fourUpViewAction.setToolTip("Switch to four up view")
        self.fourUpViewAction.connect('triggered()', self.onFourUpViewButtonClicked)
        self.conventionalViewAction = qt.QAction("Conventional View")
        self.conventionalViewAction.setToolTip("Switch to conventional view")
        self.conventionalViewAction.connect('triggered()', self.onConventionalViewButtonClicked)
        self.layoutsMenu = qt.QMenu()
        self.layoutsMenu.addAction(self.fourUpViewAction)
        self.layoutsMenu.addAction(self.conventionalViewAction)
        self.layoutsButton = qt.QToolButton()
        self.layoutsButton.setToolTip("Change view layouts")
        self.layoutsButton.setMenu(self.layoutsMenu)
        self.layoutsButton.setPopupMode(qt.QToolButton.InstantPopup)
        topLeftButtons.append(self.layoutsButton)

        self.fullSlicerInterfaceAction = qt.QAction("Show full 3D Slicer Interface")
        self.fullSlicerInterfaceAction.setToolTip("Show/hide full 3D Slicer interface")
        self.fullSlicerInterfaceAction.setCheckable(True)
        self.fullSlicerInterfaceAction.connect('toggled(bool)', self.setFull3DSlicerInterfaceVisible)
        self.fullSlicerInterfaceAction.setVisible(self.developerMode)
        self.settingsMenu = qt.QMenu()
        self.settingsMenu.addAction(self.fullSlicerInterfaceAction)

        self.settingsButton = qt.QToolButton()
        self.settingsButton.setToolTip("Settings")
        self.settingsButton.setMenu(self.settingsMenu)
        self.settingsButton.setPopupMode(qt.QToolButton.InstantPopup)

        settingActionVisible = False
        for action in self.settingsMenu.actions():
            if action.isVisible():
                settingActionVisible = True
                break

        if settingActionVisible:
          # Only show the settings button if there is at least one visible action
          topLeftButtons.append(self.settingsButton)

        centralWidget = slicer.util.mainWindow().centralWidget()
        self.topLeftWidget = OverlayWidget(centralWidget)
        self.topLeftWidget.setObjectName("buttonWidget")
        self.topLeftWidget.corner = OverlayWidget.TopLeft
        self.topLeftWidget.setLayout(qt.QHBoxLayout())
        self.topLeftWidget.layout().setMargin(0)
        self.topLeftWidget.layout().setContentsMargins(qt.QMargins(0,0,0,0))
        self.topLeftWidget.layout().setSpacing(self.spacing)
        for button in topLeftButtons:
            button.setFixedSize(self.buttonSize, self.buttonSize)
            self.topLeftWidget.layout().addWidget(button)
        self.topLeftWidget.layout().addStretch(1)  # Add stretchable space to the right side
        self.topLeftWidget.setAttribute(qt.Qt.WA_NoSystemBackground)
        self.topLeftWidget.setAttribute(qt.Qt.WA_TranslucentBackground)
        self.topLeftWidget.setAutoFillBackground(False)
        self.topLeftWidget.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
        self.topLeftWidget.setFixedHeight(self.buttonSize)
        self.topLeftWidget.setFixedWidth(len(topLeftButtons)*self.buttonSize + (len(topLeftButtons)-1)*self.spacing)
        self.topLeftWidget.show()

        self.bottomLeftWidget = OverlayWidget(centralWidget)
        self.bottomLeftWidget.setObjectName("bottomLeftWidget")
        self.bottomLeftWidget.corner = OverlayWidget.BottomLeft
        self.bottomLeftWidget.setLayout(qt.QVBoxLayout())
        self.bottomLeftWidget.layout().setMargin(0)
        self.bottomLeftWidget.layout().setContentsMargins(qt.QMargins(0,0,0,0))
        self.bottomLeftWidget.layout().setSpacing(self.spacing)
        self.bottomLeftWidget.layout().addWidget(self.ui.sequenceBrowserWidget)

        bottomRightButtons = []
        for button in self.ui.sequenceBrowserWidget.findChildren(qt.QAbstractButton):
            if button.isVisibleTo(self.ui.sequenceBrowserWidget):
                bottomRightButtons.append(button)
                button.setFixedSize(self.buttonSize, self.buttonSize)

        self.ui.sequenceBrowserSeekWidget.setFixedHeight(self.buttonSize/2.0)
        self.bottomLeftWidget.layout().addWidget(self.ui.sequenceBrowserSeekWidget)
        self.bottomLeftWidget.setAttribute(qt.Qt.WA_NoSystemBackground)
        self.bottomLeftWidget.setAttribute(qt.Qt.WA_TranslucentBackground)
        self.bottomLeftWidget.setAutoFillBackground(False)
        self.bottomLeftWidget.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
        self.bottomLeftWidget.setFixedHeight(self.buttonSize*1.5 + self.spacing)
        self.bottomLeftWidget.setFixedWidth(len(bottomRightButtons)*self.buttonSize + (len(bottomRightButtons)-1)*self.spacing)
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
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartImportEvent, self.onSceneStartImport)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndImportEvent, self.onSceneEndImport)

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()

        if self.parent.isEntered:
            self.enter()

        if not hasattr(slicer.modules, 'userstatistics'):
            slicer.util.messageBox("This modules requires the Sandbox extension. Install Sandbox and restart Slicer.")
            return

        if self.getIdleCloseEnabled():
            from UserStatistics import IdleDetectionEventFilter
            self.idleDetectionEventFilter = IdleDetectionEventFilter()
            self.idleDetectionEventFilter.setInterval(1000 * self.getIdleTimeoutSeconds())
            self.idleDetectionEventFilter.idleStarted.connect(self.onIdleStarted)
            self.idleDetectionEventFilter.idleEnded.connect(self.onIdleEnded)
            self.idleDetectionEventFilter.start()
            slicer.app.installEventFilter(self.idleDetectionEventFilter)

        self.blockGUIStateSaver = BlockGUIStateSaver()
        slicer.app.installEventFilter(self.blockGUIStateSaver)

        self.updateButtonVisibility()

    def setupDicomBrowser(self):
        """
        Setup the DICOM browser widget and view factory.
        """
        self.dicomVisualBrowser = ctk.ctkDICOMVisualBrowserWidget()
        for groupBoxName in ["ActionsCollapsibleGroupBox", "AdvancedCollapsibleGroupBox"]:
            groupBox = self.dicomVisualBrowser.findChild(ctk.ctkCollapsibleGroupBox, groupBoxName)
            if groupBox:
                groupBox.hide()
        self.dicomVisualBrowser.setDatabaseDirectory(slicer.dicomDatabase.databaseDirectory)
        if hasattr(self.dicomVisualBrowser, "onShowPatients"):
            # Older CTK: patients must be shown manually. Newer CTK removed this slot;
            # setDatabaseDirectory() already populates the patient view from the local database.
            self.dicomVisualBrowser.onShowPatients()
        # Older CTK displayed patients in a tab widget; newer CTK uses a model/view
        # based patient list and these child widgets no longer exist.
        patientsTabMenuToolButton = self.dicomVisualBrowser.findChild(qt.QToolButton, "patientsTabMenuToolButton")
        if patientsTabMenuToolButton:
            patientsTabMenuToolButton.hide()
        patientsTabWidget = self.dicomVisualBrowser.findChild(qt.QTabWidget, "PatientsTabWidget")
        if patientsTabWidget:
            patientsTabWidget.setCornerWidget(None, qt.Qt.TopLeftCorner)
        self.dicomVisualBrowser.seriesRetrieved.connect(self.onSeriesRetrieved)

        self.dicomWidget = qt.QWidget()
        self.dicomWidget.setLayout(qt.QVBoxLayout())
        self.dicomWidget.layout().addSpacing(self.buttonSize)
        self.dicomWidget.layout().addWidget(self.dicomVisualBrowser)

        self.viewFactory = slicer.qSlicerSingletonViewFactory()
        self.viewFactory.setTagName("visualdicombrowser")
        self.viewFactory.setWidget(self.dicomWidget)
        if slicer.app.layoutManager() is not None:
            slicer.app.layoutManager().registerViewFactory(self.viewFactory)
        layoutManager = slicer.app.layoutManager()
        layoutManager.layoutChanged.connect(self.onLayoutChanged)
        layout = (
            '<layout type="horizontal">'
            " <item>"
            "  <visualdicombrowser></visualdicombrowser>"
            " </item>"
            "</layout>"
        )
        layoutNode = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        self.dicomLayout = slicer.vtkMRMLLayoutNode.SlicerLayoutUserView + slicer.vtkMRMLLayoutNode.SlicerLayoutDicomBrowserView
        layoutNode.AddLayoutDescription(self.dicomLayout, layout)
        self.previousViewArrangement = layoutNode.GetViewArrangement()

    def cleanup(self) -> None:
        """Called when the application closes and the module widget is destroyed."""
        self.removeObservers()
        if self.idleDetectionEventFilter:
          self.idleDetectionEventFilter.deleteLater()
          slicer.app.removeEventFilter(self.idleDetectionEventFilter)
          self.idleDetectionEventFilter = None

        if self.idleCloseWarningDialog:
            # If the dialog is open then close it
            self.idleCloseWarningDialog.deleteLater()
            self.idleCloseWarningDialog.close()
            self.idleCloseWarningDialog = None

        if self.blockGUIStateSaver:
          self.blockGUIStateSaver.deleteLater()
          slicer.app.removeEventFilter(self.blockGUIStateSaver)
          self.blockGUIStateSaver = None

    def enter(self) -> None:
        """Called each time the user opens this module."""
        # Make sure parameter node exists and observed
        self.initializeParameterNode()
        self.setFull3DSlicerInterfaceVisible(self.getFull3DSlicerInterfaceVisible())
        sceneViewsLogic = slicer.modules.sceneviews.logic()
        if sceneViewsLogic.GetNumberOfSceneViews() > 0:
            self.logic.restoreSceneView(0)

        self.updateGUIFromMRML()
        qt.QTimer.singleShot(0, self.updateGUIFromMRML) # Update GUI again after the module is fully initialized

    def exit(self) -> None:
        """Called each time the user opens a different module."""
        # Do not react to parameter node changes (GUI will be updated when the user enters into the module)
        self.removeObservers(self.onParameterNodeModified)

    @staticmethod
    def getIdleCloseEnabled():
        return slicer.util.settingsValue('SimplifiedViewer/IdleCloseEnabled', True, converter=slicer.util.toBool)

    @staticmethod
    def getIdleTimeoutSeconds():
        """
        Get the idle timeout in seconds.
        This is the time after which the user is considered idle.
        """
        return slicer.util.settingsValue('SimplifiedViewer/IdleTimeoutSeconds', 1800, converter=float)

    @staticmethod
    def getIdleCloseSeconds():
        """
        Get the idle close timeout in seconds.
        This is the time after which the application will be closed if the user is idle.
        """
        return slicer.util.settingsValue('SimplifiedViewer/IdleCloseSeconds', 300, converter=float)

    def onIdleStarted(self):
        """
        Called when the user is idle for a certain amount of time.
        This can be used to hide the full 3D Slicer interface.
        """
        if self.getFull3DSlicerInterfaceVisible():
            # Don't show idle warning dialog if the full 3D Slicer interface is visible
            return

        if self.idleCloseWarningDialog:
            # If the dialog is already open then do not show it again
            return

        # Modal dialog to warn the user that the full 3D Slicer interface will be closed
        self.idleCloseWarningDialog = IdleCloseWarningDialog(self.parent)
        self.idleCloseWarningDialog.setWindowTitle(_("Idle Close Warning"))
        self.idleCloseWarningDialog.show()

    def onIdleEnded(self):
        """
        Called when the user is no longer idle.
        This can be used to show the full 3D Slicer interface.
        """
        if self.idleCloseWarningDialog:
            # If the dialog is open then close it
            self.idleCloseWarningDialog.deleteLater()
            self.idleCloseWarningDialog.close()
            self.idleCloseWarningDialog = None

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

    def onSceneStartImport(self, caller, event) -> None:
        """Called just before a scene is imported."""
        # Do not sync GUI from a half-imported parameter node (node references are only resolved at the end of the import)
        self.setParameterNode(None)

    def onSceneEndImport(self, caller, event) -> None:
        """Called just after a scene is imported."""
        if self.parent.isEntered:
            self.initializeParameterNode()
            self.updateGUIFromMRML()

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

    def onSeriesRetrieved(self, seriesInstanceUIDs):
        """
        Load the series by their instance UIDs.
        """
        seriesList = [str(seriesInstanceUID) for seriesInstanceUID in seriesInstanceUIDs]
        if seriesList is None or not seriesList:
            return

        from DICOMLib import DICOMUtils
        DICOMUtils.loadSeriesByUID(seriesList)
        self.toggleDicomBrowser(False)  # Hide DICOM browser after loading series

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

        pluginHandler = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        pluginLogic = pluginHandler.pluginLogic()
        if visible:
            # Show all context menu actions in views
            pluginLogic.allowedViewContextMenuActionNames = []
        else:
          # Hide all context menu actions in views
          pluginLogic.allowedViewContextMenuActionNames = ["DummyAction"]

        if self.developerMode:
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

    def toggleDicomBrowser(self, visible: bool):
        """
        Toggle the DICOM browser visibility.
        """
        if visible:
            self.previousViewArrangement = slicer.app.layoutManager().layoutLogic().GetLayoutNode().GetViewArrangement()
            slicer.app.layoutManager().setLayout(self.dicomLayout)
        else:
            # Restore the previous view arrangement
            slicer.app.layoutManager().setLayout(self.previousViewArrangement)

        self.dicomBrowserButton.checked = visible
        self.measurementsToggleButton.checked = False
        self.svToggleButton.checked = False
        self.updateSidePanelVisibility()
        self.updateButtonVisibility()

    def updateButtonVisibility(self):
        settingActionVisible = False
        for action in self.settingsMenu.actions():
            if action.isVisible():
                settingActionVisible = True
                break
        # Only show the settings button if there is at least one visible action
        self.settingsButton.setVisible(settingActionVisible)

        dicomBrowserVisible = self.dicomBrowserButton.isChecked()
        self.svToggleButton.visible = not dicomBrowserVisible
        self.measurementsToggleButton.visible = not dicomBrowserVisible
        self.crosshairVisibilityButton.visible = not dicomBrowserVisible
        self.mprVisibilityButton.visible = not dicomBrowserVisible
        self.layoutsButton.visible = not dicomBrowserVisible
        self.settingsButton.visible = settingActionVisible

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
        sizePx = 192
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
            self.dicomBrowserButton:                               "Icons/Folder.svg",
            self.svToggleButton:                                   "Icons/SceneViews.svg",
            self.measurementsToggleButton:                         "Icons/Measurements.svg",
            self.crosshairVisibilityButton:                        "Icons/Crosshair.svg",
            self.mprVisibilityButton:                              "Icons/SliceIntersections.svg",
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
        #svg_data = svg_data.replace('width="24"', f'width="{size}"')
        #svg_data = svg_data.replace('height="24"', f'height="{size}"')

        # Create a QIcon from the QPixmap
        pixmap = qt.QPixmap(384,384)
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
        full3DSlicerInterfaceVisible = self.getFull3DSlicerInterfaceVisible()
        layoutManager = slicer.app.layoutManager()
        for viewWidget in layoutManager.viewWidgets():

            viewNode = None
            if isinstance(viewWidget, slicer.qMRMLSliceWidget):
                viewNode = viewWidget.mrmlSliceNode()
            elif isinstance(viewWidget, slicer.qMRMLThreeDWidget):
                viewNode = viewWidget.mrmlViewNode()

            if isinstance(viewWidget, slicer.qMRMLSliceWidget):
                viewWidget.setSliceOffsetSliderOrientation(qt.Qt.Vertical if not full3DSlicerInterfaceVisible else qt.Qt.Horizontal)
                viewWidget.sliceController().setVisible(full3DSlicerInterfaceVisible)
            elif isinstance(viewWidget, slicer.qMRMLThreeDWidget):
                viewWidget.threeDController().setVisible(full3DSlicerInterfaceVisible)
                if not full3DSlicerInterfaceVisible:
                    viewNode.SetBackgroundColor(0,0,0)
                    viewNode.SetBackgroundColor2(0,0,0)
                    viewNode.SetBoxVisible(False)

        # Disable slice annotations
        if not full3DSlicerInterfaceVisible:
            if slicer.modules.DataProbeInstance.infoWidget:
                sliceAnnotations = slicer.modules.DataProbeInstance.infoWidget.sliceAnnotations
                sliceAnnotations.sliceViewAnnotationsEnabled = False
                sliceAnnotations.updateSliceViewFromGUI()
        self.updateViewerButtons()

    def updateViewerButtons(self):
        """
        Add/Update the buttons shown in the viewer widgets.
        """
        full3DSlicerInterfaceVisible = self.getFull3DSlicerInterfaceVisible()
        layoutManager = slicer.app.layoutManager()
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        for viewWidget in layoutManager.viewWidgets():
            overlayWidget = viewWidget.findChild(qt.QWidget, "viewOverlayWidget")
            if not overlayWidget:
                view = None
                if isinstance(viewWidget, slicer.qMRMLSliceWidget):
                    view = viewWidget.sliceView()
                elif isinstance(viewWidget, slicer.qMRMLThreeDWidget):
                    view = viewWidget.threeDView()
                overlayWidget = OverlayWidget(view)
                overlayWidget.setObjectName("viewOverlayWidget")
                overlayWidget.corner = OverlayWidget.TopRight
                overlayWidget.setLayout(qt.QHBoxLayout())
                overlayWidget.layout().setContentsMargins(qt.QMargins(0,0,0,0))
                overlayWidget.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
                overlayWidget.setFixedHeight(self.buttonSize)
                overlayWidget.layout().setSpacing(self.spacing)
                overlayWidget.setAttribute(qt.Qt.WA_NoSystemBackground)
                overlayWidget.setAttribute(qt.Qt.WA_TranslucentBackground)
                overlayWidget.setAutoFillBackground(False)
                overlayWidget.show()

                if isinstance(viewWidget, slicer.qMRMLThreeDWidget):
                    clippingEnabledAction = qt.QAction("Clipping", overlayWidget)
                    clippingEnabledAction.setObjectName("clippingEnabledAction")
                    clippingEnabledAction.setToolTip("Enable/disable clipping")
                    clippingEnabledAction.setCheckable(True)
                    clippingEnabledAction.connect('toggled(bool)', self.onClippingButtonClicked)
                    clippingPlaneVisibilityAction = qt.QAction("Clipping Plane", overlayWidget)
                    clippingPlaneVisibilityAction.setObjectName("clippingPlaneVisibilityAction")
                    clippingPlaneVisibilityAction.setToolTip("Show/hide clipping plane")
                    clippingPlaneVisibilityAction.setCheckable(True)
                    clippingPlaneVisibilityAction.connect('toggled(bool)', self.onClippingPlaneVisibilityButtonClicked)
                    visibilityMenu = qt.QMenu(overlayWidget)
                    visibilityMenu.addAction(clippingEnabledAction)
                    visibilityMenu.addAction(clippingPlaneVisibilityAction)
                    visibilityButton = qt.QToolButton()
                    visibilityButton.setObjectName("visibilityButton")
                    visibilityButton.setToolTip("Change visibility settings")
                    visibilityButton.setMenu(visibilityMenu)
                    visibilityButton.setPopupMode(qt.QToolButton.InstantPopup)
                    overlayWidget.layout().addWidget(visibilityButton)

                centerViewButton = qt.QToolButton()
                centerViewButton.setObjectName("centerViewButton")
                centerViewButton.setToolTip(_("Reset view"))
                centerViewButton.setCheckable(False)
                if isinstance(viewWidget, slicer.qMRMLSliceWidget):
                    centerViewButton.connect('clicked()', lambda viewWidget=viewWidget: viewWidget.sliceLogic().FitSliceToAll())
                elif isinstance(viewWidget, slicer.qMRMLThreeDWidget):
                    centerViewButton.connect('clicked()', lambda viewWidget=viewWidget: viewWidget.threeDView().resetFocalPoint())
                overlayWidget.layout().addWidget(centerViewButton)

                maximizeViewButton = qt.QToolButton()
                maximizeViewButton.setObjectName("maximizeViewButton")
                maximizeViewButton.setToolTip(_("Toggle full screen mode"))
                maximizeViewButton.setCheckable(False)
                maximizeViewButton.connect('clicked()', lambda viewWidget=viewWidget: self.toggleMaximizedView(viewWidget))
                overlayWidget.layout().addWidget(maximizeViewButton)

            viewNode = None
            if isinstance(viewWidget, slicer.qMRMLSliceWidget):
                viewNode = viewWidget.mrmlSliceNode()
            elif isinstance(viewWidget, slicer.qMRMLThreeDWidget):
                viewNode = viewWidget.mrmlViewNode()

            centerViewButton = overlayWidget.findChild(qt.QToolButton, "centerViewButton")
            maximizeViewButton = overlayWidget.findChild(qt.QToolButton, "maximizeViewButton")

            viewButtons = [centerViewButton, maximizeViewButton]
            viewButtonIconMap = {
                centerViewButton: "Icons/Center.svg",
                maximizeViewButton: "Icons/FullscreenExit.svg" if layoutNode.IsMaximizedViewNode(viewNode) else "Icons/Fullscreen.svg",
            }

            visibilityButton = overlayWidget.findChild(qt.QToolButton, "visibilityButton")
            if visibilityButton:
                viewButtons.append(visibilityButton)
                viewButtonIconMap[visibilityButton] = "Icons/Visibility.svg"

                for action in visibilityButton.menu().actions():
                    action.setVisible(True)
                    if action.objectName == "clippingEnabledAction":
                        action.setChecked(self.logic.getClipping())
                    elif action.objectName == "clippingPlaneVisibilityAction":
                        action.setChecked(self.logic.getClippingPlaneVisibility())

            overlayWidget.setFixedWidth(len(viewButtons) * self.buttonSize + (len(viewButtons) - 1) * self.spacing)

            palette = slicer.app.palette()
            sizePx = 32
            color = palette.color(qt.QPalette.Text)
            for button in viewButtons:
                iconPath = viewButtonIconMap[button]
                icon = self.loadSvg(self.resourcePath(iconPath), sizePx, color)
                button.setFixedSize(self.buttonSize, self.buttonSize)
                button.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
                button.setIcon(icon)
                button.setIconSize(qt.QSize(sizePx, sizePx))
                button.setVisible(not full3DSlicerInterfaceVisible)

    def onLayoutChanged(self):
        """
        Called when the layout is changed. This is used to update the viewer widgets
        """
        currentLayout = slicer.app.layoutManager().layout
        if currentLayout == slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView \
            or currentLayout == slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalWidescreenView:
            self.updateConventionalLayout()
        self.updateViewerWidgets()

    def onResizeEvent(self):
        """
        Called when the main window is resized.
        """
        currentLayout = slicer.app.layoutManager().layout
        if currentLayout == slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView \
            or currentLayout == slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalWidescreenView:
            self.updateConventionalLayout()

    def updateConventionalLayout(self):
        currentLayout = slicer.app.layoutManager().layout
        expectedLayout = slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView

        # detect landscape or portrait mode from main window size
        mainWindow = slicer.util.mainWindow()
        if mainWindow.size.width() > mainWindow.size.height():
            expectedLayout = slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalWidescreenView
        if currentLayout != expectedLayout:
            slicer.app.layoutManager().setLayout(expectedLayout)

    def toggleMaximizedView(self, viewWidget):
        """
        Toggle the maximized view for the given view widget.
        """
        viewNode = None
        if isinstance(viewWidget, slicer.qMRMLSliceWidget):
            viewNode = viewWidget.mrmlSliceNode()
        elif isinstance(viewWidget, slicer.qMRMLThreeDWidget):
            viewNode = viewWidget.mrmlViewNode()

        layoutNode = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        viewMaximized = layoutNode.IsMaximizedViewNode(viewNode)
        if viewMaximized:
            layoutNode.RemoveMaximizedViewNode(viewNode)
        else:
            layoutNode.AddMaximizedViewNode(viewNode)
        self.updateViewerWidgets

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
        self.fullSlicerInterfaceAction.setChecked(self.getFull3DSlicerInterfaceVisible())
        self.updateInputWidgets()
        self.updateSelectedNodeWidget()
        self.updateSequenceBrowserWidgets()
        self.updateClippingWidgets()
        self.updateMeasurementsWidgets()
        self.updateSidePanelVisibility()

    def updateSidePanelVisibility(self):
        full3DSlicerInterfaceVisible = self.getFull3DSlicerInterfaceVisible()
        modulePanel = slicer.util.mainWindow().findChildren("QDockWidget", "PanelDockWidget")[0]
        if not full3DSlicerInterfaceVisible:
            slicer.util.mainWindow().addDockWidget(qt.Qt.RightDockWidgetArea, modulePanel)
        else:
            slicer.util.mainWindow().addDockWidget(qt.Qt.LeftDockWidgetArea, modulePanel)
        sidePanelVisible = self.svToggleButton.checked or self.measurementsToggleButton.checked or full3DSlicerInterfaceVisible
        modulePanel.visible = sidePanelVisible
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
            pushButton.connect('clicked()', lambda sceneViewIndex=index: self.onSceneViewClicked(sceneViewIndex))
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

        wasBlocking = self.crosshairVisibilityButton.blockSignals(True)
        self.crosshairVisibilityButton.checked = self.logic.getCrosshairVisibility()
        self.crosshairVisibilityButton.blockSignals(wasBlocking)

        wasBlocking = self.mprVisibilityButton.blockSignals(True)
        self.mprVisibilityButton.checked = self.logic.getSliceIntersectionsVisibility()
        self.mprVisibilityButton.blockSignals(wasBlocking)

    def onSceneViewClicked(self, sceneViewIndex):
        self.logic.restoreSceneView(sceneViewIndex)
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
        layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalWidescreenView)

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

    def onMprVisibilityButtonClicked(self, visible):
        """
        Update the slice intersections visibility
        """
        self.logic.setSliceIntersectionsVisibility(visible)

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
        self._restoreSceneViewIndex = -1

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

        clippingNodes = self.getClippingNodes()
        for clippingNode in clippingNodes:
            if not clippingNode or not clippingNode.IsA("vtkMRMLMarkupsNode"):
                continue
            clippingNode.SetDisplayVisibility(visible)

    def getClippingNodes(self):
        clipNode = self.getParameterNode().clipNode
        if not clipNode:
            return []

        clippingNodes = []
        for index in range(clipNode.GetNumberOfClippingNodes()):
            clippingNode = clipNode.GetNthClippingNode(index)
            if clippingNode and clippingNode.IsA("vtkMRMLMarkupsNode"):
                clippingNodes.append(clippingNode)
        return clippingNodes

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

    def setSliceIntersectionsVisibility(self, visible: bool):
        appLogic = slicer.app.applicationLogic()
        if not appLogic:
            return
        appLogic.SetIntersectingSlicesEnabled(slicer.vtkMRMLApplicationLogic.IntersectingSlicesVisibility, visible)
        appLogic.SetIntersectingSlicesEnabled(slicer.vtkMRMLApplicationLogic.IntersectingSlicesInteractive, visible)

    def getSliceIntersectionsVisibility(self):
        appLogic = slicer.app.applicationLogic()
        if not appLogic:
            return False
        return appLogic.GetIntersectingSlicesEnabled(slicer.vtkMRMLApplicationLogic.IntersectingSlicesVisibility)

    def updateSceneView(self, sceneViewIndex: int):
        """
        Update the scene view with the current view settings
        """
        sceneViewLogic = slicer.modules.sceneviews.logic()
        clippingNodes = self.getClippingNodes()
        collection = vtk.vtkCollection()
        for clippingNode in clippingNodes:
            collection.AddItem(clippingNode)
        sceneViewLogic.UpdateNthSceneView(sceneViewIndex, collection)

    def restoreSceneView(self, sceneViewIndex: int):
        """
        Restore the scene view with the given index
        """

        if self._restoreSceneViewIndex >= 0:
          # Update the current scene view with the current view settings
          self.updateSceneView(self._restoreSceneViewIndex)
        self._restoreSceneViewIndex = sceneViewIndex

        # Preserve clip states
        # TODO: In the future, we may be able to prevent scene views from modifying these nodes
        clipping = self.getClipping()
        planeVisibility = self.getClippingPlaneVisibility()
        crosshairVisibility = self.getCrosshairVisibility()
        sliceIntersectionsVisibility = self.getSliceIntersectionsVisibility()

        with slicer.util.RenderBlocker():
            layoutManager = slicer.app.layoutManager()
            currentLayout = layoutManager.layout

            sceneViewLogic = slicer.modules.sceneviews.logic()
            sceneViewLogic.RestoreSceneView(sceneViewIndex)

            # TODO: Temporary fix issues with invalid layouts when switching scene views
            layoutManager.setLayout(0)
            layoutManager.setLayout(1)
            layoutManager.setLayout(currentLayout)

            # Restore clip states
            self.setClipping(clipping)
            self.setClippingPlaneVisibility(planeVisibility)
            self.setCrosshairVisibility(crosshairVisibility)
            self.setSliceIntersectionsVisibility(sliceIntersectionsVisibility)

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
