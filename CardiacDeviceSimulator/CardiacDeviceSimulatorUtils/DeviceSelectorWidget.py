import qt
from CardiacDeviceSimulatorUtils.widgethelper import UIHelper
from CardiacDeviceSimulatorUtils.widgethelper import DeviceWidget
from CardiacDeviceSimulatorUtils.devices import CardiacDeviceBase

class DeviceSelectorWidget(DeviceWidget):
  """Shows list of devices (as button row), presets, and sliders to modify presets
  """

  def __init__(self, registeredDeviceClasses, parent=None):
    DeviceWidget.__init__(self, parent)
    self.registeredDeviceClasses = registeredDeviceClasses
    self.observedParameterNodeEvents = [CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT, CardiacDeviceBase.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT]
    self.deviceWidgetFrames = dict()
    self.deviceWidgetFrame = None
    self.inUpdateGUIFromMRML = False
    self.setup()

  def setup(self):
    self.setLayout(qt.QVBoxLayout())

    self.deviceButtonGroup = qt.QButtonGroup()
    self.deviceButtonGroup.setExclusive(True)

    vBoxDeviceButtonGroup = qt.QWidget()
    vBoxDeviceButtonGroup.setLayout(qt.QGridLayout())
    numberOfColumns = 4 if len(self.registeredDeviceClasses) < 5 or len(self.registeredDeviceClasses) > 6 else 3
    for currentWidgetIndex, deviceClass in enumerate(self.registeredDeviceClasses):
      deviceWidgetButton = self.createDeviceButton(deviceClass)
      self.deviceWidgetFrames[deviceClass.ID] = DeviceImplantWidget(deviceClass)
      self.deviceButtonGroup.addButton(deviceWidgetButton)
      vBoxDeviceButtonGroup.layout().addWidget(deviceWidgetButton,
        int(currentWidgetIndex/numberOfColumns), currentWidgetIndex % numberOfColumns)

    self.deviceButtonGroup.buttonClicked.connect(self.onSwitchDevice)
    self.layout().addWidget(vBoxDeviceButtonGroup)

  def createDeviceButton(self, deviceClass):
    deviceWidgetButton = qt.QToolButton()
    deviceWidgetButton.setToolButtonStyle(qt.Qt.ToolButtonTextUnderIcon)
    deviceWidgetButton.setSizePolicy(qt.QSizePolicy.MinimumExpanding, qt.QSizePolicy.Maximum)
    icon = deviceClass.getIcon()
    if icon:
      deviceWidgetButton.setIcon(icon)
      deviceWidgetButton.iconSize = qt.QSize(48, 48)
    deviceWidgetButton.checkable = True
    deviceWidgetButton.name = deviceClass.ID
    deviceWidgetButton.setToolTip(deviceClass.NAME)
    deviceWidgetButton.text = deviceClass.ID
    return deviceWidgetButton

  def setParameterNode(self, parameterNode):
    DeviceWidget.setParameterNode(self, parameterNode)
    if self.parameterNode:
      for deviceClass in self.registeredDeviceClasses:
        self.deviceWidgetFrames[deviceClass.ID].setParameterNode(self.parameterNode)

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

    deviceClassId = self.parameterNode.GetParameter('DeviceClassId') if self.parameterNode else ""
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
    self.removeDeviceWidgetFrame()
    self.deviceWidgetFrame = self.deviceWidgetFrames[button.name]
    self.parameterNode.SetParameter('DeviceClassId', button.name)
    if button is not None:
      # Show sliders of selected device
      self.layout().addWidget(self.deviceWidgetFrames[button.name])
      self.deviceWidgetFrames[button.name].updateGUIFromMRML()
      self.deviceWidgetFrame.show()
    self.parameterNode.InvokeCustomModifiedEvent(CardiacDeviceBase.DEVICE_CLASS_MODIFIED_EVENT)

  def removeDeviceWidgetFrame(self):
    if self.deviceWidgetFrame:
      self.deviceWidgetFrame.hide()
      self.layout().removeWidget(self.deviceWidgetFrame)


class DeviceImplantWidget(qt.QFrame, UIHelper):

  def __init__(self, deviceClass, parent=None):
    super(DeviceImplantWidget, self).__init__(parent)
    self.deviceClass = deviceClass
    self.parameterNode = None
    self.setup()
    self.destroyed.connect(self._onAboutToBeDestroyed)

  def setParameterNode(self, parameterNode):
    self.parameterNode = parameterNode
    self.updateGUIFromMRML()

  def reset(self):
    wasBlocked = self._presetCombo.blockSignals(True)
    self._presetCombo.setCurrentIndex(0)
    self._presetCombo.blockSignals(wasBlocked)

  def setup(self):
    self.setLayout(qt.QFormLayout(self))
    self._addDeviceLabel()
    self._addPresetsCombo()
    self._addSliders()

  def _onAboutToBeDestroyed(self, obj):
    obj.destroyed.disconnect(self._onAboutToBeDestroyed)

  def updateGUIFromMRML(self):
    if not self.parameterNode:
      return
    presetName = self.parameterNode.GetParameter(self.deviceClass.ID + "_preset")
    wasBlocked = self._presetCombo.blockSignals(True)
    if presetName:
      self._presetCombo.setCurrentText(presetName)
    else:
      self._presetCombo.setCurrentIndex(-1)
    self._presetCombo.blockSignals(wasBlocked)

    for paramName, paramAttributes in self.deviceClass.getParameters().items():
      paramValue = self.parameterNode.GetParameter(self.deviceClass.ID+"_"+paramName)
      if not paramValue or not paramAttributes["visible"]:
        continue
      paramValue = float(paramValue)
      sliderWidget = getattr(self, "{}SliderWidget".format(paramName))
      paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
      wasBlocked = sliderWidget.blockSignals(True)
      sliderWidget.value = paramValue / paramScale
      sliderWidget.blockSignals(wasBlocked)

  def _addSliders(self):
    for paramName, paramAttributes in self.deviceClass.getParameters().items():
      if not paramAttributes["visible"]:
        continue
      setattr(self, "{}SliderWidget".format(paramName), self.addSlider(paramAttributes, self.layout(), self.onSliderMoved))

  def _addDeviceLabel(self):
    self._widgetLabel = qt.QLabel(self.deviceClass.NAME)
    self._widgetLabel.setStyleSheet('font: italic "Times New Roman"; font-size: 15px')
    self.layout().addRow("Device Name:", self._widgetLabel)

  def _addPresetsCombo(self):
    self._presets = self.deviceClass.getPresets()
    self._presetCombo = qt.QComboBox()
    self._presetCombo.sizeAdjustPolicy = qt.QComboBox.AdjustToMinimumContentsLength
    if self._presets:
      for model, properties in self._presets.items():
        values = "; ".join([properties[parameter] for parameter, attributes in self.deviceClass.getParameters().items()])
        self._presetCombo.addItem("{} | {{ {} }}".format(model, values))
      self._presetCombo.connect("currentIndexChanged(QString)", self.onPresetSelected)
      self.layout().addRow("Presets:", self._presetCombo)

  def onSliderMoved(self):
    for paramName, paramAttributes in self.deviceClass.getParameters().items():
      if not paramAttributes["visible"]:
        continue
      sliderWidget = getattr(self, "{}SliderWidget".format(paramName))
      paramValue = sliderWidget.value
      paramScale = (0.01 if paramAttributes["unit"] == "%" else 1.0)
      newParamValue = str(paramValue * paramScale)
      self.parameterNode.SetParameter(self.deviceClass.ID+"_"+paramName, newParamValue)
    self._presetCombo.setCurrentIndex(-1)
    self.parameterNode.InvokeCustomModifiedEvent(CardiacDeviceBase.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT)

  def onPresetSelected(self, text):
    presetName = text.split(' | ')[0] if text else ""
    self.parameterNode.SetParameter(self.deviceClass.ID + "_preset", presetName)
    if not presetName:
      # preset is not selected (custom settings)
      return
    params = self._presets[presetName]
    for parameter, attributes in self.deviceClass.getParameters().items():
      self.parameterNode.SetParameter(self.deviceClass.ID + "_" + parameter, str(params[parameter]))
    self.parameterNode.InvokeCustomModifiedEvent(CardiacDeviceBase.DEVICE_PARAMETER_VALUE_MODIFIED_EVENT)
