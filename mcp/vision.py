"""
vision.py – Element detection utilities for the DesktopControllerMCP-MCP project (v0.1.5).

Provides template matching (OpenCV) and an optional YOLOv8 detector
for identifying UI elements or objects within images.
"""
from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod
from dataclasses import dataclass # slots=True can offer minor perf gains
from typing import Sequence # For Python 3.9+ can use list, tuple directly for Sequence type hints

# Third-party library imports
import numpy as np # type: ignore[import-untyped]
from PIL import Image # type: ignore[import-untyped]

# Local package imports
from mcp.logger import get_logger

logger = get_logger(__name__)

# --- Optional Dependency: OpenCV ---
try:
    import cv2 # type: ignore[import-untyped]
    OPENCV_AVAILABLE = True
except ImportError:  # pragma: no cover
    logger.warning(
        "OpenCV (cv2) not found. TemplateMatching detector will not be available. "
        "Install with `pip install opencv-python`."
    )
    cv2 = None # type: ignore
    OPENCV_AVAILABLE = False

# --- Type Aliases (using Python 3.12 'type' statement - PEP 695) ---
type BBox = tuple[int, int, int, int]  # (x_top_left, y_top_left, width, height)

# --- Custom Exception Classes ---
class VisionError(Exception):
    """Base class for errors specific to the vision module."""
    pass

class TemplateNotFoundError(VisionError):
    """Raised when a template image file cannot be found or loaded."""
    pass

class DetectionError(VisionError):
    """Raised when an error occurs during the detection process itself."""
    pass

class PrerequisitesError(VisionError):
    """Raised when a required library for a detector is not available."""
    pass

# --- Detection Result Dataclass ---
@dataclass(slots=True, frozen=True) # frozen=True makes instances immutable
class Detection:
    """
    Represents a single detected object or template match.

    Attributes:
        bbox: The bounding box (x_top_left, y_top_left, width, height)
              of the detection in absolute coordinates of the searched image.
        score: The confidence score of the detection (typically 0.0 to 1.0).
        class_id: Optional class identifier (e.g., for YOLO detections).
        class_name: Optional human-readable class name.
    """
    bbox: BBox
    score: float
    class_id: int | None = None
    class_name: str | None = None

    @property
    def center(self) -> tuple[int, int]:
        """Calculates the center point (x, y) of the bounding box."""
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)

# --- Abstract Base Class for Detectors ---
class Detector(ABC):
    """Abstract base class for all detection backends."""

    @abstractmethod
    def detect(self, image: Image.Image) -> list[Detection]:
        """
        Detects all occurrences of target objects/templates in the given image.

        Args:
            image: A PIL.Image.Image object to perform detection on.

        Returns:
            A list of Detection objects, typically sorted by score in descending order.
            Returns an empty list if no detections are found.

        Raises:
            DetectionError: If a non-recoverable error occurs during the detection process.
            PrerequisitesError: If a required dependency for this detector is missing.
            TypeError: If the input image is not of the expected type.
        """
        pass

# --- Template Matching Detector (OpenCV-based) ---
class TemplateMatcher(Detector):
    """
    Performs template matching using OpenCV.
    Finds occurrences of a smaller template image within a larger source image.
    """
    DEFAULT_THRESHOLD: float = 0.8
    # Common OpenCV template matching methods. TM_CCOEFF_NORMED is often a good default.
    MATCH_METHODS: dict[str, int] = {
        "TM_SQDIFF": cv2.TM_SQDIFF if OPENCV_AVAILABLE else 0,
        "TM_SQDIFF_NORMED": cv2.TM_SQDIFF_NORMED if OPENCV_AVAILABLE else 1,
        "TM_CCORR": cv2.TM_CCORR if OPENCV_AVAILABLE else 2,
        "TM_CCORR_NORMED": cv2.TM_CCORR_NORMED if OPENCV_AVAILABLE else 3,
        "TM_CCOEFF": cv2.TM_CCOEFF if OPENCV_AVAILABLE else 4,
        "TM_CCOEFF_NORMED": cv2.TM_CCOEFF_NORMED if OPENCV_AVAILABLE else 5,
    } if OPENCV_AVAILABLE else {}


    def __init__(
        self,
        template_source: str | pathlib.Path | Image.Image | np.ndarray,
        threshold: float = DEFAULT_THRESHOLD,
        match_method_name: str = "TM_CCOEFF_NORMED",
        max_results: int | None = None,
        multiscale_factors: Sequence[float] | None = None, # e.g., [0.8, 1.0, 1.2]
    ) -> None:
        """
        Initializes the TemplateMatcher.

        Args:
            template_source: Path to the template image file (str or Path),
                             a PIL.Image object, or a pre-loaded NumPy array (grayscale).
            threshold: Minimum confidence score (0.0-1.0) for a match to be considered valid.
            match_method_name: Name of the OpenCV template matching method to use
                               (e.g., "TM_CCOEFF_NORMED").
            max_results: Optional maximum number of results to return.
            multiscale_factors: Optional sequence of scaling factors to apply to the template
                                for multi-scale matching. If None, only original scale is used.
        """
        if not OPENCV_AVAILABLE:
            raise PrerequisitesError("OpenCV (cv2) is required for TemplateMatcher but not found.")

        if not (0.0 <= threshold <= 1.0):
            raise ValueError("Threshold must be between 0.0 and 1.0.")
        self.threshold = threshold

        selected_method = self.MATCH_METHODS.get(match_method_name.upper())
        if selected_method is None:
            raise ValueError(f"Invalid OpenCV match_method_name: '{match_method_name}'. "
                             f"Available methods: {list(self.MATCH_METHODS.keys())}")
        self.cv2_match_method = selected_method

        self.max_results = max_results
        self.scale_factors = list(multiscale_factors) if multiscale_factors else [1.0]
        if not all(isinstance(s, (int, float)) and s > 0 for s in self.scale_factors):
            raise ValueError("All multiscale_factors must be positive numbers.")

        self._template_name: str
        self.template_img_gray: np.ndarray # Stored as grayscale NumPy array

        if isinstance(template_source, np.ndarray):
            self._template_name = f"numpy_array_shape_{template_source.shape}"
            if template_source.ndim == 3: # Ensure grayscale
                self.template_img_gray = cv2.cvtColor(template_source, cv2.COLOR_BGR2GRAY)
            elif template_source.ndim == 2:
                self.template_img_gray = template_source
            else:
                raise ValueError("NumPy template array must be 2D (grayscale) or 3D (BGR).")
        elif isinstance(template_source, Image.Image):
            self._template_name = f"PIL_image_mode_{template_source.mode}_size_{template_source.size}"
            pil_gray = template_source.convert("L") # Convert to grayscale PIL image
            self.template_img_gray = np.array(pil_gray, dtype=np.uint8)
        elif isinstance(template_source, (str, pathlib.Path)):
            template_path = pathlib.Path(template_source)
            self._template_name = str(template_path.name)
            if not template_path.exists() or not template_path.is_file():
                raise TemplateNotFoundError(f"Template image file not found: {template_path}")
            # Load image directly in grayscale using OpenCV
            self.template_img_gray = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
            if self.template_img_gray is None:
                raise TemplateNotFoundError(f"Failed to load template image from {template_path}. "
                                            "Ensure it's a valid image format readable by OpenCV.")
        else:
            raise TypeError("template_source must be a file path, PIL.Image, or NumPy array. "
                            f"Received: {type(template_source)}")

        if self.template_img_gray.size == 0 or self.template_img_gray.shape[0] == 0 or self.template_img_gray.shape[1] == 0:
            raise VisionError(f"Template '{self._template_name}' is empty or has zero dimensions after loading.")

        self.th, self.tw = self.template_img_gray.shape[:2] # Template height, width
        logger.debug(f"TemplateMatcher initialized for '{self._template_name}' (WxH: {self.tw}x{self.th}), "
                     f"Method: {match_method_name}, Threshold: {self.threshold}, Scales: {self.scale_factors}")

    def _match_at_scale(self, image_gray: np.ndarray, template_scaled_gray: np.ndarray) -> list[Detection]:
        """Performs template matching for a single scaled template."""
        th_s, tw_s = template_scaled_gray.shape[:2] # Scaled template height, width

        # Check if scaled template is larger than the image or has zero dimensions
        if th_s == 0 or tw_s == 0 or th_s > image_gray.shape[0] or tw_s > image_gray.shape[1]:
            logger.debug(f"Skipping scale: scaled template (WxH {tw_s}x{th_s}) is incompatible with image "
                         f"(WxH {image_gray.shape[1]}x{image_gray.shape[0]}).")
            return []

        try:
            # result_matrix dimensions: (ImageHeight - TemplateHeight + 1, ImageWidth - TemplateWidth + 1)
            result_matrix = cv2.matchTemplate(image_gray, template_scaled_gray, self.cv2_match_method)
        except cv2.error as e_cv:
            logger.error(f"OpenCV error during matchTemplate: {e_cv}")
            raise DetectionError(f"cv2.matchTemplate failed: {e_cv}") from e_cv

        detections: list[Detection] = []
        # For methods like TM_SQDIFF and TM_SQDIFF_NORMED, lower values are better matches.
        # For TM_CCORR_NORMED and TM_CCOEFF_NORMED, higher values are better.
        if self.cv2_match_method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
            # Find locations where match score is *below* (1.0 - threshold) for normed, or a heuristic for non-normed
            # This part needs careful handling based on the method.
            # For simplicity, let's assume methods where higher is better for now.
            # If using SQDIFF, threshold logic needs inversion.
            # This example proceeds assuming higher score = better match.
            loc_y_coords, loc_x_coords = np.where(result_matrix >= self.threshold)
        else: # TM_CCORR_NORMED, TM_CCOEFF_NORMED etc.
            loc_y_coords, loc_x_coords = np.where(result_matrix >= self.threshold)

        for pt_y, pt_x in zip(loc_y_coords, loc_x_coords):
            score = float(result_matrix[pt_y, pt_x])
            bbox: BBox = (pt_x, pt_y, tw_s, th_s) # (left, top, width, height)
            detections.append(Detection(bbox=bbox, score=score))

            if self.max_results is not None and len(detections) >= self.max_results:
                logger.debug(f"Reached max_results ({self.max_results}) for current scale.")
                break
        return detections

    def detect(self, image: Image.Image) -> list[Detection]:
        if not isinstance(image, Image.Image):
            raise TypeError(f"Input image must be a PIL.Image.Image, got {type(image)}")
        if not OPENCV_AVAILABLE: # Should have been caught in __init__
            raise PrerequisitesError("OpenCV (cv2) is not available for detection.")

        try:
            # Convert source PIL image to grayscale NumPy array
            source_img_pil_gray = image.convert("L")
            source_img_cv_gray = np.array(source_img_pil_gray, dtype=np.uint8)
        except Exception as e_conv:
            logger.error(f"Failed to convert input PIL image to OpenCV format: {e_conv}", exc_info=True)
            raise DetectionError(f"Image conversion failed: {e_conv}") from e_conv

        if source_img_cv_gray.ndim != 2:
             raise DetectionError("Converted input image is not grayscale as expected.")

        all_detections: list[Detection] = []
        for scale in self.scale_factors:
            if scale == 1.0:
                current_template_gray = self.template_img_gray
            else:
                new_width = int(self.tw * scale)
                new_height = int(self.th * scale)
                if new_width <= 0 or new_height <= 0:
                    logger.debug(f"Skipping scale {scale}: results in zero-size template ({new_width}x{new_height}).")
                    continue
                try:
                    # Interpolation: INTER_AREA for shrinking, INTER_CUBIC/LANCZOS4 for enlarging
                    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
                    current_template_gray = cv2.resize(self.template_img_gray, (new_width, new_height), interpolation=interp)
                except cv2.error as e_resize:
                    logger.warning(f"Could not resize template for scale {scale}: {e_resize}. Skipping scale.")
                    continue

            scale_detections = self._match_at_scale(source_img_cv_gray, current_template_gray)
            all_detections.extend(scale_detections)

            # Optional: If max_results is hit across all scales, could break early
            if self.max_results is not None and len(all_detections) >= self.max_results * len(self.scale_factors): # Heuristic
                 logger.debug("Potential early exit due to reaching a high number of raw detections.")
                 # This needs to be balanced with the NMS step later.

        if not all_detections:
            logger.debug(f"No raw detections found for template '{self._template_name}' across all scales.")
            return []

        # Apply Non-Maximum Suppression (NMS) to merge overlapping boxes
        try:
            # NMS typically benefits from scores where higher is better.
            # If using TM_SQDIFF, scores might need inversion before NMS or custom NMS.
            final_detections = _non_maximum_suppression(all_detections, iou_threshold=0.3)
        except Exception as e_nms:
            logger.error(f"Error during Non-Maximum Suppression: {e_nms}", exc_info=True)
            # Fallback: return all raw detections or re-raise as DetectionError
            raise DetectionError(f"NMS processing failed: {e_nms}") from e_nms

        # Sort final detections by score (descending)
        final_detections.sort(key=lambda d: d.score, reverse=True)

        if self.max_results is not None:
            final_detections = final_detections[:self.max_results]

        logger.info(f"Template '{self._template_name}': Found {len(all_detections)} raw detections, "
                    f"{len(final_detections)} after NMS and max_results limit.")
        return final_detections

# --- YOLOv8 Detector (Optional, requires 'ultralytics' package) ---
class YOLODetector(Detector):
    """
    Object detector using Ultralytics YOLOv8 models.
    Requires the `ultralytics` package to be installed.
    """
    _model_instance_cache: dict[str, Any] = {} # Class-level cache for YOLO model instances

    def __init__(self, model_path: str | pathlib.Path, confidence_threshold: float = 0.25):
        """
        Initializes the YOLODetector.

        Args:
            model_path: Path to the YOLOv8 model file (e.g., '.pt', '.onnx').
            confidence_threshold: Minimum confidence score for a detection to be considered.
        """
        try:
            from ultralytics import YOLO # type: ignore[import-untyped]
        except ImportError:  # pragma: no cover
            logger.error("Ultralytics package not found. YOLODetector is unavailable. "
                         "Install with `pip install ultralytics` or `poetry install --extras yolo`.")
            raise PrerequisitesError("Ultralytics package not installed. YOLODetector cannot be used.")

        self.model_path_str = str(model_path)
        self.confidence_threshold = confidence_threshold
        self.model_names: list[str] | None = None # To store class names

        # Cache YOLO model instances to avoid reloading from disk repeatedly if the same model is used.
        if self.model_path_str in YOLODetector._model_instance_cache:
            self.yolo_model = YOLODetector._model_instance_cache[self.model_path_str]
            logger.debug(f"Using cached YOLOv8 model from: {self.model_path_str}")
        else:
            logger.debug(f"Loading YOLOv8 model from: {self.model_path_str}")
            try:
                self.yolo_model = YOLO(self.model_path_str) # This loads the model
                # Attempt to get class names
                if hasattr(self.yolo_model, 'names') and isinstance(self.yolo_model.names, (dict, list)):
                    if isinstance(self.yolo_model.names, dict): # Often names is a dict {index: name}
                        self.model_names = [self.yolo_model.names[i] for i in sorted(self.yolo_model.names.keys())]
                    else: # If it's already a list
                        self.model_names = self.yolo_model.names
                YOLODetector._model_instance_cache[self.model_path_str] = self.yolo_model
            except Exception as e_load:
                logger.error(f"Failed to load YOLO model from '{self.model_path_str}': {e_load}", exc_info=True)
                raise VisionError(f"YOLO model loading failed: {e_load}") from e_load
        logger.info(f"YOLOv8 detector initialized with model '{self.model_path_str}', threshold {self.confidence_threshold}.")


    def detect(self, image: Image.Image) -> list[Detection]:
        if not isinstance(image, Image.Image):
            raise TypeError(f"Input image must be a PIL.Image.Image, got {type(image)}")

        try:
            # YOLO's `predict` method can often handle PIL Images directly.
            # `imgsz` can be tuned; using original image size by default.
            # `verbose=False` reduces console output from Ultralytics.
            yolo_results = self.yolo_model.predict(
                source=image,
                conf=self.confidence_threshold,
                verbose=False,
                # imgsz=max(image.size) # Can specify if resizing is desired
            )
        except Exception as e_pred:
            logger.error(f"YOLO prediction failed for model '{self.model_path_str}': {e_pred}", exc_info=True)
            raise DetectionError(f"YOLO prediction error: {e_pred}") from e_pred

        detections: list[Detection] = []
        if yolo_results: # yolo_results is a list of Results objects (usually one per image)
            for result_item in yolo_results: # Iterate through each image's results
                if result_item.boxes: # Check if there are any bounding boxes
                    # result_item.boxes.xywh: (center_x, center_y, width, height) - PyTorch tensor
                    # result_item.boxes.conf: confidence scores - PyTorch tensor
                    # result_item.boxes.cls: class indices - PyTorch tensor
                    for box_data_xywh, score_tensor, cls_tensor in zip(result_item.boxes.xywh, result_item.boxes.conf, result_item.boxes.cls):
                        box_list = box_data_xywh.tolist() # [x_center, y_center, w, h]
                        score = float(score_tensor.item())
                        class_id = int(cls_tensor.item())
                        class_name: str | None = None
                        if self.model_names and 0 <= class_id < len(self.model_names):
                            class_name = self.model_names[class_id]
                        else:
                            class_name = f"class_{class_id}" # Fallback name


                        x_center, y_center, w_val, h_val = box_list
                        # Convert center_x, center_y, width, height to top-left_x, top-left_y, width, height
                        x_tl = int(x_center - w_val / 2)
                        y_tl = int(y_center - h_val / 2)
                        bbox: BBox = (x_tl, y_tl, int(w_val), int(h_val))
                        detections.append(Detection(bbox=bbox, score=score, class_id=class_id, class_name=class_name))

        # YOLO results are typically sorted by confidence, but explicitly sort to ensure.
        detections.sort(key=lambda d: d.score, reverse=True)
        logger.debug(f"YOLO detector '{self.model_path_str}' found {len(detections)} detections.")
        return detections

# --- Convenience Wrapper Functions ---
def locate(image: Image.Image, detector: Detector) -> Detection | None:
    """
    Finds the **best** detection (highest score) using the given detector.

    Args:
        image: The PIL.Image.Image to search in.
        detector: An instance of a `Detector` subclass (e.g., TemplateMatcher, YOLODetector).

    Returns:
        The `Detection` object with the highest score, or `None` if no detections are found
        or an error occurs.
    """
    try:
        detections = detector.detect(image) # Detector should sort by score descending
        return detections[0] if detections else None
    except (DetectionError, PrerequisitesError, TypeError) as e_locate: # Catch known errors from detect()
        logger.warning(f"Detection failed during locate(): {type(e_locate).__name__} - {e_locate}")
        return None
    except Exception as e_unhandled: # Catch any other unexpected errors
        logger.error(f"Unexpected error in locate(): {e_unhandled}", exc_info=True)
        return None

def locate_all(
    image: Image.Image,
    detector: Detector,
    min_score: float | None = None,
) -> list[Detection]:
    """
    Finds all detections using the given detector, optionally filtered by a minimum score.

    Args:
        image: The PIL.Image.Image to search in.
        detector: An instance of a `Detector` subclass.
        min_score: If provided, only detections with a score >= min_score will be returned.

    Returns:
        A list of `Detection` objects, sorted by score in descending order.
        Returns an empty list if no detections meet the criteria or an error occurs.
    """
    try:
        detections = detector.detect(image) # Detector should sort by score descending
        if min_score is not None:
            if not (0.0 <= min_score <= 1.0):
                logger.warning(f"Invalid min_score ({min_score}) in locate_all. It should be between 0.0 and 1.0. Ignoring filter.")
            else:
                detections = [d for d in detections if d.score >= min_score]
        return detections
    except (DetectionError, PrerequisitesError, TypeError) as e_locate_all:
        logger.warning(f"Detection failed during locate_all(): {type(e_locate_all).__name__} - {e_locate_all}")
        return []
    except Exception as e_unhandled:
        logger.error(f"Unexpected error in locate_all(): {e_unhandled}", exc_info=True)
        return []

# --- Non-Maximum Suppression (NMS) Helper ---
def _non_maximum_suppression(detections: Sequence[Detection], iou_threshold: float = 0.3) -> list[Detection]:
    """
    Simple Non-Maximum Suppression (NMS) to merge overlapping detections.
    Assumes detections are already sorted by score if a score-based picking strategy is implicit.

    Args:
        detections: A sequence of `Detection` objects.
        iou_threshold: Intersection over Union (IoU) threshold. Detections with IoU
                       greater than this threshold with a higher-scored detection
                       will be suppressed.

    Returns:
        A list of `Detection` objects after applying NMS.
    """
    if not detections:
        return []
    if not isinstance(detections, Sequence) or not all(isinstance(d, Detection) for d in detections):
        logger.error("NMS input must be a sequence of Detection objects.")
        return list(detections) # Or raise error

    # Convert BBox from (x, y, w, h) to (x1, y1, x2, y2) for easier IoU calculation
    # and extract scores.
    # Using np.float32 for boxes for potential performance with np operations.
    _boxes_xywh = np.array([d.bbox for d in detections], dtype=np.float32)
    if _boxes_xywh.size == 0: return []

    _scores = np.array([d.score for d in detections], dtype=np.float32)

    x1 = _boxes_xywh[:, 0]
    y1 = _boxes_xywh[:, 1]
    x2 = _boxes_xywh[:, 0] + _boxes_xywh[:, 2] # x + width
    y2 = _boxes_xywh[:, 1] + _boxes_xywh[:, 3] # y + height

    areas = _boxes_xywh[:, 2] * _boxes_xywh[:, 3] # width * height

    # Sort by score in descending order (indices)
    order = _scores.argsort()[::-1]

    kept_indices: list[int] = []
    while order.size > 0:
        current_idx = order[0] # Index of the current highest-score detection
        kept_indices.append(current_idx)

        if order.size == 1: # No more detections to compare with
            break

        # Get coordinates of the remaining boxes
        remaining_indices = order[1:]
        xx1 = np.maximum(x1[current_idx], x1[remaining_indices])
        yy1 = np.maximum(y1[current_idx], y1[remaining_indices])
        xx2 = np.minimum(x2[current_idx], x2[remaining_indices])
        yy2 = np.minimum(y2[current_idx], y2[remaining_indices])

        # Calculate width and height of intersection boxes
        inter_w = np.maximum(0.0, xx2 - xx1)
        inter_h = np.maximum(0.0, yy2 - yy1)
        intersection_area = inter_w * inter_h

        # Calculate IoU (Intersection over Union)
        iou = intersection_area / (areas[current_idx] + areas[remaining_indices] - intersection_area + 1e-7) # Epsilon for stability

        # Keep detections that have an IoU less than or equal to the threshold
        indices_to_keep_for_next_round = np.where(iou <= iou_threshold)[0]

        # Update 'order' to only include these non-overlapping detections for the next iteration
        # Note: indices_to_keep_for_next_round are indices relative to 'remaining_indices'
        order = remaining_indices[indices_to_keep_for_next_round]

    # Return the actual Detection objects corresponding to the kept indices
    return [detections[i] for i in kept_indices]