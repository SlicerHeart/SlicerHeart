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


// header:
struct hframe
{
  uint32_t val0; // 800 increment ? //0
  uint16_t val1[2];  // 4
  uint16_t val2[2];  // 8
  uint32_t imgsize;  // 12

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


static bool ProcessDeflate(const char *outfilename, const int nslices, const int buf_size,
  const char *buf, const uint32_t len,
  const char *crcbuf, const size_t crclen)
{
  std::vector< hframe32 > crcheaders;
  crcheaders.reserve(nslices);
  {
    std::istringstream is;
    is.str(std::string(crcbuf, crclen));
    hframe32 header;
    for (int r = 0; r < nslices; ++r)
    {
      is.read((char*)&header, sizeof(header));
#if 0
      std::cout << header.val0
        << " " << header.val1[0]
        << " " << header.val1[1]
        << " " << header.val2[0]
        << " " << header.val2[1]
        << " " << header.imgsize << std::endl;
#endif
      crcheaders.push_back(header);
    }
  }

  std::istringstream is;
  is.str(std::string(buf, (size_t)len));

  uint32_t totalsize;
  is.read((char*)&totalsize, sizeof(totalsize));
  //assert( totalsize == len );

  uint32_t nframes;
  is.read((char*)&nframes, sizeof(nframes));
  assert(nframes == (uint32_t)nslices);

  std::vector< uint32_t > offsets;
  offsets.reserve(nframes);
  for (uint32_t frame = 0; frame < nframes; ++frame)
  {
    uint32_t offset;
    is.read((char*)&offset, sizeof(offset));
    offsets.push_back(offset);
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
  std::ofstream os(ss.str().c_str(), std::ios::binary);

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
    if (r + 1 == nframes)
      sourceLen = (uLong)totalsize - (uLong)offsets[r] - headerSize;
    else
      sourceLen = (uLong)offsets[r + 1] - (uLong)offsets[r] - headerSize;
    // FIXME: in-memory decompression:
    int ret = uncompress(dest, &destLen, source, sourceLen);

    ZEXTERN int ZEXPORT uncompress2 OF((Bytef *dest, uLongf *destLen,
      const Bytef *source, uLong *sourceLen));

    assert(ret == Z_OK); (void)ret;
    //assert( destLen >= (uLongf)size[0] * size[1] ); // 16bytes padding ?
    assert(destLen + headerSize == buf_size);
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

static bool ProcessNone(const char *outfilename, const int nslices, const
  int buf_size, const char *buf, const int len,
  const char *crcbuf, const size_t crclen)
{
  std::vector< hframe > crcheaders;
  crcheaders.reserve(nslices);
  {
    std::istringstream is;
    is.str(std::string(crcbuf, crclen));
    hframe header;
    for (int r = 0; r < nslices; ++r)
    {
      is.read((char*)&header, sizeof(header));
#if 0
      std::cout << header.val0
        << " " << header.val1[0]
        << " " << header.val1[1]
        << " " << header.val2[0]
        << " " << header.val2[1]
        << " " << header.imgsize << std::endl;
#endif
      crcheaders.push_back(header);
    }
  }

  std::istringstream is;
  is.str(std::string(buf, (size_t)len));

  uint32_t totalsize;
  is.read((char*)&totalsize, sizeof(totalsize));
  assert(totalsize == len);

  uint32_t nframes;
  is.read((char*)&nframes, sizeof(nframes));
  assert(nframes == (uint32_t)nslices);

  std::vector< uint32_t > offsets;
  offsets.reserve(nframes);
  for (uint32_t frame = 0; frame < nframes; ++frame)
  {
    uint32_t offset;
    is.read((char*)&offset, sizeof(offset));
    offsets.push_back(offset);
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
  std::ofstream os(ss.str().c_str(), std::ios::binary);
  outbuf.resize(buf_size); // overallocated + 16
  char *buffer = &outbuf[0];

  hframe header;
  for (unsigned int r = 0; r < nframes; ++r)
  {
    is.read((char*)&header, sizeof(header));
#if 0
    std::cout << header.val0
      << " " << header.val1[0]
      << " " << header.val1[1]
      << " " << header.val2[0]
      << " " << header.val2[1]
      << " " << header.imgsize << std::endl;
#endif
    //assert( header == crcheaders[r] );

    is.read(buffer, buf_size - 16);
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

static inline bool is_valid(const char * datatype_str)
{
  static const int n = sizeof(UDM_USD_DATATYPE_STRINGS) / sizeof(*UDM_USD_DATATYPE_STRINGS);
  bool found = false;
  if (datatype_str)
  {
    for (int i = 0; !found && i < n; ++i)
    {
      found = strcmp(datatype_str, UDM_USD_DATATYPE_STRINGS[i]) == 0;
    }
  }
  return found;
}
#endif

//----------------------------------------------------------------------------
vtkMRMLScalarVolumeNode* vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile(char *filename, char* nodeName /*=NULL*/, bool scanConvert /*=true*/, double outputSpacing[3] /*=NULL*/)
{
  using namespace gdcm;
  gdcm::Reader reader;
  reader.SetFileName(filename);
  if (!reader.Read())
  {
    vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: failed to read from file '" << (filename ? filename : "(null)") << "'");
    return NULL;
  }

  gdcm::File &file = reader.GetFile();
  gdcm::DataSet &ds1 = file.GetDataSet();

  //const PrivateTag tseq1(0x200d,0x3cf8,"Philips US Imaging DD 045");
  const PrivateTag tseq1(0x200d, 0x3cf5, "Philips US Imaging DD 045");
  if (!ds1.FindDataElement(tseq1))
  {
    vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: cannot find 'Philips US Imaging DD 045' data element");
    return NULL;
  }
  const DataElement& seq1 = ds1.GetDataElement(tseq1);

  SmartPointer<SequenceOfItems> sqi1 = seq1.GetValueAsSQ();
  if (sqi1->GetNumberOfItems() < 1)
  {
    vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element is empty");
    return NULL;
  }

  const size_t nitems = sqi1->GetNumberOfItems();
  for (size_t item = 1; item < nitems; ++item)
  {
    Item &item1 = sqi1->GetItem(item);
    DataSet &ds2 = item1.GetNestedDataSet();

    // (200d,300d)  LO  28  UDM_USD_DATATYPE_DIN_2D_ECHO
    const PrivateTag tdatatype(0x200d, 0x300d, "Philips US Imaging DD 033");
    if (!ds2.FindDataElement(tdatatype))
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 033' data element is not found");
      return NULL;
    }
    const DataElement& datatype = ds2.GetDataElement(tdatatype);
    const ByteValue *bvdatatype = datatype.GetByteValue();
    if (!bvdatatype)
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 033' data element is empty");
      return NULL;
    }

    const PrivateTag tseq2(0x200d, 0x3cf1, "Philips US Imaging DD 045");
    if (!ds2.FindDataElement(tseq2))
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element is not found");
      return NULL;
    }

    const DataElement& seq2 = ds2.GetDataElement(tseq2);

    SmartPointer<SequenceOfItems> sqi2 = seq2.GetValueAsSQ();
    if (sqi2->GetNumberOfItems() < 1)
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element is empty");
      return NULL;
    }

    // FIXME: what if not in first Item ?
    assert(sqi2->GetNumberOfItems() == 1);

    Item &item2 = sqi2->GetItem(1);
    DataSet &ds3 = item2.GetNestedDataSet();

    const PrivateTag tzlib(0x200d, 0x3cfa, "Philips US Imaging DD 045");
    if (!ds3.FindDataElement(tzlib))
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element is empty");
      return NULL;
    }
    const DataElement& zlib = ds3.GetDataElement(tzlib);

    const ByteValue *bv = zlib.GetByteValue();
    if (!bv || bv->GetLength() != 4)
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element is invalid");
      return NULL;
    }

    // (200d,3010)  IS  2  88
    const PrivateTag tnslices(0x200d, 0x3010, "Philips US Imaging DD 033");
    if (!ds3.FindDataElement(tnslices))
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 033' data element is not found");
      return NULL;
    }
    const DataElement& nslices = ds3.GetDataElement(tnslices);
    Element<VR::IS, VM::VM1> elnslices;
    elnslices.SetFromDataElement(nslices);
    const int nslicesref = elnslices.GetValue();
    assert(nslicesref >= 0);
    // (200d,3011)  IS  6  259648
    const PrivateTag tzalloc(0x200d, 0x3011, "Philips US Imaging DD 033");
    if (!ds3.FindDataElement(tzalloc))
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 033' data element is not found");
      return NULL;
    }
    const DataElement& zalloc = ds3.GetDataElement(tzalloc);
    Element<VR::IS, VM::VM1> elzalloc;
    elzalloc.SetFromDataElement(zalloc);
    const int zallocref = elzalloc.GetValue();
    assert(zallocref >= 0);
    // (200d,3021)  IS  2  0
    const PrivateTag tzero(0x200d, 0x3021, "Philips US Imaging DD 033");
    if (!ds3.FindDataElement(tzero))
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 033' data element is not found");
      return NULL;
    }
    const DataElement& zero = ds3.GetDataElement(tzero);
    Element<VR::IS, VM::VM1> elzero;
    elzero.SetFromDataElement(zero);
    const int zerocref = elzero.GetValue();
    assert(zerocref == 0); (void)zerocref;

    // (200d,3cf3) OB
    const PrivateTag tdeflate(0x200d, 0x3cf3, "Philips US Imaging DD 045");
    if (!ds3.FindDataElement(tdeflate))
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element is not found");
      return NULL;
    }
    const DataElement& deflate = ds3.GetDataElement(tdeflate);
    const ByteValue *bv2 = deflate.GetByteValue();

    // (200d,3cfb) OB
    const PrivateTag tcrc(0x200d, 0x3cfb, "Philips US Imaging DD 045");
    if (!ds3.FindDataElement(tcrc))
    {
      vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element is not found");
      return NULL;
    }
    const DataElement& crc = ds3.GetDataElement(tcrc);
    const ByteValue *bv3 = crc.GetByteValue();

    std::string outfile = std::string(bvdatatype->GetPointer(), bvdatatype->GetLength());
    outfile = LOComp::Trim(outfile.c_str());
    outfile = "c:/tmp/" + outfile;
    const char *outfilename = outfile.c_str();
    //assert( is_valid(outfilename) );
    if (bv2)
    {
      assert(bv3);
      assert(zallocref > 0);
      assert(nslicesref > 0);
      std::cout << ds2 << std::endl;

      if (strncmp(bv->GetPointer(), "ZLib", 4) == 0)
      {
        if (!ProcessDeflate(outfilename, nslicesref, zallocref, bv2->GetPointer(),
          std::streampos(bv2->GetLength()), bv3->GetPointer(), bv3->GetLength()))
        {
          vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element failed to decode");
          return NULL;
        }
      }
      else if (strncmp(bv->GetPointer(), "None", 4) == 0)
      {
        if (!ProcessNone(outfilename, nslicesref, zallocref, bv2->GetPointer(),
          std::streampos(bv2->GetLength()), bv3->GetPointer(), bv3->GetLength()))
        {
          vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element failed to decode");
          return NULL;
        }
      }
      else
      {
        std::string str(bv->GetPointer(), bv->GetLength());
        vtkErrorMacro("vtkSlicerPhilips4dUsReaderLogic::LoadPhilipsFile failed: 'Philips US Imaging DD 045' data element failed to decode from string " << str);
        return NULL;
      }
    }
  }

  return 0;
}
