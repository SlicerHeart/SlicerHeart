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

#ifndef __qSlicerKretzFileReaderPlugin
#define __qSlicerKretzFileReaderPlugin

// SlicerQt includes
#include "qSlicerFileReader.h"

class qSlicerKretzFileReaderPluginPrivate;
class vtkSlicerKretzFileReaderLogic;

//-----------------------------------------------------------------------------
/// \ingroup SlicerRt_QtModules_KretzFileReader
class qSlicerKretzFileReaderPlugin
  : public qSlicerFileReader
{
  Q_OBJECT

public:
  typedef qSlicerFileReader Superclass;
  qSlicerKretzFileReaderPlugin(QObject* parent = 0);
  qSlicerKretzFileReaderPlugin(vtkSlicerKretzFileReaderLogic* logic, QObject* parent = 0);
  virtual ~qSlicerKretzFileReaderPlugin();

  vtkSlicerKretzFileReaderLogic* logic()const;
  void setLogic(vtkSlicerKretzFileReaderLogic* logic);

  virtual QString description()const;
  virtual IOFileType fileType()const;
  virtual QStringList extensions()const;
  virtual qSlicerIOOptions* options()const;
  virtual bool load(const IOProperties& properties);

protected:
  QScopedPointer<qSlicerKretzFileReaderPluginPrivate> d_ptr;

private:
  Q_DECLARE_PRIVATE(qSlicerKretzFileReaderPlugin);
  Q_DISABLE_COPY(qSlicerKretzFileReaderPlugin);
};

#endif
