# AUTOGENERATED! DO NOT EDIT! File to edit: notebooks/02_Model.ipynb (unless otherwise specified).

__all__ = ['train_one_epoch', 'show_prediction', 'show_predictions', 'iou_metric_mask_pair',
           'iou_metric_matrix_of_example', 'largest_values_in_row_colums', 'iou_metric_example', 'iou_metric',
           'show_predictions_sorted_by_iou']

# Cell

from pathlib import Path
from typing import List, Tuple, Union, Optional, Dict, Set

# Internal Cell

import numpy as np
import pandas as pd
from datetime import datetime
import PIL
from PIL import Image
from zipfile import ZipFile
import random
import math
import sys

import torch
import torch.utils.data
from torch.hub import download_url_to_file

import torchvision
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor
from torchvision.transforms import ToPILImage

from ..datasets import stack_imgs
from dolphins_recognition_challenge import utils

from ..datasets import get_dataset

device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")

# Cell

def train_one_epoch(
    model,
    optimizer,
    data_loader,
    device,
    epoch,
    print_freq=10,
):
    """ Trains one epoch of the model. Copied from the reference implementation from https://github.com/pytorch/vision.git.
    """
    model.train()
    metric_logger = utils.MetricLogger(delimiter="  ")
    metric_logger.add_meter('lr', utils.SmoothedValue(window_size=1, fmt='{value:.6f}'))
    header = 'Epoch: [{}]'.format(epoch)

    lr_scheduler = None
    if epoch == 0:
        warmup_factor = 1. / 1000
        warmup_iters = min(1000, len(data_loader) - 1)

        lr_scheduler = utils.warmup_lr_scheduler(optimizer, warmup_iters, warmup_factor)

    for images, targets in metric_logger.log_every(data_loader, print_freq, header):
        images = list(image.to(device) for image in images)
        targets = [{k: v.to(device) for k, v in t.items()} for t in targets]

        loss_dict = model(images, targets)

        losses = sum(loss for loss in loss_dict.values())

        # reduce losses over all GPUs for logging purposes
        loss_dict_reduced = utils.reduce_dict(loss_dict)
        losses_reduced = sum(loss for loss in loss_dict_reduced.values())

        loss_value = losses_reduced.item()

        if not math.isfinite(loss_value):
            print("Loss is {}, stopping training".format(loss_value))
            print(loss_dict_reduced)
            sys.exit(1)

        optimizer.zero_grad()
        losses.backward()
        optimizer.step()

        if lr_scheduler is not None:
            lr_scheduler.step()

        metric_logger.update(loss=losses_reduced, **loss_dict_reduced)
        metric_logger.update(lr=optimizer.param_groups[0]["lr"])

    return loss_value


# Cell

def show_prediction(
    model,
    img: torch.Tensor(),
    *,
    score_threshold: float=0.5,
    width: int=820
) -> None:
    """ Show a single prediction by the model
    """
    device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")

    # convert Tensor to PIL Image
    img_bg = Image.fromarray(img.mul(255).permute(1, 2, 0).byte().numpy())
    images = [img_bg]

    model.eval()
    with torch.no_grad():
        prediction = model([img.to(device)])
    predicted_masks = prediction[0]["masks"]
    scores = prediction[0]["scores"]

    for i in range(predicted_masks.shape[0]):
        score = scores[i]
        if score >= score_threshold:
            bg = img_bg.copy()
            fg = Image.fromarray(predicted_masks[i, 0].mul(255).byte().cpu().numpy())
            bg.paste(fg.convert("RGB"), (0, 0), fg)
            images.append(bg)

    display(stack_imgs(images, width))


# Cell

def show_predictions(
    model,
    *,
    data_loader=None,
    dataset=None,
    n=None,
    score_threshold=0.5,
    iou_df=None,
    width=820
):
    """ Show at most `n` predictions for examples in a given data loader.
    """
    assert (data_loader is None) ^ (dataset is None), f"only one of dataloader ({dataloader}) and dataset({dataset}) must be defined"

    if data_loader:
        dataset = data_loader.dataset

    if n == None:
        n = len(dataset)
    else:
        n = min(n, len(dataset))

    for i in range(n):
        if iou_df is not None:
            print(f"IOU metric: {iou_df['iou'].iloc[i]}")
        show_prediction(model, img=dataset[i][0], score_threshold=score_threshold, width=width)

# Internal Cell

def get_true_and_predicted_masks(
    model: torchvision.models.detection.mask_rcnn.MaskRCNN,
    example: Tuple[torch.Tensor, Dict[str, torch.Tensor]],
    score_threshold: float = 0.5,
) -> Tuple[PIL.Image.Image, Dict[str, np.array]]:
    """ Returns a PIL image and dictionary containing both true and predicted masks as numpy arrays.
    """

    img = example[0]

    true_masks = (
        example[1]["masks"].mul(255).cpu().numpy().astype(np.int8)
    )

    model.eval()
    with torch.no_grad():
        predictions = model([img.to(device)])

    pred_scores = predictions[0]["scores"].cpu().numpy()

    pred_masks = predictions[0]["masks"].squeeze(1).mul(255).cpu().numpy().astype(np.int8)
    pred_masks = np.squeeze(pred_masks[np.argwhere(pred_scores >= score_threshold), :, :], 1)

    return ToPILImage()(img), {"true": true_masks, "predicted": pred_masks}

# Cell

def iou_metric_mask_pair(
    binary_segmentation: np.array,
    binary_gt_label: np.array,
) -> float:
    """
    Compute the IOU between two binary segmentation (typically one ground truth and a predicted one).
    Input:
        binary_segmentation: binary 2D numpy array representing the region of interest as segmented by the algorithm
        binary_gt_label: binary 2D numpy array representing the region of interest as provided in the database
    Output:
        IOU: IOU between the segmentation and the ground truth
    """

    assert binary_segmentation.dtype in [np.int, np.int8, np.int16, np.int32, np.bool]
    assert binary_gt_label.dtype in [np.int, np.int8, np.int16, np.int32, np.bool]
    assert len(binary_segmentation.shape) == 2
    assert len(binary_gt_label.shape) == 2

    # turn all variables to booleans, just in case
    binary_segmentation = np.asarray(binary_segmentation, dtype=np.bool)
    binary_gt_label = np.asarray(binary_gt_label, dtype=np.bool)

    # compute the intersection
    intersection = np.logical_and(binary_segmentation, binary_gt_label)
    union = np.logical_or(binary_segmentation, binary_gt_label)

    # count the number of True pixels in the binary segmentation
    segmentation_pixels = float(np.sum(binary_segmentation.flatten()))

    # same for the ground truth
    gt_label_pixels = float(np.sum(binary_gt_label.flatten()))

    # same for the intersection and union
    intersection = float(np.sum(intersection.flatten()))
    union = float(np.sum(union.flatten()))

    # compute the Dice coefficient
    smooth = 0.001
    iou = (intersection + smooth) / (union + smooth)

    return iou

# Cell


def iou_metric_matrix_of_example(
    model: torchvision.models.detection.mask_rcnn.MaskRCNN,
    example: Tuple[torch.Tensor, Dict[str, torch.Tensor]],
    score_threshold: float = 0.5
) -> List[List[float]]:
    _, masks = get_true_and_predicted_masks(model, example, score_threshold)

    return np.array(
        [
            [
                iou_metric_mask_pair(
                    binary_segmentation=masks["predicted"][j, :, :],
                    binary_gt_label=masks["true"][i, :, :],
                )
                for i in range(masks["true"].shape[0])
            ]
            for j in range(masks["predicted"].shape[0])
        ]
    )

# Internal Cell

def _argmax2d(xs: np.array) -> Tuple[int, int]:
    assert len(xs.shape) == 2

    n_col = xs.shape[1]
    ij = xs.argmax()
    i = ij // n_col
    j = ij % n_col
    return i, j

def _drop_max_row_and_column(xs: np.array) -> Tuple[float, np.array]:
    i, j = _argmax2d(xs)

    max_value = xs[i, j]

    xs = np.delete(xs, i, 0)
    xs = np.delete(xs, j, 1)

    return max_value, xs

# Internal Cell

def _resize_to_square(xs: np.array) -> np.array:
    new_size = max(xs.shape)
    new_xs = np.zeros((new_size, new_size))
    new_xs[:xs.shape[0], :xs.shape[1]] = xs
    return new_xs

# Cell

def largest_values_in_row_colums(xs: np.array) -> List[float]:
    """ Approximates the largest value in each row/column.
    """
    if xs.shape == (0, ):
        return [0]

    assert len(xs.shape) == 2

    # resize matrix to square dimensions if needed
    if xs.shape[0] != xs.shape[1]:
        xs = _resize_to_square(xs)

    assert xs.shape[0] == xs.shape[1]


    # return the only value if a single value in the matrix
    if xs.shape[0] == 1:
        return [xs[0, 0]]

    # find the largest value in the matirx and recursively find the largest values in the remaining matrix
    max_value, remainder = _drop_max_row_and_column(xs)
    return [max_value] + largest_values_in_row_colums(remainder)

# Cell


def iou_metric_example(
    model: torchvision.models.detection.mask_rcnn.MaskRCNN,
    example: Tuple[torch.Tensor, Dict[str, torch.Tensor]],
    score_threshold: float = 0.5,
) -> float:

    iou_matrix = iou_metric_matrix_of_example(model, example, score_threshold)
    matching_ious = largest_values_in_row_colums(iou_matrix)
    iou = np.mean(matching_ious)

    return iou

# Cell


def iou_metric(
    model: torchvision.models.detection.mask_rcnn.MaskRCNN,
    dataset: torch.utils.data.Dataset,
    score_threshold: float = 0.5,
) -> float:
    """Calculate IOU metric on the whole dataloader"""

    iou = [
        iou_metric_example(model, dataset[i], score_threshold)
        for i in range(len(dataset))
    ]

    img_paths = [f for f in dataset.img_paths]

    iou_df = pd.DataFrame(dict(paths=img_paths, iou=iou)).sort_values(by="iou")

    iou = np.mean(iou)

    return iou, iou_df

# Internal Cell

class PermutedDataset():
    def __init__(self, ds, permutation):
        self.ds = ds
        self.permutation = permutation

    def __getitem__(self, idx):
        return self.ds[self.permutation[idx]]

    def __len__(self):
        return len(self.permutation)

# Cell

def show_predictions_sorted_by_iou(model, dataset):
    iou, iou_df = iou_metric(model, dataset)

    permutation = iou_df.index.to_list()

    sorted_dataset = PermutedDataset(dataset, permutation)

    show_predictions(model, dataset=sorted_dataset, iou_df=iou_df)
