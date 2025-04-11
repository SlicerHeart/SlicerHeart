import vtk, qt, ctk, slicer
import logging
import numpy as np
from slicer.ScriptedLoadableModule import *


class LeafletAnalysis(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Leaflet Analysis"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["ValveAnnulusAnalysis"]
    self.parent.contributors = ["(Andras Lasso (PerkLab), Christian Herz (CHOP), Matt Jolley (UPenn)"]
    self.parent.helpText = """ LeafletAnalysis is used for generating leaflet surface as well as coaptation surfaces
    between leaflets of the selected valve model.
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Andras Lasso, PerkLab.
    """


class LeafletAnalysisWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  @staticmethod
  def getNumberOfControlPoints(markupsNode):
    if not markupsNode:
      return 0
    return markupsNode.GetNumberOfDefinedControlPoints()

  def __init__(self, parent):
    ScriptedLoadableModuleWidget.__init__(self, parent)

    try:
      global HeartValveLib
      import HeartValveLib
      import HeartValveLib.SmoothCurve
    except ImportError as exc:
      logging.error("{}: {}".format(self.moduleName, exc.message))

    self.valveModel = None

    self.leafletSurfaceBoundaryMarkupNode = None
    self.leafletSurfaceBoundaryMarkupNodeObserver = None
    self.coaptationBaseLineMarkupNode = None
    self.coaptationBaseLineMarkupNodeObserver = None
    self.coaptationMarginLineMarkupNode = None
    self.coaptationMarginLineMarkupNodeObserver = None

    self.inverseVolumeRendering = False

  def cleanup(self):
    self.setAndObserveLeafletSurfaceBoundaryMarkupNode()

  def enter(self):
    pass

  def exit(self):
    self.fadeCompleteLeafletCheckbox.setChecked(False)

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    valveFormLayout = qt.QFormLayout()
    self.layout.addLayout(valveFormLayout)

    self.heartValveSelector = slicer.qMRMLNodeComboBox()
    self.heartValveSelector.nodeTypes = ["vtkMRMLScriptedModuleNode"]
    self.heartValveSelector.setNodeTypeLabel("HeartValve", "vtkMRMLScriptedModuleNode")
    self.heartValveSelector.baseName = "HeartValve"
    self.heartValveSelector.addAttribute( "vtkMRMLScriptedModuleNode", "ModuleName", "HeartValve" )
    self.heartValveSelector.addEnabled = True
    self.heartValveSelector.removeEnabled = True
    self.heartValveSelector.noneEnabled = True
    self.heartValveSelector.showHidden = True # scripted module nodes are hidden by default
    self.heartValveSelector.renameEnabled = True
    self.heartValveSelector.setMRMLScene(slicer.mrmlScene)
    self.heartValveSelector.setToolTip("Select heart valve node where annulus will be added")
    valveFormLayout.addRow("Heart valve: ", self.heartValveSelector)
    self.heartValveSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onHeartValveSelect)

    self.addSurfaceExtractionSection()
    self.addCoaptationSection()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.leafletSurfaceExtractionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.coaptationCollapsibleButton)

    self.leafletSurfaceExtractionCollapsibleButton.connect('toggled(bool)', lambda toggle: self.onWorkflowStepChanged(self.leafletSurfaceExtractionCollapsibleButton, toggle))
    self.coaptationCollapsibleButton.connect('toggled(bool)', lambda toggle: self.onWorkflowStepChanged(self.coaptationCollapsibleButton, toggle))

    self.layout.addStretch(1)

    self.onHeartValveSelect(self.heartValveSelector.currentNode())

    self.leafletSurfaceExtractionCollapsibleButton.collapsed = False

  def addSurfaceExtractionSection(self):

    self.leafletSurfaceExtractionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.leafletSurfaceExtractionCollapsibleButton.objectName = "LeafletSurfaceExtraction"
    self.leafletSurfaceExtractionCollapsibleButton.text = "Leaflet surface extraction"
    self.layout.addWidget(self.leafletSurfaceExtractionCollapsibleButton)
    surfaceExtractionFormLayout = qt.QFormLayout(self.leafletSurfaceExtractionCollapsibleButton)

    self.leafletSurfaceBoundaryMarkupAutoAllButton = qt.QPushButton("Auto-extract all leaflet surfaces")
    self.leafletSurfaceBoundaryMarkupAutoAllButton.clicked.connect(self.leafletSurfaceBoundaryMarkupAutoAll)
    surfaceExtractionFormLayout.addRow(self.leafletSurfaceBoundaryMarkupAutoAllButton)

    widget = qt.QWidget()
    widget.setLayout(qt.QHBoxLayout())
    widget.layout().addWidget(qt.QLabel("Number of boundary points:"))

    self.numBoundaryPointsSpinBox = qt.QSpinBox()
    self.numBoundaryPointsSpinBox.setMinimum(30)
    self.numBoundaryPointsSpinBox.setMaximum(100)

    widget.layout().addWidget(self.numBoundaryPointsSpinBox)

    surfaceExtractionFormLayout.addRow(widget)

    self.showAllLeafletsButton = qt.QPushButton("Show all leaflets")
    self.showAllLeafletsButton.clicked.connect(self.showAllLeaflets)
    surfaceExtractionFormLayout.addRow(self.showAllLeafletsButton)

    self.leafletSegmentSelector = slicer.qMRMLSegmentsTableView()
    self.leafletSegmentSelector.selectionMode = qt.QAbstractItemView.SingleSelection
    self.leafletSegmentSelector.headerVisible = False
    self.leafletSegmentSelector.visibilityColumnVisible = False
    self.leafletSegmentSelector.opacityColumnVisible = False
    self.leafletSegmentSelector.setHideSegments(
      [HeartValveLib.VALVE_MASK_SEGMENT_ID])  # mask is not a leaflet, exclude from the segment list
    self.leafletSegmentSelector.connect('selectionChanged(QItemSelection, QItemSelection)',
                                        self.leafletSurfaceSelectionChanged)
    surfaceExtractionFormLayout.addRow(self.leafletSegmentSelector)

    self.leafletSurfaceBoundaryMarkupPlaceWidget = slicer.qSlicerMarkupsPlaceWidget()
    self.leafletSurfaceBoundaryMarkupPlaceWidget.setMRMLScene(slicer.mrmlScene)
    self.leafletSurfaceBoundaryMarkupPlaceWidget.buttonsVisible = False
    self.leafletSurfaceBoundaryMarkupPlaceWidget.placeButton().show()
    self.leafletSurfaceBoundaryMarkupPlaceWidget.deleteButton().show()
    self.leafletSurfaceBoundaryMarkupPlaceWidget.placeMultipleMarkups = slicer.qSlicerMarkupsPlaceWidget.ForcePlaceMultipleMarkups

    self.leafletSurfaceBoundaryFlipButton = qt.QPushButton("Flip")
    self.leafletSurfaceBoundaryFlipButton.setToolTip(
      "Flip between using larger/smaller area region of the segment as leaflet surface")
    self.leafletSurfaceBoundaryFlipButton.setEnabled(False)
    self.leafletSurfaceBoundaryFlipButton.clicked.connect(self.leafletSurfaceBoundaryFlip)

    self.leafletSurfaceBoundaryMarkupAutoButton = qt.QPushButton("Auto")
    self.leafletSurfaceBoundaryMarkupAutoButton.clicked.connect(self.leafletSurfaceBoundaryMarkupAuto)

    hbox = qt.QHBoxLayout()
    hbox.addWidget(self.leafletSurfaceBoundaryMarkupPlaceWidget)
    hbox.addWidget(self.leafletSurfaceBoundaryFlipButton)
    hbox.addWidget(self.leafletSurfaceBoundaryMarkupAutoButton)
    surfaceExtractionFormLayout.addRow("Leaflet boundary points:", hbox)

    self.fadeCompleteLeafletCheckbox = qt.QCheckBox()
    self.fadeCompleteLeafletCheckbox.setToolTip(
      "Fade complete leaflet in 3D view to highlight extracted leaflet surface")
    self.fadeCompleteLeafletCheckbox.toggled.connect(self.onFadeCompleteLeaflet)
    surfaceExtractionFormLayout.addRow('Show leaflet surface only:', self.fadeCompleteLeafletCheckbox)

  def addCoaptationSection(self):
    self.coaptationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.coaptationCollapsibleButton.objectName = "Coaptation"
    self.coaptationCollapsibleButton.text = "Coaptation"
    self.layout.addWidget(self.coaptationCollapsibleButton)
    self.coaptationFormLayout = qt.QFormLayout(self.coaptationCollapsibleButton)

    self.addCoaptationSurfaceButton = qt.QPushButton("Add coaptation surface")
    self.addCoaptationSurfaceButton.clicked.connect(self.addCoaptationSurface)
    self.coaptationFormLayout.addRow(self.addCoaptationSurfaceButton)
    self.removeCoaptationSurfaceButton = qt.QPushButton("Remove coaptation surface")
    self.removeCoaptationSurfaceButton.clicked.connect(self.removeCoaptationSurface)
    self.coaptationFormLayout.addRow(self.removeCoaptationSurfaceButton)

    hbox = qt.QHBoxLayout()
    hbox.addWidget(self.addCoaptationSurfaceButton)
    hbox.addWidget(self.removeCoaptationSurfaceButton)
    self.coaptationFormLayout.addRow(hbox)

    self.showAllCoaptationSurfacesButton = qt.QPushButton("Show all coaptation surfaces")
    self.showAllCoaptationSurfacesButton.clicked.connect(self.showAllCoaptations)
    self.coaptationFormLayout.addRow(self.showAllCoaptationSurfacesButton)
    self.addCoaptationTreeView()
    self.addBaseLineMarkupPlaceWidget()
    self.addCoaptationPointSelectorSlider()
    self.addMarginLineMarkupPlaceWidget()

  def addCoaptationTreeView(self):
    self.coaptationTreeView = slicer.qMRMLSubjectHierarchyTreeView()
    self.coaptationTreeView.setMRMLScene(slicer.mrmlScene)
    qSize = qt.QSizePolicy()
    qSize.setHorizontalPolicy(qt.QSizePolicy.Expanding)
    qSize.setVerticalPolicy(qt.QSizePolicy.MinimumExpanding)
    qSize.setVerticalStretch(1)
    self.coaptationTreeView.setSizePolicy(qSize)
    self.coaptationTreeView.setColumnHidden(self.coaptationTreeView.model().idColumn, True)
    self.coaptationTreeView.setColumnHidden(self.coaptationTreeView.model().transformColumn, True)
    self.coaptationTreeView.setVisible(False)  # hide until we define a root node
    self.coaptationFormLayout.addRow(self.coaptationTreeView)
    self.coaptationTreeView.connect('currentItemChanged(vtkIdType)', self.coaptationSurfaceSelectionChanged)

  def addBaseLineMarkupPlaceWidget(self):
    self.coaptationBaseLineMarkupPlaceWidget = self.getNewMarkupPlaceWidget()
    self.coaptationFormLayout.addRow("Coaptation base line:", self.coaptationBaseLineMarkupPlaceWidget)

  def addMarginLineMarkupPlaceWidget(self):
    self.coaptationMarginLineMarkupPlaceWidget = \
      self.getNewMarkupPlaceWidget(self.coaptationMarginLineMarkupPlaceModeChanged)
    self.coaptationFormLayout.addRow("Coaptation margin line:", self.coaptationMarginLineMarkupPlaceWidget)

  def getNewMarkupPlaceWidget(self, placeModeChangedCallback=None):
    placeWidget = slicer.qSlicerMarkupsPlaceWidget()
    placeWidget.setMRMLScene(slicer.mrmlScene)
    placeWidget.buttonsVisible = False
    placeWidget.placeButton().show()
    placeWidget.deleteButton().show()
    placeWidget.placeMultipleMarkups = slicer.qSlicerMarkupsPlaceWidget.ForcePlaceMultipleMarkups
    if placeModeChangedCallback:
      placeWidget.connect('activeMarkupsFiducialPlaceModeChanged(bool)', placeModeChangedCallback)
    return placeWidget

  def addCoaptationPointSelectorSlider(self):
    self.coaptationPointSelectorSlider = qt.QSlider(qt.Qt.Horizontal)
    self.coaptationPointSelectorSlider.minimum = 0
    self.coaptationPointSelectorSlider.maximum = 0
    self.coaptationPointSelectorSlider.value = 0
    self.coaptationPointSelectorSlider.setToolTip("Select coaptation point along the coaptation line")
    self.coaptationPointSelectorSlider.connect('sliderMoved(int)', self.coaptationPointSelected)
    self.coaptationFormLayout.addRow("", self.coaptationPointSelectorSlider)

  def setGuiEnabled(self, enable):
    self.leafletSurfaceExtractionCollapsibleButton.setEnabled(enable)
    self.coaptationCollapsibleButton.setEnabled(enable)

  def onWorkflowStepChanged(self, widget, toggle):
    if self.valveModel is None:
      return

    if widget == self.leafletSurfaceExtractionCollapsibleButton:
      # exit from surface editing mode
      self.leafletSegmentSelector.setSelectedSegmentIDs([])
      if toggle:
        self.valveModel.updateLeafletModelsFromSegmentation()
        self.valveModel.annulusContourCurve.curveModelNode.GetDisplayNode().SetVisibility(False)
        self.valveModel.getValveRoiModelNode().GetDisplayNode().SetVisibility(False)
      else:
        self.valveModel.annulusContourCurve.curveModelNode.GetDisplayNode().SetVisibility(True)
        self.valveModel.getValveRoiModelNode().GetDisplayNode().SetVisibility(True)
        # show all segments
        segmentationNode = self.valveModel.getLeafletSegmentationNode()
        segmentationDisplayNode = segmentationNode.GetDisplayNode()
        for leafletModel in self.valveModel.leafletModels:
          segmentationDisplayNode.SetSegmentVisibility(leafletModel.segmentId, True)
          leafletModel.surfaceModelNode.GetDisplayNode().SetVisibility(False)
    elif widget == self.coaptationCollapsibleButton:
      # exit from surface editing mode
      self.coaptationTreeView.setCurrentItem(0)
      self.coaptationSurfaceSelectionChanged()
      if toggle:
        self.valveModel.updateCoaptationModels()
        self.valveModel.getValveRoiModelNode().GetDisplayNode().SetVisibility(False)
      else:
        self.valveModel.getValveRoiModelNode().GetDisplayNode().SetVisibility(True)

  def onHeartValveSelect(self, heartValveNode):
    logging.debug("Selected heart valve node: {0}".format(heartValveNode.GetName() if heartValveNode else "None"))

    if self.valveModel and self.valveModel.getHeartValveNode() == heartValveNode:
      return

    self.valveModel = HeartValveLib.HeartValves.getValveModel(heartValveNode)

    self.setGuiEnabled(heartValveNode is not None)

    segmentationNode = self.valveModel.getLeafletSegmentationNode() if self.valveModel else None
    self.leafletSegmentSelector.setSegmentationNode(segmentationNode)

    if segmentationNode:
      segmentationDisplayNode = segmentationNode.GetDisplayNode()
      self.fadeCompleteLeafletCheckbox.setChecked(segmentationDisplayNode.GetOpacity3D()<0.5)
    HeartValveLib.goToAnalyzedFrame(self.valveModel)

    if self.valveModel:
      self.valveModel.updateLeafletModelsFromSegmentation()

  def getFirstVisibleSegmentId(self):
    segmentationNode = self.valveModel.getLeafletSegmentationNode()
    segmentationDisplayNode = segmentationNode.GetDisplayNode()
    segmentIDs = vtk.vtkStringArray()
    segmentationNode.GetSegmentation().GetSegmentIDs(segmentIDs)
    for index in range(segmentIDs.GetNumberOfValues()):
      segmentID = segmentIDs.GetValue(index)
      if segmentationDisplayNode.GetSegmentVisibility(segmentID):
        return segmentID
    return None

  def setAndObserveLeafletSurfaceBoundaryMarkupNode(self, leafletSurfaceBoundaryMarkupNode=None):
    logging.debug("Observe leaflet surface boundary markup node: {0}".format(leafletSurfaceBoundaryMarkupNode.GetName() if leafletSurfaceBoundaryMarkupNode else "None"))
    if leafletSurfaceBoundaryMarkupNode is self.leafletSurfaceBoundaryMarkupNode and self.leafletSurfaceBoundaryMarkupNodeObserver:
      # no change and node is already observed
      logging.debug("Already observed")
      return
    # Remove observer to old node
    if self.leafletSurfaceBoundaryMarkupNode and self.leafletSurfaceBoundaryMarkupNodeObserver:
      self.leafletSurfaceBoundaryMarkupNode.RemoveObserver(self.leafletSurfaceBoundaryMarkupNodeObserver)
      self.leafletSurfaceBoundaryMarkupNodeObserver = None
    # Set and observe new node
    self.leafletSurfaceBoundaryMarkupNode = leafletSurfaceBoundaryMarkupNode
    if self.leafletSurfaceBoundaryMarkupNode:
      self.leafletSurfaceBoundaryMarkupNodeObserver = \
        self.leafletSurfaceBoundaryMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                                                          self.onLeafletSurfaceBoundaryMarkupNodeModified)

    self.onLeafletSurfaceBoundaryMarkupNodeModified()

  def onLeafletSurfaceBoundaryMarkupNodeModified(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    if not self.leafletSurfaceBoundaryMarkupNode:
      return
    leafletModel = self.valveModel.findLeafletModel(self.leafletSurfaceBoundaryMarkupNode.GetAttribute('SegmentID'))
    leafletModel.updateSurface()

  def leafletSurfaceSelectionChanged(self):
    if not self.valveModel:
      return

    selectedSegmentIds = self.leafletSegmentSelector.selectedSegmentIDs()
    selectedSegmentId = selectedSegmentIds[0] if selectedSegmentIds else None

    selectedSurfaceBoundaryMarkupNode = None
    if selectedSegmentId:
      selectedLeafletModel = self.getSelectedLeafletModel(selectedSegmentId)
      selectedSurfaceBoundaryMarkupNode = selectedLeafletModel.getSurfaceBoundaryMarkupNode()
      if self.getNumberOfControlPoints(selectedLeafletModel.getSurfaceBoundaryMarkupNode()) == 0:
        self.fadeCompleteLeafletCheckbox.setChecked(False)

    segmentationNode = self.valveModel.getLeafletSegmentationNode()
    segmentationDisplayNode = segmentationNode.GetDisplayNode()
    for leafletModel in self.valveModel.leafletModels:
      selected = (leafletModel.segmentId == selectedSegmentId)
      segmentationDisplayNode.SetSegmentVisibility(leafletModel.segmentId, selected or (selectedSegmentId is None))
      leafletModel.surfaceModelNode.GetDisplayNode().SetVisibility(selected or (selectedSegmentId is None))
      leafletModel.getSurfaceBoundaryMarkupNode().GetDisplayNode().SetVisibility(selected)
      leafletModel.getSurfaceBoundaryMarkupNode().SetLocked(not selected)
      leafletModel.getSurfaceBoundaryModelNode().GetDisplayNode().SetVisibility(selected)

    # Set markups placement state so that if the user switches between leaflets
    # and activates markups placement on the toolbar, the correct markups are placed.
    slicer.modules.markups.logic().SetActiveListID(selectedSurfaceBoundaryMarkupNode)
    slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(
      slicer.vtkMRMLInteractionNode.ViewTransform)

    self.leafletSurfaceBoundaryMarkupPlaceWidget.setPlaceModeEnabled(False)
    self.leafletSurfaceBoundaryMarkupPlaceWidget.setCurrentNode(selectedSurfaceBoundaryMarkupNode)
    self.setAndObserveLeafletSurfaceBoundaryMarkupNode(selectedSurfaceBoundaryMarkupNode)
    self.leafletSurfaceBoundaryFlipButton.setEnabled(selectedSurfaceBoundaryMarkupNode is not None)
    self.leafletSurfaceBoundaryMarkupAutoButton.setEnabled(selectedSurfaceBoundaryMarkupNode is not None)

  def getSelectedLeafletModel(self, selectedSegmentId):
    selectedLeafletModel = self.valveModel.findLeafletModel(selectedSegmentId)
    if not selectedLeafletModel:
      self.valveModel.updateLeafletModelsFromSegmentation()
      selectedLeafletModel = self.valveModel.findLeafletModel(selectedSegmentId)
    return selectedLeafletModel

  def leafletSurfaceBoundaryFlip(self):
    selectedSegmentIds = self.leafletSegmentSelector.selectedSegmentIDs()
    if not selectedSegmentIds:
      return
    selectedSegmentId = selectedSegmentIds[0]
    leafletModel = self.valveModel.findLeafletModel(selectedSegmentId)
    if not leafletModel:
      return
    leafletModel.setSelectLargestRegion(not leafletModel.getSelectLargestRegion())

  def leafletSurfaceBoundaryMarkupAutoAll(self):
    [planePosition, planeNormal] = self.valveModel.getAnnulusContourPlane()

    for leafletModel in self.valveModel.leafletModels:
      leafletModel.autoDetectSurfaceBoundary(planePosition, planeNormal, self.numBoundaryPointsSpinBox.value)
      leafletModel.extractSurfaceByBoundary()
      leafletModel.updateSurface()

    self.showAllLeaflets()

    self.fadeCompleteLeafletCheckbox.setChecked(True)

  def leafletSurfaceBoundaryMarkupAuto(self):
    selectedSegmentIds = self.leafletSegmentSelector.selectedSegmentIDs()
    if not selectedSegmentIds:
      return
    selectedSegmentId = selectedSegmentIds[0]
    leafletModel = self.valveModel.findLeafletModel(selectedSegmentId)
    if not leafletModel:
      return

    [planePosition, planeNormal] = self.valveModel.getAnnulusContourPlane()
    leafletModel.autoDetectSurfaceBoundary(planePosition, planeNormal, self.numBoundaryPointsSpinBox.value)

    # Only show surface
    self.fadeCompleteLeafletCheckbox.setChecked(True)

  def onFadeCompleteLeaflet(self, toggled):
    segmentationNode = self.valveModel.getLeafletSegmentationNode()
    segmentationDisplayNode = segmentationNode.GetDisplayNode()
    opacity = 0.1 if toggled else 1.0
    segmentationDisplayNode.SetOpacity3D(opacity)

  def showAllLeaflets(self):
    self.leafletSegmentSelector.clearSelection()
    # force showing of all leaflets, even if selection did not change
    self.leafletSurfaceSelectionChanged()

  def addCoaptationSurface(self):
    coaptationModel = self.valveModel.addCoaptationModel()
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    self.coaptationTreeView.setCurrentItem(shNode.GetItemByDataNode(coaptationModel.surfaceModelNode))

  def showAllCoaptations(self):
    self.coaptationTreeView.setCurrentItem(0)
    # force showing of all leaflets, even if selection did not change
    self.coaptationSurfaceSelectionChanged()

  def coaptationSurfaceSelectionChanged(self):
    if not self.valveModel:
      return

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

    valveNodeItemId = shNode.GetItemByDataNode(self.valveModel.getHeartValveNode())
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    folderItemId = shNode.GetItemChildWithName(valveNodeItemId, 'Coaptation')
    self.coaptationTreeView.setVisible(folderItemId != 0)
    self.coaptationTreeView.setRootItem(folderItemId)

    selectedSurfaceId = self.coaptationTreeView.currentItem()
    selectedSurface = shNode.GetItemDataNode(selectedSurfaceId)

    selectedCoaptationModel = self.valveModel.findCoaptationModel(selectedSurface)

    for coaptationModel in self.valveModel.coaptationModels:
      selected = (coaptationModel == selectedCoaptationModel)

      coaptationModel.surfaceModelNode.GetDisplayNode().SetVisibility(selected or (selectedCoaptationModel is None))

      coaptationModel.getBaseLineModelNode().GetDisplayNode().SetVisibility(selected or (selectedCoaptationModel is None))
      coaptationModel.getBaseLineMarkupNode().GetDisplayNode().SetVisibility(selected)
      coaptationModel.getBaseLineMarkupNode().SetLocked(not selected)
      coaptationModel.getBaseLineMarkupNode().GetDisplayNode().SetVisibility(selected)

      coaptationModel.getMarginLineModelNode().GetDisplayNode().SetVisibility(selected or (selectedCoaptationModel is None))
      coaptationModel.getMarginLineMarkupNode().GetDisplayNode().SetVisibility(selected)
      coaptationModel.getMarginLineMarkupNode().SetLocked(not selected)
      coaptationModel.getMarginLineMarkupNode().GetDisplayNode().SetVisibility(selected)

    baseLineMarkupNode = None
    marginLineMarkupNode = None
    if selectedCoaptationModel:
      baseLineMarkupNode = selectedCoaptationModel.getBaseLineMarkupNode()
      marginLineMarkupNode = selectedCoaptationModel.getMarginLineMarkupNode()

    # Set markups placement state so that if the user switches between leaflets
    # and activates markups placement on the toolbar, the correct markups are placed.
    slicer.modules.markups.logic().SetActiveListID(baseLineMarkupNode)
    slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(
      slicer.vtkMRMLInteractionNode.ViewTransform)

    self.coaptationBaseLineMarkupPlaceWidget.setPlaceModeEnabled(False)
    self.coaptationBaseLineMarkupPlaceWidget.setCurrentNode(baseLineMarkupNode)
    self.setAndObserveCoaptationBaseLineMarkupNode(baseLineMarkupNode)

    self.coaptationMarginLineMarkupPlaceWidget.setPlaceModeEnabled(False)
    self.coaptationMarginLineMarkupPlaceWidget.setCurrentNode(marginLineMarkupNode)
    self.setAndObserveCoaptationMarginLineMarkupNode(marginLineMarkupNode)

  def setAndObserveCoaptationBaseLineMarkupNode(self, coaptationBaseLineMarkupNode):
    logging.debug("Observe coaptation base node: {0}".format(coaptationBaseLineMarkupNode.GetName() if coaptationBaseLineMarkupNode else "None"))
    if coaptationBaseLineMarkupNode == self.coaptationBaseLineMarkupNode and self.coaptationBaseLineMarkupNodeObserver:
      # no change and node is already observed
      logging.debug("Already observed")
      return
    # Remove observer to old node
    if self.coaptationBaseLineMarkupNode and self.coaptationBaseLineMarkupNodeObserver:
      self.coaptationBaseLineMarkupNode.RemoveObserver(self.coaptationBaseLineMarkupNodeObserver)
      self.coaptationBaseLineMarkupNodeObserver = None
    # Set and observe new node
    self.coaptationBaseLineMarkupNode = coaptationBaseLineMarkupNode
    if self.coaptationBaseLineMarkupNode:
      self.coaptationBaseLineMarkupNodeObserver = \
        self.coaptationBaseLineMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                                                      self.onCoaptationLineMarkupNodeModified)

    # Update model
    self.onCoaptationLineMarkupNodeModified()

  def setAndObserveCoaptationMarginLineMarkupNode(self, coaptationMarginLineMarkupNode):
    logging.debug("Observe coaptation margin node: {0}".format(coaptationMarginLineMarkupNode.GetName() if coaptationMarginLineMarkupNode else "None"))
    if coaptationMarginLineMarkupNode == self.coaptationMarginLineMarkupNode and self.coaptationMarginLineMarkupNodeObserver:
      # no change and node is already observed
      logging.debug("Already observed")
      return
    # Remove observer to old node
    if self.coaptationMarginLineMarkupNode and self.coaptationMarginLineMarkupNodeObserver:
      self.coaptationMarginLineMarkupNode.RemoveObserver(self.coaptationMarginLineMarkupNodeObserver)
      self.coaptationMarginLineMarkupNodeObserver = None
    # Set and observe new node
    self.coaptationMarginLineMarkupNode = coaptationMarginLineMarkupNode
    if self.coaptationMarginLineMarkupNode:
      self.coaptationMarginLineMarkupNodeObserver = \
        self.coaptationMarginLineMarkupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                                                        self.onCoaptationLineMarkupNodeModified)

    # Update model
    self.onCoaptationLineMarkupNodeModified()

  def getSelectedCoaptationModel(self):
    selectedSurfaceId = self.coaptationTreeView.currentItem()
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    selectedSurface = shNode.GetItemDataNode(selectedSurfaceId)
    return self.valveModel.findCoaptationModel(selectedSurface)

  def onCoaptationLineMarkupNodeModified(self, unusedArg1=None, unusedArg2=None, unusedArg3=None):
    if not self.coaptationBaseLineMarkupNode and not self.coaptationMarginLineMarkupNode:
      return
    selectedCoaptationModel = self.getSelectedCoaptationModel()
    if not selectedCoaptationModel:
      return

    if not self.coaptationBaseLineMarkupPlaceWidget.placeModeEnabled and \
      not self.coaptationMarginLineMarkupPlaceWidget.placeModeEnabled:
      selectedCoaptationModel.updateSurface()
      selectedCoaptationModel.updateSurfaceModelName(self.valveModel)

    self.updateCoaptationPointSliderRange()
    self.deleteOrphanMarginLinePoints()
    self.autoAdvanceOrDeactivateMarginLinePlacement()

  def updateCoaptationPointSliderRange(self):
    slider = self.coaptationPointSelectorSlider
    numBaseLineControlPoints = self.getNumberOfControlPoints(self.getSelectedCoaptationModel().getBaseLineMarkupNode())

    if slider.maximum < numBaseLineControlPoints - 1: # new base line point added
      wasBlocked = slider.blockSignals(True)
      self.updateCoaptationPointSliderMaximumAndValue(slider.maximum,
                                                      numBaseLineControlPoints - 1)
      slider.blockSignals(wasBlocked)

    if slider.maximum > numBaseLineControlPoints: # base line point removed
      self.updateCoaptationPointSliderMaximumAndValue(numBaseLineControlPoints - 1,
                                                      slider.value)

  def updateCoaptationPointSliderMaximumAndValue(self, value, maximum):
    self.coaptationPointSelectorSlider.maximum = maximum
    self.coaptationPointSelectorSlider.value = value

  def deleteOrphanMarginLinePoints(self):
    selectedCoaptationModel = self.getSelectedCoaptationModel()
    marginLineMarkups = selectedCoaptationModel.getMarginLineMarkupNode()
    baseLineMarkups = selectedCoaptationModel.getBaseLineMarkupNode()
    while self.getNumberOfControlPoints(marginLineMarkups) > self.getNumberOfControlPoints(baseLineMarkups):
      marginLineMarkups.RemoveNthControlPoint(self.getNumberOfControlPoints(marginLineMarkups) - 1)

  def autoAdvanceOrDeactivateMarginLinePlacement(self):
    selectedCoaptationModel = self.getSelectedCoaptationModel()
    marginLineMarkups = selectedCoaptationModel.getMarginLineMarkupNode()
    baseLineMarkups = selectedCoaptationModel.getBaseLineMarkupNode()
    if self.coaptationMarginLineMarkupPlaceWidget.placeModeEnabled:
      # Placing margin landmarks
      if self.getNumberOfControlPoints(marginLineMarkups) < self.getNumberOfControlPoints(baseLineMarkups):
        # Not all margin points have been placed yet - auto-advance to the next one
        self.coaptationPointSelectorSlider.value = self.getNumberOfControlPoints(marginLineMarkups)
        self.coaptationPointSelected(self.coaptationPointSelectorSlider.value)
      if self.getNumberOfControlPoints(marginLineMarkups) == self.getNumberOfControlPoints(baseLineMarkups):
        # All base points have a matching margin point, we are done
        self.coaptationMarginLineMarkupPlaceWidget.placeModeEnabled = False

  def coaptationBaseLineMarkupPlaceModeChanged(self, placeActive):
    self.onCoaptationLineMarkupNodeModified()

  def coaptationMarginLineMarkupPlaceModeChanged(self, placeActive):
    self.onCoaptationLineMarkupNodeModified()

  def coaptationPointSelected(self, pointIndex):
    selectedCoaptationModel = self.getSelectedCoaptationModel()
    if not selectedCoaptationModel:
      return

    axialSlice = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeRed')
    orthogonalSlice1 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeYellow')
    orthogonalSlice2 = slicer.mrmlScene.GetNodeByID('vtkMRMLSliceNodeGreen')

    baseLineMarkupNode = selectedCoaptationModel.getBaseLineMarkupNode()
    if self.getNumberOfControlPoints(baseLineMarkupNode) == 0:
      return

    selectedBaseLinePointPosition = [0,0,0,1]
    baseLineMarkupNode.GetNthFiducialWorldCoordinates(pointIndex, selectedBaseLinePointPosition)

    baseLineCurvePointId = selectedCoaptationModel.baseLine.getCurvePointIndexFromControlPointIndex(pointIndex)
    directionVector_Probe = np.append(selectedCoaptationModel.baseLine.getDirectionVector(baseLineCurvePointId),0)
    probeToRasMatrix = vtk.vtkMatrix4x4()
    self.valveModel.getProbeToRasTransformNode().GetMatrixTransformToParent(probeToRasMatrix)
    directionVector_Ras = probeToRasMatrix.MultiplyPoint(directionVector_Probe)

    import math
    orthoRotationDeg = math.atan2(directionVector_Probe[0], directionVector_Probe[1])/math.pi*180.0

    self.valveModel.setSlicePositionAndOrientation(axialSlice, orthogonalSlice1, orthogonalSlice2, selectedBaseLinePointPosition, orthoRotationDeg)

  def removeCoaptationSurface(self):
    selectedCoaptationModel = self.getSelectedCoaptationModel()
    if not selectedCoaptationModel:
      return
    self.valveModel.removeCoaptationModel(self.valveModel.coaptationModels.index(selectedCoaptationModel))

  def onReload(self):
    logging.debug("Reloading LeafletAnalysis")

    packageName='HeartValveLib'
    submoduleNames=['LeafletModel', 'SmoothCurve', 'ValveRoi', 'ValveModel', 'HeartValves']
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


class LeafletAnalysisLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual computation done by your module.  The interface should be such that
  other python code can import this class and make use of the functionality without requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)

  def createParameterNode(self):
    node = ScriptedLoadableModuleLogic.createParameterNode(self)
    node.SetName(slicer.mrmlScene.GetUniqueNameByString(self.moduleName))
    return node


class LeafletAnalysisTest(ScriptedLoadableModuleTest):
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
    self.test_LeafletAnalysis1()

  def test_LeafletAnalysis1(self):
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