/*==========================================================================

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

==========================================================================*/

#ifndef __vtkSlicerPhilips4dUsReaderLogic_h
#define __vtkSlicerPhilips4dUsReaderLogic_h

// Slicer includes
#include "vtkSlicerModuleLogic.h"

// STD includes
#include <vector>

// Philips4dUsReader includes
#include "vtkSlicerPhilips4dUsReaderLogicExport.h"

class vtkMRMLScalarVolumeNode;
class vtkMRMLScalarVolumeDisplayNode;
class vtkMRMLVolumeHeaderlessStorageNode;
class vtkStringArray;

class KretzItem;

/// \ingroup SlicerRt_QtModules_Philips4dUsReader
///
/// This class was developed by reading example image files and determine meaning
/// of DICOM fields by trial and error. As always, it is not guaranteed that the
/// algorithm works correctly.
///
class VTK_SLICER_PHILIPS4DUSREADER_LOGIC_EXPORT vtkSlicerPhilips4dUsReaderLogic :
  public vtkSlicerModuleLogic
{
public:
  static vtkSlicerPhilips4dUsReaderLogic *New();
  vtkTypeMacro(vtkSlicerPhilips4dUsReaderLogic, vtkSlicerModuleLogic);
  void PrintSelf(ostream& os, vtkIndent indent);

protected:
  vtkSlicerPhilips4dUsReaderLogic();
  virtual ~vtkSlicerPhilips4dUsReaderLogic();

private:
  vtkSlicerPhilips4dUsReaderLogic(const vtkSlicerPhilips4dUsReaderLogic&); // Not implemented
  void operator=(const vtkSlicerPhilips4dUsReaderLogic&);               // Not implemented
};

#endif
