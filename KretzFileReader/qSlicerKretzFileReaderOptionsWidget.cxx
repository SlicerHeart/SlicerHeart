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

/// Qt includes
#include <QFileInfo>

// CTK includes
#include <ctkFlowLayout.h>
#include <ctkUtils.h>

/// KretzFileReader includes
#include "qSlicerIOOptions_p.h"
#include "qSlicerKretzFileReaderOptionsWidget.h"
#include "ui_qSlicerKretzFileReaderOptionsWidget.h"

//-----------------------------------------------------------------------------
/// \ingroup SlicerRt_QtModules_KretzFileReader
class qSlicerKretzFileReaderOptionsWidgetPrivate
  : public qSlicerIOOptionsPrivate
  , public Ui_qSlicerKretzFileReaderOptionsWidget
{
public:
};

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderOptionsWidget::qSlicerKretzFileReaderOptionsWidget(QWidget* parentWidget)
  : qSlicerIOOptionsWidget(new qSlicerKretzFileReaderOptionsWidgetPrivate, parentWidget)
{
  Q_D(qSlicerKretzFileReaderOptionsWidget);
  d->setupUi(this);

  ctkFlowLayout::replaceLayout(this);

  connect(d->ScanConvertCheckBox, SIGNAL(toggled(bool)),
          this, SLOT(updateProperties()));
  connect(d->OutputSpacingSpinBox, SIGNAL(valueChanged(double)),
          this, SLOT(updateProperties()));

  // Image intensity scale and offset turned off by default
  d->ScanConvertCheckBox->setChecked(true);
  d->OutputSpacingSpinBox->setValue(0.5);
}

//-----------------------------------------------------------------------------
qSlicerKretzFileReaderOptionsWidget::~qSlicerKretzFileReaderOptionsWidget()
{
}

//-----------------------------------------------------------------------------
void qSlicerKretzFileReaderOptionsWidget::updateProperties()
{
  Q_D(qSlicerKretzFileReaderOptionsWidget);

  d->Properties["scanConvert"] = d->ScanConvertCheckBox->isChecked();
  d->Properties["outputSpacing"] = d->OutputSpacingSpinBox->value();
}
