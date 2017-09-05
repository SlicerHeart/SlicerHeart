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
#include <QtPlugin>

// SlicerQt includes
#include <qSlicerCoreApplication.h>
#include <qSlicerIOManager.h>
#include <qSlicerNodeWriter.h>

// KretzFileReader Logic includes
#include <vtkSlicerKretzFileReaderLogic.h>

// KretzFileReader QTModule includes
#include "qSlicerKretzFileReaderPlugin.h"
#include "qSlicerKretzFileReaderModule.h"
#include "qSlicerKretzFileReaderPluginWidget.h"


//-----------------------------------------------------------------------------
Q_EXPORT_PLUGIN2(qSlicerKretzFileReaderModule, qSlicerKretzFileReaderModule);

//-----------------------------------------------------------------------------
/// \ingroup SlicerRt_QtModules_KretzFileReader
class qSlicerKretzFileReaderModulePrivate
{
public:
  qSlicerKretzFileReaderModulePrivate();
};

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderModulePrivate::qSlicerKretzFileReaderModulePrivate()
{
}


//-----------------------------------------------------------------------------
qSlicerKretzFileReaderModule::qSlicerKretzFileReaderModule(QObject* _parent)
  : Superclass(_parent)
  , d_ptr(new qSlicerKretzFileReaderModulePrivate)
{
}

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderModule::~qSlicerKretzFileReaderModule()
{
}

//-----------------------------------------------------------------------------
QString qSlicerKretzFileReaderModule::helpText()const
{
  QString help = QString(
    "The KretzFileReader module enables importing and loading GE/Kretz 3D ultrasound files into Slicer.<br>"
    "The KretzFileReader module is hidden and therefore does not require an application.<br>"
    "More information: <a href=\"https://github.com/SlicerHeart/SlicerHeart\">SlicerHear extension website</a><br>");
  return help;
}

//-----------------------------------------------------------------------------
QString qSlicerKretzFileReaderModule::acknowledgementText()const
{
  QString acknowledgement = QString(
    "");
  return acknowledgement;
}

//-----------------------------------------------------------------------------
QStringList qSlicerKretzFileReaderModule::contributors()const
{
  QStringList moduleContributors;
  moduleContributors << QString("Andras Lasso (Queen's)");
  return moduleContributors;
}

//-----------------------------------------------------------------------------
QStringList qSlicerKretzFileReaderModule::categories()const
{
  return QStringList() << "";
}

//-----------------------------------------------------------------------------
void qSlicerKretzFileReaderModule::setup()
{
  this->Superclass::setup();
  
  vtkSlicerKretzFileReaderLogic* kretzFileReaderLogic =  
    vtkSlicerKretzFileReaderLogic::SafeDownCast(this->logic());

  // Adds the module to the IO Manager
  qSlicerCoreIOManager* ioManager =
    qSlicerCoreApplication::application()->coreIOManager();
  ioManager->registerIO(new qSlicerKretzFileReaderPlugin(kretzFileReaderLogic,this));
}

//-----------------------------------------------------------------------------
qSlicerAbstractModuleRepresentation* qSlicerKretzFileReaderModule::createWidgetRepresentation()
{
  return new qSlicerKretzFileReaderPluginWidget;
}

//-----------------------------------------------------------------------------
vtkMRMLAbstractLogic* qSlicerKretzFileReaderModule::createLogic()
{
  return vtkSlicerKretzFileReaderLogic::New();
}

