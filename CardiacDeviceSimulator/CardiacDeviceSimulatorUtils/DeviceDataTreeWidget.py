import qt
import slicer
from CardiacDeviceSimulatorUtils.widgethelper import DeviceWidget
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase


class DeviceDataTreeWidget(DeviceWidget):
  """Shows list of devices (as button row), presets, and sliders to modify presets
  """

  def __init__(self, parent=None):
    DeviceWidget.__init__(self, parent)
    self.observedParameterNodeEvents = [CardiacDeviceBase.QUANTIFICATION_RESULT_UPDATED_EVENT]
    self.setup()

  def setup(self):
    self.setLayout(qt.QVBoxLayout())

    self.measurementTree = slicer.qMRMLSubjectHierarchyTreeView()
    self.measurementTree.setMRMLScene(slicer.mrmlScene)
    qSize = qt.QSizePolicy()
    qSize.setHorizontalPolicy(qt.QSizePolicy.Expanding)
    qSize.setVerticalPolicy(qt.QSizePolicy.MinimumExpanding)
    qSize.setVerticalStretch(1)
    self.measurementTree.setSizePolicy(qSize)
    # self.measurementTree.editMenuActionVisible = True
    self.measurementTree.setColumnHidden(self.measurementTree.model().idColumn, True)
    self.measurementTree.setColumnHidden(self.measurementTree.model().transformColumn, True)
    self.layout().addWidget(self.measurementTree)

  def updateGUIFromMRML(self, caller=None, event=None):
    # Columns can be only hidden when they exist
    self.measurementTree.setColumnHidden(self.measurementTree.model().idColumn, True)
    self.measurementTree.setColumnHidden(self.measurementTree.model().transformColumn, True)

  def setParameterNode(self, parameterNode):
    DeviceWidget.setParameterNode(self, parameterNode)
    if parameterNode:
      shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
      parameterNodeShItem = shNode.GetItemByDataNode(parameterNode)
      self.measurementTree.setRootItem(parameterNodeShItem)
      self.measurementTree.setEnabled(True)
    else:
      self.measurementTree.setEnabled(False)
