import ctk, qt

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
    sliderWidget.tracking = False
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