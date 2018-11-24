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
vtkMRMLScalarVolumeNode* vtkSlicerKretzFileReaderLogic::LoadKretzFile(char *filename, char* nodeName /*=NULL*/, bool scanConvert /*=true*/, double outputSpacing[3] /*=NULL*/, unsigned long int fileOffset /*=0*/)
{
  ifstream readFileStream;
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
        const double transducerCenterPosition_Spherical[3] = { 0, double(numj) / 2.0, double(numk) / 2.0 };
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
bool vtkSlicerKretzFileReaderLogic::ReadKretzItemHeader(ifstream &readFileStream, KretzItem& item)
{
  readFileStream.read((char*)(&item.TagGroup), sizeof(item.TagGroup));
  readFileStream.read((char*)(&item.TagElement), sizeof(item.TagElement));
  readFileStream.read((char*)(&item.ItemDataSize), sizeof(item.ItemDataSize));
  return !readFileStream.fail();
}

//----------------------------------------------------------------------------
bool vtkSlicerKretzFileReaderLogic::ReadKretzItemData(ifstream &readFileStream, KretzItem& item, char* buffer /*=NULL*/)
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
bool vtkSlicerKretzFileReaderLogic::SkipKretzItemData(ifstream &readFileStream, KretzItem& item)
{
  readFileStream.ignore(item.ItemDataSize);
  return !readFileStream.fail();
}













/*=========================================================================

  Program: GDCM (Grassroots DICOM). A DICOM library

  Copyright (c) 2006-2011 Mathieu Malaterre
  All rights reserved.
  See Copyright.txt or http://gdcm.sourceforge.net/Copyright.html for details.

     This software is distributed WITHOUT ANY WARRANTY; without even
     the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
     PURPOSE.  See the above copyright notice for more information.

=========================================================================*/
#include "gdcmReader.h"
#include "gdcmDeflateStream.h"
#include "gdcm_zlib.h"

/*
 * This example extract the ZLIB compressed US image from a Philips private tag
 *
 * Everything done in this code is for the sole purpose of writing interoperable
 * software under Sect. 1201 (f) Reverse Engineering exception of the DMCA.
 * If you believe anything in this code violates any law or any of your rights,
 * please contact us (gdcm-developers@lists.sourceforge.net) so that we can
 * find a solution.
 *
 * Everything you do with this code is at your own risk, since decompression
 * algorithm was not written from specification documents.
 *
 * Usage:
 *
 * $ DumpPhilipsECHO private_us.dcm raw_us_img.raw
 * $ gdcmimg --sop-class-uid 1.2.840.10008.5.1.4.1.1.3.1 --size 608,427,88 raw_us_img.raw raw_us_img.dcm
 */

// header:
struct hframe
{
  uint32_t val0; // 800 increment ?
  uint16_t val1[2];
  uint16_t val2[2];
  uint32_t imgsize;

  bool operator==(const hframe &h) const
    {
    return val0 == h.val0 &&
      val1[0] == h.val1[0] &&
      val1[1] == h.val1[1] &&
      val2[0] == h.val2[0] &&
      val2[1] == h.val2[1] &&
      imgsize == h.imgsize;
    }
};

struct hframe32
{
  uint32_t val0; // 800 increment ?
  uint16_t val1[2];
  uint16_t val2[2];
  uint32_t val3;
  uint32_t imgsize;
  uint32_t val5;
  uint32_t val6;
  uint32_t val7;

  bool operator==(const hframe &h) const
  {
    return val0 == h.val0 &&
      val1[0] == h.val1[0] &&
      val1[1] == h.val1[1] &&
      val2[0] == h.val2[0] &&
      val2[1] == h.val2[1] &&
      imgsize == h.imgsize;
  }

};


static bool ProcessDeflate( const char *outfilename, const int nslices, const int buf_size,
  const char *buf, const uint32_t len,
  const char *crcbuf, const size_t crclen )
{
  std::vector< hframe32 > crcheaders;
  crcheaders.reserve( nslices );
    {
    std::istringstream is;
    is.str( std::string( crcbuf, crclen ) );
    hframe32 header;
    for( int r = 0; r < nslices; ++r )
      {
      is.read( (char*)&header, sizeof( header ));
#if 0
      std::cout << header.val0
         << " " << header.val1[0]
         << " " << header.val1[1]
         << " " << header.val2[0]
         << " " << header.val2[1]
         << " " << header.imgsize << std::endl;
#endif
      crcheaders.push_back( header );
      }
    }

  std::istringstream is;
  is.str( std::string( buf, (size_t)len ) );

  uint32_t totalsize;
  is.read( (char*)&totalsize, sizeof( totalsize ));
  //assert( totalsize == len );

  uint32_t nframes;
  is.read( (char*)&nframes, sizeof( nframes ));
  assert( nframes == (uint32_t)nslices );

  std::vector< uint32_t > offsets;
  offsets.reserve( nframes );
  for( uint32_t frame = 0; frame < nframes ; ++frame )
    {
    uint32_t offset;
    is.read( (char*)&offset, sizeof( offset ));
    offsets.push_back( offset );
    }

  uLongf headerSize = 32;

  //const int size[2] = { 608, 427 }; // FIXME: where does it comes from ?
  //const int size[2] = { 960, 1280 }; // FIXME: where does it comes from ?
  std::stringstream ss;
  ss << outfilename;
  ss << '_';
  ss << buf_size;
  //ss << crcheaders[0].imgsize; // FIXME: Assume all header are identical !
  /*ss << size[0];
  ss << '_';
  ss << size[1];*/
  ss << '_';
  ss << nframes;
  ss << ".raw";
  std::ofstream os( ss.str().c_str(), std::ios::binary );

  std::string headerFileName = ss.str() + "h";
  std::ofstream osheader(headerFileName.c_str(), std::ios::binary);

  //assert( buf_size >= size[0] * size[1] );
  std::vector<char> outbuf(buf_size, 0);

  hframe32* header;
  //uint32_t prev = 0;
  //for( unsigned int r = 0; r < nframes; ++r )
  for (unsigned int r = 0; r < 1; ++r)
    {
    //is.read((char*)&header_buffer, sizeof(header_buffer));
    header = (hframe32*)(buf + offsets[r]);
    osheader.write((char*)header, 32);
    //is.read( (char*)&header, sizeof( header ));
    //is.read((char*)&header, sizeof(header)); // 32 byte header

    //assert( header == crcheaders[r] );
    
    //assert( header.val1[0] == 2000 );
    //assert( header.val1[1] == 3 );
    //assert( header.val2[0] == 1 );
    //assert( header.val2[1] == 1280 );

    //assert(header.val1[0] == 9660);
    //assert(header.val1[1] == 65027);
    //assert(header.val2[0] == 43);
    //assert(header.val2[1] == 1280 || header.val2[1] == 1288);

    /*
    assert(header.val1[0] == 0);
    assert(header.val1[1] == 0);
    assert(header.val2[0] == 37082);   
    assert(header.val2[1] == 234);
    */

    uLongf destLen = buf_size; // >= 608,427
    Bytef *dest = (Bytef*)&outbuf[0];
    //assert( is.tellg() == offsets[r] + headerSize );
    const Bytef *source = (Bytef*)buf + offsets[r] + headerSize;
    uLong sourceLen;
    if( r + 1 == nframes )
      sourceLen = (uLong)totalsize - (uLong)offsets[r] - headerSize;
    else
      sourceLen = (uLong)offsets[r+1] - (uLong)offsets[r] - headerSize;
    // FIXME: in-memory decompression:
    int ret = uncompress (dest, &destLen, source, sourceLen);

    ZEXTERN int ZEXPORT uncompress2 OF((Bytef *dest, uLongf *destLen,
      const Bytef *source, uLong *sourceLen));

    assert( ret == Z_OK ); (void)ret;
    //assert( destLen >= (uLongf)size[0] * size[1] ); // 16bytes padding ?
    assert( destLen + headerSize == buf_size );
    //assert( header.imgsize == (uint32_t)size[0] * size[1] );
    //os.write( &outbuf[0], outbuf.size() );
   // os.write( &outbuf[0], size[0] * size[1] );
    //os.write(&outbuf[0], header.imgsize);
    //os.write(&outbuf[0], destLen);
    os.write(&outbuf[0], buf_size);

    // skip data:
    //is.seekg( sourceLen, std::ios::cur );
    }
  os.close();
  osheader.close();
  //assert( is.tellg() == totalsize );

  return true;
}

static bool ProcessNone( const char *outfilename, const int nslices, const
  int buf_size, const char *buf, const int len,
  const char *crcbuf, const size_t crclen )
{
  std::vector< hframe > crcheaders;
  crcheaders.reserve( nslices );
    {
    std::istringstream is;
    is.str( std::string( crcbuf, crclen ) );
    hframe header;
    for( int r = 0; r < nslices; ++r )
      {
      is.read( (char*)&header, sizeof( header ));
#if 0
      std::cout << header.val0
         << " " << header.val1[0]
         << " " << header.val1[1]
         << " " << header.val2[0]
         << " " << header.val2[1]
         << " " << header.imgsize << std::endl;
#endif
      crcheaders.push_back( header );
      }
    }

  std::istringstream is;
  is.str( std::string( buf, (size_t)len ) );

  uint32_t totalsize;
  is.read( (char*)&totalsize, sizeof( totalsize ));
  assert( totalsize == len );

  uint32_t nframes;
  is.read( (char*)&nframes, sizeof( nframes ));
  assert( nframes == (uint32_t)nslices );

  std::vector< uint32_t > offsets;
  offsets.reserve( nframes );
  for( uint32_t frame = 0; frame < nframes ; ++frame )
    {
    uint32_t offset;
    is.read( (char*)&offset, sizeof( offset ));
    offsets.push_back( offset );
    //std::cout << offset << std::endl;
    }

  std::vector<char> outbuf;
  // No idea how to present the data, I'll just append everything, and present it as 2D
  std::stringstream ss;
  ss << outfilename;
  ss << '_';
  ss << crcheaders[0].imgsize; // FIXME: Assume all header are identical !
  ss << '_';
  ss << nframes;
  ss << ".raw";
  std::ofstream os( ss.str().c_str(), std::ios::binary );
  outbuf.resize( buf_size ); // overallocated + 16
  char *buffer = &outbuf[0];

  hframe header;
  for( unsigned int r = 0; r < nframes; ++r )
    {
    is.read( (char*)&header, sizeof( header ));
#if 0
      std::cout << header.val0
         << " " << header.val1[0]
         << " " << header.val1[1]
         << " " << header.val2[0]
         << " " << header.val2[1]
         << " " << header.imgsize << std::endl;
#endif
    //assert( header == crcheaders[r] );

    is.read( buffer, buf_size - 16 );
    //os.write( buffer, header.imgsize );
    os.write(buffer, buf_size - 16);
    }
  //assert( is.tellg() == totalsize );
  os.close();

  return true;
}

#ifndef NDEBUG
static const char * const UDM_USD_DATATYPE_STRINGS[] = {
  "UDM_USD_DATATYPE_DIN_2D_ECHO",
  "UDM_USD_DATATYPE_DIN_2D_ECHO_CONTRAST",
  "UDM_USD_DATATYPE_DIN_DOPPLER_CW",
  "UDM_USD_DATATYPE_DIN_DOPPLER_PW",
  "UDM_USD_DATATYPE_DIN_DOPPLER_PW_TDI",
  "UDM_USD_DATATYPE_DIN_2D_COLOR_FLOW",
  "UDM_USD_DATATYPE_DIN_2D_COLOR_PMI",
  "UDM_USD_DATATYPE_DIN_2D_COLOR_CPA",
  "UDM_USD_DATATYPE_DIN_2D_COLOR_TDI",
  "UDM_USD_DATATYPE_DIN_MMODE_ECHO",
  "UDM_USD_DATATYPE_DIN_MMODE_COLOR",
  "UDM_USD_DATATYPE_DIN_MMODE_COLOR_TDI",
  "UDM_USD_DATATYPE_DIN_PARAM_BLOCK",
  "UDM_USD_DATATYPE_DIN_2D_COLOR_VELOCITY",
  "UDM_USD_DATATYPE_DIN_2D_COLOR_POWER",
  "UDM_USD_DATATYPE_DIN_2D_COLOR_VARIANCE",
  "UDM_USD_DATATYPE_DIN_DOPPLER_AUDIO",
  "UDM_USD_DATATYPE_DIN_DOPPLER_HIGHQ",
  "UDM_USD_DATATYPE_DIN_PHYSIO",
  "UDM_USD_DATATYPE_DIN_2D_COLOR_STRAIN",
  "UDM_USD_DATATYPE_DIN_COMPOSITE_RGB",
  "UDM_USD_DATATYPE_DIN_XFOV_REALTIME_GRAPHICS",
  "UDM_USD_DATATYPE_DIN_XFOV_MOSAIC",
  "UDM_USD_DATATYPE_DIN_COMPOSITE_R",
  "UDM_USD_DATATYPE_DIN_COMPOSITE_G",
  "UDM_USD_DATATYPE_DIN_COMPOSITE_B",
  "UDM_USD_DATATYPE_DIN_MMODE_COLOR_VELOCITY",
  "UDM_USD_DATATYPE_DIN_MMODE_COLOR_POWER",
  "UDM_USD_DATATYPE_DIN_MMODE_COLOR_VARIANCE",
  "UDM_USD_DATATYPE_DIN_2D_ELASTO",
};

static inline bool is_valid( const char * datatype_str )
{
  static const int n = sizeof( UDM_USD_DATATYPE_STRINGS ) / sizeof( *UDM_USD_DATATYPE_STRINGS );
  bool found = false;
  if( datatype_str )
    {
    for( int i = 0; !found && i < n; ++i )
      {
      found = strcmp( datatype_str, UDM_USD_DATATYPE_STRINGS[i] ) == 0;
      }
    }
  return found;
}
#endif

//----------------------------------------------------------------------------
vtkMRMLScalarVolumeNode* vtkSlicerKretzFileReaderLogic::LoadPhilipsFile(char *filename, char* nodeName /*=NULL*/, bool scanConvert /*=true*/, double outputSpacing[3] /*=NULL*/)
{
  using namespace gdcm;
  gdcm::Reader reader;
  reader.SetFileName( filename );
  if( !reader.Read() )
  {
    vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: failed to read from file '" << (filename ? filename : "(null)") << "'");
    return NULL;
  }

  gdcm::File &file = reader.GetFile();
  gdcm::DataSet &ds1 = file.GetDataSet();

  //const PrivateTag tseq1(0x200d,0x3cf8,"Philips US Imaging DD 045");
  const PrivateTag tseq1(0x200d, 0x3cf5, "Philips US Imaging DD 045");
  if( !ds1.FindDataElement( tseq1 ) )
  {
    vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: cannot find 'Philips US Imaging DD 045' data element");
    return NULL;
  }
  const DataElement& seq1 = ds1.GetDataElement( tseq1 );

  SmartPointer<SequenceOfItems> sqi1 = seq1.GetValueAsSQ();
  if (sqi1->GetNumberOfItems() < 1)
  {
    vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element is empty");
    return NULL;
  }

  const size_t nitems = sqi1->GetNumberOfItems();
  for( size_t item = 1; item < nitems; ++item )
    {
    Item &item1 = sqi1->GetItem(item);
    DataSet &ds2 = item1.GetNestedDataSet();

    // (200d,300d)  LO  28  UDM_USD_DATATYPE_DIN_2D_ECHO
    const PrivateTag tdatatype(0x200d,0x300d,"Philips US Imaging DD 033");
    if( !ds2.FindDataElement( tdatatype ) )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 033' data element is not found");
      return NULL;
    }
    const DataElement& datatype = ds2.GetDataElement( tdatatype );
    const ByteValue *bvdatatype = datatype.GetByteValue();
    if( !bvdatatype )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 033' data element is empty");
      return NULL;
    }

    const PrivateTag tseq2(0x200d,0x3cf1,"Philips US Imaging DD 045");
    if( !ds2.FindDataElement( tseq2 ) )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element is not found");
      return NULL;
    }

    const DataElement& seq2 = ds2.GetDataElement( tseq2 );

    SmartPointer<SequenceOfItems> sqi2 = seq2.GetValueAsSQ();
    if ( sqi2->GetNumberOfItems() < 1 )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element is empty");
      return NULL;
    }

    // FIXME: what if not in first Item ?
    assert( sqi2->GetNumberOfItems() == 1 );

    Item &item2 = sqi2->GetItem(1);
    DataSet &ds3 = item2.GetNestedDataSet();

    const PrivateTag tzlib(0x200d,0x3cfa,"Philips US Imaging DD 045");
    if( !ds3.FindDataElement( tzlib ) )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element is empty");
      return NULL;
    }
    const DataElement& zlib = ds3.GetDataElement( tzlib );

    const ByteValue *bv = zlib.GetByteValue();
    if (!bv || bv->GetLength() != 4)
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element is invalid");
      return NULL;
    }

    // (200d,3010)  IS  2  88
    const PrivateTag tnslices(0x200d,0x3010,"Philips US Imaging DD 033");
    if( !ds3.FindDataElement( tnslices ) )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 033' data element is not found");
      return NULL;
    }
    const DataElement& nslices = ds3.GetDataElement( tnslices );
    Element<VR::IS,VM::VM1> elnslices;
    elnslices.SetFromDataElement( nslices );
    const int nslicesref = elnslices.GetValue();
    assert( nslicesref >= 0 );
    // (200d,3011)  IS  6  259648
    const PrivateTag tzalloc(0x200d,0x3011,"Philips US Imaging DD 033");
    if( !ds3.FindDataElement( tzalloc ) )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 033' data element is not found");
      return NULL;
    }
    const DataElement& zalloc = ds3.GetDataElement( tzalloc );
    Element<VR::IS,VM::VM1> elzalloc;
    elzalloc.SetFromDataElement( zalloc );
    const int zallocref = elzalloc.GetValue();
    assert( zallocref >= 0 );
    // (200d,3021)  IS  2  0
    const PrivateTag tzero(0x200d,0x3021,"Philips US Imaging DD 033");
    if( !ds3.FindDataElement( tzero ) )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 033' data element is not found");
      return NULL;
    }
    const DataElement& zero = ds3.GetDataElement( tzero );
    Element<VR::IS,VM::VM1> elzero;
    elzero.SetFromDataElement( zero );
    const int zerocref = elzero.GetValue();
    assert( zerocref == 0 ); (void)zerocref;

    // (200d,3cf3) OB
    const PrivateTag tdeflate(0x200d,0x3cf3,"Philips US Imaging DD 045");
    if( !ds3.FindDataElement( tdeflate) )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element is not found");
      return NULL;
    }
    const DataElement& deflate = ds3.GetDataElement( tdeflate );
    const ByteValue *bv2 = deflate.GetByteValue();

    // (200d,3cfb) OB
    const PrivateTag tcrc(0x200d,0x3cfb,"Philips US Imaging DD 045");
    if( !ds3.FindDataElement( tcrc ) )
    {
      vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element is not found");
      return NULL;
    }
    const DataElement& crc = ds3.GetDataElement( tcrc );
    const ByteValue *bv3 = crc.GetByteValue();

    std::string outfile = std::string( bvdatatype->GetPointer(), bvdatatype->GetLength() );
    outfile = LOComp::Trim( outfile.c_str() );
    outfile = "c:/tmp/"+outfile;
    const char *outfilename = outfile.c_str();
    //assert( is_valid(outfilename) );
    if( bv2 )
      {
      assert( bv3 );
      assert( zallocref > 0 );
      assert( nslicesref > 0 );
      std::cout << ds2 << std::endl;

      if( strncmp(bv->GetPointer(), "ZLib", 4) == 0 )
        {
        if( !ProcessDeflate( outfilename, nslicesref, zallocref, bv2->GetPointer(),
            std::streampos(bv2->GetLength()), bv3->GetPointer(), bv3->GetLength() ) )
          {
            vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element failed to decode");
            return NULL;
          }
        }
      else if( strncmp(bv->GetPointer(), "None", 4) == 0 )
        {
        if( !ProcessNone( outfilename, nslicesref, zallocref, bv2->GetPointer(),
            std::streampos(bv2->GetLength()), bv3->GetPointer(), bv3->GetLength() ) )
          {
            vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element failed to decode");
            return NULL;
          }
        }
      else
        {
        std::string str( bv->GetPointer(), bv->GetLength() );
        vtkErrorMacro("vtkSlicerKretzFileReaderLogic::LoadKretzFile failed: 'Philips US Imaging DD 045' data element failed to decode from string "<<str);
        return NULL;
        }
      }
    }

  return 0;
}