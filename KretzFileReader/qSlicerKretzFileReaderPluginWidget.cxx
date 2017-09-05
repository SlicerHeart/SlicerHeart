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

/// KretzFileReader includes
#include "qSlicerKretzFileReaderPluginWidget.h"
#include "ui_qSlicerKretzFileReaderPluginWidget.h"
#include "vtkSlicerKretzFileReaderLogic.h"

//-----------------------------------------------------------------------------
/// \ingroup SlicerRt_QtModules_KretzFileReader
class qSlicerKretzFileReaderPluginWidgetPrivate: public Ui_qSlicerKretzFileReaderPluginWidget
{
public:
  qSlicerKretzFileReaderPluginWidgetPrivate();
};

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderPluginWidgetPrivate::qSlicerKretzFileReaderPluginWidgetPrivate()
{
}

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderPluginWidget::qSlicerKretzFileReaderPluginWidget(QWidget* parentWidget)
  : Superclass( parentWidget )
  , d_ptr( new qSlicerKretzFileReaderPluginWidgetPrivate )
{
}

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderPluginWidget::~qSlicerKretzFileReaderPluginWidget()
{
}

//-----------------------------------------------------------------------------
void qSlicerKretzFileReaderPluginWidget::setup()
{
  Q_D(qSlicerKretzFileReaderPluginWidget);
  d->setupUi(this);
  this->Superclass::setup();
}
