import vtk, qt, ctk, slicer
import logging
from AbstractScriptedSubjectHierarchyPlugin import *

class HeartValvesSubjectHierarchyPlugin(AbstractScriptedSubjectHierarchyPlugin):
  """ Scripted subject hierarchy plugin for the Segment Statistics module.

      This is also an example for scripted plugins, so includes all possible methods.
      The methods that are not needed (i.e. the default implementation in
      qSlicerSubjectHierarchyAbstractPlugin is satisfactory) can simply be
      omitted in plugins created based on this one.
  """

  # Necessary static member to be able to set python source to scripted subject hierarchy plugin
  filePath = __file__

  def __init__(self, scriptedPlugin):
    scriptedPlugin.name = 'HeartValves'
    AbstractScriptedSubjectHierarchyPlugin.__init__(self, scriptedPlugin)

    self.HeartValvesAction = qt.QAction("Calculate statistics...", scriptedPlugin)
    self.HeartValvesAction.connect("triggered()", self.onCalculateStatistics)

  def canAddNodeToSubjectHierarchy(self, node, parentItemID = None):
    if node is not None and node.IsA("vtkMRMLScriptedModuleNode"):
      if node.GetAttribute("ModuleName") == "HeartValve":
        return 0.9
      if node.GetAttribute("ModuleName") == "HeartValveMeasurement":
        return 0.9
      if node.GetAttribute("ModuleName") == "CardiacDeviceAnalysis":
        return 0.9
      if node.GetAttribute("ModuleName") == "ValveFEMExport":
        return 0.9
    return 0.0

  def canOwnSubjectHierarchyItem(self, itemID):
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    shNode = pluginHandlerSingleton.subjectHierarchyNode()
    associatedNode = shNode.GetItemDataNode(itemID)
    return self.canAddNodeToSubjectHierarchy(associatedNode)

  def roleForPlugin(self):
    return "HeartValve"

  def helpText(self):
    # return ("<p style=\" margin-top:4px; margin-bottom:1px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">"
      # "<span style=\" font-family:'sans-serif'; font-size:9pt; font-weight:600; color:#000000;\">"
      # "HeartValves module subject hierarchy help text"
      # "</span>"
      # "</p>"
      # "<p style=\" margin-top:0px; margin-bottom:11px; margin-left:26px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">"
      # "<span style=\" font-family:'sans-serif'; font-size:9pt; color:#000000;\">"
      # "This is how you can add help text to the subject hierarchy module help box via a python scripted plugin."
      # "</span>"
      # "</p>\n")
    return ""

  def icon(self, itemID):
    import os
    iconPath = None
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    shNode = pluginHandlerSingleton.subjectHierarchyNode()
    associatedNode = shNode.GetItemDataNode(itemID)
    if associatedNode is not None and associatedNode.IsA("vtkMRMLScriptedModuleNode"):
      if associatedNode.GetAttribute("ModuleName")=="HeartValve":
        iconPath = os.path.join(os.path.dirname(__file__), '../Resources/Icons/ValveAnnulusAnalysis.png')
      elif associatedNode.GetAttribute("ModuleName")=="HeartValveMeasurement":
        iconPath = os.path.join(os.path.dirname(__file__), '../../ValveQuantification/Resources/Icons/ValveQuantification.png')
      elif associatedNode.GetAttribute("ModuleName")=="CardiacDeviceAnalysis":
        iconPath = os.path.join(os.path.dirname(__file__), '../../CardiacModelGenerator/Resources/Icons/CardiacModelGenerator.png')
      elif associatedNode.GetAttribute("ModuleName")=="ValveFEMExport":
        iconPath = os.path.join(os.path.dirname(__file__), '../Resources/Icons/ValveAnnulusAnalysis.png')
    if iconPath and os.path.exists(iconPath):
      return qt.QIcon(iconPath)
    # Item unknown by plugin
    return qt.QIcon()

  def visibilityIcon(self, visible):
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    return pluginHandlerSingleton.pluginByName('Default').visibilityIcon(visible)

  def editProperties(self, itemID):
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    pluginHandlerSingleton.pluginByName('Default').editProperties(itemID)

  def itemContextMenuActions(self):
    return [self.HeartValvesAction]

  def onCalculateStatistics(self):
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    currentItemID = pluginHandlerSingleton.currentItem()
    if currentItemID == slicer.vtkMRMLSubjectHierarchyNode.GetInvalidItemID():
      logging.error("Invalid current item")

    shNode = pluginHandlerSingleton.subjectHierarchyNode()
    segmentationNode = shNode.GetItemDataNode(currentItemID)

    # Select segmentation node in segment statistics
    pluginHandlerSingleton.pluginByName('Default').switchToModule('HeartValves')
    statisticsWidget = slicer.modules.HeartValves.widgetRepresentation().self()
    statisticsWidget.segmentationSelector.setCurrentNode(segmentationNode)

    # Get master volume from segmentation
    masterVolume = segmentationNode.GetNodeReference(slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole())
    if masterVolume is not None:
      statisticsWidget.grayscaleSelector.setCurrentNode(masterVolume)

  def sceneContextMenuActions(self):
    return []

  def showContextMenuActionsForItem(self, itemID):
    # Scene
    if itemID == slicer.vtkMRMLSubjectHierarchyNode.GetInvalidItemID():
      # No scene context menu actions in this plugin
      return

    # Volume but not LabelMap
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    if pluginHandlerSingleton.pluginByName('HeartValves').canOwnSubjectHierarchyItem(itemID):
      # Get current item
      currentItemID = pluginHandlerSingleton.currentItem()
      if currentItemID == slicer.vtkMRMLSubjectHierarchyNode.GetInvalidItemID():
        logging.error("Invalid current item")
        return
      self.HeartValvesAction.visible = True

  def tooltip(self, itemID):
    return "Heart valve"

  def setDisplayVisibility(self, itemID, visible):
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    pluginHandlerSingleton.pluginByName('Default').setDisplayVisibility(itemID, visible)

  def getDisplayVisibility(self, itemID):
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    return pluginHandlerSingleton.pluginByName('Default').getDisplayVisibility(itemID)
