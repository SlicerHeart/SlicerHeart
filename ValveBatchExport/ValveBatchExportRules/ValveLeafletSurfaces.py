import os
from pathlib import Path

import slicer

from .base import ValveBatchExportRule


class ValveLeafletSurfacesExportRule(ValveBatchExportRule):

  BRIEF_USE = "Valve leaflet surfaces (.vtk)"
  DETAILED_DESCRIPTION = "Export leaflet surface models as individual .vtk files."

  CMD_FLAG = "-vls"

  def processScene(self, sceneFileName):
    for valveModel in self.getHeartValveModelNodes():
      frameNumber = self.getAssociatedFrameNumber(valveModel)
      filename, _ = os.path.splitext(os.path.basename(sceneFileName))
      valveType = valveModel.heartValveNode.GetAttribute('ValveType')
      cardiacCyclePhaseName = valveModel.cardiacCyclePhasePresets[valveModel.getCardiacCyclePhase()]["shortname"]
      valveModelName = self.generateValveModelName(filename, valveType, cardiacCyclePhaseName, frameNumber)

      for leafletModel in valveModel.leafletModels:
        surfaceModel = leafletModel.surfaceModelNode
        valid = surfaceModel is not None and surfaceModel.GetPolyData() is not None and surfaceModel.GetPolyData().GetNumberOfPoints() > 0
        if valid:
          filename = f"{valveModelName}_{leafletModel.getName().replace(' ', '_')}.vtk"
          slicer.util.saveNode(surfaceModel, str(Path(self.outputDir) / filename))
