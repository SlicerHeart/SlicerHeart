/*==============================================================================

  Copyright (c) Laboratory for Percutaneous Surgery (PerkLab)
  Queen's University, Kingston, ON, Canada. All Rights Reserved.

  See COPYRIGHT.txt
  or http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  This file was originally developed by Andras Lasso, PerkLab.

==============================================================================*/

// Qt includes
#include <QApplication>
#include <QFileInfo>

// SlicerQt includes
#include "qSlicerKretzFileReaderPlugin.h"
#include "qSlicerKretzFileReaderOptionsWidget.h"

// Logic includes
#include "vtkSlicerKretzFileReaderLogic.h"

// MRML includes
#include <vtkMRMLScalarVolumeNode.h>
#include <vtkMRMLSelectionNode.h>

//-----------------------------------------------------------------------------
/// \ingroup SlicerRt_QtModules_KretzFileReader
class qSlicerKretzFileReaderPluginPrivate
{
  public:
  vtkSmartPointer<vtkSlicerKretzFileReaderLogic> Logic;
};

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderPlugin::qSlicerKretzFileReaderPlugin(QObject* _parent)
  : Superclass(_parent)
  , d_ptr(new qSlicerKretzFileReaderPluginPrivate)
{
}

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderPlugin::qSlicerKretzFileReaderPlugin(vtkSlicerKretzFileReaderLogic* logic, QObject* _parent)
  : Superclass(_parent)
  , d_ptr(new qSlicerKretzFileReaderPluginPrivate)
{
  this->setLogic(logic);
}

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderPlugin::~qSlicerKretzFileReaderPlugin()
{
}

//-----------------------------------------------------------------------------
void qSlicerKretzFileReaderPlugin::setLogic(vtkSlicerKretzFileReaderLogic* logic)
{
  Q_D(qSlicerKretzFileReaderPlugin);
  d->Logic = logic;
}

//-----------------------------------------------------------------------------
vtkSlicerKretzFileReaderLogic* qSlicerKretzFileReaderPlugin::logic()const
{
  Q_D(const qSlicerKretzFileReaderPlugin);
  return d->Logic.GetPointer();
}

//-----------------------------------------------------------------------------
QString qSlicerKretzFileReaderPlugin::description()const
{
  return "GE Kretz ultrasound volume";
}

//-----------------------------------------------------------------------------
qSlicerIO::IOFileType qSlicerKretzFileReaderPlugin::fileType()const
{
  return QString("KretzFile");
}

//-----------------------------------------------------------------------------
QStringList qSlicerKretzFileReaderPlugin::extensions()const
{
  return QStringList() << "GE Kretz ultrasound volume (*.vol *.v00 *.v01 *.v02 *.v03 *.v04 *.v05)";
}

//-----------------------------------------------------------------------------
qSlicerIOOptions* qSlicerKretzFileReaderPlugin::options()const
{
  return new qSlicerKretzFileReaderOptionsWidget;
}

//-----------------------------------------------------------------------------
bool qSlicerKretzFileReaderPlugin::load(const IOProperties& properties) 
{
  Q_D(qSlicerKretzFileReaderPlugin);
  
  Q_ASSERT(properties.contains("fileName"));
  QString fileName = properties["fileName"].toString();

  QString name = QFileInfo(fileName).completeBaseName();
  if (properties.contains("name"))
  {
    name = properties["name"].toString();
  }

  bool scanConvert = true;
  if (properties.contains("scanConvert"))
  {
    properties["scanConvert"].toBool();
  }

  double outputSpacing = 0.5;
  if (properties.contains("outputSpacing"))
  {
    properties["outputSpacing"].toDouble();
  }

  double outputSpacingVector[3] = { outputSpacing, outputSpacing, outputSpacing };

  QApplication::setOverrideCursor(QCursor(Qt::BusyCursor)); 
  vtkMRMLNode* loadedVolumeNode = d->Logic->LoadKretzFile(fileName.toLatin1().data(), name.toLatin1().data(), scanConvert, outputSpacingVector);
  QApplication::restoreOverrideCursor();

  if (!loadedVolumeNode)
  {
    return false;
  }

  vtkSlicerApplicationLogic* appLogic = d->Logic->GetApplicationLogic();
  vtkMRMLSelectionNode* selectionNode = appLogic ? appLogic->GetSelectionNode() : 0;
  if (selectionNode)
  {
    selectionNode->SetReferenceActiveVolumeID(loadedVolumeNode->GetID());
    if (appLogic)
    {
      appLogic->PropagateVolumeSelection(); // includes FitSliceToAll by default
    }
  }
  this->setLoadedNodes(QStringList() << loadedVolumeNode->GetID());

  return true;
}
