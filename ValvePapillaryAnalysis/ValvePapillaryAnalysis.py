import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
import HeartValveLib
from HeartValveLib.Constants import PAPILLARY_MUSCLE_POINT_LABELS
from HeartValveWidgets.ValveSequenceBrowserWidget import ValveSequenceBrowserWidget

class ValvePapillaryAnalysis(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Valve Papillary Analysis"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["ValveAnnulusAnalysis"]
    self.parent.contributors = ["Andras Lasso (PerkLab), Christian Herz (CHOP), Matt Jolley (UPenn)"]
    self.parent.helpText = """Specify position and size of papillary muscles"""
    self.parent.acknowledgementText = """This file was originally developed by Andras Lasso, PerkLab."""


class ValvePapillaryAnalysisWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  @property
  def parameterNode(self):
    return self._parameterNode

  @parameterNode.setter
  def parameterNode(self, parameterNode):
    if parameterNode is self.parameterNode and self.parameterNodeObserver:  # no change and node is already observed
      return
    self.removeParameterNodeObserver()
    self._parameterNode = parameterNode
    self.addParameterNodeObserver()
    self.onParameterNodeModified()
    self.onDisplayFourUpView(resetViewOrientations=True)
    # Hide all slice views from 3D
    HeartValveLib.showSlices(False)

  def __init__(self, parent):
    ScriptedLoadableModuleWidget.__init__(self, parent)

    self.logic = ValvePapillaryAnalysisLogic()

    self._parameterNode = None
    self.parameterNodeObserver = None

    self.axialSlice = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeRed')
    self.orthogonalSlice1 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeYellow')
    self.orthogonalSlice2 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeGreen')

    self.papillaryMusclePointNames = PAPILLARY_MUSCLE_POINT_LABELS

    self.papillaryLineMarkupNode = None
    self.papillaryLineMarkupNodeObservers = []

    # Stores the currently selected HeartValveNode (scripted loadable module node)
    # and also provides methods to operate on it.
    self.valveModel = None

  def onReload(self):
    logging.debug("Reloading {}".format(self.moduleName))

    packageName = 'HeartValveLib'
    submoduleNames=['LeafletModel', 'ValveRoi', 'ValveModel', 'ValveSeries', 'HeartValves']
    import imp
    f, filename, description = imp.find_module(packageName)
    package = imp.load_module(packageName, f, filename, description)
    for submoduleName in submoduleNames:
      f, filename, description = imp.find_module(submoduleName, package.__path__)
      try:
          imp.load_module(packageName+'.'+submoduleName, f, filename, description)
      finally:
          f.close()
    ScriptedLoadableModuleWidget.onReload(self)

  def enter(self):
    pass

  def exit(self):
    pass

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)
    self.setupHeartValveSelector()
    self.setupSequenceBrowserWidget()
    self.setupPapillaryMusclesSection()
    self.setupQuantificationSection()
    self.layout.addStretch(1)

    # Define list of widgets for updateGUIFromParameterNode, updateParameterNodeFromGUI, and addGUIObservers
    self.nodeSelectorWidgets = {"HeartValve": self.heartValveSelector}

    # Use singleton parameter node (it is created if does not exist yet)
    self.parameterNode = self.logic.getParameterNode()
    # Set parameter node (widget will observe it and also updates GUI)
    self.onHeartValveSelect(self.heartValveSelector.currentNode())
    self.addGUIObservers()

  def setupSequenceBrowserWidget(self):
    self.valveSequenceBrowserWidget = ValveSequenceBrowserWidget(self.layout)
    self.valveSequenceBrowserWidget.valveBrowserNodeModified.connect(self.onValveSequenceBrowserNodeModified)
    self.valveSequenceBrowserWidget.heartValveNodeModified.connect(self.onValveSequenceBrowserNodeModified)
    self.valveSequenceBrowserWidget.readOnly = True

  def setupPapillaryMusclesSection(self):
    self.papillaryMusclesCollapsibleButton = ctk.ctkCollapsibleButton()
    self.papillaryMusclesCollapsibleButton.objectName = "PapillaryMuscles"
    self.papillaryMusclesCollapsibleButton.text = "Muscle points marking"
    self.papillaryMusclesCollapsibleButton.setLayout(qt.QFormLayout())
    self.layout.addWidget(self.papillaryMusclesCollapsibleButton)

    self.addShowAllPapillaryMusclesButton()
    self.addPapillaryMusclesTreeView()

    addTimePointWidget = qt.QWidget()
    addTimePointLayout = qt.QHBoxLayout(addTimePointWidget)
    addTimePointLayout.setContentsMargins(0, 0, 0, 0)
    self.papillaryMusclesCollapsibleButton.layout().addRow(addTimePointWidget)

    self.addTimePointButton = qt.QPushButton("Add time point")
    self.addTimePointButton.connect('clicked()', self.onAddTimePoint)
    addTimePointLayout.addWidget(self.addTimePointButton)

    self.removeTimePointButton = qt.QPushButton("Remove time point")
    self.removeTimePointButton.connect('clicked()', self.onRemoveTimePoint)
    addTimePointLayout.addWidget(self.removeTimePointButton)

    self.addPapillaryMusclePlaceWidget()
    self.addMuscleCenteringButtons()
    self.addOrthogonalSlicerRotationSliderWidget()

  def addShowAllPapillaryMusclesButton(self):
    self.showAllPapillaryMusclesButton = qt.QPushButton("Show all papillary muscles")
    self.showAllPapillaryMusclesButton.clicked.connect(self.showAllPapillaryMuscles)
    self.papillaryMusclesCollapsibleButton.layout().addRow(self.showAllPapillaryMusclesButton)

  def addPapillaryMusclesTreeView(self):
    self.papillaryMusclesTreeView = slicer.qMRMLSubjectHierarchyTreeView()
    self.papillaryMusclesTreeView.setMRMLScene(slicer.mrmlScene)
    self.papillaryMusclesTreeView.setSelectionMode(qt.QTableWidget.SelectRows)
    self.papillaryMusclesTreeView.setSizePolicy(self.getMusclesTreeViewSizePolicy())
    model = self.papillaryMusclesTreeView.model()
    self.papillaryMusclesTreeView.hideColumn(model.idColumn)
    self.papillaryMusclesTreeView.hideColumn(model.transformColumn)
    self.papillaryMusclesTreeView.setVisible(False)  # hide until we define a root node
    self.papillaryMusclesTreeView.connect('currentItemChanged(vtkIdType)', self.papillaryMuscleModelSelectionChanged)
    self.papillaryMusclesCollapsibleButton.layout().addRow(self.papillaryMusclesTreeView)

  def getMusclesTreeViewSizePolicy(self):
    qSize = qt.QSizePolicy()
    qSize.setHorizontalPolicy(qt.QSizePolicy.Expanding)
    qSize.setVerticalPolicy(qt.QSizePolicy.MinimumExpanding)
    qSize.setVerticalStretch(1)
    return qSize

  def addPapillaryMusclePlaceWidget(self):
    self.papillaryMuscleLineMarkupPlaceWidget = slicer.qSlicerMarkupsPlaceWidget()
    self.papillaryMuscleLineMarkupPlaceWidget.setMRMLScene(slicer.mrmlScene)
    self.papillaryMuscleLineMarkupPlaceWidget.buttonsVisible = False
    self.papillaryMuscleLineMarkupPlaceWidget.placeButton().show()
    self.papillaryMuscleLineMarkupPlaceWidget.placeButton().toolButtonStyle = qt.Qt.ToolButtonTextBesideIcon
    self.papillaryMuscleLineMarkupPlaceWidget.deleteButton().show()
    self.papillaryMuscleLineMarkupPlaceWidget.placeMultipleMarkups = \
      slicer.qSlicerMarkupsPlaceWidget.ForcePlaceMultipleMarkups
    self.papillaryMuscleLineMarkupPlaceWidget.connect('activeMarkupsFiducialPlaceModeChanged(bool)',
                                                      self.onPapillaryLineMarkupPlaceModeChanged)
    self.papillaryMusclesCollapsibleButton.layout().addRow("Add/remove muscle point:",
                                                           self.papillaryMuscleLineMarkupPlaceWidget)

  def onAddTimePoint(self):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    selectedSurfaceId = self.papillaryMusclesTreeView.currentItem()
    selectedSurface = shNode.GetItemDataNode(selectedSurfaceId)

    papillaryModel = self.valveModel.findPapillaryModel(selectedSurface)
    if papillaryModel is None:
      logging.error("Selected papillary muscle not found")
      return

    selectedPapillaryMarkupNode = papillaryModel.getPapillaryLineMarkupNode()
    sequenceNode = self.valveModel.valveBrowserNode.GetSequenceNode(selectedPapillaryMarkupNode)
    if sequenceNode is None:
      logging.error("Selected papillary muscle not found in sequence browser")
      return

    self.valveModel.valveBrowser.addCurrentTimePointToSequence(sequenceNode)
    self.updateTimePointButtons()
    self.onPapillaryLineMarkupNodeModified()

  def onRemoveTimePoint(self):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    selectedSurfaceId = self.papillaryMusclesTreeView.currentItem()
    selectedSurface = shNode.GetItemDataNode(selectedSurfaceId)

    papillaryModel = self.valveModel.findPapillaryModel(selectedSurface)
    if papillaryModel is None:
      logging.error("Selected papillary muscle not found")
      return

    selectedPapillaryMarkupNode = papillaryModel.getPapillaryLineMarkupNode()
    sequenceNode = self.valveModel.valveBrowserNode.GetSequenceNode(selectedPapillaryMarkupNode)
    if sequenceNode is None:
      logging.error("Selected papillary muscle not found in sequence browser")
      return

    _, indexValue = self.valveModel.valveBrowser.getDisplayedHeartValveSequenceIndexAndValue()
    sequenceNode.RemoveDataNodeAtValue(indexValue)
    self.updateTimePointButtons()
    self.onPapillaryLineMarkupNodeModified()

  def addMuscleCenteringButtons(self):
    self.showMuscleButtons = []
    hbox = qt.QHBoxLayout()
    for muscleIndex, muscleName in enumerate(self.papillaryMusclePointNames):
      showMuscleButton = qt.QPushButton(muscleName.capitalize())
      showMuscleButton.connect('clicked()', lambda n=muscleIndex: self.onShowMusclePoint(n))
      hbox.addWidget(showMuscleButton)
      self.showMuscleButtons.append(showMuscleButton)
    self.papillaryMusclesCollapsibleButton.layout().addRow("Center views on:", hbox)

  def addOrthogonalSlicerRotationSliderWidget(self):
    self.orthogonalSlicerRotationSliderWidget = ctk.ctkSliderWidget()
    self.orthogonalSlicerRotationSliderWidget.singleStep = 1
    self.orthogonalSlicerRotationSliderWidget.minimum = -360
    self.orthogonalSlicerRotationSliderWidget.maximum = 360
    self.orthogonalSlicerRotationSliderWidget.value = 0
    self.orthogonalSlicerRotationSliderWidget.setToolTip("Rotation angle of the orthogonal views. To change center of "
                                                         "rotation hold down shift and move the mouse over the slice "
                                                         "views.")
    self.orthogonalSlicerRotationSliderWidget.connect('valueChanged(double)',
                                                      self.onOrthogonalSlicerRotationAngleChanged)
    self.papillaryMusclesCollapsibleButton.layout().addRow("Rotation angle:", self.orthogonalSlicerRotationSliderWidget)

  def setupQuantificationSection(self):
    self.quantificationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.quantificationCollapsibleButton.objectName = "Quantification"
    self.quantificationCollapsibleButton.text = "Quantification"
    self.layout.addWidget(self.quantificationCollapsibleButton)

    quantificationFormLayout = qt.QFormLayout(self.quantificationCollapsibleButton)
    self.muscleAngleWidget = qt.QLabel()
    quantificationFormLayout.addRow("Muscle angle:", self.muscleAngleWidget)

    self.muscleLengthWidget = qt.QLabel()
    quantificationFormLayout.addRow("Muscle length:", self.muscleLengthWidget)

    self.chordalLengthWidget = qt.QLabel()
    quantificationFormLayout.addRow("Chordal length:", self.chordalLengthWidget)

  def setupHeartValveSelector(self):
    valveFormLayout = qt.QFormLayout()
    self.layout.addLayout(valveFormLayout)
    self.heartValveSelector = slicer.qMRMLNodeComboBox()
    self.heartValveSelector.nodeTypes = ["vtkMRMLScriptedModuleNode"]
    self.heartValveSelector.setNodeTypeLabel("HeartValve", "vtkMRMLScriptedModuleNode")
    self.heartValveSelector.baseName = "HeartValve"
    self.heartValveSelector.addAttribute("vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve")
    self.heartValveSelector.addEnabled = True
    self.heartValveSelector.removeEnabled = True
    self.heartValveSelector.noneEnabled = False
    self.heartValveSelector.showHidden = True  # scripted module nodes are hidden by default
    self.heartValveSelector.renameEnabled = True
    self.heartValveSelector.setMRMLScene(slicer.mrmlScene)
    self.heartValveSelector.setToolTip("Select heart valve node where annulus will be added")
    self.heartValveSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onHeartValveSelect)
    valveFormLayout.addRow("Heart valve: ", self.heartValveSelector)

  def cleanup(self):
    self.removeGUIObservers()
    self.removeNodeObservers()
    self.parameterNode = None

  def addGUIObservers(self):
    for parameterName in self.nodeSelectorWidgets:
      self.nodeSelectorWidgets[parameterName].connect("currentNodeIDChanged(QString)", self.updateParameterNodeFromGUI)

  def removeGUIObservers(self):
    for parameterName in self.nodeSelectorWidgets:
      self.nodeSelectorWidgets[parameterName].disconnect("currentNodeIDChanged(QString)",
                                                         self.updateParameterNodeFromGUI)

  def removeNodeObservers(self):
    self.setAndObservePapillaryLineMarkupNode(None)

  def addParameterNodeObserver(self):
    if self.parameterNode:
      self.parameterNodeObserver = self.parameterNode.AddObserver(vtk.vtkCommand.ModifiedEvent,
                                                                  self.onParameterNodeModified)

  def removeParameterNodeObserver(self):
    if self.parameterNode and self.parameterNodeObserver:
      self.parameterNode.RemoveObserver(self.parameterNodeObserver)
      self.parameterNodeObserver = None

  def onParameterNodeModified(self, observer=None, eventid=None):
    if not self.parameterNode:
      return
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self):
    for parameterName, widget in self.nodeSelectorWidgets.items():
      oldBlockSignalsState = widget.blockSignals(True)
      widget.setCurrentNodeID(self.parameterNode.GetNodeReferenceID(parameterName))
      widget.blockSignals(oldBlockSignalsState)
    self.updateTimePointButtons()

  def updateParameterNodeFromGUI(self):
    oldModifiedState = self.parameterNode.StartModify()
    for parameterName in self.nodeSelectorWidgets:
      self.parameterNode.SetNodeReferenceID(parameterName, self.nodeSelectorWidgets[parameterName].currentNodeID)
    self.parameterNode.EndModify(oldModifiedState)

  def onHeartValveSelect(self, node):
    logging.debug("Selected heart valve node: {0}".format(node.GetName() if node else "None"))
    self.setHeartValveNode(node)
    self.updateGuiEnabled()

  def setHeartValveNode(self, heartValveNode):
    if self.valveModel and self.valveModel.getHeartValveNode() == heartValveNode:
      return

    self.valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)
    self.removeNodeObservers()

    if self.valveModel:
      valveVolumeNode = self.valveModel.getValveVolumeNode()
      if not valveVolumeNode:
        # select background volume by default as valve volume (to spare a click for the user)
        appLogic = slicer.app.applicationLogic()
        selNode = appLogic.GetSelectionNode()
        if selNode.GetActiveVolumeID():
          valveVolumeNode = slicer.mrmlScene.GetNodeByID(selNode.GetActiveVolumeID())
          self.valveModel.setValveVolumeNode(valveVolumeNode)
      self.valveModel.updatePapillaryModels()
      self.showAllPapillaryMuscles()

    self.onDisplayFourUpView(resetViewOrientations=True, resetFov=True)
    self.updateGuiEnabled()
    HeartValveLib.goToAnalyzedFrame(self.valveModel)

    # Update browser node for selected valve
    browserNode = self.valveModel.valveBrowserNode if self.valveModel else None
    self.valveSequenceBrowserWidget.valveBrowserNode = browserNode

  def updateGuiEnabled(self):
    valveModuleSelected = self.valveModel is not None
    self.papillaryMusclesCollapsibleButton.setEnabled(valveModuleSelected)
    self.quantificationCollapsibleButton.setEnabled(valveModuleSelected)

  def onValveSequenceBrowserNodeModified(self):
    self.updateTimePointButtons()
    self.updatePapillaryMuscleWidgets()
    self.onPapillaryLineMarkupNodeModified()

  def onOrthogonalSlicerRotationAngleChanged(self, newRotationValue):
    if not self.valveModel:
      return
    self.onShowMusclePoint(forcedOrthoRotationUsingSlider=True)

  def onDisplayFourUpView(self, resetFov=False, resetViewOrientations=False):
    # Switch to default cardiac 4-up layout
    HeartValveLib.setupDefaultLayout()

    # Show valve volume as background volume
    if self.valveModel and self.valveModel.getValveVolumeNode():
      valveVolumeNode = self.valveModel.getValveVolumeNode()
      if valveVolumeNode.GetImageData():
        # Show volume in slice viewers
        appLogic = slicer.app.applicationLogic()
        selNode = appLogic.GetSelectionNode()
        # Updating the volume resets the FOV, so only do it when the volume is changed
        if selNode.GetActiveVolumeID() != valveVolumeNode.GetID():
          selNode.SetReferenceActiveVolumeID(valveVolumeNode.GetID())
          appLogic.PropagateVolumeSelection()
      else:
        logging.warning('onResetAnnulusView failed: valve volume does not contain a valid image')

    if resetViewOrientations and self.valveModel:
      HeartValveLib.setupDefaultSliceOrientation(resetFov=resetFov, valveModelOrBrowser=self.valveModel,
                                                 show3DSliceName=self.orthogonalSlice2.GetName())

  def onShowMusclePoint(self, musclePointIndex=None, excludeSliceViewName=None, forcedOrthoRotationUsingSlider=False):
    import numpy as np

    if self.papillaryLineMarkupNode is None or musclePointIndex is None:
      jumpLocation = HeartValveLib.getPlaneIntersectionPoint(self.axialSlice,
                                                             self.orthogonalSlice1,
                                                             self.orthogonalSlice2)
    else:
      jumpLocation = np.array([0, 0, 0])
      self.papillaryLineMarkupNode.GetNthControlPointPositionWorld(musclePointIndex, jumpLocation)

    axialSlice = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeRed')
    orthogonalSlice1 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeYellow')
    orthogonalSlice2 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeGreen')
    if axialSlice.GetLayoutName() == excludeSliceViewName:
      axialSlice = None
    if orthogonalSlice1.GetLayoutName() == excludeSliceViewName:
      orthogonalSlice1 = None
    if orthogonalSlice2.GetLayoutName() == excludeSliceViewName:
      orthogonalSlice2 = None

    orthoRotationDeg = self.orthogonalSlicerRotationSliderWidget.value

    if (self.papillaryLineMarkupNode is None) or (self.papillaryLineMarkupNode.GetNumberOfDefinedControlPoints() == 0):
      if forcedOrthoRotationUsingSlider:
        self.valveModel.setSlicePositionAndOrientation(axialSlice, orthogonalSlice1, orthogonalSlice2,
                                                       jumpLocation, orthoRotationDeg)

    elif (self.papillaryLineMarkupNode.GetNumberOfDefinedControlPoints() == 1) and (not forcedOrthoRotationUsingSlider):
      # There is only a single point, jump only

      for sliceNode in [axialSlice, orthogonalSlice1, orthogonalSlice2]:
        if not sliceNode:
          continue
        sliceNode.JumpSliceByCentering(jumpLocation[0], jumpLocation[1], jumpLocation[2])

    else:
      # Multiple points are defined, keep all them in plane

      if self.papillaryLineMarkupNode.GetNumberOfDefinedControlPoints() < 2:
        axialSliceToRas = None
      else:
        axialSliceToRas = vtk.vtkMatrix4x4()
        axialSliceToRasTransformNode = self.valveModel.getAxialSliceToRasTransformNode()
        axialSliceToRasTransformNode.GetMatrixTransformToParent(axialSliceToRas)

        firstPoint = np.array([0, 0, 0])
        self.papillaryLineMarkupNode.GetNthControlPointPositionWorld(0, firstPoint)
        lastPoint = np.array([0, 0, 0])
        self.papillaryLineMarkupNode.GetNthControlPointPositionWorld(self.papillaryLineMarkupNode.GetNumberOfDefinedControlPoints()-1, lastPoint)

        axialSliceNormal = (lastPoint-firstPoint)
        axialSliceNormal = axialSliceNormal/np.linalg.norm(axialSliceNormal)
        if np.dot(axialSliceNormal, [axialSliceToRas.GetElement(0, 2), axialSliceToRas.GetElement(1, 2), axialSliceToRas.GetElement(2, 2)]) < 0:
          axialSliceNormal = -axialSliceNormal
        axialSliceY = [axialSliceToRas.GetElement(0, 1), axialSliceToRas.GetElement(1, 1), axialSliceToRas.GetElement(2, 1)]
        axialSliceX = np.cross(axialSliceY, axialSliceNormal)
        axialSliceX = axialSliceX/np.linalg.norm(axialSliceX)
        axialSliceY = np.cross(axialSliceNormal, axialSliceX)

        for row in range(3):
          axialSliceToRas.SetElement(row, 0, axialSliceX[row])
          axialSliceToRas.SetElement(row, 1, axialSliceY[row])
          axialSliceToRas.SetElement(row, 2, axialSliceNormal[row])
          axialSliceToRas.SetElement(row, 3, 0)

      if self.papillaryLineMarkupNode.GetNumberOfDefinedControlPoints() == 3 and not forcedOrthoRotationUsingSlider:
        # 3 points defined, rotate view to keep all of them in the ortho1 view
        middlePoint = np.array([0, 0, 0,])
        self.papillaryLineMarkupNode.GetNthControlPointPositionWorld(1, middlePoint)

        axialSliceX_Ras = (middlePoint-firstPoint)
        rasToAxialSlice = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(axialSliceToRas, rasToAxialSlice)
        axialSliceX_axialSlice = rasToAxialSlice.MultiplyPoint([axialSliceX_Ras[0], axialSliceX_Ras[1], axialSliceX_Ras[2], 1])
        import math
        orthoRotationDeg = math.atan2(axialSliceX_axialSlice[1], axialSliceX_axialSlice[0]) / math.pi * 180.0

        # Try to remain close to default view orientations
        if orthoRotationDeg < -90:
          orthoRotationDeg += 180
        elif orthoRotationDeg > 90:
          orthoRotationDeg -= 180

        wasBlocked = self.orthogonalSlicerRotationSliderWidget.blockSignals(True)
        self.orthogonalSlicerRotationSliderWidget.value = orthoRotationDeg
        self.orthogonalSlicerRotationSliderWidget.blockSignals(wasBlocked)

      self.valveModel.setSlicePositionAndOrientation(axialSlice, orthogonalSlice1, orthogonalSlice2,
                                                       jumpLocation, orthoRotationDeg,
                                                       axialSliceToRas = axialSliceToRas)

  def trackFiducialInSliceView(self):
    # Get the view where the user is dragging the markup and don't change that view
    # (it would move the image while the user is marking a point on it and so the screw would drift)
    if self.papillaryLineMarkupNode is None:
      return
    excludeSliceView = self.papillaryLineMarkupNode.GetAttribute('Markups.MovingInSliceView')
    movingMarkupIndex = self.papillaryLineMarkupNode.GetAttribute('Markups.MovingMarkupIndex')
    if excludeSliceView and movingMarkupIndex:
      self.onShowMusclePoint(int(movingMarkupIndex), excludeSliceView)

  def showAllPapillaryMuscles(self):
    self.papillaryMusclesTreeView.setCurrentItem(0)
    # force showing of all leaflets, even if selection did not change
    self.papillaryMuscleModelSelectionChanged()
    HeartValveLib.setupDefaultSliceOrientation(resetFov=True, valveModelOrBrowser=self.valveModel,
                                               show3DSliceName=self.orthogonalSlice2.GetName())

    for papillaryModel in self.valveModel.papillaryModels:
      papillaryModel.getPapillaryLineMarkupNode().SetLocked(True)
      papillaryModel.getPapillaryLineMarkupNode().GetDisplayNode().SetVisibility(True)

  def papillaryMuscleModelSelectionChanged(self):
    if not self.valveModel:
      return

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

    valveNodeItemId = shNode.GetItemByDataNode(self.valveModel.getHeartValveNode())
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    folderItemId = shNode.GetItemChildWithName(valveNodeItemId, 'PapillaryMuscles')
    self.papillaryMusclesTreeView.setVisible(folderItemId != 0)
    self.papillaryMusclesTreeView.setRootItem(folderItemId)

    selectedSurfaceId = self.papillaryMusclesTreeView.currentItem()
    selectedSurface = shNode.GetItemDataNode(selectedSurfaceId)

    selectedPapillaryModel = self.valveModel.findPapillaryModel(selectedSurface)

    for papillaryModel in self.valveModel.papillaryModels:
      selected = (papillaryModel == selectedPapillaryModel)
      papillaryModel.getPapillaryLineMarkupNode().SetLocked(not selected)
      papillaryModel.getPapillaryLineMarkupNode().GetDisplayNode().SetVisibility(selected)

    papillaryLineMarkupNode = None
    if selectedPapillaryModel:
      papillaryLineMarkupNode = selectedPapillaryModel.getPapillaryLineMarkupNode()

    # Set markups placement state so that if the user switches between leaflets
    # and activates markups placement on the toolbar, the correct markups are placed.
    slicer.modules.markups.logic().SetActiveListID(papillaryLineMarkupNode)
    slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(
      slicer.vtkMRMLInteractionNode.ViewTransform)

    self.setAndObservePapillaryLineMarkupNode(papillaryLineMarkupNode)

    if papillaryLineMarkupNode and papillaryLineMarkupNode.GetNumberOfControlPoints() > 0:
      self.onShowMusclePoint(0)

    self.updateTimePointButtons()

  def updateTimePointButtons(self):
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    if shNode is None:
      return
    selectedSurfaceId = self.papillaryMusclesTreeView.currentItem()
    selectedSurface = shNode.GetItemDataNode(selectedSurfaceId)
    selectedPapillaryModel = self.valveModel.findPapillaryModel(selectedSurface) if selectedSurface else None
    papillaryLineMarkupNode = selectedPapillaryModel.getPapillaryLineMarkupNode() if selectedPapillaryModel else None
    defined = self.valveModel.isNodeSpecifiedForCurrentTimePoint(papillaryLineMarkupNode) if papillaryLineMarkupNode else False

    self.addTimePointButton.enabled = not defined and papillaryLineMarkupNode is not None
    self.removeTimePointButton.enabled = defined and papillaryLineMarkupNode is not None

    self.papillaryMuscleLineMarkupPlaceWidget.setPlaceModeEnabled(False)
    self.papillaryMuscleLineMarkupPlaceWidget.setCurrentNode(papillaryLineMarkupNode)
    self.papillaryMuscleLineMarkupPlaceWidget.enabled = defined and papillaryLineMarkupNode is not None

  def setAndObservePapillaryLineMarkupNode(self, papillaryLineMarkupNode):
    logging.debug("Observe papillary line node: {0}".format(papillaryLineMarkupNode.GetName() if papillaryLineMarkupNode else "None"))
    if papillaryLineMarkupNode == self.papillaryLineMarkupNode and len(self.papillaryLineMarkupNodeObservers) > 0:
      # no change and node is already observed
      logging.debug("Already observed")
      return
    # Remove observer to old node
    if self.papillaryLineMarkupNode:
      for observer in self.papillaryLineMarkupNodeObservers:
        self.papillaryLineMarkupNode.RemoveObserver(observer)
      self.papillaryLineMarkupNodeObservers = []
    # Set and observe new node
    self.papillaryLineMarkupNode = papillaryLineMarkupNode
    if self.papillaryLineMarkupNode:
      self.papillaryLineMarkupNodeObservers = [
        self.papillaryLineMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                                                 self.onPapillaryLineMarkupNodeModified),
        self.papillaryLineMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointAddedEvent,
                                                 self.onPapillaryLineMarkupNodeModified),
        self.papillaryLineMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointRemovedEvent,
                                                 self.onPapillaryLineMarkupNodeModified)
        ]
      self.papillaryLineMarkupNode.MaximumNumberOfControlPoints = len(self.papillaryMusclePointNames)

    # Update model
    self.onPapillaryLineMarkupNodeModified()

  def getSelectedPapillaryModel(self):
    selectedModelId = self.papillaryMusclesTreeView.currentItem()
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    selectedLineModel = shNode.GetItemDataNode(selectedModelId)
    selectedPapillaryModel = self.valveModel.findPapillaryModel(selectedLineModel)
    return selectedPapillaryModel

  def updatePapillaryMuscleWidgets(self):

    if not self.papillaryLineMarkupNode:
      for showMuscleButton in self.showMuscleButtons:
        showMuscleButton.enabled = False
      self.papillaryMuscleLineMarkupPlaceWidget.placeButton().text = ""
      self.updateQuantification(None)
      return

    selectedPapillaryModel = self.getSelectedPapillaryModel()
    if not selectedPapillaryModel:
      self.updateQuantification(None)
      return

    numberOfPapillaryMuscles = len(self.papillaryMusclePointNames)
    papillaryLineMarkups = selectedPapillaryModel.getPapillaryLineMarkupNode()
    # Auto-advance or deactivate margin landmark placement
    if self.papillaryMuscleLineMarkupPlaceWidget.placeModeEnabled:
      # Placing landmarks
      if papillaryLineMarkups.GetNumberOfDefinedControlPoints() >= numberOfPapillaryMuscles:
        # All 3 muscle points have been placed
        self.papillaryMuscleLineMarkupPlaceWidget.placeModeEnabled = False

    numberOfPapillaryLineMarkups = papillaryLineMarkups.GetNumberOfDefinedControlPoints()
    if numberOfPapillaryLineMarkups<numberOfPapillaryMuscles:
      nextFiducialPlaceText = "Place " + self.papillaryMusclePointNames[numberOfPapillaryLineMarkups]
    else:
      nextFiducialPlaceText = ""

    for muscleIndex in range(min(papillaryLineMarkups.GetNumberOfControlPoints(), numberOfPapillaryMuscles)):
      papillaryLineMarkups.SetNthControlPointLabel(muscleIndex, self.papillaryMusclePointNames[muscleIndex])
    self.papillaryMuscleLineMarkupPlaceWidget.placeButton().text = nextFiducialPlaceText
    self.papillaryMuscleLineMarkupPlaceWidget.placeButton().enabled = numberOfPapillaryLineMarkups < numberOfPapillaryMuscles

    for muscleIndex, showMuscleButton in enumerate(self.showMuscleButtons):
      showMuscleButton.enabled = numberOfPapillaryLineMarkups > muscleIndex

  def onPapillaryLineMarkupNodeModified(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    self.updatePapillaryMuscleWidgets()
    self.trackFiducialInSliceView()

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    selectedSurfaceId = self.papillaryMusclesTreeView.currentItem()
    selectedSurface = shNode.GetItemDataNode(selectedSurfaceId)
    selectedPapillaryModel = self.valveModel.findPapillaryModel(selectedSurface)
    self.updateQuantification(selectedPapillaryModel)

  def onPapillaryLineMarkupPlaceModeChanged(self, placeActive):
    self.onPapillaryLineMarkupNodeModified()

  def updateQuantification(self, selectedPapillaryModel):
    if selectedPapillaryModel:
      self._quantifyMuscleAngle(selectedPapillaryModel)
      self._quantifyChordLength(selectedPapillaryModel)
      self._quantifyMuscleLength(selectedPapillaryModel)
    else:
      self._displayNoPapillaryMuscleSelected()

  def _quantifyMuscleAngle(self, papillaryModel):
    annulusContourMarkupNode = self.valveModel.getAnnulusContourMarkupNode()
    annulusPlaneNormal = None
    if annulusContourMarkupNode.GetNumberOfDefinedControlPoints() >= 3:
      _, annulusPlaneNormal = self.valveModel.getAnnulusContourPlane()
    if annulusPlaneNormal is not None:
      muscleAngles = {
        '%3.1f deg (tip-chord to annulus-plane)': papillaryModel.getTipChordMuscleAngleDeg(annulusPlaneNormal),
        '%3.1f deg (base-chord to annulus-plane)': papillaryModel.getBaseChordMuscleAngleDeg(annulusPlaneNormal)
      }
      values = [name % val for name,val in muscleAngles.items() if val is not None]
      self.muscleAngleWidget.text = "\n".join(values) if values is not None else "NA"
    else:
      self.muscleAngleWidget.text = "NA (annulus contour is required)"

  def _quantifyChordLength(self, papillaryModel):
    chordLength = papillaryModel.getMuscleChordLength()
    self.chordalLengthWidget.text = ("%3.1f mm" % chordLength) if chordLength is not None else "NA"

  def _quantifyMuscleLength(self, papillaryModel):
    muscleLength = papillaryModel.getMuscleLength()
    self.muscleLengthWidget.text = ("%3.1f mm" % muscleLength) if muscleLength is not None else "NA"

  def _displayNoPapillaryMuscleSelected(self):
    self.muscleAngleWidget.text = "No papillary muscle is selected"
    self.muscleLengthWidget.text = ""
    self.chordalLengthWidget.text = ""


class ValvePapillaryAnalysisLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual computation done by your module. The interface
  should be such that other python code can import this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)


class ValvePapillaryAnalysisTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_ValvePapillaryAnalysis1()

  def test_ValvePapillaryAnalysis1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("No tests are implemented")
