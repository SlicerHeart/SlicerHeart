import os
import unittest
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging

#
# Philips4dUsDicomPatcher
#

class Philips4dUsDicomPatcher(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Philips 4D US DICOM patcher"
    self.parent.categories = ["Heart"]
    self.parent.dependencies = ["DICOM"]
    self.parent.contributors = ["Andras Lasso (PerkLab), Steve Pieper (Isomics)"]
    self.parent.helpText = """Fix invalid 4D US DICOM files so that they can be imported into Slicer."""
    self.parent.acknowledgementText = """Funded by CHOP"""

#
# Philips4dUsDicomPatcherWidget
#

class Philips4dUsDicomPatcherWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Instantiate and connect widgets ...

    #
    # Parameters Area
    #
    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    # Layout within the dummy collapsible button
    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    self.inputDirSelector = ctk.ctkPathLineEdit()
    self.inputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
    self.inputDirSelector.settingKey = 'Philips4dUsDicomPatcherInputDir'
    parametersFormLayout.addRow("Input DICOM directory:", self.inputDirSelector)

    self.outputDirSelector = ctk.ctkPathLineEdit()
    self.outputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
    self.outputDirSelector.settingKey = 'Philips4dUsDicomPatcherOutputDir'
    parametersFormLayout.addRow("Output DICOM directory:", self.outputDirSelector)
    
    self.enableNrrdOutputCheckBox = qt.QCheckBox()
    self.enableNrrdOutputCheckBox.checked = 0
    self.enableNrrdOutputCheckBox.setToolTip("If checked, 4D US DICOM files will be also saved as NRRD files")
    parametersFormLayout.addRow("Export to NRRD files", self.enableNrrdOutputCheckBox) 
    
    #
    # Patch Button
    #
    self.patchButton = qt.QPushButton("Patch")
    self.patchButton.toolTip = "Fix and optionally anonymize DICOM files"
    parametersFormLayout.addRow(self.patchButton)

    # connections
    self.patchButton.connect('clicked(bool)', self.onPatchButton)
    
    self.statusLabel = qt.QPlainTextEdit()
    self.statusLabel.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
    parametersFormLayout.addRow(self.statusLabel)

    # Add vertical spacer
    self.layout.addStretch(1)
    
    self.logic = Philips4dUsDicomPatcherLogic()
    self.logic.logCallback = self.addLog

  def cleanup(self):
    pass

  def onPatchButton(self):
    slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
    try:
      self.inputDirSelector.addCurrentPathToHistory()
      self.outputDirSelector.addCurrentPathToHistory()
      self.statusLabel.plainText = ''
      self.logic.patchDicomDir(self.inputDirSelector.currentPath, self.outputDirSelector.currentPath, self.enableNrrdOutputCheckBox.checked)
    except Exception as e:
      self.addLog("Unexpected error: {0}".format(e.message))
    slicer.app.restoreOverrideCursor();
  
  def addLog(self, text):
    """Append text to log window
    """
    self.statusLabel.appendPlainText(text)
    slicer.app.processEvents() # force update

#
# Philips4dUsDicomPatcherLogic
#

class Philips4dUsDicomPatcherLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)
    self.logCallback = None
    
  def addLog(self, text):
    logging.info(text)
    if self.logCallback:
      self.logCallback(text)

  def isDicomUltrasoundFile(self, inputDicomFilePath):
    from DICOMLib import DICOMLoadable
    dicomPlugin = slicer.modules.dicomPlugins['DicomUltrasoundPlugin']()    
    files = [inputDicomFilePath]
    loadables = dicomPlugin.examineFiles(files)
    return len(loadables)>0
      
  def convertUltrasoundDicomToNrrd(self, inputDicomFilePath, outputNrrdFilePath):

    # Load from DICOM
    from DICOMLib import DICOMLoadable
    loadable = DICOMLoadable()
    loadable.files = [inputDicomFilePath]
    loadable.name = os.path.basename(inputDicomFilePath)
    loadable.tooltip = ''
    loadable.selected = True
    loadable.confidence = 1.
    loadable.createBrowserNode = False # don't create browser nodes (it would clutter the scene when batch processing)
    dicomPlugin = slicer.modules.dicomPlugins['DicomUltrasoundPlugin']()        
    sequenceNode = dicomPlugin.load(loadable)
    
    # Write to NRRD
    storageNode = sequenceNode.GetStorageNode()
    storageNode.SetFileName(outputNrrdFilePath)
    success = storageNode.WriteData(sequenceNode)
    
    # Clean up
    slicer.mrmlScene.RemoveNode(sequenceNode)
    
    return success    
      
  def patchDicomDir(self, inputDirPath, outputDirPath, exportUltrasoundToNrrd):
    """
    Since CTK (rightly) requires certain basic information [1] before it can import
    data files that purport to be dicom, this code patches the files in a directory
    with some needed fields.  Apparently it is possible to export files from the
    Philips PMS QLAB system with these fields missing.

    Calling this function with a directory path will make a patched copy of each file.
    Importing the old files to CTK should still fail, but the new ones should work.

    The directory is assumed to have a set of instances that are all from the
    same study of the same patient.  Also that each instance (file) is an
    independent (multiframe) series.

    [1] https://github.com/commontk/CTK/blob/16aa09540dcb59c6eafde4d9a88dfee1f0948edc/Libs/DICOM/Core/ctkDICOMDatabase.cpp#L1283-L1287
    """

    import dicom

    if not outputDirPath:
      outputDirPath = inputDirPath
    
    self.addLog('DICOM patching started...')
    logging.debug('DICOM patch input directory: '+inputDirPath)
    logging.debug('DICOM patch output directory: '+outputDirPath)

    studyUIDToRandomUIDMap = {}
    seriesUIDToRandomUIDMap = {}
    
    # All files without a patient ID will be assigned to the same patient
    randomPatientID = dicom.UID.generate_uid(None)
    
    requiredTags = ['PatientName', 'PatientID', 'StudyInstanceUID', 'SeriesInstanceUID']
    for root, subFolders, files in os.walk(inputDirPath):
    
      # Assume that all files in a directory belongs to the same study
      randomStudyUID = dicom.UID.generate_uid(None)
      
      currentSubDir = os.path.relpath(root, inputDirPath)
      rootOutput = os.path.join(outputDirPath, currentSubDir)
      
      for file in files:
        filePath = os.path.join(root,file)
        self.addLog('Examining %s...' % os.path.join(currentSubDir,file))
        try:
          ds = dicom.read_file(filePath)
        except (IOError, dicom.filereader.InvalidDicomError):
          self.addLog('  Non-DICOM file. Skipped.'.format(file))
          continue          
        self.addLog('  Patching...')

        for tag in requiredTags:
          if not hasattr(ds,tag):
            setattr(ds,tag,'')

        # Generate a new SOPInstanceUID to avoid different files having the same SOPInstanceUID
        ds.SOPInstanceUID = dicom.UID.generate_uid(None)
            
        if ds.PatientName == '':
          ds.PatientName = "Unspecified Patient"
        if ds.PatientID == '':
          ds.PatientID = randomPatientID
        if ds.StudyInstanceUID == '':
          ds.StudyInstanceUID = randomStudyUID
        if ds.SeriesInstanceUID == '':
          ds.SeriesInstanceUID = dicom.UID.generate_uid(None)

        if inputDirPath==outputDirPath:
          patchedFilePath = filePath + "-patched"
        else:
          patchedFilePath = os.path.abspath(os.path.join(rootOutput,file))
          if not os.path.exists(rootOutput):
            os.makedirs(rootOutput)
        
        dicom.write_file(patchedFilePath, ds)
        self.addLog('  Created patched DICOM file: %s' % patchedFilePath)
        
        if exportUltrasoundToNrrd and self.isDicomUltrasoundFile(patchedFilePath):
          self.addLog('  Save as NRRD...')
          nrrdFilePath = os.path.splitext(patchedFilePath)[0]+'.nrrd'
          if self.convertUltrasoundDicomToNrrd(patchedFilePath, nrrdFilePath):
            self.addLog('  Created NRRD file: %s' % nrrdFilePath)
          else:
            self.addLog('  NRRD file save failed')
        
    self.addLog('DICOM patching completed.')


class Philips4dUsDicomPatcherTest(ScriptedLoadableModuleTest):
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
    self.test_Philips4dUsDicomPatcher1()

  def test_Philips4dUsDicomPatcher1(self):
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

    self.delayDisplay("No tests are implemented")
