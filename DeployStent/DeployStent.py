import logging
import os
import pathlib
import shutil
import tempfile
from typing import Annotated, Optional

import qt
import vtk

import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)

from slicer import vtkMRMLModelNode


class DeployStent(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("DeployStent")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Examples")]
        self.parent.dependencies = []
        self.parent.contributors = ["John Doe (AnyWare Corp.)"]
        self.parent.helpText = _(
            """
Run stent deployment by executing deploy_stent_with_intermediates.py on selected model inputs,
then load and display deployed outputs in the scene.
"""
        )
        self.parent.acknowledgementText = _(
            """
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
"""
        )


@parameterNodeWrapper
class DeployStentParameterNode:
    inputSurfaceModel: vtkMRMLModelNode
    inputCenterlineModel: vtkMRMLModelNode
    startPointId: int = 0
    targetRadius: Annotated[float, WithinRange(0.0001, 100.0)] = 0.4
    startRadius: Annotated[float, WithinRange(0.0001, 100.0)] = 0.05
    stentLength: Annotated[float, WithinRange(0.0001, 1000.0)] = 3.0
    enableSnapshots: bool = False
    saveStep: Annotated[float, WithinRange(0.0001, 100.0)] = 0.1
    preserveTemporaryFiles: bool = False
    outputMeshFileName: str = "deployed_surface.vtp"
    outputCenterlineFileName: str = "deployed_centerline.vtp"
    outputSurfaceModel: Optional[vtkMRMLModelNode] = None
    outputCenterlineModel: Optional[vtkMRMLModelNode] = None


class DeployStentWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/DeployStent.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = DeployStentLogic()

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.ui.applyButton.connect("clicked(bool)", self.onApplyButton)
        self.ui.enableSnapshotsCheckBox.connect("toggled(bool)", self.onSnapshotToggleChanged)
        self.ui.logPlainTextEdit.setMaximumBlockCount(2000)
        self.ui.statusLabel.text = _("Idle")

        self.initializeParameterNode()

    def cleanup(self) -> None:
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()

    def exit(self) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self._parameterNodeGuiTag = None
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)

    def onSceneStartClose(self, caller, event) -> None:
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        self.setParameterNode(self.logic.getParameterNode())

        if not self._parameterNode.inputSurfaceModel:
            firstModelNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLModelNode")
            if firstModelNode:
                self._parameterNode.inputSurfaceModel = firstModelNode

        if not self._parameterNode.inputCenterlineModel:
            modelCount = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLModelNode")
            if modelCount > 1:
                self._parameterNode.inputCenterlineModel = slicer.mrmlScene.GetNthNodeByClass(1, "vtkMRMLModelNode")

        self.onSnapshotToggleChanged(self.ui.enableSnapshotsCheckBox.checked)

    def setParameterNode(self, inputParameterNode: DeployStentParameterNode | None) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
        self._parameterNode = inputParameterNode
        if self._parameterNode:
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
            self._checkCanApply()

    def onSnapshotToggleChanged(self, enabled: bool) -> None:
        self.ui.saveStepSpinBox.enabled = enabled
        self.ui.labelSaveStep.enabled = enabled
        self._checkCanApply()

    def _checkCanApply(self, caller=None, event=None) -> None:
        if not self._parameterNode:
            self.ui.applyButton.enabled = False
            return

        hasRequiredInputs = bool(
            self._parameterNode.inputSurfaceModel
            and self._parameterNode.inputCenterlineModel
            and self._parameterNode.targetRadius > 0.0
            and self._parameterNode.startRadius > 0.0
            and self._parameterNode.stentLength > 0.0
        )

        validSnapshotConfig = (not self._parameterNode.enableSnapshots) or (self._parameterNode.saveStep > 0.0)

        validRadiusConfig = self._parameterNode.startRadius < self._parameterNode.targetRadius

        canApply = hasRequiredInputs and validSnapshotConfig and validRadiusConfig
        self.ui.applyButton.enabled = canApply

        if not hasRequiredInputs:
            self.ui.applyButton.toolTip = _("Select both input model nodes and valid deployment parameters.")
        elif not validRadiusConfig:
            self.ui.applyButton.toolTip = _("Start radius must be smaller than target radius.")
        elif not validSnapshotConfig:
            self.ui.applyButton.toolTip = _("Save step must be > 0 when snapshots are enabled.")
        else:
            self.ui.applyButton.toolTip = _("Run stent deployment and load output models.")

    def _setStatus(self, text: str) -> None:
        self.ui.statusLabel.text = text
        slicer.app.processEvents()

    def _appendLog(self, text: str) -> None:
        if not text:
            return
        self.ui.logPlainTextEdit.appendPlainText(text)
        scrollbar = self.ui.logPlainTextEdit.verticalScrollBar()
        maximumValue = scrollbar.maximum() if callable(getattr(scrollbar, "maximum", None)) else scrollbar.maximum
        scrollbar.setValue(maximumValue)
        slicer.app.processEvents()

    def _handleProcessMessage(self, text: str, isError: bool = False) -> None:
        lines = [line for line in text.replace("\r", "\n").split("\n") if line.strip()]
        for line in lines:
            logLine = f"[stderr] {line}" if isError else line
            self._appendLog(logLine)
            self._setStatus(_("Running: {line}").format(line=line[:120]))

    def onApplyButton(self) -> None:
        with slicer.util.tryWithErrorDisplay(_("Failed to deploy stent."), waitCursor=True):
            self.ui.applyButton.enabled = False
            self.ui.logPlainTextEdit.clear()
            self._setStatus(_("Starting deployment..."))
            try:
                outputMeshFileName = "deployed_surface.vtp"
                outputCenterlineFileName = "deployed_centerline.vtp"
                outputSurfaceNode, outputCenterlineNode = self.logic.process(
                    inputSurfaceModel=self.ui.inputSurfaceSelector.currentNode(),
                    inputCenterlineModel=self.ui.inputCenterlineSelector.currentNode(),
                    startPointId=int(self.ui.startPointIdSpinBox.value),
                    targetRadius=float(self.ui.targetRadiusSpinBox.value),
                    startRadius=float(self.ui.startRadiusSpinBox.value),
                    stentLength=float(self.ui.stentLengthSpinBox.value),
                    enableSnapshots=bool(self.ui.enableSnapshotsCheckBox.checked),
                    saveStep=float(self.ui.saveStepSpinBox.value),
                    preserveTemporaryFiles=bool(self.ui.preserveTempFilesCheckBox.checked),
                    outputMeshFileName=outputMeshFileName,
                    outputCenterlineFileName=outputCenterlineFileName,
                    outputSurfaceModel=self.ui.outputSurfaceSelector.currentNode(),
                    outputCenterlineModel=self.ui.outputCenterlineSelector.currentNode(),
                    processMessageCallback=self._handleProcessMessage,
                )
                if outputSurfaceNode:
                    self.ui.outputSurfaceSelector.setCurrentNode(outputSurfaceNode)
                if outputCenterlineNode:
                    self.ui.outputCenterlineSelector.setCurrentNode(outputCenterlineNode)

                self._setStatus(_("Completed"))
            except Exception:
                self._setStatus(_("Failed"))
                raise
            finally:
                self._checkCanApply()


class DeployStentLogic(ScriptedLoadableModuleLogic):
    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)

    def getParameterNode(self):
        return DeployStentParameterNode(super().getParameterNode())

    def _scriptPath(self) -> str:
        moduleDir = os.path.dirname(__file__)
        scriptPath = os.path.join(moduleDir, "Resources", "Scripts", "deploy_stent_with_intermediates.py")
        if not os.path.exists(scriptPath):
            raise RuntimeError(f"Deployment script not found: {scriptPath}")
        return scriptPath

    def _writePolyDataToVtp(self, polyData: vtk.vtkPolyData, outputPath: str) -> None:
        writer = vtk.vtkXMLPolyDataWriter()
        writer.SetFileName(outputPath)
        writer.SetInputData(polyData)
        if writer.Write() != 1:
            raise RuntimeError(f"Failed to write VTP file: {outputPath}")

    def _loadPolyDataFromVtp(self, inputPath: str) -> vtk.vtkPolyData:
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(inputPath)
        reader.Update()
        polyData = vtk.vtkPolyData()
        polyData.DeepCopy(reader.GetOutput())
        return polyData

    def _ensureOutputModelNode(self, node: vtkMRMLModelNode | None, name: str) -> vtkMRMLModelNode:
        if node:
            return node
        return slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name)

    def _setDisplayedPolyData(self, node: vtkMRMLModelNode, polyData: vtk.vtkPolyData) -> None:
        node.SetAndObservePolyData(polyData)
        displayNode = node.GetDisplayNode()
        if not displayNode:
            node.CreateDefaultDisplayNodes()
            displayNode = node.GetDisplayNode()
        if displayNode:
            displayNode.SetVisibility(True)
            displayNode.SetOpacity(1.0)

    def _runScript(
        self,
        scriptPath: str,
        arguments: list[str],
        processMessageCallback=None,
    ) -> tuple[int, str, str]:
        import shutil

        pythonSlicerExecutablePath = shutil.which("PythonSlicer")
        if not pythonSlicerExecutablePath:
            raise RuntimeError("PythonSlicer executable was not found")

        cmd = [pythonSlicerExecutablePath, scriptPath, *arguments]
        logging.debug(f"Launch DeployStent script: {cmd}")
        proc = slicer.util.launchConsoleProcess(cmd)
        return self._logProcessOutput(proc, processMessageCallback=processMessageCallback)

    def _logProcessOutput(self, proc, processMessageCallback=None) -> tuple[int, str, str]:
        def emitProcessMessage(text: str, isError: bool = False) -> None:
            if not processMessageCallback:
                return
            try:
                processMessageCallback(text, isError)
            except Exception:
                logging.exception("DeployStent process message callback failed")

        def toText(chunk) -> str:
            if chunk is None:
                return ""
            if isinstance(chunk, bytes):
                return chunk.decode("utf-8", errors="replace")
            return str(chunk)

        stdOutParts = []
        stdErrParts = []

        while True:
            line = proc.stdout.readline()
            if not line:
                break
            line = toText(line)
            lineText = line.rstrip()
            stdOutParts.append(line)
            emitProcessMessage(lineText, False)
            slicer.app.processEvents()

        proc.wait()
        returnCode = proc.returncode

        if getattr(proc, "stderr", None):
            stderrText = toText(proc.stderr.read())
            if stderrText:
                stdErrParts.append(stderrText)
                emitProcessMessage(stderrText.rstrip(), True)

        stdOut = "".join(stdOutParts)
        stdErr = "".join(stdErrParts)
        return returnCode, stdOut, stdErr

    def process(
        self,
        inputSurfaceModel: vtkMRMLModelNode,
        inputCenterlineModel: vtkMRMLModelNode,
        startPointId: int,
        targetRadius: float,
        startRadius: float,
        stentLength: float,
        enableSnapshots: bool,
        saveStep: float,
        preserveTemporaryFiles: bool,
        outputMeshFileName: str,
        outputCenterlineFileName: str,
        outputSurfaceModel: vtkMRMLModelNode | None = None,
        outputCenterlineModel: vtkMRMLModelNode | None = None,
        processMessageCallback=None,
    ) -> tuple[vtkMRMLModelNode, vtkMRMLModelNode]:
        if not inputSurfaceModel or not inputCenterlineModel:
            raise ValueError("Input surface and centerline model nodes are required")
        if startRadius >= targetRadius:
            raise ValueError("Start radius must be smaller than target radius")
        if enableSnapshots and saveStep <= 0.0:
            raise ValueError("Save step must be > 0 when snapshots are enabled")

        inputSurfacePolyData = inputSurfaceModel.GetPolyData()
        inputCenterlinePolyData = inputCenterlineModel.GetPolyData()
        if not inputSurfacePolyData or inputSurfacePolyData.GetNumberOfPoints() == 0:
            raise ValueError("Input surface model has no polydata")
        if not inputCenterlinePolyData or inputCenterlinePolyData.GetNumberOfPoints() == 0:
            raise ValueError("Input centerline model has no polydata")

        safeOutputMeshFileName = outputMeshFileName if outputMeshFileName else "deployed_surface.vtp"
        safeOutputCenterlineFileName = outputCenterlineFileName if outputCenterlineFileName else "deployed_centerline.vtp"
        if not safeOutputMeshFileName.lower().endswith(".vtp"):
            safeOutputMeshFileName = f"{safeOutputMeshFileName}.vtp"
        if not safeOutputCenterlineFileName.lower().endswith(".vtp"):
            safeOutputCenterlineFileName = f"{safeOutputCenterlineFileName}.vtp"

        outputSurfaceNodeName = pathlib.Path(safeOutputMeshFileName).stem
        outputCenterlineNodeName = pathlib.Path(safeOutputCenterlineFileName).stem

        workDir = tempfile.mkdtemp(prefix="DeployStent_")
        shouldDeleteTemporaryFiles = not preserveTemporaryFiles
        try:
            workDirPath = pathlib.Path(workDir)
            inputSurfacePath = str(workDirPath / "input_surface.vtp")
            inputCenterlinePath = str(workDirPath / "input_centerline.vtp")
            outputSurfacePath = str(workDirPath / safeOutputMeshFileName)
            outputCenterlinePath = str(workDirPath / safeOutputCenterlineFileName)

            self._writePolyDataToVtp(inputSurfacePolyData, inputSurfacePath)
            self._writePolyDataToVtp(inputCenterlinePolyData, inputCenterlinePath)

            scriptArgs = [
                "--mesh", inputSurfacePath,
                "--cline", inputCenterlinePath,
                "--centerline-type", "single",
                "--start", str(int(startPointId)),
                "--target-R", str(float(targetRadius)),
                "--start-R", str(float(startRadius)),
                "--length", str(float(stentLength)),
                "--out-mesh", outputSurfacePath,
                "--out-cl", outputCenterlinePath,
            ]
            if enableSnapshots:
                scriptArgs.extend(["--save-step", str(float(saveStep))])

            startTime = qt.QDateTime.currentDateTimeUtc()
            logging.info("Starting DeployStent script execution")
            exitCode, stdOut, stdErr = self._runScript(
                self._scriptPath(),
                scriptArgs,
                processMessageCallback=processMessageCallback,
            )

            if stdOut.strip():
                logging.info(stdOut)
            if stdErr.strip():
                logging.warning(stdErr)

            if exitCode != 0:
                raise RuntimeError(
                    f"deploy_stent_with_intermediates.py failed with exit code {exitCode}.\n"
                    f"Stdout:\n{stdOut}\n\nStderr:\n{stdErr}"
                )

            if not os.path.exists(outputSurfacePath):
                raise RuntimeError(f"Expected output surface file was not created: {outputSurfacePath}")
            if not os.path.exists(outputCenterlinePath):
                raise RuntimeError(f"Expected output centerline file was not created: {outputCenterlinePath}")

            outputSurfacePolyData = self._loadPolyDataFromVtp(outputSurfacePath)
            outputCenterlinePolyData = self._loadPolyDataFromVtp(outputCenterlinePath)

            outputSurfaceNode = self._ensureOutputModelNode(outputSurfaceModel, outputSurfaceNodeName)
            outputCenterlineNode = self._ensureOutputModelNode(outputCenterlineModel, outputCenterlineNodeName)

            self._setDisplayedPolyData(outputSurfaceNode, outputSurfacePolyData)
            self._setDisplayedPolyData(outputCenterlineNode, outputCenterlinePolyData)

            slicer.util.resetThreeDViews()

            elapsedMs = startTime.msecsTo(qt.QDateTime.currentDateTimeUtc())
            logging.info(f"DeployStent completed in {elapsedMs / 1000.0:.2f} seconds")

            return outputSurfaceNode, outputCenterlineNode
        finally:
            if shouldDeleteTemporaryFiles:
                shutil.rmtree(workDir, ignore_errors=True)
            else:
                logging.info(f"Preserved temporary files in: {workDir}")
                if processMessageCallback:
                    processMessageCallback(f"Preserved temporary files in: {workDir}", False)


class DeployStentTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_DeployStent_smoke()

    def test_DeployStent_smoke(self):
        self.delayDisplay("Starting DeployStent smoke test")

        surfaceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "surface")
        centerlineNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "centerline")
        sphere = vtk.vtkSphereSource()
        sphere.Update()
        line = vtk.vtkLineSource()
        line.Update()
        surfaceNode.SetAndObservePolyData(sphere.GetOutput())
        centerlineNode.SetAndObservePolyData(line.GetOutput())

        logic = DeployStentLogic()
        self.assertTrue(os.path.exists(logic._scriptPath()))

        self.delayDisplay("DeployStent smoke test passed")
