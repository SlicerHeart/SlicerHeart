"""
Read a csv file containing exported annulus contours and compute mean annulus contour of all cases in each phase.

For users
---------

How to run:


# Computer-specific data and source code location
slicer_heart_data = 'c:/D/SlicerHeartSandbox/Data'
from HeartValveBatchAnalysis import annulus_shape_analysis

csv_filename=slicer_heart_data+'/annulus_shape_analysis/NEW_2.2.18_MildorLessTR_AnnulusContourPoints.csv'
label_order = ['S', 'A', 'L', 'P']
annulus_shape_analysis.run(csv_filename, label_order)

# Without size normalization
csv_filename=slicer_heart_data+'/annulus_shape_analysis/CavcContourPoints.csv'
label_order = ['R', 'RA', 'MA', 'LA', 'L', 'LP', 'MP', 'RP']
annulus_shape_analysis.run(csv_filename, label_order, valve_type="cavc", number_of_points_per_segment=30)
label_order = ['R', 'A', 'L', 'P']
annulus_shape_analysis.run(csv_filename, label_order, valve_type="aortic", number_of_points_per_segment=30)

# With size normalization
csv_filename=slicer_heart_data+'/annulus_shape_analysis/CavcContourPoints.csv'
scale_factors = annulus_shape_analysis.compute_scale_factors(csv_filename, valve_type="cavc")
label_order = ['R', 'RA', 'MA', 'LA', 'L', 'LP', 'MP', 'RP']
annulus_shape_analysis.run(csv_filename, label_order, valve_type="cavc", number_of_points_per_segment=30, scale_factors=scale_factors)
label_order = ['R', 'A', 'L', 'P']
annulus_shape_analysis.run(csv_filename, label_order, valve_type="aortic", number_of_points_per_segment=30, scale_factors=scale_factors)

# With alignment of multiple valves
csv_filename=slicer_heart_data+'/annulus_shape_analysis/Normal_Mitrals.csv'
annulus_phases=None
valve_type_1="mitral"
valve_type_2="aortic"
label_order_1 = ['A', 'AL', 'P', 'PM']
label_order_2 = ['R', 'A', 'L', 'P']
scale_factors = annulus_shape_analysis.compute_scale_factors(csv_filename, valve_type=valve_type_1, annulus_phases=annulus_phases)
normalized_annulus_to_valve1_first_phase = annulus_shape_analysis.get_normalized_annulus_to_valve1_first_phase(csv_filename,
  principal_labels_1=label_order_1, valve_type_1=valve_type_1,
  principal_labels_2=label_order_2, valve_type_2=valve_type_2,
  annulus_phases=annulus_phases,
  scale_factors=scale_factors,
  stop_on_warning=False)
annulus_shape_analysis.run(csv_filename,
                           label_order_1, valve_type=valve_type_1, number_of_points_per_segment=30,
                           scale_factors=scale_factors, annulus_phases=annulus_phases,
                           normalized_annulus_to_valve1_first_phase=normalized_annulus_to_valve1_first_phase,
                           principal_labels=label_order_1)
annulus_shape_analysis.run(csv_filename,
                           label_order_2, valve_type=valve_type_2, number_of_points_per_segment=30,
                           scale_factors=scale_factors, annulus_phases=annulus_phases,
                           normalized_annulus_to_valve1_first_phase=normalized_annulus_to_valve1_first_phase,
                           principal_labels=label_order_2)

# With alignment of multiple valves
csv_filename=slicer_heart_data+'/annulus_shape_analysis/CavcContourPoints.csv'
annulus_phases=None
valve_type_1="cavc"
valve_type_2="aortic"
label_order_1 = ['R', 'RA', 'MA', 'LA', 'L', 'LP', 'MP', 'RP']
principal_label_order_1 = ['R', 'MA', 'L', 'MP']
label_order_2 = ['R', 'A', 'L', 'P']
principal_label_order_2 = label_order_2
scale_factors = annulus_shape_analysis.compute_scale_factors(csv_filename, valve_type=valve_type_1, annulus_phases=annulus_phases)
normalized_annulus_to_valve1_first_phase = annulus_shape_analysis.get_normalized_annulus_to_valve1_first_phase(csv_filename,
  principal_labels_1=principal_label_order_1, valve_type_1=valve_type_1,
  principal_labels_2==principal_label_order_2, valve_type_2=valve_type_2,
  annulus_phases=annulus_phases,
  scale_factors=scale_factors,
  stop_on_warning=False)
annulus_shape_analysis.run(csv_filename,
                           label_order_1, valve_type=valve_type_1, number_of_points_per_segment=30,
                           scale_factors=scale_factors, annulus_phases=annulus_phases,
                           normalized_annulus_to_valve1_first_phase=normalized_annulus_to_valve1_first_phase,
                           principal_labels=label_order_1)
annulus_shape_analysis.run(csv_filename,
                           label_order_2, valve_type=valve_type_2, number_of_points_per_segment=30,
                           scale_factors=scale_factors, annulus_phases=annulus_phases,
                           normalized_annulus_to_valve1_first_phase=normalized_annulus_to_valve1_first_phase,
                           principal_labels=label_order_2)


For developers
--------------

Reload analysis scripts after changing .py files without restarting Slicer:

import HeartValveBatchAnalysis
HeartValveBatchAnalysis.reload()

"""

import os
import logging
import numpy as np
from HeartValveLib.util import *
import vtk, qt, ctk, slicer


# Contour processing
###############################

def get_unique_column_values(csv_filename, columnName):
    """Get all values of a selected column. Values are unique (if the same value occurs multiple times in the column,
    it is only included in the returned values once)."""

    import csv
    with open(csv_filename, 'r') as csv_file:
        table_reader = csv.reader(csv_file)
        file_header = next(table_reader)
        if columnName not in file_header:
            return None
        column_index = file_header.index(columnName)
        used = set()  # stores which values have been already encountered
        unique_values = [row[column_index] for row in table_reader if
                         row[column_index] not in used and (used.add(row[column_index]) or True)]
    return unique_values


def get_annulus_contour_points(csv_filename, annulus_filename, annulus_phase, valve_type):
    """Get point coordinates for the selected filename and phase."""
    import csv
    with open(csv_filename, 'r') as csv_file:
        table_reader = csv.reader(csv_file)
        file_header = next(table_reader)
        filename_column_index = file_header.index('Filename')
        phase_column_index = file_header.index('Phase')
        valve_column_index = file_header.index('Valve')
        x_column_index = file_header.index('AnnulusContourX')
        y_column_index = file_header.index('AnnulusContourY')
        z_column_index = file_header.index('AnnulusContourZ')
        label_column_index = file_header.index('AnnulusContourLabel')
        rows_for_annulus_filename_phase = list(filter(
            lambda p: p[filename_column_index] == annulus_filename and p[phase_column_index] == annulus_phase and p[valve_column_index] == valve_type,
            table_reader))
        coordinates = [[float(row[x_column_index]), float(row[y_column_index]), float(row[z_column_index])] for row in
                       rows_for_annulus_filename_phase]
        labels = {row[label_column_index]: i for i, row in enumerate(rows_for_annulus_filename_phase) if
                  row[label_column_index] != ''}
    return [np.array(coordinates), labels]


def order_annulus_contour_points(annulus_point_coordinates, labels, label_order):
    """Orders annulus contour points so that the first point position is the one that
    has the first label. If necessary, order of points are inverted so that labels are listed
    in the output in the same order as in the requested label order."""
    number_of_annulus_points = annulus_point_coordinates.shape[0]
    if label_order[0] not in labels:
        raise ValueError(
            "First label ({0}) is not defined for contour. Defined labels: {1}".format(label_order[0], labels.keys()))

    starting_point_index = labels[label_order[0]]

    # Compute label indexes so that the first label's index becomes 0
    second_label_index = (labels[label_order[1]] - starting_point_index) % number_of_annulus_points
    third_label_index = (labels[label_order[2]] - starting_point_index) % number_of_annulus_points
    need_to_reverse = (second_label_index > third_label_index)

    # Compute new point indexes
    point_indexes = []
    point_indexes.extend(range(starting_point_index, number_of_annulus_points))
    point_indexes.extend(range(0, starting_point_index))
    if need_to_reverse:
        point_indexes.reverse()
        # rotate point_indexes by one so that first label becomes the first item
        point_indexes = [point_indexes[-1]] + point_indexes[:-1]

    # Compute new label indexes
    new_labels = {}
    last_index = -1
    for label in label_order:
        new_index = point_indexes.index(labels[label])
        new_labels[label] = new_index
        if new_index <= last_index == need_to_reverse:  # (new_index <= last_index) must be true if not reversed
            raise ValueError(
                "Cannot get contour points in desired order. Required order: {0}. Defined labels: {1}".format(
                    label_order, labels))
        last_index = new_index

    # Get new point coordinates
    new_annulus_point_coordinates = annulus_point_coordinates[point_indexes]
    return [new_annulus_point_coordinates, new_labels]


def resample_annulus_contour_points(annulus_point_coordinates, labels, label_order,
                                    resampled_number_of_points_per_segment):
    """Resamples contour points to have exactly resampled_number_of_points_per_segment points for each contour segment."""
    number_of_annulus_points = annulus_point_coordinates.shape[0]
    interpolated_annulus_point_coordinates = np.zeros([len(label_order) * resampled_number_of_points_per_segment, 3])
    for label_index in range(len(label_order)):
        start_index = labels[label_order[label_index]]
        end_index = labels[label_order[label_index + 1]] if label_index + 1 < len(
            label_order) else number_of_annulus_points - 1
        number_of_points_per_segment = end_index - start_index
        for axis in range(3):
            interpolated_annulus_point_coordinates[label_index * resampled_number_of_points_per_segment:(label_index + 1) * resampled_number_of_points_per_segment,
            axis] = np.interp(
                np.linspace(0, number_of_points_per_segment - 1, resampled_number_of_points_per_segment),
                range(number_of_points_per_segment), annulus_point_coordinates[start_index:end_index, axis])
    return interpolated_annulus_point_coordinates


def get_annulus_to_mean_annulus_transforms(landmark_points):
    """Uses groupwise Procrustes alignment to align landmark points and return list of transformation
    matrices that transforms each annulus to the mean annulus.
    All annuli are aligned to the first annulus.
    """

    landmark_points_group = vtk.vtkMultiBlockDataGroupFilter()
    number_of_cases = landmark_points.shape[0]
    centroids = np.zeros([number_of_cases, 3])
    for case_index in range(number_of_cases):
        polyData = createPolyDataFromPointArray(landmark_points[case_index])
        landmark_points_group.AddInputData(polyData)
        centroids[case_index] = landmark_points[case_index].mean(0)

    procrustes1 = vtk.vtkProcrustesAlignmentFilter()
    procrustes1.SetInputConnection(landmark_points_group.GetOutputPort())
    # procrustes1.StartFromCentroidOn()
    procrustes1.GetLandmarkTransform().SetModeToRigidBody()
    procrustes1.Update()

    landmarkTransform = procrustes1.GetLandmarkTransform()
    annulus_to_mean_annulus_transforms = []
    for case_index in range(number_of_cases):
        landmarkTransform.SetSourceLandmarks(createPolyDataFromPointArray(landmark_points[case_index]).GetPoints())
        landmarkTransform.SetTargetLandmarks(procrustes1.GetOutput().GetBlock(case_index).GetPoints())
        landmarkTransform.Update()
        transformMatrix = vtk.vtkMatrix4x4()
        transformMatrix.DeepCopy(landmarkTransform.GetMatrix())
        annulus_to_mean_annulus_transforms.append(transformMatrix)

    return annulus_to_mean_annulus_transforms


def align_annulus_contours(all_annulus_point_coordinates, annulus_to_mean_annulus_transforms):
    """Applies corresponding alignment transform to each annulus."""

    all_aligned_annulus_point_coordinates = np.array([]).reshape([0, 3])
    for case_index in range(all_annulus_point_coordinates.shape[0]):
        transformPolyData = vtk.vtkTransformPolyDataFilter()
        transform = vtk.vtkTransform()
        transform.SetMatrix(annulus_to_mean_annulus_transforms[case_index])
        transformPolyData.SetInputData(createPolyDataFromPointArray(all_annulus_point_coordinates[case_index]))
        transformPolyData.SetTransform(transform)
        transformPolyData.Update()
        aligned_point_array = getPointArrayFromPolyData(transformPolyData.GetOutput())
        all_aligned_annulus_point_coordinates = np.concatenate(
            [all_aligned_annulus_point_coordinates, aligned_point_array])

    all_aligned_annulus_point_coordinates = all_aligned_annulus_point_coordinates.reshape(
        all_annulus_point_coordinates.shape)

    # Adjust the transform so that annuli are not transformed to the first annulus but transformed to the centroid of all the annuli.
    firstCaseCentroid = all_annulus_point_coordinates[0,:,:].mean(0)
    averageCentroid = all_annulus_point_coordinates.mean(0).mean(0)
    shiftToAverageCentroid = averageCentroid-firstCaseCentroid
    all_aligned_annulus_point_coordinates = all_aligned_annulus_point_coordinates+shiftToAverageCentroid

    return all_aligned_annulus_point_coordinates


def compute_scale_factors(csv_filename, valve_type=None, annulus_phases=None, progress_function=None):
    """
    :param csv_filename: input CSV file containing columns Filename, Phase, Valve, AnnulusContourX, AnnulusContourY, AnnulusContourZ, AnnulusContourLabel
    :param valve_type: name of valve type that will be processed. If not defined then the first occurring valve type will be used.  # Verify that label_order does not contain duplicates
    :param progress_function: a callback function f(current_step, total_steps) for indicating current computation progress.
    """

    annulus_filenames = get_unique_column_values(csv_filename, 'Filename')
    number_of_filenames = len(annulus_filenames)
    if progress_function is not None:
        progress_function(0, number_of_filenames)

    if annulus_phases is None:
        # if user does not provide phases then process all phases
        annulus_phases = get_unique_column_values(csv_filename, 'Phase')
    elif type(annulus_phases) == str:
        # if user provides a simple string then convert it to a single-element list
        annulus_phases = [annulus_phases]

    if valve_type is None:
        # if user does not provide phases then process first valve type
        valve_types = get_unique_column_values(csv_filename, 'Valve')
        if valve_types is None:
            raise ValueError("CSV file {0} does not contain 'Valve' column".format(csv_filename))
        valve_type = valve_types[0]

    mean_sizes = []  # mean size for each annulus_filename
    mean_sizes_filenames = []
    for index, annulus_filename in enumerate(annulus_filenames):
        logging.info('Compute scale factor for ' + annulus_filename)
        if progress_function is not None:
            progress_function(index, number_of_filenames)
        slicer.app.processEvents()

        mean_sizes_for_filename = []
        for annulus_phase in annulus_phases:
            try:
                [annulus_point_coordinates, labels] = get_annulus_contour_points(csv_filename, annulus_filename,
                                                                                 annulus_phase, valve_type)
                relative_point_coords = annulus_point_coordinates - annulus_point_coordinates.mean(0)
                distances = np.linalg.norm(relative_point_coords, axis=1)
                mean_sizes_for_filename.append(distances.mean())
            except Exception as e:
                import traceback
                logging.debug(traceback.format_exc())
                logging.warning(
                    "Skipping {0} valve {1} phase - {2}: {3}".format(valve_type, annulus_phase, annulus_filename, e))
                continue

        if len(mean_sizes_for_filename) == 0:
            continue

        mean_sizes.append(np.array(mean_sizes_for_filename).mean())
        mean_sizes_filenames.append(annulus_filename)

    if len(mean_sizes) == 0:
        raise ValueError("Could not find valid contours in CSV file {0} for valve {1}".format(csv_filename, valve_type))

    mean_sizes = np.array(mean_sizes)

    # Compute relative scale factor and save in filename->scale_factor map
    scale_factors_array = mean_sizes.mean() / mean_sizes
    scale_factors = {}
    for case_index in range(len(scale_factors_array)):
        scale_factors[mean_sizes_filenames[case_index]] = scale_factors_array[case_index]

    return scale_factors

def get_world_to_normalized_transform(annulus_landmarks):
    """
    Compute transform that translates and rotates annulus points to a normalized position and
    orientataion so that:
    - landmarks' centroid is translated into the origin
    - landmark0->landmark2 gets aligned with X axis,
    - landmark1->landmark3 gets aligned with Y axis.
    The resulting transform only includes translation and rotation (no scaling).
    :param annulus_landmarks principal landmark positions as a 4x3 numpy array
    :return transform from valve 2 coordinate system to normalized coordinate system as a 4x4 numpy array
    """

    axis_x = annulus_landmarks[2]-annulus_landmarks[0]
    axis_x = axis_x/np.linalg.norm(axis_x)
    axis_y = annulus_landmarks[3]-annulus_landmarks[1]
    axis_y = axis_y/np.linalg.norm(axis_y)
    axis_z = np.cross(axis_x, axis_y)
    # orthogonalize y
    axis_y = np.cross(axis_z, axis_x)
    center = np.mean(annulus_landmarks, axis=0)
    normalized_to_annulus = np.eye(4)
    normalized_to_annulus[0:3, 0] = axis_x
    normalized_to_annulus[0:3, 1] = axis_y
    normalized_to_annulus[0:3, 2] = axis_z
    normalized_to_annulus[0:3, 3] = center

    return np.linalg.inv(normalized_to_annulus)

def quaternion_weighted_average(Q, weights):
    '''
    Averaging Quaternions.

    Arguments:
        Q(ndarray): an Mx4 ndarray of quaternions.
        weights(list): an M elements list, a weight for each quaternion.

    Source: https://stackoverflow.com/questions/12374087/average-of-multiple-quaternions
    '''

    import numpy as np

    # Form the symmetric accumulator matrix
    A = np.zeros((4, 4))
    M = Q.shape[0]
    wSum = 0

    for i in range(M):
        q = Q[i, :]
        w_i = weights[i]
        A += w_i * (np.outer(q, q)) # rank 1 update
        wSum += w_i

    # scale
    A /= wSum

    # Get the eigenvector corresponding to largest eigen value
    return np.linalg.eigh(A)[1][:, -1]

def get_mean_transform(transforms):
    """
    Computes average transform for a list of homogeneous transforms, defined by 4x4 numpy arrays
    """

    mean_transform = np.eye(4)

    translations = np.zeros([len(transforms),3])
    rotation_quaternions = np.zeros([len(transforms),4])
    for transform_index, transform in enumerate(transforms):
        translations[transform_index,:] = transform[0:3,3]

        rotation_quaternion = [0.0] * 4
        vtk.vtkMath.Matrix3x3ToQuaternion(transform[0:3,0:3], rotation_quaternion)
        rotation_quaternions[transform_index,:] = rotation_quaternion

    mean_transform[0:3,3] = np.mean(translations, axis=0)

    mean_rotation_quaternion = quaternion_weighted_average(rotation_quaternions, [1.0] * len(transforms))
    #mean_rotation_matrix = np.eye(3)
    vtk.vtkMath.QuaternionToMatrix3x3(mean_rotation_quaternion,mean_transform[0:3, 0:3])
    #mean_transform[0:3, 0:3] = mean_rotation_matrix

    return mean_transform

def get_normalized_annulus_to_valve1_first_phase(csv_filename, principal_labels_1, valve_type_1, principal_labels_2, valve_type_2, annulus_phases=None, scale_factors=None, stop_on_warning=False, progress_function=None):
    """
    Get average relative pose between two valve contours
    :param csv_filename: input CSV file containing columns Filename, Phase, Valve, AnnulusContourX, AnnulusContourY, AnnulusContourZ, AnnulusContourLabel
    :param principal_labels_1: list of strings defining order of labels. All labels must be defined for all contours. Label 0->2 defines x axis; label 1->3 defines y axis.
    :param valve_type_1: name of valve type that will be processed.
    :param principal_labels_2: labels for valve 2
    :param valve_type_2: type of valve 2
    :param annulus_phases: name (or list of names) of all phases ('ES', 'ED', ...) that will be processed. If not defined then all phases will be processed.
    :param scale_factors: dict that maps annulus_filename to relative scale factor
    :param stop_on_warning: stop processing immediately when an error occurs instead of just ignoring the invalid contour. By default it is set to False.
    :param progress_function: a callback function f(current_step, total_steps) for indicating current computation progress.
    :return Dictionary object with two item (key: valve type), that contain dictionary objects (key: phase) that transforms from selected valve and phase
        to valve 1 first phase.
    """

    # Verify that label_order contains exactly 4 labels
    if len(principal_labels_1) != 4:
        raise ValueError("4 label names are expected in principal_labels_1")
    if len(principal_labels_2) != 4:
        raise ValueError("4 label names are expected in principal_labels_2")

    # Verify that label_order does not contain duplicates
    if len(principal_labels_1) != len(set(principal_labels_1)):
        raise ValueError("Duplicate elements found in label order 1: {0}".format(principal_labels_1))
    if len(principal_labels_2) != len(set(principal_labels_2)):
        raise ValueError("Duplicate elements found in label order 2: {0}".format(principal_labels_2))

    annulus_filenames = get_unique_column_values(csv_filename, 'Filename')

    if annulus_phases is None:
        # if user does not provide phases then process all phases
        annulus_phases = get_unique_column_values(csv_filename, 'Phase')
    elif type(annulus_phases) == str:
        # if user provides a simple string then convert it to a single-element list
        annulus_phases = [annulus_phases]

    mean_annulus_1_to_annulus_1_phase_0_transforms = {}  # key: phase name, value: 4x4 numpy transformation matrix
    mean_annulus_2_to_annulus_1_phase_0_transforms = {}  # key: phase name, value: 4x4 numpy transformation matrix
    number_of_annulus_filenames = len(annulus_filenames)
    number_of_loops = len(annulus_phases) * number_of_annulus_filenames
    if progress_function is not None:
        progress_function(0, number_of_loops)
    for annulus_phase_index, annulus_phase in enumerate(annulus_phases):
        logging.info("Compute relative pose for {0}/{1} valve {2} phase".format(valve_type_1, valve_type_2, annulus_phase))
        slicer.app.processEvents()

        # Get all relative valve transforms for this phase
        annulus_2_to_1_transforms = []
        world_to_normalized_annulus_1_transforms = []
        world_to_normalized_annulus_2_transforms = []
        for annulus_filename_index, annulus_filename in enumerate(annulus_filenames):
            try:
                if progress_function is not None:
                    progress_function(annulus_phase_index * number_of_annulus_filenames + annulus_filename_index, number_of_loops)
                [annulus_point_coordinates_1, labels_1] = get_annulus_contour_points(csv_filename, annulus_filename, annulus_phase, valve_type_1)
                [annulus_point_coordinates_2, labels_2] = get_annulus_contour_points(csv_filename, annulus_filename, annulus_phase, valve_type_2)
                if scale_factors is not None:
                    annulus_point_coordinates_1 *= scale_factors[annulus_filename]
                    annulus_point_coordinates_2 *= scale_factors[annulus_filename]

                valve_landmarks_1 = np.zeros([4,3])
                valve_landmarks_2 = np.zeros([4,3])
                for label_index in range(4):
                    valve_landmarks_1[label_index,:] = annulus_point_coordinates_1[labels_1[principal_labels_1[label_index]], :]
                    valve_landmarks_2[label_index,:] = annulus_point_coordinates_2[labels_2[principal_labels_2[label_index]], :]

                world_to_normalized_annulus_1_transform = get_world_to_normalized_transform(valve_landmarks_1)
                world_to_normalized_annulus_2_transform = get_world_to_normalized_transform(valve_landmarks_2)

                world_to_normalized_annulus_1_transforms.append(world_to_normalized_annulus_1_transform)
                world_to_normalized_annulus_2_transforms.append(world_to_normalized_annulus_2_transform)
                annulus_2_to_1_transform = np.dot(world_to_normalized_annulus_1_transform, np.linalg.inv(world_to_normalized_annulus_2_transform))
                annulus_2_to_1_transforms.append(annulus_2_to_1_transform)
            except Exception as e:
                import traceback
                logging.debug(traceback.format_exc())
                logging.warning(
                    "Skipping {0}/{1} valve {2} phase - {3}: {4}".format(valve_type_1, valve_type_2, annulus_phase, annulus_filename, e))
                if stop_on_warning:
                    return False
                continue

        if len(annulus_2_to_1_transforms) == 0:
            logging.warning("Skipping {0}/{1} valve {2} phase completely: no valid labels was found".format(valve_type_1, valve_type_2, annulus_phase))
            continue

        # Compute mean transform from annulus 2 to annulus 1
        mean_annulus_2_to_1_transform = get_mean_transform(annulus_2_to_1_transforms)

        # Compute mean transform from annulus 1 current phase to annulus 1 first phase
        mean_world_to_normalized_annulus_1_transform = get_mean_transform(world_to_normalized_annulus_1_transforms)
        mean_world_to_normalized_annulus_2_transform = get_mean_transform(world_to_normalized_annulus_2_transforms)

        # Save result
        if annulus_phase == annulus_phases[0]:
            mean_world_to_normalized_annulus_1_phase0_transform = mean_world_to_normalized_annulus_1_transform
            mean_annulus_1_to_annulus_1_phase_0_transforms[annulus_phase] = np.eye(4)
            mean_annulus_2_to_annulus_1_phase_0_transforms[annulus_phase] = mean_annulus_2_to_1_transform
        else:
            mean_annulus_1_to_annulus_1_phase_0_transforms[annulus_phase] = np.dot(mean_world_to_normalized_annulus_1_phase0_transform, np.linalg.inv(mean_world_to_normalized_annulus_1_transform))
            mean_annulus_2_to_annulus_1_phase_0_transforms[annulus_phase] = np.dot(mean_annulus_1_to_annulus_1_phase_0_transforms[annulus_phase],  mean_annulus_2_to_1_transform)

    normalized_annulus_to_valve1_first_phase = {valve_type_1: mean_annulus_1_to_annulus_1_phase_0_transforms, valve_type_2: mean_annulus_2_to_annulus_1_phase_0_transforms}
    return normalized_annulus_to_valve1_first_phase

def pca_analysis(all_annulus_point_coordinates, number_of_variation_steps = 2, variation_step_size = 1.0, proportion_of_variation = 0.95):
    """Applies corresponding alignment transform to each annulus.
    :param all_annulus_point_coordinates list of aligned annulus points"""

    # Convert annulus points to multiblock data set (PCA filter requires that input format)
    annulus_points_multiblock = vtk.vtkMultiBlockDataSet()
    number_of_cases = all_annulus_point_coordinates.shape[0]
    annulus_points_multiblock.SetNumberOfBlocks(number_of_cases)
    for case_index in range(number_of_cases):
        points_polydata = createPolyDataFromPointArray(all_annulus_point_coordinates[case_index])
        annulus_points_multiblock.SetBlock(case_index, points_polydata)

    pca = vtk.vtkPCAAnalysisFilter()
    pca.SetInputData(annulus_points_multiblock)
    pca.Update()

    number_of_modes = pca.GetModesRequiredFor(proportion_of_variation)

    params = vtk.vtkFloatArray()
    params.SetNumberOfComponents(1)
    params.SetNumberOfTuples(number_of_modes)
    all_modes_annulus_point_coordinates = []
    for mode_index in range(number_of_modes):
        # Set all parameters to 0 except the current mode (that will be set later)
        for mode_index_tmp in range(number_of_modes):
            params.SetTuple1(mode_index_tmp, 0.0)

        # Get number_of_variation_steps*2+1 shapes that illustrates variation caused by mode_index-th mode
        modes_annulus_point_coordinates = []
        for variation_step in range(-number_of_variation_steps, number_of_variation_steps+1):
            # variation_step example: [-2, -1, 0, 1, 2] (for number_of_variation_steps = 2)
            params.SetTuple1(mode_index, variation_step * variation_step_size)
            # all_annulus_point_coordinates[0] is just needed because an initialized polydata is required as input
            # point coordinate values of the input data will not be used
            points_polydata = createPolyDataFromPointArray(all_annulus_point_coordinates[0])
            pca.GetParameterisedShape(params, points_polydata)
            annulus_point_coordinates = getPointArrayFromPolyData(points_polydata)
            modes_annulus_point_coordinates.append(annulus_point_coordinates)

        all_modes_annulus_point_coordinates.append(modes_annulus_point_coordinates)

    return all_modes_annulus_point_coordinates

# Data processing
###############################

def run(csv_filename, label_order, number_of_points_per_segment=100, valve_type=None, annulus_phases=None,
        scale_factors=None, principal_labels=None, normalized_annulus_to_valve1_first_phase=None, stop_on_warning=False):
    """
    Run annulus curve analysis
    :param csv_filename: input CSV file containing columns Filename, Phase, Valve, AnnulusContourX, AnnulusContourY, AnnulusContourZ, AnnulusContourLabel
    :param label_order: list of strings defining order of labels. All labels must be defined for all contours.
    :param number_of_points_per_segment: each curve segment (section between two labels) will be resampled to contain this many points
    :param valve_type: name of valve type that will be processed. If not defined then the first occurring valve type will be used.
    :param annulus_phases: name (or list of names) of all phases ('ES', 'ED', ...) that will be processed. If not defined then all phases will be processed.
    :param scale_factors: dict that maps annulus_filename to relative scale factor
    :param stop_on_warning: stop processing immediately when an error occurs instead of just ignoring the invalid contour. By default it is set to False.
    """

    # Verify that label_order does not contain duplicates
    if len(label_order) != len(set(label_order)):
        raise ValueError("Duplicate elements found in label order: {0}".format(label_order))

    draw_individual_annulus_contours = True
    draw_original_contours = False  # useful mainly for debugging
    draw_pca = True

    # Display options
    meanTubeRadius = 0.5
    meanColors = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 1, 1]]
    individualTubeRadius = 0.1
    individualColors = [[0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5], [0, 0.5, 0.5]]

    annulus_filenames = get_unique_column_values(csv_filename, 'Filename')

    if annulus_phases is None:
        # if user does not provide phases then process all phases
        annulus_phases = get_unique_column_values(csv_filename, 'Phase')
    elif type(annulus_phases) == str:
        # if user provides a simple string then convert it to a single-element list
        annulus_phases = [annulus_phases]

    if valve_type is None:
        # if user does not provide phases then process first valve type
        valve_types = get_unique_column_values(csv_filename, 'Valve')
        if valve_types is None:
            raise ValueError("CSV file {0} does not contain 'Valve' column".format(csv_filename))
        valve_type = valve_types[0]

    number_of_annulus_segments = len(label_order)

    # Create subject hierarchy root folder
    filenameWithoutExtension = os.path.splitext(os.path.basename(csv_filename))[0]
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    shRootFolderId = shNode.CreateFolderItem(shNode.GetSceneItemID(),
                                             '{0} {1} contours'.format(filenameWithoutExtension, valve_type))
    shNode.SetItemExpanded(shRootFolderId, True)

    for annulus_phase_index, annulus_phase in enumerate(annulus_phases):
        logging.info('Processing {0} valve {1} phase'.format(valve_type, annulus_phase))
        slicer.app.processEvents()

        # Get all annulus contours for this phase
        all_ordered_resampled_annulus_point_coordinates = np.array([]).reshape([0, 3])
        for annulus_filename in annulus_filenames:
            # logging.debug('Annulus: {0} - {1}'.format(annulus_filename, annulus_phase))
            try:
                [annulus_point_coordinates, labels] = get_annulus_contour_points(csv_filename, annulus_filename,
                                                                                 annulus_phase, valve_type)
                if scale_factors is not None:
                    annulus_point_coordinates *= scale_factors[annulus_filename]
                [ordered_annulus_point_coordinates, ordered_labels] = order_annulus_contour_points(
                    annulus_point_coordinates, labels, label_order)
                ordered_resampled_annulus_point_coordinates = resample_annulus_contour_points(
                    ordered_annulus_point_coordinates, ordered_labels, label_order, number_of_points_per_segment)
                all_ordered_resampled_annulus_point_coordinates = np.concatenate(
                    [all_ordered_resampled_annulus_point_coordinates, ordered_resampled_annulus_point_coordinates])
            except Exception as e:
                import traceback
                logging.debug(traceback.format_exc())
                logging.warning(
                    "Skipping {0} valve {1} phase - {2}: {3}".format(valve_type, annulus_phase, annulus_filename, e))
                if stop_on_warning:
                    return False
                continue

        if all_ordered_resampled_annulus_point_coordinates.shape[0] == 0:
            logging.warning(
                "Skipping {0} valve {1} phase completely: no valid contour was found".format(valve_type, annulus_phase))
            continue

        all_annulus_point_coordinates = all_ordered_resampled_annulus_point_coordinates.reshape(-1, number_of_annulus_segments * number_of_points_per_segment, 3)

        # Correspondence between points in annulus points is already established by resampling based on landmarks.
        # For alignment of the contours we use all the points to minimize difference between all the points (not just between 4-6 landmark points).
        # PCA confirms that this leads to better alignment (less PCA modes can describe same amount of variance).
        annulus_to_mean_annulus_transforms = get_annulus_to_mean_annulus_transforms(all_annulus_point_coordinates)
        all_aligned_annulus_point_coordinates = align_annulus_contours(all_annulus_point_coordinates,
                                                                       annulus_to_mean_annulus_transforms)

        # Landmark points are the 0th, 100th, 200th, 300th points.
        landmark_points         =         all_annulus_point_coordinates[:,range(0, number_of_annulus_segments * number_of_points_per_segment, number_of_points_per_segment), :]
        aligned_landmark_points = all_aligned_annulus_point_coordinates[:,range(0, number_of_annulus_segments * number_of_points_per_segment, number_of_points_per_segment), :]

        # Compute normalization transform, which puts centroid of the mean annulus into the origin and aligns
        # axes based on principal labels
        annulus_to_world_transform = np.eye(4)
        if (principal_labels is not None) and (normalized_annulus_to_valve1_first_phase is not None):
            # Get the 4 principal landmarks of the mean contour

            try:

              principal_landmark_positions = np.zeros([4,3])
              for principal_landmark_index, principal_label in enumerate(principal_labels):
                  landmark_index = label_order.index(principal_label)
                  mean_landmark_position = np.mean(aligned_landmark_points[:, landmark_index, :], axis=0)
                  principal_landmark_positions[principal_landmark_index, :] = mean_landmark_position

              world_to_normalized_transform = get_world_to_normalized_transform(principal_landmark_positions)
              annulus_to_world_transform = np.dot(normalized_annulus_to_valve1_first_phase[valve_type][annulus_phase], world_to_normalized_transform)

            except Exception as e:
                import traceback
                logging.debug(traceback.format_exc())
                logging.warning(
                    "Skipping pose normalization for {0} valve {1} phase - {2}: {3}".format(valve_type, annulus_phase, annulus_filename, e))
                if stop_on_warning:
                    return False

        annulus_to_world_transform_vtk = vtk.vtkMatrix4x4()
        for row in range(3):
            for col in range(4):
                annulus_to_world_transform_vtk.SetElement(row, col, annulus_to_world_transform[row,col])

        annulus_to_world_transform_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTransformNode", "Annulus pose {0} {1}".format(valve_type, annulus_phase))
        annulus_to_world_transform_node.SetMatrixTransformToParent(annulus_to_world_transform_vtk)
        shNode.SetItemParent(shNode.GetItemByDataNode(annulus_to_world_transform_node), shRootFolderId)

        # Draw individual contours
        if draw_individual_annulus_contours:
            shSubFolderId = shNode.CreateFolderItem(shRootFolderId,
                                                    'aligned {0} {1} contours'.format(valve_type, annulus_phase))

            landmark_points_fiducials_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode",
                                                                                'aligned {0} {1} landmarks'.format(
                                                                                    valve_type, annulus_phase))
            landmark_points_fiducials_node.SetAndObserveTransformNodeID(annulus_to_world_transform_node.GetID())
            landmark_points_fiducials_node.CreateDefaultDisplayNodes()
            landmark_points_fiducials_display_node = landmark_points_fiducials_node.GetDisplayNode()
            landmark_points_fiducials_display_node.SetTextScale(0)
            landmark_points_fiducials_display_node.SetColor(individualColors[annulus_phase_index])
            landmark_points_fiducials_display_node.SetGlyphScale(
                landmark_points_fiducials_display_node.GetGlyphScale() / 2.)
            shNode.SetItemParent(shNode.GetItemByDataNode(landmark_points_fiducials_node), shSubFolderId)

            landmark_points_fiducials_node_modified = landmark_points_fiducials_node.StartModify()
            for case_index in range(all_aligned_annulus_point_coordinates.shape[0]):
                annulus_name = annulus_filenames[case_index] + " " + valve_type + " " + annulus_phase
                nodes = createTubeModelFromPointArray(all_aligned_annulus_point_coordinates[case_index],
                                                      color=individualColors[annulus_phase_index],
                                                      radius=individualTubeRadius, name=annulus_name)
                for node in nodes:
                    shNode.SetItemParent(shNode.GetItemByDataNode(node), shSubFolderId)
                    if node.IsA('vtkMRMLTransformableNode'):
                        node.SetAndObserveTransformNodeID(annulus_to_world_transform_node.GetID())

                for landmark_index, landmark_name in enumerate(label_order):
                    fid_index = landmark_points_fiducials_node.AddFiducial(
                        aligned_landmark_points[case_index, landmark_index, 0],
                        aligned_landmark_points[case_index, landmark_index, 1],
                        aligned_landmark_points[case_index, landmark_index, 2],
                        annulus_name + " " + landmark_name)
                    landmark_points_fiducials_node.SetNthFiducialSelected(fid_index, False)
            landmark_points_fiducials_node.EndModify(landmark_points_fiducials_node_modified)

            shNode.SetItemExpanded(shSubFolderId, False)

        if draw_original_contours:
            shSubFolderId = shNode.CreateFolderItem(shRootFolderId,
                                                    'original {0} {1} contours'.format(valve_type, annulus_phase))
            for case_index in range(all_annulus_point_coordinates.shape[0]):
                nodes = createTubeModelFromPointArray(all_annulus_point_coordinates[case_index],
                                                      color=individualColors[annulus_phase_index],
                                                      radius=individualTubeRadius,
                                                      name=annulus_filenames[
                                                               case_index] + " " + valve_type + " " + annulus_phase)
                for node in nodes:
                    shNode.SetItemParent(shNode.GetItemByDataNode(node), shSubFolderId)
                    if node.IsA('vtkMRMLTransformableNode'):
                        node.SetAndObserveTransformNodeID(annulus_to_world_transform_node.GetID())

            shNode.SetItemExpanded(shSubFolderId, False)

        # Draw mean contour
        mean_annulus_point_coordinates = np.mean(all_aligned_annulus_point_coordinates, axis=0)
        nodes = createTubeModelFromPointArray(mean_annulus_point_coordinates, color=meanColors[annulus_phase_index],
                                              radius=meanTubeRadius, name=valve_type + ' ' + annulus_phase + ' mean',
                                              keepGeneratorNodes=True) # allow changing radius
        for node in nodes:
            shNode.SetItemParent(shNode.GetItemByDataNode(node), shRootFolderId)
            if node.IsA('vtkMRMLTransformableNode'):
                node.SetAndObserveTransformNodeID(annulus_to_world_transform_node.GetID())


        # Draw mean landmarks
        mean_landmark_points_fiducials_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", valve_type + ' ' + annulus_phase + ' mean landmarks')
        mean_landmark_points_fiducials_node.SetAndObserveTransformNodeID(annulus_to_world_transform_node.GetID())
        mean_landmark_points_fiducials_node.CreateDefaultDisplayNodes()
        mean_landmark_points_fiducials_display_node = mean_landmark_points_fiducials_node.GetDisplayNode()
        # mean_landmark_points_fiducials_display_node.SetTextScale(0)
        mean_landmark_points_fiducials_display_node.SetColor(meanColors[annulus_phase_index])
        # mean_landmark_points_fiducials_display_node.SetGlyphScale(landmark_points_fiducials_display_node.GetGlyphScale() / 2.)
        shNode.SetItemParent(shNode.GetItemByDataNode(mean_landmark_points_fiducials_node), shRootFolderId)
        for landmark_index, landmark_name in enumerate(label_order):
            mean_landmark_position = np.mean(aligned_landmark_points[:, landmark_index, :], axis=0)
            fid_index = mean_landmark_points_fiducials_node.AddFiducial(mean_landmark_position[0],
                                                                   mean_landmark_position[1],
                                                                   mean_landmark_position[2],
                                                                   landmark_name)
            mean_landmark_points_fiducials_node.SetNthFiducialSelected(fid_index, False)

        if draw_pca:
            shSubFolderId = shNode.CreateFolderItem(shRootFolderId, 'PCA analysis {0} {1}'.format(valve_type, annulus_phase))

            pca_number_of_variation_steps = 2
            pca_variation_step_size = 1.0
            all_modes_annulus_point_coordinates = pca_analysis(all_aligned_annulus_point_coordinates,
                                                               number_of_variation_steps=2, variation_step_size=1.0)
            for mode_index in range(len(all_modes_annulus_point_coordinates)):
                shSubSubFolderId = shNode.CreateFolderItem(shSubFolderId, 'PCA mode {0}'.format(mode_index))
                for variation_step_index, variation_step in enumerate(range(-pca_number_of_variation_steps, pca_number_of_variation_steps+1)):
                    import colorsys
                    # Use slightly different color hue in proximal and distal regions
                    colorHsv = colorsys.rgb_to_hsv(*individualColors[annulus_phase_index])
                    # use 1.0 instead of colorHsv[2] to make the colors brighter
                    if variation_step >= 0:
                        color = colorsys.hsv_to_rgb(colorHsv[0] + variation_step * 0.1, colorHsv[1], 1.0)
                    else:
                        color = colorsys.hsv_to_rgb(colorHsv[0] + variation_step * 0.1 + 1, colorHsv[1], 1.0)

                    name = "PCA mode {0} {1}SD {2} {3}".format(mode_index, variation_step * pca_variation_step_size, valve_type,annulus_phase)
                    nodes = createTubeModelFromPointArray(all_modes_annulus_point_coordinates[mode_index][variation_step_index],
                                                          color=color,
                                                          visible=False,
                                                          radius=individualTubeRadius,
                                                          name=name)
                    for node in nodes:
                        shNode.SetItemParent(shNode.GetItemByDataNode(node), shSubSubFolderId)
                        if node.IsA('vtkMRMLTransformableNode'):
                            node.SetAndObserveTransformNodeID(annulus_to_world_transform_node.GetID())

                shNode.SetItemExpanded(shSubSubFolderId, False)

            shNode.SetItemExpanded(shSubFolderId, False)

    logging.info('Processing is completed')
    return True
