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

// SlicerQt includes
#include <qSlicerCoreApplication.h>
#include <qSlicerIOManager.h>
#include <qSlicerNodeWriter.h>

// Philips4dUsReader Logic includes
#include <vtkSlicerPhilips4dUsReaderLogic.h>

// Philips4dUsReader QTModule includes
#include "qSlicerPhilips4dUsReaderModule.h"

//-----------------------------------------------------------------------------

#if (QT_VERSION < QT_VERSION_CHECK(5, 0, 0))
#include <QtPlugin>
Q_EXPORT_PLUGIN2(qSlicerPhilips4dUsReaderModule, qSlicerPhilips4dUsReaderModule);
#endif

//-----------------------------------------------------------------------------
/// \ingroup SlicerRt_QtModules_Philips4dUsReader
class qSlicerPhilips4dUsReaderModulePrivate
{
public:
  qSlicerPhilips4dUsReaderModulePrivate();
};

//-----------------------------------------------------------------------------
qSlicerPhilips4dUsReaderModulePrivate::qSlicerPhilips4dUsReaderModulePrivate()
{
}


//-----------------------------------------------------------------------------
qSlicerPhilips4dUsReaderModule::qSlicerPhilips4dUsReaderModule(QObject* _parent)
  : Superclass(_parent)
  , d_ptr(new qSlicerPhilips4dUsReaderModulePrivate)
{
}

//-----------------------------------------------------------------------------
qSlicerPhilips4dUsReaderModule::~qSlicerPhilips4dUsReaderModule()
{
}

//-----------------------------------------------------------------------------
QString qSlicerPhilips4dUsReaderModule::helpText()const
{
  QString help = QString(
    "The Philips4dUsReader module enables importing and loading Philips 4D Ultrasound DICOM files into Slicer.<br>"
    "The Philips4dUsReader module is hidden and therefore does not require a module widget.<br>"
    "More information: <a href=\"https://github.com/SlicerHeart/SlicerHeart\">SlicerHear extension website</a><br>");
  return help;
}

//-----------------------------------------------------------------------------
QString qSlicerPhilips4dUsReaderModule::acknowledgementText()const
{
  // must not be empty
  QString acknowledgement = QString(
    "The module was originally developed by Andras Lasso (PerkLab, Queen's University)");
  return acknowledgement;
}

//-----------------------------------------------------------------------------
QStringList qSlicerPhilips4dUsReaderModule::contributors()const
{
  QStringList moduleContributors;
  moduleContributors << QString("Andras Lasso (Queen's)");
  return moduleContributors;
}

//-----------------------------------------------------------------------------
QStringList qSlicerPhilips4dUsReaderModule::categories()const
{
  return QStringList() << "Cardiac";
}

//-----------------------------------------------------------------------------
void qSlicerPhilips4dUsReaderModule::setup()
{
  this->Superclass::setup();
}

//-----------------------------------------------------------------------------
qSlicerAbstractModuleRepresentation* qSlicerPhilips4dUsReaderModule::createWidgetRepresentation()
{
  // The module does not have GUI
  return NULL;
}

//-----------------------------------------------------------------------------
vtkMRMLAbstractLogic* qSlicerPhilips4dUsReaderModule::createLogic()
{
  return vtkSlicerPhilips4dUsReaderLogic::New();
}
