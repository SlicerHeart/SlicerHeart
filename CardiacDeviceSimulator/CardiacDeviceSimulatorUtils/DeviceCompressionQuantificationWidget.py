import qt, vtk
from CardiacDeviceSimulatorUtils.widgethelper import UIHelper
from CardiacDeviceSimulatorUtils.widgethelper import DeviceWidget
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase


class DeviceCompressionQuantificationWidget(DeviceWidget):
  """Shows list of devices (as button row), presets, and sliders to modify presets
  """

  def __init__(self, parent=None):
    DeviceWidget.__init__(self, parent)
    self.observedParameterNodeEvents = [vtk.vtkCommand.ModifiedEvent]
    self.setup()

  def setup(self):
    self.setLayout(qt.QFormLayout())

    self.colorTableRangeMmSliderWidget = UIHelper.addSlider({
      "name": "Color table range:", "info": "Maximum compression represented in the color table", "value": 10,
      "unit": "mm", "minimum": 0, "maximum": 20, "singleStep": 1, "pageStep": 1, "decimals": 0}, self.layout(),
      self.onColorTableRangeChanged)
    self.computeMetricsButton = qt.QPushButton("Compute metrics")
    self.layout().addRow(self.computeMetricsButton)
    self.computeMetricsButton.connect('clicked(bool)', self.onComputeMetrics)

  def setParameterNode(self, parameterNode):
    DeviceWidget.setParameterNode(self, parameterNode)

  def updateGUIFromMRML(self, caller=None, event=None):
    wasBlocked = self.colorTableRangeMmSliderWidget.blockSignals(True)
    self.colorTableRangeMmSliderWidget.value = float(self.parameterNode.GetParameter("ColorTableRangeMm")) if self.parameterNode else 0.0
    self.colorTableRangeMmSliderWidget.blockSignals(wasBlocked)

  def onComputeMetrics(self):
    if not self.logic.parameterNode:
      return

    qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
    tableNode = self.logic.computeMetrics()
    qt.QApplication.restoreOverrideCursor()

    # Show table
    #slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView)
    #slicer.app.applicationLogic().GetSelectionNode().SetReferenceActiveTableID(tableNode.GetID())
    #slicer.app.applicationLogic().PropagateTableSelection()

    # Show deformed surface model
    resultModel = self.logic.parameterNode.GetNodeReference("WholeDeformedSurfaceModel")
    resultModel.GetDisplayNode().SetVisibility(True)

    self.logic.parameterNode.InvokeCustomModifiedEvent(CardiacDeviceBase.QUANTIFICATION_RESULT_UPDATED_EVENT)

  def onColorTableRangeChanged(self):
    if self.logic.parameterNode:
      self.logic.parameterNode.SetParameter("ColorTableRangeMm", str(self.colorTableRangeMmSliderWidget.value))
