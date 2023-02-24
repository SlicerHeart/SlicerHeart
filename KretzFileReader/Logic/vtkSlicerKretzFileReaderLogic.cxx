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

// KretzFileReader includes
#include "vtkSlicerKretzFileReaderLogic.h"

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

//----------------------------------------------------------------------------
vtkStandardNewMacro(vtkSlicerKretzFileReaderLogic);

class KretzItem
{
public:
  KretzItem(vtkTypeUInt16 group=0, vtkTypeUInt16 element=0)
    : TagGroup(group)
    , TagElement(element)
    , ItemDataSize(0)
  {
  }

  bool operator==(const KretzItem& other)
  {
    return (this->TagGroup == other.TagGroup && this->TagElement == other.TagElement);
  }

  template <class T>
  T GetData(T defaultValue, unsigned int index = 0)
  {
    if (index*sizeof(T) + sizeof(T) > this->ItemData.size())
    {
      // index out of range
      return defaultValue;
    }
    return *((T*)(&this->ItemData[0])+index);
  }

  vtkTypeUInt16 TagGroup;
  vtkTypeUInt16 TagElement;
  vtkTypeUInt32 ItemDataSize;
  std::vector<unsigned char> ItemData;
};

//----------------------------------------------------------------------------
vtkSlicerKretzFileReaderLogic::vtkSlicerKretzFileReaderLogic()
{
}

//----------------------------------------------------------------------------
vtkSlicerKretzFileReaderLogic::~vtkSlicerKretzFileReaderLogic()
{
}

//----------------------------------------------------------------------------
void vtkSlicerKretzFileReaderLogic::PrintSelf(ostream& os, vtkIndent indent)
{
  this->Superclass::PrintSelf(os, indent);
}

void writeTestOutput(const char* filename, vtkStructuredGrid* dataset)
{
  vtkNew<vtkStructuredGridWriter> writer;
  writer->SetFileName(filename);
  writer->SetInputData(dataset);
  writer->Write();
}

//----------------------------------------------------------------------------
vtkMRMLScalarVolumeNode* vtkSlicerKretzFileReaderLogic::LoadKretzFile(const char *filename, const char* nodeName /*=NULL*/, bool scanConvert /*=true*/, double outputSpacing[3] /*=NULL*/, unsigned long int fileOffset /*=0*/)
{
  std::ifstream readFileStream;
  readFileStream.open(filename, std::ios::binary);
  
  // Useful when the ultrasound file is embedded into a DICOM file
  readFileStream.seekg(fileOffset);

  if (readFileStream.fail())
  {
    vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: failed to open file '" << (filename ? filename : "(null)") << "'");
    return NULL;
  }

  std::string expectedHeader = "KRETZFILE 1.0   ";
  std::string actualheader(expectedHeader.size(), ' ');
  readFileStream.read((char*)(&actualheader[0]), expectedHeader.size());
  if (expectedHeader != actualheader)
  {
    vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: file '" << (filename ? filename : "(null)")
      << "' expected to start with '" << expectedHeader << "'");
    return NULL;
  }

  vtkMRMLScalarVolumeNode* loadedVolumeNode = NULL;
  int volumeDimensions_Spherical[3] = { 0 };

  std::vector<double> thetaAnglesRad;
  std::vector<double> phiAnglesRad;
  double offset1 = 0.0;
  double offset2 = 0.0;
  double resolution = 1.0;
  bool foundVoxelData = false;
  double cartesianSpacing = 1.0;

  while (!readFileStream.eof() && !readFileStream.fail())
  {
    KretzItem item;
    if (!this->ReadKretzItemHeader(readFileStream, item))
    {
      break;
    }
    if (item == KretzItem(0xC000, 0x0001))
    {
      // Dimension I
      this->ReadKretzItemData(readFileStream, item);
      volumeDimensions_Spherical[0] = item.GetData<vtkTypeUInt16>(0);
    }
    else if (item == KretzItem(0xC000, 0x0002))
    {
      // Dimension J
      this->ReadKretzItemData(readFileStream, item);
      volumeDimensions_Spherical[1] = item.GetData<vtkTypeUInt16>(0);
    }
    else if (item == KretzItem(0xC000, 0x0003))
    {
      // Dimension K
      this->ReadKretzItemData(readFileStream, item);
      volumeDimensions_Spherical[2] = item.GetData<vtkTypeUInt16>(0);
    }
    else if (item == KretzItem(0xC100, 0x0001))
    {
      // Radial resolution
      this->ReadKretzItemData(readFileStream, item);
      resolution = item.GetData<double>(0) * 1000.0;
    }
    else if (item == KretzItem(0xC300, 0x0002))
    {
      // Theta angles
      thetaAnglesRad.resize(int(item.ItemDataSize / sizeof(double)));
      if (!this->ReadKretzItemData(readFileStream, item, (char*)(&thetaAnglesRad[0])))
      {
        vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: file '" << (filename ? filename : "(null)")
          << "' invalid theta angles");
        return NULL;
      }
    }
    else if (item == KretzItem(0xC200, 0x0001))
    {
      this->ReadKretzItemData(readFileStream, item);
      offset1 = item.GetData<vtkTypeFloat64>(0);
    }
    else if (item == KretzItem(0xC200, 0x0002))
    {
      this->ReadKretzItemData(readFileStream, item);
      offset2 = item.GetData<vtkTypeFloat64>(0);
    }
    else if (item == KretzItem(0xC300, 0x0001))
    {
      // Phi angles
      phiAnglesRad.resize(int(item.ItemDataSize / sizeof(double)));
      if (!this->ReadKretzItemData(readFileStream, item, (char*)(&phiAnglesRad[0])))
      {
        vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: file '" << (filename ? filename : "(null)")
          << "' invalid phi angles");
        return NULL;
      }
    }
    else if (item == KretzItem(0x0010, 0x0022))
    {
      // Spacing when reading a Cartesian volume.
      // It is not confirmed that this spacing value can be used, but seems to work.
      // Probably other spacing values should be read, too.
      this->ReadKretzItemData(readFileStream, item);
      cartesianSpacing = item.GetData<double>(0);
    }
    else if (item == KretzItem(0xD000, 0x0001))
    {  
      // Voxel data
      foundVoxelData = true;
      vtkNew<vtkMRMLScalarVolumeNode> volumeNode;

      if (scanConvert)
      {
        if (phiAnglesRad.size() == 0 || thetaAnglesRad.size() == 0)
        {
          // It is a Cartesian volume, no need for scan conversion
          scanConvert = false;
        }
      }

      if (scanConvert)
      {
        // Create a grid
        vtkNew<vtkStructuredGrid> structuredGrid;
        vtkNew<vtkPoints> points_Cartesian;

        const unsigned int numi = volumeDimensions_Spherical[0];
        const unsigned int numj = volumeDimensions_Spherical[1];
        const unsigned int numk = volumeDimensions_Spherical[2];

        const unsigned long numberOfPoints = numi * numj * numk;

        if (phiAnglesRad.size() != numk)
        {
          vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: file '" << (filename ? filename : "(null)")
            << "' phi angle array is invalid (expected " << numk << " elements, found " << phiAnglesRad.size());
          return NULL;
        }

        if (thetaAnglesRad.size() != numj)
        {
          vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: file '" << (filename ? filename : "(null)")
            << "' theta angle array is invalid (expected " << numj << " elements, found " << thetaAnglesRad.size());
          return NULL;
        }

        double radialSpacingMm = resolution;
        double radialSpacingStartMm = offset1*resolution;
        double bModeRadius = -offset2*resolution;

        points_Cartesian->Allocate(numberOfPoints);
        double phiAnglesRadCentre = vtkMath::Pi() / 2.0;
        double thetaAnglesRadCentre = vtkMath::Pi() / 2.0;
        for (unsigned int k_Spherical = 0; k_Spherical < numk; k_Spherical++)
        {
          double phi = phiAnglesRad[k_Spherical] - phiAnglesRadCentre;
          for (unsigned int j_Spherical = 0; j_Spherical < numj; j_Spherical++)
          {
            double theta = thetaAnglesRad[j_Spherical] - thetaAnglesRadCentre;
            for (unsigned int i_Spherical = 0; i_Spherical < numi; i_Spherical++)
            {
              double r = radialSpacingStartMm + i_Spherical * radialSpacingMm;
              points_Cartesian->InsertNextPoint(
                r * sin(theta),
                -(r * cos(theta) - bModeRadius) * sin(phi),
                bModeRadius*(1-cos(phi))+r*cos(theta)*cos(phi));
            }
          }
        }

        structuredGrid->SetPoints(points_Cartesian.GetPointer());
        structuredGrid->SetExtent(0, volumeDimensions_Spherical[0] - 1,
          0, volumeDimensions_Spherical[1] - 1,
          0, volumeDimensions_Spherical[2] - 1);
        vtkPointData* pointData = structuredGrid->GetPointData();
        vtkNew<vtkUnsignedCharArray> voxelValues;
        voxelValues->SetNumberOfValues(numberOfPoints);
        if (!this->ReadKretzItemData(readFileStream, item, (char*)voxelValues->GetPointer(0)))
        {
          vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: file '" << (filename ? filename : "(null)")
            << "' failed to read voxel data");
          return NULL;
        }
        voxelValues->SetName("VoxelIntensity");
        pointData->AddArray(voxelValues.GetPointer());
        structuredGrid->GetPointData()->SetActiveAttribute("VoxelIntensity", vtkDataSetAttributes::SCALARS);

        // Writing of unstructured grid can be enabled for testing by uncommenting the following line
        //writeTestOutput("C:\\tmp\\us.vtk", structuredGrid.GetPointer());

        double* bounds_Cartesian = structuredGrid->GetBounds();

        double volumeSpacing_Cartesian[3] = { 1.0, 1.0, 1.0 };
        if (outputSpacing)
        {
          for (int i = 0; i < 3; i++)
          {
            if (outputSpacing[i] > 0)
            {
              volumeSpacing_Cartesian[i] = outputSpacing[i];
            }
          }
        }

        int volumeDimensions_Spherical[3] =
        {
          int(ceil((bounds_Cartesian[1] - bounds_Cartesian[0]) / volumeSpacing_Cartesian[0])),
          int(ceil((bounds_Cartesian[3] - bounds_Cartesian[2]) / volumeSpacing_Cartesian[1])),
          int(ceil((bounds_Cartesian[5] - bounds_Cartesian[4]) / volumeSpacing_Cartesian[2]))
        };

        vtkNew<vtkResampleToImage> imageResampler;
        imageResampler->SetInputDataObject(structuredGrid.GetPointer());
        imageResampler->SetSamplingDimensions(volumeDimensions_Spherical);
        imageResampler->Update();
        vtkImageData* volume_Cartesian = imageResampler->GetOutput();

        if (volume_Cartesian
          && volume_Cartesian->GetPointData()
          && volume_Cartesian->GetPointData()->GetArray("vtkValidPointMask"))
        {
          // vtkValidPointMask would trigger error messages, which would slow down slice browsing
          volume_Cartesian->GetPointData()->RemoveArray("vtkValidPointMask");
        }

        // Set image data in volume node
        volumeNode->SetSpacing(volume_Cartesian->GetSpacing());
        volumeNode->SetOrigin(volume_Cartesian->GetOrigin());
        volumeNode->SetIToRASDirection( 1.0, 0.0, 0.0);
        volumeNode->SetJToRASDirection( 0.0, 1.0, 0.0);
        volumeNode->SetKToRASDirection( 0.0, 0.0, 1.0);
        volume_Cartesian->SetSpacing(1.0, 1.0, 1.0);
        volume_Cartesian->SetOrigin(0.0, 0.0, 0.0);

        volumeNode->SetAndObserveImageData(volume_Cartesian);
      }
      else
      {
        vtkNew<vtkImageData> volume_Spherical;
        volume_Spherical->SetExtent(0, volumeDimensions_Spherical[0] - 1,
          0, volumeDimensions_Spherical[1] - 1,
          0, volumeDimensions_Spherical[2] - 1);
        volume_Spherical->AllocateScalars(VTK_UNSIGNED_CHAR, 1);
        if (!this->ReadKretzItemData(readFileStream, item, (char*)volume_Spherical->GetScalarPointer()))
        {
          vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: file '" << (filename ? filename : "(null)")
            << "' failed to read voxel data");
          return NULL;
        }

        volumeNode->SetSpacing(cartesianSpacing, cartesianSpacing, cartesianSpacing);
        volumeNode->SetAndObserveImageData(volume_Spherical.GetPointer());
      }

      if (nodeName)
      {
        volumeNode->SetName(nodeName);
      }
      this->GetMRMLScene()->AddNode(volumeNode.GetPointer());

      volumeNode->CreateDefaultDisplayNodes();
      vtkMRMLScalarVolumeDisplayNode* displayNode = vtkMRMLScalarVolumeDisplayNode::SafeDownCast(volumeNode->GetDisplayNode());
      if (displayNode)
      {
        displayNode->SetAutoWindowLevel(false);
        // Minimum = 15 to make dark noisy areas appear as clear black
        // Maximum = 150 (instead of maximum range of 255) to increase the image contrast, without very noticeable saturation
        displayNode->SetWindowLevelMinMax(15.0, 150.0);
      }
      loadedVolumeNode = volumeNode.GetPointer();
    }
    else
    {
      this->SkipKretzItemData(readFileStream, item);
    }
  }

  readFileStream.close();

  if (!foundVoxelData)
  {
    vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: file '" << (filename ? filename : "(null)")
      << "' voxel data not found. Make sure the file contains uncompressed voxel data.");
  }

  return loadedVolumeNode;
}

//----------------------------------------------------------------------------
bool vtkSlicerKretzFileReaderLogic::ReadKretzItemHeader(std::ifstream &readFileStream, KretzItem& item)
{
  readFileStream.read((char*)(&item.TagGroup), sizeof(item.TagGroup));
  readFileStream.read((char*)(&item.TagElement), sizeof(item.TagElement));
  readFileStream.read((char*)(&item.ItemDataSize), sizeof(item.ItemDataSize));
  return !readFileStream.fail();
}

//----------------------------------------------------------------------------
bool vtkSlicerKretzFileReaderLogic::ReadKretzItemData(std::ifstream &readFileStream, KretzItem& item, char* buffer /*=NULL*/)
{
  if (buffer == NULL)
  {
    item.ItemData.resize(item.ItemDataSize, 0);
    buffer = (char*)(&item.ItemData[0]);
  }
  readFileStream.read(buffer, item.ItemDataSize);
  return !readFileStream.fail();
}

//----------------------------------------------------------------------------
bool vtkSlicerKretzFileReaderLogic::SkipKretzItemData(std::ifstream &readFileStream, KretzItem& item)
{
  readFileStream.ignore(item.ItemDataSize);
  return !readFileStream.fail();
}
