from slicer.util import VTKObservationMixin 
import ctk, qt, vtk
import slicer

class DeviceSelectorWidget(VTKObservationMixin, qt.QWidget):
  """Shows list of devices (as button row), presets, and sliders to modify presets
  """

  def __init__(self, registeredDeviceClasses, parent=None):
    VTKObservationMixin.__init__(self)
    qt.QWidget.__init__(self, parent)
    self.registeredDeviceClasses = registeredDeviceClasses
    self.parameterNode = None
    self.deviceWidgetFrames = dict()
    self.deviceWidgetFrame = None
    self.inUpdateGUIFromMRML = False
    self.setup()

  def cleanup(self):
    # TODO: check if it is called
    self.removeObservers()

  def createDeviceButton(self, deviceClass):
    deviceWidgetButton = qt.QPushButton()
    icon = deviceClass.getIcon()
    if icon:
      deviceWidgetButton.setIcon(icon)
      deviceWidgetButton.iconSize = qt.QSize(48, 48)
    deviceWidgetButton.checkable = True
    deviceWidgetButton.name = deviceClass.ID
    deviceWidgetButton.setToolTip(deviceClass.NAME)
    return deviceWidgetButton

  def setup(self, showPreview=False):
    self.setLayout(qt.QVBoxLayout())

    self.deviceButtonGroup = qt.QButtonGroup()
    self.deviceButtonGroup.setExclusive(True)

    vBoxDeviceButtonGroup = qt.QWidget()
    vBoxDeviceButtonGroup.setLayout(qt.QHBoxLayout())
    from CardiacDeviceSimulatorUtils.devices import DeviceImplantWidget
    for deviceClass in self.registeredDeviceClasses:
      deviceWidgetButton = self.createDeviceButton(deviceClass)
      self.deviceWidgetFrames[deviceClass.ID] = DeviceImplantWidget(deviceClass)
      self.deviceButtonGroup.addButton(deviceWidgetButton)
      vBoxDeviceButtonGroup.layout().addWidget(deviceWidgetButton)

    self.deviceButtonGroup.connect('buttonClicked(QAbstractButton*)', self.onSwitchDevice)
    self.layout().addWidget(vBoxDeviceButtonGroup)

    #self.deviceWidgetFrame = qt.QFrame()
    #self.layout().addWidget(self.deviceWidgetFrame)

  def setParameterNode(self, parameterNode):
    from CardiacDeviceSimulatorUtils.devices import DeviceImplantWidget
    if self.parameterNode:
      self.removeObserver(self.parameterNode, DeviceImplantWidget.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT, self.updateGUIFromMRML)
    self.parameterNode = parameterNode
    if self.parameterNode:
      self.setParameterNodeDefaults()
      for deviceClass in self.registeredDeviceClasses:
        self.deviceWidgetFrames[deviceClass.ID].setParameterNode(self.parameterNode)
      self.updateGUIFromMRML()
      self.addObserver(self.parameterNode, DeviceImplantWidget.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT, self.updateGUIFromMRML)

  def setParameterNodeDefaults(self):
    pass
    #for deviceClass in self.registeredDeviceClasses:
    #  self.deviceWidgetFrames

  def updateMRMLFromGUI(self):
    if self.inUpdateGUIFromMRML:
      # Updating GUI from MRML, ignore MRML update events until finished
      return
    button = self.deviceButtonGroup.checkedButton()
    if not button:
      return
    self.deviceWidgetFrames[button.name].updateMRMLFromGUI(self.parameterNode)

  def updateGUIFromMRML(self, caller=None, event=None):
    self.inUpdateGUIFromMRML = True
    for button in self.deviceButtonGroup.buttons():
      button.setEnabled(self.parameterNode is not None)

    deviceClassId = self.parameterNode.GetParameter('DeviceClassId')
    previousDeviceClassId = self.deviceButtonGroup.checkedButton().name if self.deviceButtonGroup.checkedButton() else ''
    if previousDeviceClassId != deviceClassId:
      # Model type has changed: update device selector button and parameter frame
      for button in self.deviceButtonGroup.buttons():
        if button.name == deviceClassId or not deviceClassId:  # choose the first model type if nothing is in parameterNode
          wasBlocked = self.deviceButtonGroup.blockSignals(True)
          button.checked = True
          self.deviceButtonGroup.blockSignals(wasBlocked)
          self.onSwitchDevice(button)
          break
    elif deviceClassId:
      # Model type has not changed, just update the sliders
      self.deviceWidgetFrames[deviceClassId].updateGUIFromMRML()
    self.inUpdateGUIFromMRML = False

  def onSwitchDevice(self, button=None):
    if self.deviceWidgetFrame == self.deviceWidgetFrames[button.name]:
      # required frame is already visible
      return
    self.removeDeviceWidgetFrame()
    self.deviceWidgetFrame = self.deviceWidgetFrames[button.name]
    self.parameterNode.SetParameter('DeviceClassId', button.name)
    if button is not None:
      # Show sliders of selected device
      self.layout().addWidget(self.deviceWidgetFrames[button.name])
      self.deviceWidgetFrames[button.name].updateGUIFromMRML()
      self.deviceWidgetFrame.show()
    from CardiacDeviceSimulatorUtils.devices import DeviceImplantWidget
    self.parameterNode.InvokeCustomModifiedEvent(DeviceImplantWidget.DEVICE_CLASS_MODIFIED_EVENT)

  def removeDeviceWidgetFrame(self):
    if self.deviceWidgetFrame:
      self.deviceWidgetFrame.hide()
      self.layout().removeWidget(self.deviceWidgetFrame)


class UIHelper(object):

  @staticmethod
  def addSlider(attributes, layout, valueChangedCallback):
    sliderWidget = ctk.ctkSliderWidget()
    sliderWidget.singleStep = attributes["singleStep"]
    sliderWidget.pageStep = attributes["pageStep"]
    sliderWidget.minimum = attributes["minimum"]
    sliderWidget.maximum = attributes["maximum"]
    sliderWidget.value = attributes["value"]
    sliderWidget.suffix = attributes["unit"]
    sliderWidget.decimals = attributes["decimals"]
    sliderWidget.setToolTip(attributes["info"])
    sliderWidget.tracking = True
    sliderWidget.connect('valueChanged(double)', lambda val: valueChangedCallback())
    layout.addRow(attributes["name"], sliderWidget)
    return sliderWidget

  @staticmethod
  def addCommonSection(name, layout, buttonGroup=None, collapsed=True):
    collapsibleButton = ctk.ctkCollapsibleButton()
    collapsibleButton.text = name
    collapsibleButton.collapsed = collapsed
    layout.addWidget(collapsibleButton)
    formLayout = qt.QFormLayout(collapsibleButton)
    if buttonGroup:
      buttonGroup.addButton(collapsibleButton)
    return [formLayout, collapsibleButton]