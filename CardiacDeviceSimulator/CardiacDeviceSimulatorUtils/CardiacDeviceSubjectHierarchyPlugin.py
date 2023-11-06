import qt, ctk, slicer
from AbstractScriptedSubjectHierarchyPlugin import *


class CardiacDeviceSubjectHierarchyPlugin(AbstractScriptedSubjectHierarchyPlugin):

  module_names = ["CardiacDeviceSimulator", "AsdVsdDeviceSimulator", "TCAVValveSimulator"]

  # Necessary static member to be able to set python source to scripted subject hierarchy plugin
  filePath = __file__

  def __init__(self, scriptedPlugin):
    scriptedPlugin.name = 'CardiacDeviceSimulator'
    AbstractScriptedSubjectHierarchyPlugin.__init__(self, scriptedPlugin)

  def canAddNodeToSubjectHierarchy(self, node, parentItemID = None):
    if node is not None and node.IsA("vtkMRMLScriptedModuleNode"):
      if node.GetAttribute("ModuleName") in self.module_names:
        return 0.9
    return 0.0

  def canOwnSubjectHierarchyItem(self, itemID):
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    shNode = pluginHandlerSingleton.subjectHierarchyNode()
    associatedNode = shNode.GetItemDataNode(itemID)
    return self.canAddNodeToSubjectHierarchy(associatedNode)

  def roleForPlugin(self):
    return "CardiacDeviceSimulator"

  def icon(self, itemID):
    import os
    iconPath = None
    pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
    shNode = pluginHandlerSingleton.subjectHierarchyNode()
    associatedNode = shNode.GetItemDataNode(itemID)
    if associatedNode is not None and associatedNode.IsA("vtkMRMLScriptedModuleNode"):
      if associatedNode.GetAttribute("ModuleName") in self.module_names:
        iconPath = os.path.join(os.path.dirname(__file__), '../Resources/Icons/CardiacDeviceSimulator.png')
    if iconPath and os.path.exists(iconPath):
      return qt.QIcon(iconPath)
    # Item unknown by plugin
    return qt.QIcon()

  def tooltip(self, itemID):
    return "Cardiac Device"

