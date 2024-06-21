from pathlib import Path

import qt
import slicer

import HeartValveLib
from HeartValveLib.util import Signal


import pandas as pd


# TODO: collect validation functions and create valve completion class
getValveVolumeSequenceIndex = lambda valveModel: valveModel.getValveVolumeSequenceIndex()
hasAnnulusContourDefined = \
  lambda valveModel: valveModel.annulusContourCurveNode.GetNumberOfControlPoints() > 0 if valveModel.annulusContourCurveNode is not None else False
hasLeafletSegmentation = lambda valveModel: valveModel.leafletSegmentationNode is not None


class ValveSeriesInfo(qt.QAbstractTableModel):

  GREEN_COLOR = qt.QColor(17, 84, 18)
  RED_COLOR = qt.QColor(120, 14, 14)
  HEADER_NAMES = ["Volume Index", "Annulus Contour", " Leaflet Segmentation"]
  ATTR_GETTER_FUNCTIONS = {
    HEADER_NAMES[0]: getValveVolumeSequenceIndex,
    HEADER_NAMES[1]: hasAnnulusContourDefined,
    HEADER_NAMES[2]: hasLeafletSegmentation
  }

  @property
  def valveBrowser(self):
    return HeartValveLib.HeartValves.getValveBrowser(self.valveBrowserNode)

  @property
  def valveBrowserNode(self):
    return self._valveBrowserNode

  @valveBrowserNode.setter
  def valveBrowserNode(self, valveBrowserNode: slicer.vtkMRMLSequenceBrowserNode):
    self._valveBrowserNode = valveBrowserNode
    self.update()

  def update(self):
    valveBrowser = self.valveBrowser
    if valveBrowser is None:
      self._df = None
    else:
      data = self.analyzeSequence()
      self._df = pd.DataFrame(data)
    self.layoutChanged()

  def __init__(self, parent=None):
    super().__init__(parent)
    self._valveBrowserNode = None
    self._df = None

  def rowCount(self):
    return len(self._df) if self._df is not None else 0

  def columnCount(self, parent=qt.QModelIndex()):
    return len(self._df.columns) if self._df is not None else 0

  def data(self, index, role=qt.Qt.DisplayRole):
    if not index.isValid():
      return None

    if self._df is not None:
      if role == qt.Qt.DisplayRole:
        val = self._df.iat[index.row(), index.column()].item()
        if type(val) is bool:
          return ""
        return str(val)
      elif role == qt.Qt.DecorationRole:
        val = self._df.iat[index.row(), index.column()].item()
        if not type(val) is bool:
          return None

        icon = slicer.app.style().standardIcon(qt.QStyle.SP_DialogApplyButton if val else qt.QStyle.SP_DialogCancelButton)
        icon.addPixmap(icon.pixmap(qt.QSize(16, 16)), qt.QIcon.Normal)
        icon.addPixmap(icon.pixmap(qt.QSize(16, 16)), qt.QIcon.Selected)
        return icon
    if role == qt.Qt.TextAlignmentRole:
      return qt.Qt.AlignCenter
    return None

  def headerData(self, section, orientation, role=qt.Qt.DisplayRole):
    if role == qt.Qt.DisplayRole and orientation == qt.Qt.Horizontal:
      return self._df.columns[section] if self._df is not None else ""
    return None

  def getRowIdxForValveSequenceIndex(self, volumeSequenceIndex):
    try:
      return self._df[self.HEADER_NAMES[0]].tolist().index(volumeSequenceIndex)
    except (ValueError, TypeError):
      return -1

  def analyzeSequence(self):
    valveBrowser = self.valveBrowser
    data = {attr: [] for attr in self.HEADER_NAMES}
    heartValveSequenceNode = valveBrowser.heartValveSequenceNode
    origIndex = valveBrowser.volumeSequenceBrowserNode.GetSelectedItemNumber()
    for idx in range(heartValveSequenceNode.GetNumberOfDataNodes()):
      valveBrowser.valveBrowserNode.SetSelectedItemNumber(idx)

      for colName in self.HEADER_NAMES:
        data[colName].append(self.ATTR_GETTER_FUNCTIONS[colName](valveBrowser.valveModel))

    valveBrowser.volumeSequenceBrowserNode.SetSelectedItemNumber(origIndex)
    return data


class ValveSequenceInfoWidget:

  _tableModelClass = ValveSeriesInfo  # can be replaced with custom model

  @classmethod
  def setInfoModelClass(cls, infoClass: ValveSeriesInfo):
    cls._tableModelClass = infoClass

  @classmethod
  def getTableModelClass(cls):
    return cls._tableModelClass

  @property
  def valveBrowserNode(self):
    return self._valveBrowserNode

  @valveBrowserNode.setter
  def valveBrowserNode(self, valveBrowserNode: slicer.vtkMRMLSequenceBrowserNode):
    selectionModel = self.ui.valveSeriesInfoView.selectionModel()
    if selectionModel:
      selectionModel.selectionChanged.disconnect(self._onSelectionChanged)

    self._seriesInfoModel = self.getTableModelClass()()
    self._seriesInfoModel.valveBrowserNode = valveBrowserNode

    self.ui.valveSeriesInfoView.setModel(self._seriesInfoModel)
    selectionModel = self.ui.valveSeriesInfoView.selectionModel()
    if selectionModel:
      selectionModel.selectionChanged.connect(self._onSelectionChanged)
    self.ui.updateButton.enabled = valveBrowserNode is not None

  @property
  def visible(self):
    return self.ui.visible

  @visible.setter
  def visible(self, visibility):
    self.ui.visible = visibility

  def __init__(self, parent: qt.QLayout = None):
    uiFile = str(Path(__file__).parent.parent / "Resources/UI/ValveSequenceInfoWidget.ui")
    if not Path(uiFile).exists():
      raise FileNotFoundError(f"UI file ({uiFile}) could not be found for {self.__class__.__name__}.")
    self.ui = slicer.util.loadUI(uiFile)
    self.ui.setMRMLScene(slicer.mrmlScene)

    self._valveBrowserNode = None

    self.selectionChanged = Signal()

    self._seriesInfoModel = None

    self.setup(parent)

  def update(self):
    if self._seriesInfoModel is not None:
      self._seriesInfoModel.update()

  def _onSelectionChanged(self):
    self.selectionChanged.emit()

  def destroy(self):
    self._disconnectSignals()
    self.ui.setParent(None)
    self.ui.deleteLater()

  def setup(self, parent):
    if parent is not None:
      parent.addWidget(self.ui)

    palette = self.ui.valveSeriesInfoView.palette
    palette.setBrush(qt.QPalette.Highlight, qt.QBrush(qt.QColor(125,125,125,180)))
    # palette.setBrush(qt.QPalette.HighlightedText, qt.QBrush(qt.Qt.black))
    self.ui.valveSeriesInfoView.setPalette(palette)

    self._connectSignals()

  def _connectSignals(self):
    self.ui.updateButton.clicked.connect(self.update)

  def _disconnectSignals(self):
    self.ui.updateButton.clicked.disconnect(self.update)
    self.selectionChanged.disconnectAll()
    selectionModel = self.ui.valveSeriesInfoView.selectionModel()
    if selectionModel:
      selectionModel.selectionChanged.connect(self._onSelectionChanged)

  def show(self):
    self.ui.show()

  def hide(self):
    self.ui.hide()

  def getSelectedVolumeSequenceIndex(self):
    selectionModel = self.ui.valveSeriesInfoView.selectionModel()
    model = selectionModel.model
    if selectionModel.selectedRows():
      modelIndex = selectionModel.selectedRows()[0]
      return int(model.data(modelIndex))
    else:
      return -1

  def selectOrClearVolumeSequenceIndex(self, volumeSequenceIndex):
    selectionModel = self.ui.valveSeriesInfoView.selectionModel()
    if selectionModel is None:
      return
    model = selectionModel.model
    if model is None:
      return
    rowIdx = model.getRowIdxForValveSequenceIndex(volumeSequenceIndex)
    if rowIdx != -1:
      self.ui.valveSeriesInfoView.selectRow(rowIdx)
    else:
      selectionModel.clearSelection()