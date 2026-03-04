import logging
import importlib.util
import os
import pathlib
import queue
import shutil
import subprocess
import threading
import tempfile
import time
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

from slicer import vtkMRMLMarkupsCurveNode, vtkMRMLMarkupsFiducialNode, vtkMRMLMarkupsNode, vtkMRMLModelNode, vtkMRMLNode, vtkMRMLSegmentationNode


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
    inputVesselSegmentation: Optional[vtkMRMLSegmentationNode] = None
    inputVesselSegmentId: str = ""
    inputCenterlineCurve: Optional[vtkMRMLNode] = None
    centerPointMarkup: Optional[vtkMRMLMarkupsFiducialNode] = None
    targetRadius: Annotated[float, WithinRange(0.0001, 30.0)] = 10.0
    startRadius: Annotated[float, WithinRange(0.0001, 30.0)] = 5.0
    stentLength: Annotated[float, WithinRange(0.0001, 100.0)] = 30.0
    enableSnapshots: bool = False
    verboseLogging: bool = False
    saveStep: Annotated[float, WithinRange(0.0001, 100.0)] = 1.0
    preserveTemporaryFiles: bool = False
    outputMeshFileName: str = "deployed_surface.vtp"
    outputCenterlineFileName: str = "deployed_centerline.vtp"
    outputSurfaceModel: Optional[vtkMRMLModelNode] = None
    outputCenterlineModel: Optional[vtkMRMLModelNode] = None
    stentPreviewModel: Optional[vtkMRMLModelNode] = None


class DeployStentWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)

        # Fast preview update state
        self._previewUpdateTimer = qt.QTimer()
        self._previewUpdateTimer.setSingleShot(True)
        self._previewUpdateTimer.setInterval(25)  # debounce rapid changes
        self._previewUpdateTimer.connect("timeout()", self._updateStentPreviewModelNow)

        self._lastPreviewKey = None
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None
        self._centerPointMarkupNode = None
        self._isProcessing = False

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
        self.ui.inputSurfaceSelector.currentNodeChanged.connect(self._checkCanApply)
        self.ui.inputSurfaceSelector.currentSegmentChanged.connect(self._checkCanApply)
        self.ui.inputCenterlineSelector.currentNodeChanged.connect(self._onInputCenterlineNodeChanged)
        self.ui.inputCenterlineSelector.currentNodeChanged.connect(self._checkCanApply)
        self.ui.inputCenterlineSelector.currentNodeChanged.connect(self._updateStentPreviewModel)
        self.ui.centerPointMarkupSelector.currentNodeChanged.connect(self._onCenterPointMarkupSelectorChanged)
        self.ui.centerPointMarkupSelector.currentNodeChanged.connect(self._checkCanApply)
        self.ui.centerPointMarkupSelector.currentNodeChanged.connect(self._updateStentPreviewModel)
        self.ui.stentPreviewModelSelector.currentNodeChanged.connect(self._updateStentPreviewModel)
        self.ui.startRadiusSpinBox.connect("valueChanged(double)", self._updateStentPreviewModel)
        self.ui.targetRadiusSpinBox.connect("valueChanged(double)", self._updateStentPreviewModel)
        self.ui.stentLengthSpinBox.connect("valueChanged(double)", self._updateStentPreviewModel)
        self.ui.enableSnapshotsCheckBox.connect("toggled(bool)", self.onSnapshotToggleChanged)
        self.ui.startPointPlaceWidget.setMRMLScene(slicer.mrmlScene)
        self.ui.startPointPlaceWidget.placeMultipleMarkups = slicer.qSlicerMarkupsPlaceWidget.ForcePlaceSingleMarkup
        self.ui.startPointPlaceWidget.deleteAllControlPointsOptionVisible = False
        self.ui.startPointPlaceWidget.placeButton().show()
        self.ui.startPointPlaceWidget.deleteButton().show()
        self.ui.startPointPlaceWidget.connect("activeMarkupsFiducialPlaceModeChanged(bool)", self._checkCanApply)
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
            self._setCenterPointMarkupNode(None)

    def onSceneStartClose(self, caller, event) -> None:
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        self.setParameterNode(self.logic.getParameterNode())

        if not self._parameterNode.inputVesselSegmentation:
            firstSegmentationNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
            if firstSegmentationNode:
                self._parameterNode.inputVesselSegmentation = firstSegmentationNode

        if not self.ui.inputSurfaceSelector.currentNode() and self._parameterNode.inputVesselSegmentation:
            self.ui.inputSurfaceSelector.setCurrentNode(self._parameterNode.inputVesselSegmentation)

        if not self.ui.inputCenterlineSelector.currentNode() and self._parameterNode.inputCenterlineCurve:
            self.ui.inputCenterlineSelector.setCurrentNode(self._parameterNode.inputCenterlineCurve)

        if self.ui.inputSurfaceSelector.currentNode() and not self.ui.inputSurfaceSelector.currentSegmentID():
            segmentation = self.ui.inputSurfaceSelector.currentNode().GetSegmentation()
            if segmentation and segmentation.GetNumberOfSegments() > 0:
                self.ui.inputSurfaceSelector.setCurrentSegmentID(segmentation.GetNthSegmentID(0))

        if not self._parameterNode.inputCenterlineCurve:
            firstCurveNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLMarkupsCurveNode")
            if firstCurveNode:
                self._parameterNode.inputCenterlineCurve = firstCurveNode
            modelCount = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLModelNode")
            if not self._parameterNode.inputCenterlineCurve and modelCount > 1:
                self._parameterNode.inputCenterlineCurve = slicer.mrmlScene.GetNthNodeByClass(1, "vtkMRMLModelNode")

        self._ensureCenterPointMarkupNode()

        self.onSnapshotToggleChanged(self.ui.enableSnapshotsCheckBox.checked)
        self._updateStentPreviewModel()

    def _onInputCenterlineNodeChanged(self, node: vtkMRMLNode | None) -> None:
        if self._parameterNode:
            self._parameterNode.inputCenterlineCurve = node

    def _onCenterPointMarkupSelectorChanged(self, node: vtkMRMLNode | None) -> None:
        if not self._parameterNode:
            return
        centerPointMarkupNode = node if (node and node.IsA("vtkMRMLMarkupsFiducialNode")) else None
        self._parameterNode.centerPointMarkup = centerPointMarkupNode
        if centerPointMarkupNode:
            self._configureCenterPointMarkupNode(centerPointMarkupNode)
            if self.ui.startPointPlaceWidget.currentNode() != centerPointMarkupNode:
                self.ui.startPointPlaceWidget.setCurrentNode(centerPointMarkupNode)
            self._setCenterPointMarkupNode(centerPointMarkupNode)
        else:
            self._setCenterPointMarkupNode(None)

    def _ensureCenterPointMarkupNode(self) -> vtkMRMLMarkupsFiducialNode | None:
        if not self._parameterNode:
            return None

        centerPointMarkupNode = self._parameterNode.centerPointMarkup

        if (not centerPointMarkupNode) or (centerPointMarkupNode.GetScene() is None):
            centerPointMarkupNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "CenterPoint")
            self._parameterNode.centerPointMarkup = centerPointMarkupNode

        self._configureCenterPointMarkupNode(centerPointMarkupNode)
        if self.ui.startPointPlaceWidget.currentNode() != centerPointMarkupNode:
            self.ui.startPointPlaceWidget.setCurrentNode(centerPointMarkupNode)
        self._setCenterPointMarkupNode(centerPointMarkupNode)
        return centerPointMarkupNode

    def _configureCenterPointMarkupNode(self, centerPointMarkupNode: vtkMRMLMarkupsFiducialNode | None) -> None:
        if not centerPointMarkupNode:
            return
        centerPointMarkupNode.SetMaximumNumberOfControlPoints(1)
        if not centerPointMarkupNode.GetDisplayNode():
            centerPointMarkupNode.CreateDefaultDisplayNodes()
        while centerPointMarkupNode.GetNumberOfControlPoints() > 1:
            centerPointMarkupNode.RemoveNthControlPoint(centerPointMarkupNode.GetNumberOfControlPoints() - 1)

    def _setCenterPointMarkupNode(self, centerPointMarkupNode: vtkMRMLMarkupsFiducialNode | None) -> None:
        if self._centerPointMarkupNode:
            if self.hasObserver(self._centerPointMarkupNode, vtk.vtkCommand.ModifiedEvent, self._onCenterPointMarkupModified):
                self.removeObserver(self._centerPointMarkupNode, vtk.vtkCommand.ModifiedEvent, self._onCenterPointMarkupModified)
            if self.hasObserver(self._centerPointMarkupNode, vtkMRMLMarkupsNode.PointModifiedEvent, self._onCenterPointMarkupModified):
                self.removeObserver(self._centerPointMarkupNode, vtkMRMLMarkupsNode.PointModifiedEvent, self._onCenterPointMarkupModified)
        self._centerPointMarkupNode = centerPointMarkupNode
        if self._centerPointMarkupNode:
            self.addObserver(self._centerPointMarkupNode, vtk.vtkCommand.ModifiedEvent, self._onCenterPointMarkupModified)
            self.addObserver(self._centerPointMarkupNode, vtkMRMLMarkupsNode.PointModifiedEvent, self._onCenterPointMarkupModified)

    def _onCenterPointMarkupModified(self, caller=None, event=None) -> None:
        self._configureCenterPointMarkupNode(self._centerPointMarkupNode)
        self._checkCanApply()
        self._updateStentPreviewModel()

    def setParameterNode(self, inputParameterNode: DeployStentParameterNode | None) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
        self._parameterNode = inputParameterNode
        if self._parameterNode:
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
            if self.ui.inputCenterlineSelector.currentNode() != self._parameterNode.inputCenterlineCurve:
                self.ui.inputCenterlineSelector.setCurrentNode(self._parameterNode.inputCenterlineCurve)
            self._ensureCenterPointMarkupNode()
            self._checkCanApply()
            self._updateStentPreviewModel()
        else:
            self._setCenterPointMarkupNode(None)

    def onSnapshotToggleChanged(self, enabled: bool) -> None:
        self.ui.saveStepSpinBox.enabled = enabled
        self.ui.labelSaveStep.enabled = enabled
        self._checkCanApply()

    def _checkCanApply(self, caller=None, event=None) -> None:
        if self._isProcessing:
            self.ui.applyButton.enabled = True
            self.ui.applyButton.text = _("Cancel")
            self.ui.applyButton.toolTip = _("Cancel running stent deployment.")
            return

        self.ui.applyButton.text = _("Apply")
        if not self._parameterNode:
            self.ui.applyButton.enabled = False
            self.ui.applyButton.toolTip = _("Parameter node is not available.")
            return

        inputVesselSegmentation = self.ui.inputSurfaceSelector.currentNode()
        inputVesselSegmentId = self.ui.inputSurfaceSelector.currentSegmentID()
        inputCenterlineCurve = self.ui.inputCenterlineSelector.currentNode()
        centerPointMarkupNode = self._ensureCenterPointMarkupNode()
        hasCenterPoint = bool(centerPointMarkupNode and centerPointMarkupNode.GetNumberOfControlPoints() > 0)

        disabledReason = None
        if not inputVesselSegmentation:
            disabledReason = _("Select an input surface segmentation.")
        elif not inputVesselSegmentId:
            disabledReason = _("Select an input surface segment.")
        elif not inputCenterlineCurve:
            disabledReason = _("Select an input centerline model/curve.")
        elif not hasCenterPoint:
            disabledReason = _("Place one center point.")
        elif self._parameterNode.targetRadius <= 0.0:
            disabledReason = _("Target radius must be > 0.")
        elif self._parameterNode.startRadius <= 0.0:
            disabledReason = _("Start radius must be > 0.")
        elif self._parameterNode.stentLength <= 0.0:
            disabledReason = _("Stent length must be > 0.")
        elif self._parameterNode.startRadius >= self._parameterNode.targetRadius:
            disabledReason = _("Start radius must be smaller than target radius.")
        elif self._parameterNode.enableSnapshots and self._parameterNode.saveStep <= 0.0:
            disabledReason = _("Save step must be > 0 when snapshots are enabled.")

        canApply = disabledReason is None
        self.ui.applyButton.enabled = canApply
        self.ui.applyButton.toolTip = disabledReason if disabledReason else _("Run stent deployment and load output models.")

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
            if "->  R =" in line:
                self._setStatus(_("Running: {line}").format(line=line[:120]))

    def _updateStentPreviewModel(self) -> None:
        # Keep existing call sites; now debounced
        self._scheduleStentPreviewUpdate()

    def _scheduleStentPreviewUpdate(self) -> None:
        if self._previewUpdateTimer.isActive():
            self._previewUpdateTimer.stop()
        self._previewUpdateTimer.start()

    def _updateStentPreviewModelNow(self) -> None:
        parameterNode = self._parameterNode
        if not parameterNode or not parameterNode.stentPreviewModel:
            self._lastPreviewKey = None
            return

        centerlineNode = parameterNode.inputCenterlineCurve
        if not centerlineNode:
            self._setDisplayedPolyData(parameterNode.stentPreviewModel, None, defaultOpacity=0.5, defaultColor=(0.0, 0.0, 1.0))
            self._lastPreviewKey = None
            return

        centerPointPos = None
        if parameterNode.centerPointMarkup and parameterNode.centerPointMarkup.GetNumberOfControlPoints() > 0:
            p = [0.0, 0.0, 0.0]
            parameterNode.centerPointMarkup.GetNthControlPointPositionWorld(0, p)
            centerPointPos = (round(p[0], 3), round(p[1], 3), round(p[2], 3))

        previewKey = (
            parameterNode.stentPreviewModel.GetID() if parameterNode.stentPreviewModel else None,
            centerlineNode.GetID(),
            centerlineNode.GetMTime(),
            centerPointPos,
            round(float(parameterNode.stentLength), 4),
            round(float(parameterNode.startRadius), 4),
            round(float(parameterNode.targetRadius), 4),
        )
        if previewKey == self._lastPreviewKey:
            return
        self._lastPreviewKey = previewKey
        centerPointPositionWorld = None
        if parameterNode.centerPointMarkup and parameterNode.centerPointMarkup.GetNumberOfControlPoints() > 0:
            centerPointPositionWorld = [0.0, 0.0, 0.0]
            parameterNode.centerPointMarkup.GetNthControlPointPositionWorld(0, centerPointPositionWorld)

        try:
            centerlinePolyData = self.logic.getResampledCenterlinePolyDataForPreview(centerlineNode, pointCount=100)
            previewPolyData = self.logic.createStentPreviewPolyData(
                centerlinePolyData=centerlinePolyData,
                stentLength=float(parameterNode.stentLength),
                startRadius=float(parameterNode.startRadius),
                targetRadius=float(parameterNode.targetRadius),
                centerPositionWorld=centerPointPositionWorld,
            )
        except Exception:
            logging.exception("Failed to update stent preview model")
            previewPolyData = vtk.vtkPolyData()

        self.logic._setDisplayedPolyData(parameterNode.stentPreviewModel, previewPolyData, defaultOpacity=0.5, defaultColor=(0.0, 0.0, 1.0))


    def _ensureJaxInstalled(self) -> None:
        if importlib.util.find_spec("jax"):
            return

        self._appendLog(_("JAX is not installed. Installing jax..."))
        self._setStatus(_("Installing jax..."))
        try:
            slicer.util.pip_install("jax")
        except Exception as exc:
            raise RuntimeError(_("Failed to install required dependency 'jax'.")) from exc

        if not importlib.util.find_spec("jax"):
            raise RuntimeError(_("Failed to verify 'jax' installation."))

        self._appendLog(_("JAX installation completed."))

    def onApplyButton(self) -> None:
        if self._isProcessing:
            self.logic.requestCancel()
            self.ui.applyButton.enabled = False
            self.ui.applyButton.toolTip = _("Cancelling deployment...")
            self._setStatus(_("Cancelling..."))
            return

        with slicer.util.tryWithErrorDisplay(_("Failed to deploy stent."), waitCursor=True):
            self._isProcessing = True
            self._checkCanApply()
            self.ui.logPlainTextEdit.clear()
            self._setStatus(_("Starting deployment..."))
            try:
                self._ensureJaxInstalled()
                centerPointMarkupNode = self.ui.startPointPlaceWidget.currentNode()
                if self._parameterNode and centerPointMarkupNode:
                    referencedCenterPointMarkupNode = self._parameterNode.centerPointMarkup
                    if referencedCenterPointMarkupNode != centerPointMarkupNode:
                        self._parameterNode.centerPointMarkup = centerPointMarkupNode
                    self._configureCenterPointMarkupNode(centerPointMarkupNode)
                    self._setCenterPointMarkupNode(centerPointMarkupNode)

                outputSurfaceModelNode = self.ui.outputSurfaceSelector.currentNode()
                if outputSurfaceModelNode is None:
                    outputSurfaceModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "deployed_surface")
                    self.ui.outputSurfaceSelector.setCurrentNode(outputSurfaceModelNode)

                outputCenterlineModelNode = self.ui.outputCenterlineSelector.currentNode()
                if outputCenterlineModelNode is None:
                    outputCenterlineModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "deployed_centerline")
                    self.ui.outputCenterlineSelector.setCurrentNode(outputCenterlineModelNode)

                outputSurfaceNode, outputCenterlineNode = self.logic.process(
                    inputVesselSegmentation=self.ui.inputSurfaceSelector.currentNode(),
                    inputVesselSegmentId=self.ui.inputSurfaceSelector.currentSegmentID(),
                    inputCenterlineCurve=self.ui.inputCenterlineSelector.currentNode(),
                    centerPointMarkup=centerPointMarkupNode,
                    targetRadius=float(self.ui.targetRadiusSpinBox.value),
                    startRadius=float(self.ui.startRadiusSpinBox.value),
                    stentLength=float(self.ui.stentLengthSpinBox.value),
                    enableSnapshots=bool(self.ui.enableSnapshotsCheckBox.checked),
                    verboseLogging=bool(self.ui.verboseLoggingCheckBox.checked),
                    saveStep=float(self.ui.saveStepSpinBox.value),
                    preserveTemporaryFiles=bool(self.ui.preserveTempFilesCheckBox.checked),
                    outputSurfaceModel=outputSurfaceModelNode,
                    outputCenterlineModel=outputCenterlineModelNode,
                    processMessageCallback=self._handleProcessMessage,
                )
                if outputSurfaceNode:
                    self.ui.outputSurfaceSelector.setCurrentNode(outputSurfaceNode)
                if outputCenterlineNode:
                    self.ui.outputCenterlineSelector.setCurrentNode(outputCenterlineNode)

                self._setStatus(_("Completed"))
            except DeployStentCancelledError:
                self._appendLog(_("Deployment cancelled by user."))
                self._setStatus(_("Cancelled"))
            except Exception:
                self._setStatus(_("Failed"))
                raise
            finally:
                self._isProcessing = False
                self._checkCanApply()


class DeployStentCancelledError(RuntimeError):
    pass


class DeployStentLogic(ScriptedLoadableModuleLogic):
    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self._activeProcess = None
        self._cancelRequested = False
        self._previewResampledCenterlineCache = None
        self._mmToCm = 0.1
        self._cmToMm = 10.0

    def requestCancel(self) -> None:
        self._cancelRequested = True
        proc = self._activeProcess
        if not proc:
            return
        self._stopProcessImmediately(proc)

    def _stopProcessImmediately(self, proc) -> None:
        if not proc:
            return
        if proc.poll() is not None:
            return

        try:
            processId = getattr(proc, "pid", None)
            if processId and os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(processId), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=0.2)
                except Exception:
                    if proc.poll() is None:
                        proc.kill()
        except Exception:
            logging.exception("Failed to stop DeployStent process immediately")

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

    def _scaledPolyData(self, polyData: vtk.vtkPolyData, scaleFactor: float) -> vtk.vtkPolyData:
        transform = vtk.vtkTransform()
        transform.Scale(float(scaleFactor), float(scaleFactor), float(scaleFactor))
        transformFilter = vtk.vtkTransformPolyDataFilter()
        transformFilter.SetTransform(transform)
        transformFilter.SetInputData(polyData)
        transformFilter.Update()
        scaledPolyData = vtk.vtkPolyData()
        scaledPolyData.DeepCopy(transformFilter.GetOutput())
        return scaledPolyData

    def _getSegmentClosedSurfacePolyData(self, segmentationNode: vtkMRMLSegmentationNode, segmentId: str) -> vtk.vtkPolyData:
        if not segmentationNode:
            raise ValueError("Input surface segmentation node is required")
        if not segmentId:
            raise ValueError("Input surface segment is required")

        segmentation = segmentationNode.GetSegmentation()
        if not segmentation:
            raise ValueError("Selected segmentation node has no segmentation data")
        if not segmentation.GetSegment(segmentId):
            raise ValueError("Selected segment was not found in input segmentation")

        if not segmentationNode.CreateClosedSurfaceRepresentation():
            raise RuntimeError("Failed to create closed surface representation for selected segment")

        polyData = vtk.vtkPolyData()
        success = segmentationNode.GetClosedSurfaceRepresentation(segmentId, polyData)
        if not success or not polyData or polyData.GetNumberOfPoints() == 0:
            raise RuntimeError("Selected segment has no closed surface representation")

        return polyData

    def _ensureOutputModelNode(self, node: vtkMRMLModelNode | None, name: str) -> vtkMRMLModelNode:
        if node:
            return node
        return slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name)

    def _getCenterlinePolyData(self, centerlineNode: vtkMRMLNode) -> vtk.vtkPolyData:
        if not centerlineNode:
            raise ValueError("Input centerline node is required")

        centerlinePolyData = vtk.vtkPolyData()
        if centerlineNode.IsA("vtkMRMLModelNode"):
            modelNode = centerlineNode
            modelPolyData = modelNode.GetPolyData()
            if not modelPolyData or modelPolyData.GetNumberOfPoints() == 0:
                raise ValueError("Input centerline model has no polydata")
            centerlinePolyData.DeepCopy(modelPolyData)
        elif centerlineNode.IsA("vtkMRMLMarkupsCurveNode"):
            curveNode = centerlineNode
            curvePolyData = curveNode.GetCurveWorld()
            if not curvePolyData or curvePolyData.GetNumberOfPoints() == 0:
                raise ValueError("Input centerline curve has no curve points")
            centerlinePolyData.DeepCopy(curvePolyData)
        else:
            raise ValueError("Input centerline node must be a model or markups curve node")

        if centerlinePolyData.GetNumberOfPoints() == 0:
            raise ValueError("Input centerline has no polydata")
        return centerlinePolyData

    def _resamplePolylineToPointCount(self, polyData: vtk.vtkPolyData, pointCount: int = 100) -> vtk.vtkPolyData:
        points = self._polylinePointsFromPolyData(polyData)
        if len(points) < 2:
            return vtk.vtkPolyData()

        targetPointCount = max(2, int(pointCount))

        cumulativeDistances = [0.0]
        for pointIndex in range(1, len(points)):
            cumulativeDistances.append(cumulativeDistances[-1] + vtk.vtkMath.Distance2BetweenPoints(points[pointIndex - 1], points[pointIndex]) ** 0.5)

        totalLength = cumulativeDistances[-1]
        if totalLength <= 0.0:
            return vtk.vtkPolyData()

        sampleDistances = [totalLength * sampleIndex / (targetPointCount - 1) for sampleIndex in range(targetPointCount)]
        sampledPoints = [self._interpolatedPointAtDistance(points, cumulativeDistances, sampleDistance) for sampleDistance in sampleDistances]

        vtkPointsObject = vtk.vtkPoints()
        vtkLineObject = vtk.vtkPolyLine()
        vtkLineObject.GetPointIds().SetNumberOfIds(len(sampledPoints))
        for pointIndex, point in enumerate(sampledPoints):
            vtkPointId = vtkPointsObject.InsertNextPoint(point)
            vtkLineObject.GetPointIds().SetId(pointIndex, vtkPointId)

        lines = vtk.vtkCellArray()
        lines.InsertNextCell(vtkLineObject)
        resampledPolyData = vtk.vtkPolyData()
        resampledPolyData.SetPoints(vtkPointsObject)
        resampledPolyData.SetLines(lines)
        return resampledPolyData

    def getResampledCenterlinePolyDataForPreview(self, centerlineNode: vtkMRMLNode, pointCount: int = 100) -> vtk.vtkPolyData:
        if not centerlineNode:
            return vtk.vtkPolyData()

        cacheKey = (centerlineNode.GetID(), centerlineNode.GetMTime(), int(pointCount))
        if self._previewResampledCenterlineCache and self._previewResampledCenterlineCache.get("key") == cacheKey:
            return self._previewResampledCenterlineCache["polyData"]

        centerlinePolyData = self._getCenterlinePolyData(centerlineNode)
        resampledPolyData = self._resamplePolylineToPointCount(centerlinePolyData, pointCount=pointCount)

        cachedPolyData = vtk.vtkPolyData()
        cachedPolyData.DeepCopy(resampledPolyData)
        self._previewResampledCenterlineCache = {
            "key": cacheKey,
            "polyData": cachedPolyData,
        }
        return cachedPolyData

    def _setDisplayedPolyData(self, node: vtkMRMLModelNode, polyData: vtk.vtkPolyData, defaultOpacity: float | None = None, defaultColor: tuple[float, float, float] | None = None) -> None:
        node.SetAndObservePolyData(polyData)
        displayNode = node.GetDisplayNode()
        if not displayNode:
            node.CreateDefaultDisplayNodes()
            displayNode = node.GetDisplayNode()
            if defaultOpacity is not None:
                displayNode.SetOpacity(defaultOpacity)
            if defaultColor is not None:
                displayNode.SetColor(defaultColor[0], defaultColor[1], defaultColor[2])

    def _polylinePointIdsAndPointsFromPolyData(self, polyData: vtk.vtkPolyData) -> tuple[list[int], list[tuple[float, float, float]]]:
        if not polyData or polyData.GetNumberOfPoints() < 2:
            return [], []

        lines = polyData.GetLines()
        idList = vtk.vtkIdList()
        bestPointIds = None
        bestPointCount = 0
        if lines:
            lines.InitTraversal()
            while lines.GetNextCell(idList):
                pointCount = idList.GetNumberOfIds()
                if pointCount > bestPointCount:
                    bestPointCount = pointCount
                    bestPointIds = [idList.GetId(i) for i in range(pointCount)]

        points = polyData.GetPoints()
        if bestPointIds and len(bestPointIds) >= 2:
            return bestPointIds, [points.GetPoint(pointId) for pointId in bestPointIds]
        pointIds = list(range(polyData.GetNumberOfPoints()))
        return pointIds, [points.GetPoint(pointId) for pointId in pointIds]

    def _polylinePointsFromPolyData(self, polyData: vtk.vtkPolyData) -> list[tuple[float, float, float]]:
        _, points = self._polylinePointIdsAndPointsFromPolyData(polyData)
        return points

    def _interpolatedPointAtDistance(self, points: list[tuple[float, float, float]], cumulativeDistances: list[float], distanceValue: float) -> tuple[float, float, float]:
        if distanceValue <= cumulativeDistances[0]:
            return points[0]
        if distanceValue >= cumulativeDistances[-1]:
            return points[-1]

        for pointIndex in range(len(cumulativeDistances) - 1):
            segmentStartDistance = cumulativeDistances[pointIndex]
            segmentEndDistance = cumulativeDistances[pointIndex + 1]
            if segmentStartDistance <= distanceValue <= segmentEndDistance:
                segmentLength = segmentEndDistance - segmentStartDistance
                if segmentLength <= 1e-12:
                    return points[pointIndex]
                interpolation = (distanceValue - segmentStartDistance) / segmentLength
                pointA = points[pointIndex]
                pointB = points[pointIndex + 1]
                return (
                    pointA[0] + interpolation * (pointB[0] - pointA[0]),
                    pointA[1] + interpolation * (pointB[1] - pointA[1]),
                    pointA[2] + interpolation * (pointB[2] - pointA[2]),
                )
        return points[-1]

    def _startPointIdFromCenterAndLength(self, polyData: vtk.vtkPolyData, centerWorldPosition: list[float], stentLength: float) -> int:
        pointIds, points = self._polylinePointIdsAndPointsFromPolyData(polyData)
        if len(points) < 1:
            raise ValueError("Input centerline has no points")
        if len(points) == 1:
            return int(pointIds[0])

        cumulativeDistances = [0.0]
        for pointIndex in range(1, len(points)):
            cumulativeDistances.append(cumulativeDistances[-1] + vtk.vtkMath.Distance2BetweenPoints(points[pointIndex - 1], points[pointIndex]) ** 0.5)

        centerIndex = min(
            range(len(points)),
            key=lambda index: vtk.vtkMath.Distance2BetweenPoints(points[index], centerWorldPosition),
        )

        targetDistanceFromStart = cumulativeDistances[centerIndex] + max(float(stentLength) * 0.5, 0.0)
        if targetDistanceFromStart >= cumulativeDistances[-1]:
            return int(pointIds[-1])

        for pointIndex in range(centerIndex, len(cumulativeDistances) - 1):
            if cumulativeDistances[pointIndex] <= targetDistanceFromStart <= cumulativeDistances[pointIndex + 1]:
                segmentLength = cumulativeDistances[pointIndex + 1] - cumulativeDistances[pointIndex]
                if segmentLength <= 1e-12:
                    return int(pointIds[pointIndex])
                interpolation = (targetDistanceFromStart - cumulativeDistances[pointIndex]) / segmentLength
                targetLocalIndex = pointIndex + 1 if interpolation >= 0.5 else pointIndex
                return int(pointIds[targetLocalIndex])

        return int(pointIds[-1])

    def _segmentPolylineByLengthAroundPoint(
        self,
        polyData: vtk.vtkPolyData,
        segmentLength: float,
        centerPositionWorld: list[float] | None = None,
    ) -> vtk.vtkPolyData:
        points = self._polylinePointsFromPolyData(polyData)
        if len(points) < 2:
            return vtk.vtkPolyData()

        cumulativeDistances = [0.0]
        for pointIndex in range(1, len(points)):
            cumulativeDistances.append(cumulativeDistances[-1] + vtk.vtkMath.Distance2BetweenPoints(points[pointIndex - 1], points[pointIndex]) ** 0.5)

        totalLength = cumulativeDistances[-1]
        if totalLength <= 0.0:
            return vtk.vtkPolyData()

        clampedSegmentLength = min(max(segmentLength, 1e-6), totalLength)

        if centerPositionWorld:
            closestPointIndex = min(
                range(len(points)),
                key=lambda index: vtk.vtkMath.Distance2BetweenPoints(points[index], centerPositionWorld),
            )
            centerDistance = cumulativeDistances[closestPointIndex]
        else:
            centerDistance = totalLength * 0.5

        startDistance = max(0.0, centerDistance - clampedSegmentLength * 0.5)
        endDistance = min(totalLength, centerDistance + clampedSegmentLength * 0.5)
        if endDistance - startDistance < clampedSegmentLength:
            if startDistance <= 1e-9:
                endDistance = min(totalLength, clampedSegmentLength)
            elif endDistance >= totalLength - 1e-9:
                startDistance = max(0.0, totalLength - clampedSegmentLength)

        sampledPoints = [self._interpolatedPointAtDistance(points, cumulativeDistances, startDistance)]
        for pointIndex, pointDistance in enumerate(cumulativeDistances):
            if startDistance < pointDistance < endDistance:
                sampledPoints.append(points[pointIndex])
        sampledPoints.append(self._interpolatedPointAtDistance(points, cumulativeDistances, endDistance))

        vtkPointsObject = vtk.vtkPoints()
        vtkLineObject = vtk.vtkPolyLine()
        vtkLineObject.GetPointIds().SetNumberOfIds(len(sampledPoints))
        for pointIndex, point in enumerate(sampledPoints):
            vtkPointId = vtkPointsObject.InsertNextPoint(point)
            vtkLineObject.GetPointIds().SetId(pointIndex, vtkPointId)

        lines = vtk.vtkCellArray()
        lines.InsertNextCell(vtkLineObject)
        segmentPolyData = vtk.vtkPolyData()
        segmentPolyData.SetPoints(vtkPointsObject)
        segmentPolyData.SetLines(lines)
        return segmentPolyData

    def _createPreviewTube(self, centerlinePolyData: vtk.vtkPolyData, radius: float) -> vtk.vtkPolyData:
        tube = vtk.vtkTubeFilter()
        tube.SetInputData(centerlinePolyData)
        tube.SetRadius(max(radius, 0.0001))
        tube.SetNumberOfSides(16)   # faster preview
        tube.SetCapping(False)     # uncapped as requested
        tube.Update()
        return tube.GetOutput()

    def createStentPreviewPolyData(
        self,
        centerlinePolyData: vtk.vtkPolyData,
        stentLength: float,
        startRadius: float,
        targetRadius: float,
        centerPositionWorld: list[float] | None = None,
    ) -> vtk.vtkPolyData:
        centerlineSegment = self._segmentPolylineByLengthAroundPoint(
            centerlinePolyData,
            stentLength,
            centerPositionWorld=centerPositionWorld,
        )
        if centerlineSegment.GetNumberOfPoints() < 2:
            return vtk.vtkPolyData()

        startTube = self._createPreviewTube(centerlineSegment, startRadius)
        targetTube = self._createPreviewTube(centerlineSegment, targetRadius)

        appendFilter = vtk.vtkAppendPolyData()
        if startTube.GetNumberOfPoints() > 0:
            appendFilter.AddInputData(startTube)
        if targetTube.GetNumberOfPoints() > 0:
            appendFilter.AddInputData(targetTube)
        appendFilter.Update()

        cleanFilter = vtk.vtkCleanPolyData()
        cleanFilter.SetInputConnection(appendFilter.GetOutputPort())
        cleanFilter.Update()

        previewPolyData = vtk.vtkPolyData()
        previewPolyData.DeepCopy(cleanFilter.GetOutput())
        return previewPolyData

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
        self._activeProcess = proc
        try:
            return self._logProcessOutput(proc, processMessageCallback=processMessageCallback)
        finally:
            self._activeProcess = None

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

        stdoutQueue: queue.Queue = queue.Queue()
        stderrQueue: queue.Queue = queue.Queue()

        def streamReader(stream, outputQueue: queue.Queue) -> None:
            if not stream:
                outputQueue.put(None)
                return
            try:
                while True:
                    chunk = stream.readline()
                    if not chunk:
                        break
                    outputQueue.put(chunk)
            finally:
                outputQueue.put(None)

        stdoutThread = threading.Thread(target=streamReader, args=(getattr(proc, "stdout", None), stdoutQueue), daemon=True)
        stderrThread = threading.Thread(target=streamReader, args=(getattr(proc, "stderr", None), stderrQueue), daemon=True)
        stdoutThread.start()
        stderrThread.start()

        stdoutClosed = False
        stderrClosed = False
        cancelSignalSent = False

        while True:
            while True:
                try:
                    chunk = stdoutQueue.get_nowait()
                except queue.Empty:
                    break
                if chunk is None:
                    stdoutClosed = True
                    continue
                text = toText(chunk)
                stdOutParts.append(text)
                emitProcessMessage(text.rstrip(), False)

            while True:
                try:
                    chunk = stderrQueue.get_nowait()
                except queue.Empty:
                    break
                if chunk is None:
                    stderrClosed = True
                    continue
                text = toText(chunk)
                stdErrParts.append(text)
                emitProcessMessage(text.rstrip(), True)

            if self._cancelRequested and not cancelSignalSent:
                cancelSignalSent = True
                emitProcessMessage("Cancellation requested. Stopping deployment process...", True)
                self._stopProcessImmediately(proc)
                break

            if proc.poll() is not None and stdoutClosed and stderrClosed:
                break

            slicer.app.processEvents()
            time.sleep(0.01)

        if self._cancelRequested:
            self._stopProcessImmediately(proc)
            returnCode = proc.poll()
            if returnCode is None:
                returnCode = -1
        else:
            returnCode = proc.wait()
            stdoutThread.join(timeout=0.1)
            stderrThread.join(timeout=0.1)

        stdOut = "".join(stdOutParts)
        stdErr = "".join(stdErrParts)
        return returnCode, stdOut, stdErr

    def process(
        self,
        inputVesselSegmentation: vtkMRMLSegmentationNode,
        inputVesselSegmentId: str,
        inputCenterlineCurve: vtkMRMLNode,
        centerPointMarkup: vtkMRMLMarkupsFiducialNode,
        targetRadius: float,
        startRadius: float,
        stentLength: float,
        enableSnapshots: bool,
        verboseLogging: bool,
        saveStep: float,
        preserveTemporaryFiles: bool,
        outputSurfaceModel: vtkMRMLModelNode | None = None,
        outputCenterlineModel: vtkMRMLModelNode | None = None,
        processMessageCallback=None,
    ) -> tuple[vtkMRMLModelNode, vtkMRMLModelNode]:
        if not inputVesselSegmentation or not inputVesselSegmentId or not inputCenterlineCurve:
            raise ValueError("Input surface segmentation/segment and centerline node are required")
        if not centerPointMarkup or centerPointMarkup.GetNumberOfControlPoints() < 1:
            raise ValueError("One center point fiducial is required")
        if startRadius >= targetRadius:
            raise ValueError("Start radius must be smaller than target radius")
        if enableSnapshots and saveStep <= 0.0:
            raise ValueError("Save step must be > 0 when snapshots are enabled")

        self._cancelRequested = False

        inputSurfacePolyData = self._getSegmentClosedSurfacePolyData(inputVesselSegmentation, inputVesselSegmentId)
        inputCenterlinePolyData = self._getCenterlinePolyData(inputCenterlineCurve)
        inputSurfacePolyDataCm = self._scaledPolyData(inputSurfacePolyData, self._mmToCm)
        inputCenterlinePolyDataCm = self._scaledPolyData(inputCenterlinePolyData, self._mmToCm)
        centerPointPositionWorld = [0.0, 0.0, 0.0]
        centerPointMarkup.GetNthControlPointPositionWorld(0, centerPointPositionWorld)
        centerPointPositionWorldCm = [coordinate * self._mmToCm for coordinate in centerPointPositionWorld]
        targetRadiusCm = float(targetRadius) * self._mmToCm
        startRadiusCm = float(startRadius) * self._mmToCm
        stentLengthCm = float(stentLength) * self._mmToCm
        saveStepCm = float(saveStep) * self._mmToCm
        startPointId = self._startPointIdFromCenterAndLength(inputCenterlinePolyDataCm, centerPointPositionWorldCm, stentLengthCm)
        if not inputSurfacePolyDataCm or inputSurfacePolyDataCm.GetNumberOfPoints() == 0:
            raise ValueError("Input surface model has no polydata")

        safeOutputMeshFileName = "deployed_surface.vtp"
        safeOutputCenterlineFileName = "deployed_centerline.vtp"

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

            self._writePolyDataToVtp(inputSurfacePolyDataCm, inputSurfacePath)
            self._writePolyDataToVtp(inputCenterlinePolyDataCm, inputCenterlinePath)

            scriptArgs = [
                "--mesh", inputSurfacePath,
                "--cline", inputCenterlinePath,
                "--centerline-type", "single",
                "--start", str(int(startPointId)),
                "--target-R", str(float(targetRadiusCm)),
                "--start-R", str(float(startRadiusCm)),
                "--length", str(float(stentLengthCm)),
                "--out-mesh", outputSurfacePath,
                "--out-cl", outputCenterlinePath,
                "--log-level", "2" if verboseLogging else "1"
            ]
            if enableSnapshots:
                scriptArgs.extend(["--save-step", str(float(saveStepCm))])
            else:
                scriptArgs.extend(["--save-step", "10000"])  # effectively disable snapshots by setting very high save step

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

            if self._cancelRequested:
                raise DeployStentCancelledError("Deployment cancelled by user")

            if exitCode != 0:
                raise RuntimeError(
                    f"deploy_stent_with_intermediates.py failed with exit code {exitCode}.\n"
                    f"Stdout:\n{stdOut}\n\nStderr:\n{stdErr}"
                )

            if not os.path.exists(outputSurfacePath):
                raise RuntimeError(f"Expected output surface file was not created: {outputSurfacePath}")
            if not os.path.exists(outputCenterlinePath):
                raise RuntimeError(f"Expected output centerline file was not created: {outputCenterlinePath}")

            outputSurfacePolyDataCm = self._loadPolyDataFromVtp(outputSurfacePath)
            outputCenterlinePolyDataCm = self._loadPolyDataFromVtp(outputCenterlinePath)
            outputSurfacePolyData = self._scaledPolyData(outputSurfacePolyDataCm, self._cmToMm)
            outputCenterlinePolyData = self._scaledPolyData(outputCenterlinePolyDataCm, self._cmToMm)

            outputSurfaceNode = self._ensureOutputModelNode(outputSurfaceModel, outputSurfaceNodeName)
            outputCenterlineNode = self._ensureOutputModelNode(outputCenterlineModel, outputCenterlineNodeName)

            self._setDisplayedPolyData(outputSurfaceNode, outputSurfacePolyData, defaultOpacity=0.5, defaultColor=(1.0, 0.5, 0.0))
            self._setDisplayedPolyData(outputCenterlineNode, outputCenterlinePolyData)

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
