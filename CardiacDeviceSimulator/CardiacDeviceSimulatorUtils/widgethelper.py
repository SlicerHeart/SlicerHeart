import ctk, qt
from slicer.util import VTKObservationMixin


class DeviceWidget(VTKObservationMixin, qt.QWidget):
  """Shows list of devices (as button row), presets, and sliders to modify presets
  """

  def __init__(self, registeredDeviceClasses, parent=None):
    VTKObservationMixin.__init__(self)
    qt.QWidget.__init__(self, parent)
    self.parameterNode = None
    self.observedParameterNodeEvents = []
    self.logic = None

  def setup(self):
    """Add widgets to layout
    """
    raise NotImplementedError

  def cleanup(self):
    """Called before widget destruction
    """
    self.removeObservers()

  def enter(self):
    """Runs whenever the module is opened
    """
    pass

  def exit(self):
    """Runs whenever the module is exited
    """
    pass

  def setLogic(self, logic):
    if self.logic == logic:
      return
    self.logic = logic
    self.updateGUIFromMRML()

  def setParameterNode(self, parameterNode):
    """Set and observe parameter node
    """
    if self.parameterNode:
      for eventId in self.observedParameterNodeEvents:
        self.removeObserver(self.parameterNode, eventId, self.updateGUIFromMRML)
    self.parameterNode = parameterNode
    if self.parameterNode:
      self.updateGUIFromMRML()
      for eventId in self.observedParameterNodeEvents:
        self.addObserver(self.parameterNode, eventId, self.updateGUIFromMRML)
    self.setEnabled(self.parameterNode is not None)

  def updateGUIFromMRML(self):
    """Update all GUI after node changed"""
    pass


class UIHelper(object):

  @staticmethod
  def createHLayout(elements):
    widget = qt.QWidget()
    rowLayout = qt.QHBoxLayout()
    widget.setLayout(rowLayout)
    for element in elements:
      rowLayout.addWidget(element)
    return widget

  @staticmethod
  def addSlider(attributes, layout, valueChangedCallback):
    sliderWidget = UIHelper.createSliderWidget(attributes, valueChangedCallback)
    layout.addRow(attributes["name"], sliderWidget)
    return sliderWidget

  @staticmethod
  def createSliderWidget(attributes, valueChangedCallback):
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
    return sliderWidget

  @staticmethod
  def addCommonSection(name, layout, buttonGroup=None, collapsed=True, widget=None):
    collapsibleButton = ctk.ctkCollapsibleButton()
    collapsibleButton.text = name
    collapsibleButton.collapsed = collapsed
    layout.addWidget(collapsibleButton)
    formLayout = qt.QFormLayout(collapsibleButton)
    if buttonGroup:
      buttonGroup.addButton(collapsibleButton)
    if widget:
      formLayout.addRow(widget)
    return [formLayout, collapsibleButton]
