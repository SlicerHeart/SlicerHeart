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

#ifndef __vtkSlicerKretzFileReaderLogic_h
#define __vtkSlicerKretzFileReaderLogic_h

// Slicer includes
#include "vtkSlicerModuleLogic.h"

// STD includes
#include <vector>

// KretzFileReader includes
#include "vtkSlicerKretzFileReaderLogicExport.h"

class vtkMRMLScalarVolumeNode;
class vtkMRMLScalarVolumeDisplayNode;
class vtkMRMLVolumeHeaderlessStorageNode;
class vtkStringArray;

class KretzItem;

/// \ingroup SlicerRt_QtModules_KretzFileReader
class VTK_SLICER_KRETZFILEREADER_LOGIC_EXPORT vtkSlicerKretzFileReaderLogic :
  public vtkSlicerModuleLogic
{
public:
  static vtkSlicerKretzFileReaderLogic *New();
  vtkTypeMacro(vtkSlicerKretzFileReaderLogic, vtkSlicerModuleLogic);
  void PrintSelf(ostream& os, vtkIndent indent);

  /// Load KRETZ volume from file
  /// \param filename Path and filename of the KRETZ file
  /// \param scanConvert Boolean flag which is set to true by default, to convert the volume to a Cartesian coordinate system
  vtkMRMLScalarVolumeNode* LoadKretzFile(char* filename, char* nodeName = NULL, bool scanConvert = true, double outputSpacing[3] = NULL, unsigned long int fileOffset=0);

protected:

  bool ReadKretzItemHeader(ifstream &readFileStream, KretzItem& item);
  bool ReadKretzItemData(ifstream &readFileStream, KretzItem& item, char* buffer = NULL);
  bool SkipKretzItemData(ifstream &readFileStream, KretzItem& item);

protected:
  vtkSlicerKretzFileReaderLogic();
  virtual ~vtkSlicerKretzFileReaderLogic();

private:
  vtkSlicerKretzFileReaderLogic(const vtkSlicerKretzFileReaderLogic&); // Not implemented
  void operator=(const vtkSlicerKretzFileReaderLogic&);               // Not implemented
};

#endif
