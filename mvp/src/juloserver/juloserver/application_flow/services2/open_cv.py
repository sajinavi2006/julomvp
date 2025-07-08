import math
from builtins import min, round

import cv2
import numpy as np

from juloserver.application_flow.constants import ImageKtpConstants

MAX_IMAGE_SIZE = 600
BKG_THRESH = 60


def resize_image_proportionally_to_height(image, height):
    ratio = float(height) / float(image.shape[0])
    width = round(ratio * image.shape[1])
    dim = (width, height)

    resized_image = cv2.resize(image, dim)
    return resized_image


def scale_down_image(image):
    ratio = min(
        float(MAX_IMAGE_SIZE) / float(image.shape[1]), float(MAX_IMAGE_SIZE) / float(image.shape[0])
    )
    width = round(ratio * image.shape[1])
    height = round(ratio * image.shape[0])
    dim = (width, height)

    resized_image = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)

    return image, resized_image


def image_check_blur(image, blur_threshold, scaled_image=None):
    if scaled_image is not None:
        image = scaled_image

    # CONVERTING IN TO GRAY-SCALE IMAGE
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    lap = cv2.Laplacian(gray, cv2.CV_64F)

    median, std = cv2.meanStdDev(lap)

    blur_value = math.pow(std[0][0], 2.0)

    # CONDITION : VARIANCE OF LAPLACIAN MATRIX
    if blur_value < blur_threshold:
        return True, blur_value
    else:
        return False, blur_value


def image_check_glare(image, glare_threshold, limit_pct, scaled_image=None):
    if scaled_image is not None:
        image = scaled_image

    # CONVERTING IN TO GRAY-SCALE IMAGE
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # APPLYNG BINARY THRESHOLDING FOR BRIGHT SPOT
    binary = cv2.threshold(gray, glare_threshold, 255, cv2.THRESH_BINARY)[1]

    all_area = len(binary) * len(binary[0])
    glare_area = cv2.countNonZero(binary)
    white_pct = (float(glare_area) / float(all_area)) * 100.0

    # CONDITION : VARIANCE OF BINARY MATRIX
    if white_pct >= limit_pct:
        return True, white_pct
    else:
        return False, white_pct


def image_check_dark(
    image, limit_black_bin, black_pct, limit_white_bin, white_pct, scaled_image=None
):
    if scaled_image is not None:
        image = scaled_image

    # CONVERTING IN TO GRAY-SCALE IMAGE
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [8], [0, 256])
    black_spot = calculate_black_spot(hist, limit_black_bin)
    all_area = len(image) * len(image[0])
    blacks = black_spot / all_area * 100
    is_dark = False
    if blacks >= black_pct:
        white_spot = calculate_white_spot(hist, limit_black_bin, limit_white_bin)
        whites = white_spot / all_area * 100
        if whites < white_pct:
            is_dark = True

    if is_dark:
        return True, blacks
    else:
        return False, blacks


def calculate_black_spot(histogram, limit):
    total = 0
    iteration = 0
    for row in histogram:
        value = np.sum(row)
        total += value
        iteration += 1
        if iteration == limit:
            break

    return total


def calculate_white_spot(histogram, limit_black, limit_white):
    limit = limit_black if limit_white < limit_black else limit_white
    total = 0
    for i in range(limit, len(histogram)):
        value = np.sum(histogram[i])
        total += value

    return total


def crop_based_on_edge_detection(image):
    image_orig, image = scale_down_image(image=image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gaus = cv2.GaussianBlur(gray, (5, 5), 0)

    edge = cv2.Canny(gaus, 30.0, 90.0)
    # Finding contours
    suspected_cnt = find_ktp_guideline(edge)
    if suspected_cnt is None:
        return None, None

    copy_image = image.copy()
    cv2.drawContours(copy_image, suspected_cnt, -1, (0, 255, 0), 3)

    sorted_cnt, coordinate_points = sort_point(suspected_cnt)

    transformed_image = do_perspective_transform(sorted_cnt, image)
    coordinates_response = build_coordinates_response(coordinate_points)
    transformed_image = cv2.rotate(transformed_image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    transformed_image = cv2.flip(transformed_image, 0)
    return transformed_image, coordinates_response


def do_perspective_transform(sorted_cnt, image_ori):
    # Extract points
    top_left = sorted_cnt[0][0]
    top_right = sorted_cnt[1][0]
    btm_right = sorted_cnt[2][0]
    btm_left = sorted_cnt[3][0]

    width_a = int(
        math.sqrt(math.pow(btm_right[0] - btm_left[0], 2) + math.pow(btm_right[1] - btm_left[1], 2))
    )
    width_b = int(
        math.sqrt(math.pow(top_right[0] - top_left[0], 2) + math.pow(top_right[1] - top_left[1], 2))
    )

    height_a = int(
        math.sqrt(
            math.pow(top_right[0] - btm_right[0], 2) + math.pow(top_right[1] - btm_right[1], 2)
        )
    )
    height_b = int(
        math.sqrt(math.pow(top_left[0] - btm_left[0], 2) + math.pow(top_left[1] - btm_left[1], 2))
    )
    max_width = max(width_a, width_b)
    max_height = max(height_a, height_b)
    dst = np.zeros((4, 1, 2), np.float32)
    dst[0][0] = [0, 0]
    dst[1][0] = [max_width - 1, 0]
    dst[2][0] = [max_width - 1, max_height - 1]
    dst[3][0] = [0, max_height - 1]

    transformed_cnt = cv2.getPerspectiveTransform(sorted_cnt, dst)
    return cv2.warpPerspective(image_ori, transformed_cnt, (max_width, max_height))


def get_first_point_by_sum_and_delete_from_list(dst_dict, point_sum):
    for key in dst_dict.keys():
        if dst_dict[key][0] == point_sum:
            point = dst_dict[key][1]
            del dst_dict[key]
            return point


def sort_point(src):
    dst = np.zeros((4, 1, 2), np.float32)
    point1 = src[0][0]
    point2 = src[1][0]
    point3 = src[2][0]
    point4 = src[3][0]
    dst_dict = {
        1: (np.sum(point1), point1),
        2: (np.sum(point2), point2),
        3: (np.sum(point3), point3),
        4: (np.sum(point4), point4),
    }
    # get the most max and min
    list_of_point_sum = [x[0] for x in dst_dict.values()]
    mins = min(list_of_point_sum)
    dst[0][0] = get_first_point_by_sum_and_delete_from_list(dst_dict, mins)
    maxs = max(list_of_point_sum)
    dst[2][0] = get_first_point_by_sum_and_delete_from_list(dst_dict, maxs)

    # second level max and min
    list_of_point_sum = [x[0] for x in dst_dict.values()]
    mins = min(list_of_point_sum)
    dst[1][0] = get_first_point_by_sum_and_delete_from_list(dst_dict, mins)
    maxs = max(list_of_point_sum)
    dst[3][0] = get_first_point_by_sum_and_delete_from_list(dst_dict, maxs)
    coordinate_points = [point1, point2, point3, point4]
    return dst, coordinate_points


def build_coordinates_response(points):
    response = {}
    for i, point in enumerate(points):
        response['p' + str(i + 1)] = {'x': int(point[0]), 'y': int(point[1])}
    return response


def build_image_arrays(raw_ktp_image, ktp_image):
    try:
        raw_ktp_image_array = cv2.imdecode(
            np.fromstring(raw_ktp_image.read(), np.uint8), cv2.IMREAD_UNCHANGED
        )
        ktp_image_array = cv2.imdecode(
            np.fromstring(ktp_image.read(), np.uint8), cv2.IMREAD_UNCHANGED
        )
        return raw_ktp_image_array, ktp_image_array
    except Exception:
        return None, None


def find_ktp_guideline(image):
    contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    sorted_contour = sorted(contours, key=lambda contour: cv2.contourArea(contour), reverse=True)
    suspected_cnt = None
    for cnt in sorted_contour:
        arc_length = cv2.arcLength(cnt, True)
        epsilon = 0.1 * arc_length
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        if len(approx) == 4:
            suspected_cnt = approx
            break
    return suspected_cnt


def is_ktp_detected(image):
    height, width, chanel = image.shape
    image_ratio = max(height, width) / min(height, width)
    image_resolution = height * width
    if (
        ImageKtpConstants.MIN_KTP_RATIO < image_ratio < ImageKtpConstants.MAX_KTP_RATIO
        and image_resolution >= ImageKtpConstants.MIN_KTP_RESOLUTION
    ):
        return True
    return False
