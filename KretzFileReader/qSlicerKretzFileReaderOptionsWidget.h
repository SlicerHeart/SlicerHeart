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

#ifndef __qSlicerKretzFileReaderOptionsWidget_h
#define __qSlicerKretzFileReaderOptionsWidget_h

// CTK includes
#include <ctkPimpl.h>

// SlicerQt includes
#include "qSlicerIOOptionsWidget.h"

// KretzFileReader includes
#include "qSlicerKretzFileReaderModuleExport.h"

class qSlicerKretzFileReaderOptionsWidgetPrivate;

/// \ingroup SlicerRt_QtModules_KretzFileReader
class Q_SLICER_KRETZFILEREADER_EXPORT qSlicerKretzFileReaderOptionsWidget :
  public qSlicerIOOptionsWidget
{
  Q_OBJECT
public:
  typedef qSlicerIOOptionsWidget Superclass;
  qSlicerKretzFileReaderOptionsWidget(QWidget *parent=0);
  virtual ~qSlicerKretzFileReaderOptionsWidget();


protected slots:
  void updateProperties();

private:
  Q_DECLARE_PRIVATE_D(qGetPtrHelper(qSlicerIOOptions::d_ptr), qSlicerKretzFileReaderOptionsWidget);
  //Q_DECLARE_PRIVATE(qSlicerKretzFileReaderOptionsWidget);
  Q_DISABLE_COPY(qSlicerKretzFileReaderOptionsWidget);
};

#endif
