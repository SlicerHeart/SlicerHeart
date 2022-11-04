import logging
from pathlib import Path
import sys
import argparse
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from HeartValveLib.Constants import CARDIAC_CYCLE_PHASE_PRESETS
from HeartValveLib.helpers import getAllFilesWithExtension, isMRBFile
from ValveBatchExportRules import *
from collections import deque


class STATE:

  PENDING = 'Pending'
  NOT_RUNNING = 'NotRunning'
  STARTING = 'Starting'
  RUNNING = 'Running'
  COMPLETED = 'Completed'


ProcessError = {
  qt.QProcess.FailedToStart: "FailedToStart",
  qt.QProcess.Crashed: "Crashed",
  qt.QProcess.Timedout: "Timedout",
  qt.QProcess.ReadError: "ReadError",
  qt.QProcess.WriteError: "WriteError",
  qt.QProcess.UnknownError: "UnknownError"
}


ProcessState = {
  qt.QProcess.NotRunning: STATE.NOT_RUNNING,
  qt.QProcess.Starting: STATE.STARTING,
  qt.QProcess.Running: STATE.RUNNING
}


#
# ValveBatchExport
#

class ValveBatchExport(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Valve batch export"
    self.parent.categories = ["Cardiac"]
    self.parent.dependencies = ["ValveAnnulusAnalysis"]
    self.parent.contributors = ["Andras Lasso (PerkLab), Christian Herz (CHOP), Matt Jolley (UPenn)"]
    self.parent.helpText = """Export data to CSV files from heart valve scene files."""
    self.parent.acknowledgementText = """ """

    try:
      import pandas
    except ImportError:
      logging.warning(f"{self.__class__.__name__} requires python package 'pandas'. Installing ...")
      slicer.util.pip_install("pandas")


#
# ValveBatchExportWidget
#

class ValveBatchExportWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  registeredExportPlugins = [ValveBatchExportPlugin(AnnulusContourCoordinatesExportRule),
                             ValveBatchExportPlugin(AnnulusContourModelExportRule, False),
                             ValveBatchExportPlugin(ValveLandmarkCoordinatesExportRule),
                             ValveBatchExportPlugin(ValveLandmarkLabelsExportRule, False),
                             ValveBatchExportPlugin(ValveLandmarksExportRule, False),
                             ValveBatchExportPlugin(ValveVolumeExportRule, False),
                             ValveBatchExportPlugin(QuantificationResultsExportRule),
                             ValveBatchExportPlugin(PapillaryAnalysisResultsExportRule),
                             ValveBatchExportPlugin(LeafletSegmentationExportRule, False),
                             ]

  @classmethod
  def registerExportPlugin(cls, exportPluginClass):
    if not isinstance(exportPluginClass, ValveBatchExportPlugin):
      return
    if not exportPluginClass in cls.registeredExportPlugins:
      cls.registeredExportPlugins.append(exportPluginClass)

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    self.logic = ValveBatchExportLogic(logCallback=self.addLog,
                                       progressCallback=self.progressUpdate,
                                       completedCallback=self._resetExport)

    # Instantiate and connect widgets ...

    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    # Layout within the dummy collapsible button
    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    self.inputDirSelector = ctk.ctkPathLineEdit()
    self.inputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
    self.inputDirSelector.settingKey = 'ValveBatchExportInputDir'
    self.inputDirSelector.setToolTip("Directory containing scene (.mrb) files with heart valves.")
    parametersFormLayout.addRow("Input directory:", self.inputDirSelector)

    self.outputDirSelector = ctk.ctkPathLineEdit()
    self.outputDirSelector.filters = ctk.ctkPathLineEdit.Dirs
    self.outputDirSelector.settingKey = 'ValveBatchExportOutputDir'
    self.outputDirSelector.setToolTip("Directory that will contain exported data.")
    parametersFormLayout.addRow("Output directory:", self.outputDirSelector)

    self.exportOptionsFrame = qt.QGroupBox("Export options")
    self.exportOptionsFrameLayout = qt.QFormLayout()
    self.exportOptionsFrame.setLayout(self.exportOptionsFrameLayout)

    # add ui of export plugins here
    for exportPlugin in self.registeredExportPlugins:
      self.exportOptionsFrameLayout.addRow(exportPlugin.getDescription(), exportPlugin)

    self.setupPhaseSelectionSection()
    self.exportOptionsFrameLayout.addRow("Phases (if available)", self.phaseSelectionWidget)

    parametersFormLayout.addRow(self.exportOptionsFrame)

    from multiprocessing import cpu_count
    self.parallelProcessesSpinBox = ctk.ctkDoubleSpinBox()
    self.parallelProcessesSpinBox.minimum = 1
    self.parallelProcessesSpinBox.maximum = cpu_count()
    self.parallelProcessesSpinBox.decimals = 0
    self.parallelProcessesSpinBox.value = self.logic.numParallelProcesses
    self.parallelProcessesSpinBox.valueChanged.connect(self.onNumParallelProcessesChanged)

    self.minProcessesButton = qt.QPushButton("min")
    self.minProcessesButton.toolTip = "Minimum number of processes"
    self.minProcessesButton.clicked.connect(lambda : self.parallelProcessesSpinBox.setValue(1))

    self.maxProcessesButton = qt.QPushButton("max")
    self.maxProcessesButton.toolTip = "Maximum number of parallel processes"
    self.maxProcessesButton.clicked.connect(lambda : self.parallelProcessesSpinBox.setValue(cpu_count()))

    hbox = qt.QHBoxLayout()
    hbox.addWidget(self.parallelProcessesSpinBox)
    hbox.addWidget(self.minProcessesButton)
    hbox.addWidget(self.maxProcessesButton)
    parametersFormLayout.addRow("Parallel processes", hbox)

    self.exportButton = qt.QPushButton("Start Export")
    self.exportButton.toolTip = \
      "Iterate through all the scene files in the input directory and write results to the output directory"
    parametersFormLayout.addRow(self.exportButton)
    self.exportButton.clicked.connect(self.onExportButtonClicked)

    self.statusLabel = qt.QPlainTextEdit()
    self.statusLabel.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
    parametersFormLayout.addRow(self.statusLabel)

    self.progressbar = qt.QProgressBar()
    parametersFormLayout.addRow(self.progressbar)

    self._exportRunning = False

  def onNumParallelProcessesChanged(self, val):
    self.logic.numParallelProcesses = int(val)

  def progressUpdate(self, value, maximum):
    self.progressbar.setValue(value)
    self.progressbar.setMaximum(maximum)

  def setupPhaseSelectionSection(self):
    self.phaseCheckboxes = []
    self.phaseSelectionWidget = qt.QWidget()
    self.phaseSelectionWidget.setLayout(qt.QGridLayout())
    self.phaseSelectionWidget.layout().setSpacing(0)
    self.phaseSelectionWidget.layout().setMargin(0)

    maxCols = 5
    for idx, (phaseName, phaseAttributes) in enumerate(CARDIAC_CYCLE_PHASE_PRESETS.items()):
      checkbox = qt.QCheckBox(phaseAttributes['shortname'])
      checkbox.setProperty('name', phaseAttributes['shortname'])
      checkbox.setToolTip(f"{phaseName}({phaseAttributes['shortname']})")
      checkbox.checked = True
      self.phaseCheckboxes.append(checkbox)
      self.phaseSelectionWidget.layout().addWidget(checkbox, idx // maxCols, idx % maxCols)

    button = qt.QPushButton("Select/Deselect All")
    self.phaseSelectionWidget.layout().addWidget(button, idx // maxCols + 1, 0, 1, maxCols)
    button.clicked.connect(self.onPhasesSelectionButtonClicked)

  def onPhasesSelectionButtonClicked(self):
    uncheckedFound = any(checkbox.checked is False for checkbox in self.phaseCheckboxes)
    deque(map(lambda checkbox: checkbox.setChecked(uncheckedFound), self.phaseCheckboxes))

  def getCheckedPhases(self):
    return [checkbox.property('name') for checkbox in self.phaseCheckboxes if checkbox.checked is True]

  def onExportButtonClicked(self):
    if self._exportRunning:
      self.logic.stopExport()
      self._resetExport()
    else:
      try:
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        self._startExport()
      except Exception as e:
        self.addLog(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        self._resetExport()
      finally:
        slicer.app.restoreOverrideCursor()

  def _startExport(self):
    self.exportButton.text = "Stop Export"
    self._exportRunning = True
    self.inputDirSelector.addCurrentPathToHistory()
    self.outputDirSelector.addCurrentPathToHistory()
    self.statusLabel.plainText = ''
    ValveBatchExportRule.setPhasesToExport(self.getCheckedPhases())
    self.logic.clearRules()
    for registeredPlugin in self.registeredExportPlugins:
      if registeredPlugin.activated:
        self.logic.addRule(registeredPlugin.getRuleClass())
    outputDir = self.outputDirSelector.currentPath
    if not outputDir:
      outputDir = self.inputDirSelector.currentPath
    self.logic.exportDir(self.inputDirSelector.currentPath, outputDir)

  def _resetExport(self):
    self.exportButton.text = "Start Export"
    self._exportRunning = False
    self._hasErrors = False

  def addLog(self, text):
    """Append text to log window
    """
    self.statusLabel.appendPlainText(text)
    slicer.app.processEvents() # force update


#
# ValveBatchExportLogic
#

class ValveBatchExportLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self,
               logCallback=None,
               progressCallback=None,
               completedCallback=None):
    ScriptedLoadableModuleLogic.__init__(self)
    self.logCallback = logCallback
    self.progressCallback = progressCallback
    self.completedCallback = completedCallback
    self._exportRules = []
    self.numParallelProcesses = 1
    self.parallelExport = None

  def clearRules(self):
    self._exportRules = []

  def addRule(self, ruleClass):
    ruleInstance = ruleClass()
    self._exportRules.append(ruleInstance)

  def addLog(self, text):
    logging.info(text)
    if self.logCallback:
      self.logCallback(text)

  def exportDir(self, inputDirPath, outputDirPath):
    """
    Export data extracted from all scene files in a directory (and its subdirectories)
    """

    self.addLog('Export started...')
    self.addLog(f'Input directory: {inputDirPath}')
    self.addLog(f'Output directory: {outputDirPath}')

    self.outputDirPath = outputDirPath
    self.examineInputs(inputDirPath)

    self.resetExport()

    if self.numParallelProcesses > 1:
      self._runMultiThreadedExport()
    else:
      self._runSingleThreadedExport()

  def examineInputs(self, inputDirPath):
    self._inputData = dict()
    for filePath in getAllFilesWithExtension(inputDirPath, ".mrb"):
      subOutputDirPath = Path(self.outputDirPath) / Path(filePath).stem
      self._inputData[filePath] = subOutputDirPath

  def _runMultiThreadedExport(self):
    self.parallelExport = ProcessesLogic(progressFinishedCallback=self.onProcessFinished,
                                         completedCallback=self.onProcessesCompleted,
                                         maximumRunningProcesses=self.numParallelProcesses,
                                         logCallback=self.addLog)
    for filePath, subOutputDirPath in self._inputData.items():
      process = self._createProcess(filePath, subOutputDirPath)
      self.parallelExport.addProcess(process)
    self.parallelExport.run()

  def _createProcess(self, filePath, subOutputDirPath):
    path = Path(subOutputDirPath)
    process = SlicerInstanceProcess(scriptPath=__file__,
                                    scriptArguments=self._createProcessArgs(filePath, subOutputDirPath),
                                    logDir=path)
    process.name = path.name
    return process

  def _createProcessArgs(self, inputFilePath, outputDirectory):
    args = ["-in", inputFilePath,
            "-out", outputDirectory]

    for rule in self._exportRules:
      args.append(rule.CMD_FLAG)
      args.extend(rule.OTHER_FLAGS)
    args.extend(["-ph", *ValveBatchExportRule.EXPORT_PHASES])
    return args

  def resetExport(self):
    self._cancelExport = False
    if self.progressCallback:
      self.progressCallback(0, len(self._inputData))

  def stopExport(self):
    if self.parallelExport:
      self.parallelExport.terminate()
      self.onExportStopped()
    self._cancelExport = True

  def onExportStopped(self):
    self.addLog("Export was cancelled.")
    self.resetExport()

  def _runSingleThreadedExport(self):
    for fIdx, (filePath, subOutputDirPath) in enumerate(self._inputData.items()):
      if self._cancelExport:
        self.onExportStopped()
        return
      self.exportMRBFile(filePath, subOutputDirPath)
      self.onProcessFinished(fIdx + 1, len(self._inputData))
    self.onProcessesCompleted()

  def onProcessFinished(self, numCompleted, numProcesses, process=None, exitCode=None, exitStatus=None):
    if process:
      if exitCode != qt.QProcess.NormalExit:
        self.addLog(f'{process.name} failed with exit status: {ProcessError[exitStatus]}')
      else:
        self.addLog(f"{process.name} finished")
    self.addLog(f"{numCompleted} of {numProcesses} exports complete.")
    if self.progressCallback:
      self.progressCallback(numCompleted, numProcesses)

  def onProcessesCompleted(self):
    for rule in self._exportRules:
      rule.mergeTables(list(self._inputData.values()), self.outputDirPath)
    self.addLog(f'\nExport completed.')
    if self.completedCallback:
      self.completedCallback()

  def exportMRBFile(self, filePath, outputDirPath):
    if not isMRBFile(filePath):
      self.addLog(f'  {filePath} is not a mrb file. Skipped.')
      return

    proceed = True
    if not Path(outputDirPath).exists():
      Path(outputDirPath).mkdir(parents=True, exist_ok=True)
    else:
      proceeds = []
      # iterate over all rules and check if all data is available
      for rule in self._exportRules:
        if not rule.OUTPUT_CSV_FILES:
          self.addLog(f"{rule} has no output csv files assigned. Proceeding...")
          proceeds.append(True)
          continue
        allExist = all((Path(outputDirPath) / csvFileName).exists() for csvFileName in rule.OUTPUT_CSV_FILES)
        proceeds.append(not allExist)
      proceed = all(proceeds)

    if not proceed:
      return

    self.addLog(f'Exporting mrb file: {filePath}')
    self.addLog(f'Output directory: {outputDirPath}')

    # set properties and initiate process start
    for rule in self._exportRules:
      rule.logCallback = self.addLog
      rule.outputDir = outputDirPath
      rule.processStart()

    self.addLog('  Loading scene...')
    try:
      slicer.mrmlScene.Clear(False)
      slicer.util.loadScene(filePath)
      # NB: this happens in Slicer_4.11 even though the scene was successfully loaded -- need to fix
    except RuntimeError:
      self.addLog(f'  Warning: errors found while loading scene from {filePath}')
      # slicer.mrmlScene.Clear(False)
      # return

    self.addLog('  Collecting data...')

    for rule in self._exportRules:
      rule.processScene(filePath)

    for rule in self._exportRules:
      rule.afterProcessScene(filePath)

    slicer.mrmlScene.Clear(False)

    self.addLog('Writing results...')
    for rule in self._exportRules:
      rule.processEnd()


class ProcessesLogic(object):
  """ source: SlicerProcesses """

  @property
  def totalNumProcesses(self):
    return len(self.processLists[STATE.RUNNING]) + \
           len(self.processLists[STATE.PENDING]) + \
           len(self.processLists[STATE.COMPLETED])

  def __init__(self,
               maximumRunningProcesses=None,
               progressFinishedCallback=None,
               completedCallback=None,
               logCallback=None):
    self.maximumRunningProcesses = os.cpu_count() if not maximumRunningProcesses else maximumRunningProcesses
    self.completedCallback = completedCallback
    self.progressFinishedCallback = progressFinishedCallback
    self.logCallback = logCallback
    self.__initializeProcessLists()

  def __initializeProcessLists(self):
    self.processLists = {}
    for processState in [STATE.PENDING, STATE.RUNNING, STATE.COMPLETED]:
      self.processLists[processState] = []

  def addProcess(self, process):
    self.processLists[STATE.PENDING].append(process)

  def addLog(self, text):
    logging.info(text)
    if self.logCallback:
      self.logCallback(text)

  def terminate(self):
    if self.processLists[STATE.RUNNING]:
      for process in self.processLists[STATE.RUNNING]:
        self.disconnectSignals(process)
        process.terminate()
    self.__initializeProcessLists()

  def __checkFinished(self):
    if not self.processLists[STATE.RUNNING] and not self.processLists[STATE.PENDING]:
      self.completedCallback()
    else:
      self.run()

  def waitForFinished(self):
    while self.processLists[STATE.RUNNING]:
      self.run()
      self.processLists[STATE.RUNNING][0].waitForFinished()
      self.__checkFinished()

  def run(self):
    while self.processLists[STATE.PENDING]:
      if len(self.processLists[STATE.RUNNING]) >= self.maximumRunningProcesses:
        break
      process = self.processLists[STATE.PENDING].pop()
      self.connectSignals(process)
      self.addLog(f"Starting export process {process.name}")
      process.run()
      self.processLists[STATE.RUNNING].append(process)

  def connectSignals(self, process):
    process.connect('finished(int,QProcess::ExitStatus)',
                    lambda exitCode, exitStatus: self.onProcessFinished(process, exitCode, exitStatus))
    process.stateChanged.connect(lambda status: self.onStateChanged(process, status))

  def disconnectSignals(self, process):
    # NB: disconnecting ALL slots from the specified signals. lambda returns a new function everytime. Otherwise could
    #     also hold a reference for the lambda function for every process and connected signal
    process.stateChanged.disconnect()
    process.disconnect('finished(int,QProcess::ExitStatus)')

  def onProcessFinished(self, process, exitCode, exitStatus):
    self.disconnectSignals(process)
    self.processLists[STATE.RUNNING].remove(process)
    self.processLists[STATE.COMPLETED].append(process)
    if self.progressFinishedCallback:
      self.progressFinishedCallback(len(self.processLists[STATE.COMPLETED]), self.totalNumProcesses,
                                    process, exitCode, exitStatus)
    self.__checkFinished()

  def onStateChanged(self, process, newState):
    logging.debug(f'{process.name} process status: {newState, ProcessState[newState]}')


class SlicerInstanceProcess(qt.QProcess):

  def __init__(self, scriptPath, scriptArguments, name="Process", logDir=None):
    super().__init__()
    self.name = name
    self.processState = STATE.PENDING
    self.scriptPath = scriptPath
    self.scriptArguments = scriptArguments
    self.logDir = logDir

  def run(self):
    if self.logDir:
      self._initLogFiles()
    args = ["--no-splash", "--python-script", self.scriptPath, *self.scriptArguments]
    logging.info(args)
    self.start(slicer.app.applicationFilePath(), args)

  def _initLogFiles(self):
    logDir = Path(self.logDir)
    if not logDir.exists():
      logDir.mkdir(parents=True, exist_ok=True)
    assert logDir.exists()
    self.setStandardOutputFile(str(logDir / f"{self.name}.log"))
    self.setStandardErrorFile(str(logDir / f"{self.name}_err.log"))


class ValveBatchExportTest(ScriptedLoadableModuleTest):
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
    self.test_ValveBatchExport1()

  def test_ValveBatchExport1(self):
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
    # TODO: implement tests
    pass


def main(argv):
  parser = argparse.ArgumentParser(description="Valve Batch Export")
  parser.add_argument("-in", "--input_mrb", metavar="PATH", help="input .mrb file", required=True)
  parser.add_argument("-out", "--output_directory", metavar="PATH", required=True,
                      help="data output directory")
  parser.add_argument("-ph", "--phases", metavar="PHASE_SHORTNAME", type=str, nargs="+", required=True,
                      help="cardiac phases which will be exported")
  parser.add_argument(AnnulusContourCoordinatesExportRule.CMD_FLAG, "--export_annulus_coordinates", action='store_true')
  parser.add_argument(QuantificationResultsExportRule.CMD_FLAG, "--export_quantification_results", action='store_true')
  parser.add_argument(ValveLandmarkCoordinatesExportRule.CMD_FLAG, "--export_landmark_coordinates", action='store_true')
  parser.add_argument(PapillaryAnalysisResultsExportRule.CMD_FLAG, "--export_papillary_results", action='store_true')
  parser.add_argument(ValveVolumeExportRule.CMD_FLAG, "--export_image_volume", action='store_true')
  parser.add_argument(LeafletSegmentationExportRule.CMD_FLAG, "--export_leaflet_segmentation", action='store_true')
  parser.add_argument(LeafletSegmentationExportRule.CMD_FLAG_1, "--individual_segmentation_files", action='store_true')
  parser.add_argument(ValveLandmarkLabelsExportRule.CMD_FLAG, "--valve_landmark_labels", action='store_true')
  parser.add_argument(ValveLandmarkLabelsExportRule.CMD_FLAG_QUADRANTS,
                      "--valve_landmark_label_quadrants", action='store_true')
  parser.add_argument(ValveLandmarkLabelsExportRule.CMD_FLAG_COMMISSURES,
                      "--valve_landmark_label_commissures", action='store_true')
  parser.add_argument(ValveLandmarkLabelsExportRule.CMD_FLAG_SEPARATE_FILES,
                      "--valve_landmark_label_individual_files", action='store_true')
  parser.add_argument(ValveLandmarksExportRule.CMD_FLAG, "--valve_landmarks_fcsv", action='store_true')
  parser.add_argument(AnnulusContourModelExportRule.CMD_FLAG, "--valve_annulus_contour", action='store_true')
  parser.add_argument(AnnulusContourModelExportRule.CMD_FLAG_SEGMENTATION, "--valve_annulus_contour_label", action='store_true')
  parser.add_argument(AnnulusContourModelExportRule.CMD_FLAG_MODEL, "--valve_annulus_contour_model", action='store_true')

  parser.add_argument("-d", "--debug", action='store_true', help="run python debugger upon Slicer start")
  args = parser.parse_args(argv)

  import slicer

  if args.debug:
    slicer.app.layoutManager().selectModule("PyDevRemoteDebug")
    w = slicer.modules.PyDevRemoteDebugWidget
    w.connectButton.click()

  logic = ValveBatchExportLogic()

  ValveBatchExportRule.EXPORT_PHASES = args.phases

  if args.export_quantification_results:
    logic.addRule(QuantificationResultsExportRule)
  if args.export_annulus_coordinates:
    logic.addRule(AnnulusContourCoordinatesExportRule)
  if args.export_landmark_coordinates:
    logic.addRule(ValveLandmarkCoordinatesExportRule)
  if args.export_papillary_results:
    logic.addRule(PapillaryAnalysisResultsExportRule)
  if args.valve_landmarks_fcsv:
    logic.addRule(ValveLandmarksExportRule)
  if args.export_image_volume:
    logic.addRule(ValveVolumeExportRule)
  if args.export_leaflet_segmentation:
    if args.individual_segmentation_files:
      LeafletSegmentationExportRule.ONE_FILE_PER_SEGMENT = True
    logic.addRule(LeafletSegmentationExportRule)
  if args.valve_annulus_contour:
    AnnulusContourModelExportRule.EXPORT_ANNULUS_AS_MODEL = args.valve_annulus_contour_model
    AnnulusContourModelExportRule.EXPORT_ANNULUS_AS_LABEL = args.valve_annulus_contour_label
    logic.addRule(AnnulusContourModelExportRule)
  if args.valve_landmark_labels:
    ValveLandmarkLabelsExportRule.EXPORT_QUADRANT_LANDMARKS = args.valve_landmark_label_quadrants
    ValveLandmarkLabelsExportRule.EXPORT_COMMISSURAL_LANDMARKS = args.valve_landmark_label_commissures
    ValveLandmarkLabelsExportRule.ONE_FILE_PER_LANDMARK = args.valve_landmark_label_individual_files
    logic.addRule(ValveLandmarkLabelsExportRule)

  assert Path(args.input_mrb).exists

  input_mrb = args.input_mrb

  try:
    logic.exportMRBFile(input_mrb,
                        args.output_directory)
  finally:
    import shutil
    logFilePath = slicer.app.errorLogModel().filePath
    shutil.copy(logFilePath, Path(args.output_directory) / f"{Path(input_mrb).stem}_Slicer.log")

  sys.exit(0)


if __name__ == "__main__":
  main(sys.argv[1:])