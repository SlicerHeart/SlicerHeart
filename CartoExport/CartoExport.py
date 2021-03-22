import vtk, qt, slicer
from slicer.ScriptedLoadableModule import *
import logging

#
# CartoExport
#

class CartoExport(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "CartoExport"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = []
    self.parent.contributors = ["Christian Herz (CHOP), Andras Lasso (PerkLab, Queen's University)", "Matt Jolley (CHOP/UPenn)"]
    self.parent.helpText = """ 
    This module provides support for saving a VTK node into the legacy VTK format including patient name and MRN.
    """
    self.parent.helpText += self.getDefaultModuleDocumentationLink()
    self.parent.acknowledgementText = """ """ # replace with organization, grant and thanks.

#
# CartoExportWidget
#

class CartoExportWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    self.logic = CartoExportLogic()

    frame = qt.QFrame()
    lay = qt.QFormLayout()
    frame.setLayout(lay)
    self.layout.addWidget(frame)

    self.vtkModelSelector = slicer.qMRMLNodeComboBox()
    self.vtkModelSelector.nodeTypes = ["vtkMRMLModelNode"]
    self.vtkModelSelector.noneEnabled = True
    self.vtkModelSelector.renameEnabled = True
    self.vtkModelSelector.setMRMLScene(slicer.mrmlScene)
    self.vtkModelSelector.setToolTip("VTK model node that needs to be converted")

    self.firstNameLineEdit = qt.QLineEdit(self.logic.FIRST)
    self.lastNameLineEdit = qt.QLineEdit(self.logic.LAST)
    self.mrnLineEdit = qt.QLineEdit(self.logic.ID)
    self.mrnLineEdit.setValidator(qt.QRegExpValidator(qt.QRegExp("[0-9]*"), self.mrnLineEdit))
    self.exportButton = qt.QPushButton("Export ...")
    self.exportButton.enabled = False

    lay.addRow("VTK Model Node:", self.vtkModelSelector)
    lay.addRow("First name:", self.firstNameLineEdit)
    lay.addRow("Last name:", self.lastNameLineEdit)
    lay.addRow("MRN:", self.mrnLineEdit)
    lay.addWidget(self.exportButton)


    self.vtkModelSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onCurrentModelNodeChanged)
    self.exportButton.clicked.connect(self.onSaveClicked)
    self.firstNameLineEdit.editingFinished.connect(lambda: setattr(self.logic, "FIRST", self.firstNameLineEdit.text))
    self.lastNameLineEdit.editingFinished.connect(lambda: setattr(self.logic, "LAST", self.lastNameLineEdit.text))
    self.mrnLineEdit.editingFinished.connect(lambda: setattr(self.logic, "ID", self.mrnLineEdit.text))

    self.layout.addStretch(1)

    self.onCurrentModelNodeChanged(self.vtkModelSelector.currentNode())

  def cleanup(self):
    pass

  def onCurrentModelNodeChanged(self, node=None):
    self.exportButton.enabled = node is not None
    self.logic.modelNode = node

  def onSaveClicked(self):
    filename = qt.QFileDialog.getSaveFileName(None, "Save VTK model as ...", "{}.vtk".format(self.logic.getFileName()))
    if filename:
      try:
        self.logic.save(filename)
        slicer.util.messageBox("Saved legacy VTK file with header to {}".format(filename))
      except Exception as exc:
        logging.error("Saving into VTK legacy format failed with error message: {}".format(exc))


#
# CartoExportLogic
#

class CartoExportLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  FIRST = "First"
  LAST = "Last"
  ID = "ID"

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)
    self.modelNode = None

  def getPatientDataRow(self):
    return "PatientData {}".format(self.getFileName(False))

  def getFileName(self, replaceWhiteSpaces=True):
    text = "{} {} {}".format(self.FIRST, self.LAST, self.ID)
    if replaceWhiteSpaces:
      text = text.replace(" ", "_")
    return text

  def save(self, filepath):
    node = self.modelNode

    if node.GetPolyData() is not None:
      writer = vtk.vtkPolyDataWriter()
      writer.SetInputConnection(node.GetPolyDataConnection())
    else:
      writer = vtk.vtkUnstructuredGridWriter()
      writer.SetInputConnection(node.GetMeshConnection())

    writer.SetFileName(filepath)
    writer.SetFileType(vtk.VTK_ASCII)
    writer.SetHeader(self.getPatientDataRow())
    writer.Write()


class CartoExportTest(ScriptedLoadableModuleTest):
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
    self.test_CartoExport1()

  def test_CartoExport1(self):
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

    self.delayDisplay("Starting the test")

    # TODO: implement test here

    self.delayDisplay('Test passed!')
