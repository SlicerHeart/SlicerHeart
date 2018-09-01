/*==============================================================================

  Program: 3D Slicer

  Portions (c) Copyright Brigham and Women's Hospital (BWH) All Rights Reserved.

  See COPYRIGHT.txt
  or http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

==============================================================================*/

// GeUsMovieReader Logic includes
#include "vtkSlicerGeUsMovieReaderLogic.h"

// MRML includes
#include "vtkMRMLScalarVolumeNode.h"
#include "vtkMRMLScalarVolumeDisplayNode.h"
#include "vtkMRMLScene.h"
#include "vtkMRMLSelectionNode.h"
#include "vtkMRMLSequenceNode.h"
#include "vtkMRMLSequenceBrowserNode.h"

// VTK includes
#include <vtkImageData.h>
#include <vtkIntArray.h>
#include <vtkMatrix4x4.h>
#include <vtkNew.h>
#include <vtkObjectFactory.h>

// GDCM DICOM parser includes
#include "gdcmReader.h"

//----------------------------------------------------------------------------
vtkStandardNewMacro(vtkSlicerGeUsMovieReaderLogic);

//----------------------------------------------------------------------------
vtkSlicerGeUsMovieReaderLogic::vtkSlicerGeUsMovieReaderLogic()
{
}

//----------------------------------------------------------------------------
vtkSlicerGeUsMovieReaderLogic::~vtkSlicerGeUsMovieReaderLogic()
{
}

//----------------------------------------------------------------------------
void vtkSlicerGeUsMovieReaderLogic::PrintSelf(ostream& os, vtkIndent indent)
{
  this->Superclass::PrintSelf(os, indent);
}


//---------------------------------------------------------------------------
vtkMRMLSequenceNode* vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile(char* filename, char* nodeName /*=NULL*/)
{
  if (!filename)
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: invalid filename");
    return NULL;
  }

  using namespace gdcm;
  gdcm::Reader reader;
  reader.SetFileName(filename);
  reader.Read();

  const PrivateTag movieGroupRootTag(0x7fe1, 0x1, "GEMS_Ultrasound_MovieGroup_001");
  const PrivateTag  movieGroupLevel1Tag(0x7fe1, 0x10, "GEMS_Ultrasound_MovieGroup_001");
  const PrivateTag   movieGroupLevel2Tag(0x7fe1, 0x20, "GEMS_Ultrasound_MovieGroup_001");
  const PrivateTag    image2dTag(0x7fe1, 0x26, "GEMS_Ultrasound_MovieGroup_001");
  const PrivateTag    imageSizeTag(0x7fe1, 0x86, "GEMS_Ultrasound_MovieGroup_001");
  const PrivateTag    voxelDataGroupsTag(0x7fe1, 0x36, "GEMS_Ultrasound_MovieGroup_001");
  const PrivateTag     voxelDataGroupSizeTag(0x7fe1, 0x37, "GEMS_Ultrasound_MovieGroup_001");
  const PrivateTag     voxelDataGroupTimestampsTag(0x7fe1, 0x43, "GEMS_Ultrasound_MovieGroup_001");
  const PrivateTag     voxelDataGroupVoxelsTag(0x7fe1, 0x60, "GEMS_Ultrasound_MovieGroup_001");

  gdcm::File &file = reader.GetFile();
  gdcm::DataSet &ds = file.GetDataSet();
  if (!ds.FindDataElement(movieGroupRootTag))
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: (7fe1, 0001) GEMS_Ultrasound_MovieGroup_001 element not found");
    return NULL;
  }
  const DataElement& movieGroupRootSeq = ds.GetDataElement(movieGroupRootTag);
  SmartPointer<SequenceOfItems> movieGroupRootSeqItems = movieGroupRootSeq.GetValueAsSQ();
  assert(movieGroupRootSeqItems->GetNumberOfItems() == 1);
  Item &movieGroupRootSeqItem0 = movieGroupRootSeqItems->GetItem(1);
  DataSet &movieGroupRootSeqItem0DataSet = movieGroupRootSeqItem0.GetNestedDataSet();
  if (!movieGroupRootSeqItem0DataSet.FindDataElement(movieGroupLevel1Tag))
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: (7fe1, 0010) GEMS_Ultrasound_MovieGroup_001 element not found");
    return NULL;
  }
  const DataElement& movieGroupLevel1Seq = movieGroupRootSeqItem0DataSet.GetDataElement(movieGroupLevel1Tag);
  SmartPointer<SequenceOfItems> movieGroupLevel1SeqItems = movieGroupLevel1Seq.GetValueAsSQ();

  Item &movieGroupLevel1SeqItem1 = movieGroupLevel1SeqItems->GetItem(1);
  DataSet &movieGroupLevel1SeqItem1DataSet = movieGroupLevel1SeqItem1.GetNestedDataSet();

  if (!movieGroupLevel1SeqItem1DataSet.FindDataElement(movieGroupLevel2Tag))
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: (7fe1, 0020) GEMS_Ultrasound_MovieGroup_001 element not found");
    return NULL;
  }
  const DataElement& movieGroupLevel2Seq = movieGroupLevel1SeqItem1DataSet.GetDataElement(movieGroupLevel2Tag);
  SmartPointer<SequenceOfItems> movieGroupLevel2SeqItems = movieGroupLevel2Seq.GetValueAsSQ();
  size_t movieGroupLevel2SeqItemsCount = movieGroupLevel2SeqItems->GetNumberOfItems();
  if (movieGroupLevel2SeqItems->GetNumberOfItems() < 1)
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: movieGroupLevel2SeqItems expected to have items");
    return NULL;
  }
  Item &movieGroupLevel2SeqItem1 = movieGroupLevel2SeqItems->GetItem(1);
  DataSet &movieGroupLevel2SeqItem1DataSet = movieGroupLevel2SeqItem1.GetNestedDataSet();

  if (!movieGroupLevel2SeqItem1DataSet.FindDataElement(image2dTag))
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: (7fe1, 0026) GEMS_Ultrasound_MovieGroup_001 element not found");
    return NULL;
  }
  const DataElement& image2dSeq = movieGroupLevel2SeqItem1DataSet.GetDataElement(image2dTag);
  SmartPointer<SequenceOfItems> image2dSeqItems = image2dSeq.GetValueAsSQ();
  size_t image2dSeqItemCount = image2dSeqItems->GetNumberOfItems();
  if (image2dSeqItemCount < 1)
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: movieGroupLevel2SeqItems expected to have items");
    return NULL;
  }

  int imageSliceSize[3] = { 0, 0, 1 };
  double pixelSpacing[3] = { 1.0, 1.0, 1.0 }; // TODO: read it from file

  for (size_t image2dSeqItemIndex = 1; image2dSeqItemIndex <= image2dSeqItemCount; ++image2dSeqItemIndex)
  {
    Item &image2dSeqItem = image2dSeqItems->GetItem(image2dSeqItemIndex);
    DataSet &image2dSeqItemDataSet = image2dSeqItem.GetNestedDataSet();
    if (image2dSeqItemDataSet.FindDataElement(imageSizeTag))
    {
      Element<VR::SL, VM::VM4> el;
      el.SetFromDataElement(image2dSeqItemDataSet.GetDataElement(imageSizeTag));
      imageSliceSize[0] = el.GetValue(0);
      imageSliceSize[1] = el.GetValue(1);
    }
  }

  if (!movieGroupLevel2SeqItem1DataSet.FindDataElement(voxelDataGroupsTag))
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: (7fe1, 0036) GEMS_Ultrasound_MovieGroup_001 element not found");
    return NULL;
  }
  const DataElement& voxelDataGroupsSeq = movieGroupLevel2SeqItem1DataSet.GetDataElement(voxelDataGroupsTag);

  SmartPointer<SequenceOfItems> voxelDataGroupsSeqItems = voxelDataGroupsSeq.GetValueAsSQ();
  size_t voxelDataGroupsSeqItemCount = voxelDataGroupsSeqItems->GetNumberOfItems();
  if (voxelDataGroupsSeqItemCount < 1)
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: voxelDataGroupsSeq expected to have items");
    return NULL;
  }

  vtkMRMLSequenceNode* sequenceNode = vtkMRMLSequenceNode::SafeDownCast(this->GetMRMLScene()->AddNewNodeByClass("vtkMRMLSequenceNode", nodeName ? nodeName : ""));
  if (!sequenceNode)
  {
    vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: cannot create sequence node");
    return NULL;
  }
  sequenceNode->SetIndexName("time");
  sequenceNode->SetIndexType(vtkMRMLSequenceNode::NumericIndex);
  sequenceNode->SetIndexUnit("s");

  int frameNumber = 0;
  for (size_t voxelDataGroupsSeqItemIndex = 1; voxelDataGroupsSeqItemIndex <= voxelDataGroupsSeqItemCount; ++voxelDataGroupsSeqItemIndex)
  {
    Item &voxelDataGroupsSeqItem = voxelDataGroupsSeqItems->GetItem(voxelDataGroupsSeqItemIndex);
    DataSet &voxelDataGroupsSeqItemDataSet = voxelDataGroupsSeqItem.GetNestedDataSet();

    if (!voxelDataGroupsSeqItemDataSet.FindDataElement(voxelDataGroupSizeTag))
    {
      vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: (7fe1, 0037) GEMS_Ultrasound_MovieGroup_001 element not found");
      continue;
    }
    const DataElement& de8 = voxelDataGroupsSeqItemDataSet.GetDataElement(voxelDataGroupSizeTag);
    Element<VR::UL, VM::VM1> ldimz;
    ldimz.SetFromDataElement(de8);
    int dimz = ldimz.GetValue();

    if (!voxelDataGroupsSeqItemDataSet.FindDataElement(voxelDataGroupTimestampsTag))
    {
      vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: (7fe1, 0043) GEMS_Ultrasound_MovieGroup_001 element not found");
      continue;
    }
    const DataElement& voxelDataGroupTimestampsData = voxelDataGroupsSeqItemDataSet.GetDataElement(voxelDataGroupTimestampsTag);
    const ByteValue *voxelDataGroupTimestampsDataBytes = voxelDataGroupTimestampsData.GetByteValue();
    const double* timestamps = reinterpret_cast<const double*>(voxelDataGroupTimestampsDataBytes->GetPointer());
    const int timestampsCount = (voxelDataGroupTimestampsDataBytes->GetLength() / sizeof(timestamps[0]));

    if (!voxelDataGroupsSeqItemDataSet.FindDataElement(voxelDataGroupVoxelsTag))
    {
      vtkErrorMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile failed: (7fe1, 0020) GEMS_Ultrasound_MovieGroup_001 element not found");
      continue;
    }
    const DataElement& seq5 = voxelDataGroupsSeqItemDataSet.GetDataElement(voxelDataGroupVoxelsTag);
    const ByteValue *bv5 = seq5.GetByteValue();

    const char* voxelBuffer = bv5->GetPointer();
    size_t voxelBufferLength = bv5->GetLength();
    size_t imageSliceSizeInBytes = imageSliceSize[0] * imageSliceSize[1] * imageSliceSize[2];
    if (voxelBufferLength < imageSliceSizeInBytes * dimz)
    {
      vtkWarningMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile: missing frames in frame buffer");
      dimz = voxelBufferLength / imageSliceSizeInBytes;
    }
    for (int frameIndex = 0; frameIndex < dimz; ++frameIndex)
    {
      vtkNew<vtkMRMLScalarVolumeNode> slice;
      vtkNew<vtkImageData> sliceImageData;
      sliceImageData->SetExtent(0, imageSliceSize[0] - 1, 0, imageSliceSize[1] - 1, 0, imageSliceSize[2] - 1);
      sliceImageData->AllocateScalars(VTK_UNSIGNED_CHAR, 1);
      memcpy(sliceImageData->GetScalarPointer(), voxelBuffer + frameIndex * imageSliceSizeInBytes, imageSliceSizeInBytes);
      slice->SetAndObserveImageData(sliceImageData);

      // Image stored row by row, therefore x spacing is written to second row,
      // y spacing is written to first row.
      vtkNew<vtkMatrix4x4> ijkToRas;
      ijkToRas->SetElement(0, 0, 0.0);
      ijkToRas->SetElement(0, 1, -pixelSpacing[1]);
      ijkToRas->SetElement(1, 0, -pixelSpacing[0]);
      ijkToRas->SetElement(1, 1, 0.0);
      ijkToRas->SetElement(2, 2, -pixelSpacing[2]);
      slice->SetIJKToRASMatrix(ijkToRas.GetPointer());

      std::ostringstream nameStr;
      nameStr << "frame_" << std::setw(4) << std::setfill('0') << frameNumber << std::ends;
      slice->SetName(nameStr.str().c_str());

      if (frameIndex >= timestampsCount)
      {
        vtkWarningMacro("vtkSlicerGeUsMovieReaderLogic::LoadGeUsMovieFile: missing timestamps for frame " << frameIndex << " - skip frame");
        continue;
      }

      std::ostringstream indexStr;
      indexStr << timestamps[frameIndex] << std::ends;
      sequenceNode->SetDataNodeAtValue(slice.GetPointer(), indexStr.str());

      ++frameNumber;
    }
  }

  vtkMRMLSequenceBrowserNode* sequenceBrowserNode = vtkMRMLSequenceBrowserNode::SafeDownCast(
    this->GetMRMLScene()->AddNewNodeByClass("vtkMRMLSequenceBrowserNode", nodeName ? nodeName : ""));
  sequenceBrowserNode->SetAndObserveMasterSequenceNodeID(sequenceNode->GetID());

  // If save changes are allowed then proxy nodes are updated using shallow copy, which is much faster for images
  // (and images are usually not modified, so the risk of accidentally modifying data in the sequence is low).
  sequenceBrowserNode->SetSaveChanges(sequenceNode, true);

  return sequenceNode;
}
