/*==============================================================================

  Program: 3D Slicer

  Portions (c) Copyright Brigham and Women's Hospital (BWH) All Rights Reserved.

  See COPYRIGHT.txt
  or http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

==============================================================================*/

// GeUsMovieReader Logic includes
#include <vtkSlicerGeUsMovieReaderLogic.h>

// GeUsMovieReader includes
#include "qSlicerGeUsMovieReaderModule.h"

//-----------------------------------------------------------------------------
#if (QT_VERSION < QT_VERSION_CHECK(5, 0, 0))
#include <QtPlugin>
Q_EXPORT_PLUGIN2(qSlicerGeUsMovieReaderModule, qSlicerGeUsMovieReaderModule);
#endif

//-----------------------------------------------------------------------------
/// \ingroup Slicer_QtModules_ExtensionTemplate
class qSlicerGeUsMovieReaderModulePrivate
{
public:
  qSlicerGeUsMovieReaderModulePrivate();
};

//-----------------------------------------------------------------------------
// qSlicerGeUsMovieReaderModulePrivate methods

//-----------------------------------------------------------------------------
qSlicerGeUsMovieReaderModulePrivate::qSlicerGeUsMovieReaderModulePrivate()
{
}

//-----------------------------------------------------------------------------
// qSlicerGeUsMovieReaderModule methods

//-----------------------------------------------------------------------------
qSlicerGeUsMovieReaderModule::qSlicerGeUsMovieReaderModule(QObject* _parent)
  : Superclass(_parent)
  , d_ptr(new qSlicerGeUsMovieReaderModulePrivate)
{
}

//-----------------------------------------------------------------------------
qSlicerGeUsMovieReaderModule::~qSlicerGeUsMovieReaderModule()
{
}

//-----------------------------------------------------------------------------
QString qSlicerGeUsMovieReaderModule::helpText() const
{
  return "This module can import GE 2D ultrasoudn image sequences from DICOM files"
    " that contain GEMS_Ultrasound_MovieGroup_001 private elements";
}

//-----------------------------------------------------------------------------
QString qSlicerGeUsMovieReaderModule::acknowledgementText() const
{
  // must not be empty
  QString acknowledgement = QString(
    "The module was originally developed by Andras Lasso (PerkLab, Queen's University)");
  return acknowledgement;
}

//-----------------------------------------------------------------------------
QStringList qSlicerGeUsMovieReaderModule::contributors() const
{
  QStringList moduleContributors;
  moduleContributors << QString("Andras Lasso (Queen's)");
  return moduleContributors;
}

//-----------------------------------------------------------------------------
QIcon qSlicerGeUsMovieReaderModule::icon() const
{
  return QIcon(":/Icons/GeUsMovieReader.png");
}

//-----------------------------------------------------------------------------
QStringList qSlicerGeUsMovieReaderModule::categories() const
{
  return QStringList() << "Cardiac";
}

//-----------------------------------------------------------------------------
QStringList qSlicerGeUsMovieReaderModule::dependencies() const
{
  return QStringList() << "Sequences";
}

//-----------------------------------------------------------------------------
void qSlicerGeUsMovieReaderModule::setup()
{
  this->Superclass::setup();
}

//-----------------------------------------------------------------------------
qSlicerAbstractModuleRepresentation* qSlicerGeUsMovieReaderModule
::createWidgetRepresentation()
{
  // this module does not need a graphical user interface
  return NULL;
}

//-----------------------------------------------------------------------------
vtkMRMLAbstractLogic* qSlicerGeUsMovieReaderModule::createLogic()
{
  return vtkSlicerGeUsMovieReaderLogic::New();
}

//-----------------------------------------------------------------------------
bool qSlicerGeUsMovieReaderModule::isHidden() const
{
  // this module does not need a graphical user interface
  return true;
}