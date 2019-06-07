/*=========================================================================
 *
 *  Copyright Insight Software Consortium
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *         http://www.apache.org/licenses/LICENSE-2.0.txt
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 *
 *=========================================================================*/

#include "itkFFTPadImageFilter.h"
#include "itkImageFileReader.h"
#include "itkImageFileWriter.h"
#include "itkPeriodicBoundaryCondition.h"
#include "itkPhaseSymmetryImageFilter.h"

#include "PhaseSymmetryFilterCLP.h"

template< unsigned int VDimension >
int PhaseSymmetryFilter( int argc, char * argv[] )
{
  PARSE_ARGS;

  using PixelType = float;
  const unsigned int Dimension = VDimension;
  using ImageType = itk::Image< PixelType, Dimension >;

  using ReaderType = itk::ImageFileReader< ImageType >;
  typename ReaderType::Pointer reader = ReaderType::New();
  reader->SetFileName( inputImage );
  try
    {
    reader->Update();
    }
  catch ( itk::ExceptionObject & excp )
    {
    std::cerr << excp << std::endl;
    return EXIT_FAILURE;
    }

  typename ImageType::Pointer readImage = reader->GetOutput();
  readImage->DisconnectPipeline();
  
  // FFT requires image size of multiple of 2
  typename itk::FFTPadImageFilter< ImageType > FFTPadType;
  FFTPadType::Pointer fftpad = FFTPadType::New();
  fftpad->SetInput(readImage);
  fftpad->SetSizeGreatestPrimeFactor(2);
  itk::PeriodicBoundaryCondition< ImageType > wrapCond;
  fftpad->SetBoundaryCondition(&wrapCond);

  using PhaseSymmetryFilterType = itk::PhaseSymmetryImageFilter< ImageType, ImageType >;
  typename PhaseSymmetryFilterType::Pointer phaseSymmetryFilter = PhaseSymmetryFilterType::New();
  phaseSymmetryFilter->SetInput(fftpad->GetOutput());

  using Array2DType = itk::Array2D< double >;
  const unsigned int scales = wavelengths.size() / Dimension;
  // TODO: assert mod is zero and orientations have the same size.
  Array2DType wavelengthsArray2D( scales, Dimension );
  for( unsigned int ii = 0; ii < scales; ++ii )
    {
    for( unsigned int jj = 0; jj < Dimension; ++jj )
      {
      wavelengthsArray2D( ii, jj ) = wavelengths[ii * Dimension + jj];
      }
    }
  phaseSymmetryFilter->SetWavelengths( wavelengthsArray2D );

  const unsigned int orientationDirections = orientations.size() / Dimension;
  Array2DType orientationsArray2D( orientationDirections, Dimension );
  for( unsigned int ii = 0; ii < orientationDirections; ++ii )
    {
    for( unsigned int jj = 0; jj < Dimension; ++jj )
      {
      orientationsArray2D( ii, jj ) = orientations[ii * Dimension + jj];
      }
    }
  phaseSymmetryFilter->SetOrientations( orientationsArray2D );

  phaseSymmetryFilter->SetSigma( sigma );
  phaseSymmetryFilter->SetAngleBandwidth( angularBandwidth );
  phaseSymmetryFilter->SetPolarity( polarity );
  phaseSymmetryFilter->SetNoiseThreshold( noiseThreshold );

  phaseSymmetryFilter->Initialize();

  using WriterType = itk::ImageFileWriter< ImageType >;
  typename WriterType::Pointer writer = WriterType::New();
  writer->SetInput( phaseSymmetryFilter->GetOutput() );
  writer->SetFileName( outputImage );
  try
    {
    writer->Update();
    }
  catch ( itk::ExceptionObject & excp )
    {
    std::cerr << excp << std::endl;
    return EXIT_FAILURE;
    }

  return EXIT_SUCCESS;
}

int main( int argc, char * argv[] )
{
  PARSE_ARGS;

  itk::ImageIOBase::Pointer imageIO = itk::ImageIOFactory::CreateImageIO(
    inputImage.c_str(), itk::ImageIOFactory::ReadMode );
  if( imageIO.IsNull() )
    {
    std::cerr << "Could create ImageIO for file: " << inputImage << std::endl;
    return EXIT_FAILURE;
    }
  imageIO->SetFileName( inputImage );
  imageIO->ReadImageInformation();

  const unsigned int dimension = imageIO->GetNumberOfDimensions();
  switch( dimension )
    {
  case 2:
    return PhaseSymmetryFilter< 2 >( argc, argv );
  case 3:
    return PhaseSymmetryFilter< 3 >( argc, argv );
  default:
    std::cerr << "Error: Unsupported image dimension." << std::endl;
    return EXIT_FAILURE;
    }

  return EXIT_SUCCESS;
}
