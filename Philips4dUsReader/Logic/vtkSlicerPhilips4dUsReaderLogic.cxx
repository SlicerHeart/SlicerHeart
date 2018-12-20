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

// Philips4dUsReader includes
#include "vtkSlicerPhilips4dUsReaderLogic.h"

// VTK includes
#include <vtkDoubleArray.h>
#include <vtkImageData.h>
#include <vtkImageShiftScale.h>
#include <vtkMatrix4x4.h>
#include <vtkNew.h>
#include <vtkObjectFactory.h>
#include <vtkPointData.h>
#include <vtkResampleToImage.h>
#include <vtkStructuredGrid.h>
#include <vtkStructuredGridWriter.h>
#include <vtkUnsignedCharArray.h>

// MRML includes
#include <vtkMRMLScalarVolumeNode.h>
#include <vtkMRMLScalarVolumeDisplayNode.h>
#include <vtkMRMLScene.h>
#include <vtkMRMLSelectionNode.h>

// Slicer logic includes
#include <vtkSlicerApplicationLogic.h>

// STD includes
#include <vector>
#include <iostream>
#include <fstream>
#include <string>
#include <algorithm>
#include <cctype>
#include <functional>

#include <ctype.h> // For isspace

// GDCM includes
#include "gdcmReader.h"
#include "gdcmDeflateStream.h"
#include "gdcm_zlib.h"


//----------------------------------------------------------------------------
vtkStandardNewMacro(vtkSlicerPhilips4dUsReaderLogic);




//----------------------------------------------------------------------------
vtkSlicerPhilips4dUsReaderLogic::vtkSlicerPhilips4dUsReaderLogic()
{
}

//----------------------------------------------------------------------------
vtkSlicerPhilips4dUsReaderLogic::~vtkSlicerPhilips4dUsReaderLogic()
{
}

//----------------------------------------------------------------------------
void vtkSlicerPhilips4dUsReaderLogic::PrintSelf(ostream& os, vtkIndent indent)
{
  this->Superclass::PrintSelf(os, indent);
}

