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

#ifndef __qSlicerKretzFileReaderPluginWidget_h
#define __qSlicerKretzFileReaderPluginWidget_h

// SlicerQt includes
#include "qSlicerAbstractModuleWidget.h"

// KretzFileReader includes
#include "qSlicerKretzFileReaderModuleExport.h"

class qSlicerKretzFileReaderPluginWidgetPrivate;

/// \ingroup SlicerRt_QtModules_KretzFileReader
class Q_SLICER_KRETZFILEREADER_EXPORT qSlicerKretzFileReaderPluginWidget :
  public qSlicerAbstractModuleWidget
{
  Q_OBJECT
public:
  typedef qSlicerAbstractModuleWidget Superclass;
  qSlicerKretzFileReaderPluginWidget(QWidget *parent=0);
  virtual ~qSlicerKretzFileReaderPluginWidget();

protected:
  QScopedPointer<qSlicerKretzFileReaderPluginWidgetPrivate> d_ptr;
  virtual void setup();

private:
  Q_DECLARE_PRIVATE(qSlicerKretzFileReaderPluginWidget);
  Q_DISABLE_COPY(qSlicerKretzFileReaderPluginWidget);
};

#endif
