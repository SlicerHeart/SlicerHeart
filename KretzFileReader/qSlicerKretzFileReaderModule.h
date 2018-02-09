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

#ifndef __qSlicerKretzFileReaderModule_h
#define __qSlicerKretzFileReaderModule_h

// SlicerQt includes
#include "qSlicerLoadableModule.h"

// KretzFileReader includes
#include "qSlicerKretzFileReaderModuleExport.h"

class qSlicerKretzFileReaderModulePrivate;

/// \ingroup SlicerRt_QtModules_KretzFileReader
class Q_SLICER_KRETZFILEREADER_EXPORT qSlicerKretzFileReaderModule:
  public qSlicerLoadableModule
{
  Q_OBJECT
#ifdef Slicer_HAVE_QT5
  Q_PLUGIN_METADATA(IID "org.slicer.modules.loadable.qSlicerLoadableModule/1.0");
#endif
  Q_INTERFACES(qSlicerLoadableModule);

public:

  typedef qSlicerLoadableModule Superclass;
  qSlicerKretzFileReaderModule(QObject *parent=0);
  virtual ~qSlicerKretzFileReaderModule();

  virtual QString helpText()const;
  virtual QString acknowledgementText()const;
  virtual QStringList contributors()const;
  virtual QStringList categories()const;
  qSlicerGetTitleMacro(QTMODULE_TITLE);

  // Makes the module hidden
  virtual bool isHidden()const { return true; };

protected:
  /// Initialize the module. Register the volumes reader/writer
  virtual void setup();

  /// Create and return the widget representation associated to this module
  virtual qSlicerAbstractModuleRepresentation* createWidgetRepresentation();

  /// Create and return the logic associated to this module
  virtual vtkMRMLAbstractLogic* createLogic();

protected:
  QScopedPointer<qSlicerKretzFileReaderModulePrivate> d_ptr;

private:
  Q_DECLARE_PRIVATE(qSlicerKretzFileReaderModule);
  Q_DISABLE_COPY(qSlicerKretzFileReaderModule);
};

#endif
