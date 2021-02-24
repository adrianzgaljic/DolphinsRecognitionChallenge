# AUTOGENERATED! DO NOT EDIT! File to edit: notebooks/01_Datasets.ipynb (unless otherwise specified).

__all__ = ['ToTensor', 'stack_imgs', 'display_batches', 'get_image2tensor_transforms', 'get_dataset', 'Compose',
           'RandomHorizontalFlip']

# Cell

from pathlib import Path
from typing import *

# Internal Cell


import numpy as np
import shutil
from datetime import datetime
import torch
import torch.utils.data
from torch.hub import download_url_to_file
import torchvision
import PIL
from PIL import Image
from zipfile import ZipFile
import random

from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor

from torchvision.transforms import functional as F
from torchvision.transforms import ToPILImage

from tempfile import TemporaryDirectory

from dolphins_recognition_challenge import utils


# Internal Cell

dataset_url = "https://s3.eu-central-1.amazonaws.com/ai-league.cisex.org/2020-2021/dolphins-instance-segmentation/dolphins_200_train_val.zip"

# Internal Cell

dataset_root = Path("./data/dolphins_200_train_val")
dataset_zip = dataset_root.parent / "dolphins_200_train_val.zip"

def _download_data_if_needed():

    dataset_zip.parent.mkdir(parents=True, exist_ok=True)

    if not dataset_zip.exists():
        torch.hub.download_url_to_file(
            dataset_url,
            dataset_zip,
            hash_prefix=None,
            progress=True,
        )


    with ZipFile(dataset_zip, 'r') as zip_ref:
        zip_ref.extractall(dataset_root)


# Internal Cell


def _enumerate_colors_for_fname(fname: Path) -> Tuple[int, int, int]:
    """Finds all colors in the image"""
    img = Image.open(fname)
    colors = [y for x, y in img.getcolors()]
    return colors

# Internal Cell


def _enumerate_colors_for_fnames(fnames: List[Path]) -> Dict[Tuple[int, int, int], int]:
    """This function is used to pin (0, 0, 0) color to the front of palette"""
    colors = np.array([_enumerate_colors_for_fname(fname) for fname in fnames]).reshape(
        -1, 3
    )
    colors = set([tuple(x) for x in colors.tolist() if tuple(x) != (0, 0, 0)])
    colors = [(0, 0, 0)] + list(colors)
    return {x: i for i, x in enumerate(colors)}

# Internal Cell


def _substitute_values(xs: np.array, x, y):
    """Not sure I understand what this does"""
    ix_x = xs == x
    ix_y = xs == y
    xs[ix_x] = y
    xs[ix_y] = x

# Internal Cell


def _enumerate_image_for_instances(
    im: Image, force_black_to_zero: bool = True, max_colors=16
) -> np.array:
    """convert rgb image mask to enumerated image mask"""
    pallete_mask = im.convert("P", palette=Image.ADAPTIVE, colors=max_colors)

    xs = np.array(pallete_mask)

    if force_black_to_zero:
        _substitute_values(xs, 0, xs.max())

    return xs

# Internal Cell


def _enumerate_image_for_classes(
    im: Image,
    colors: Dict[Tuple[int], int] = None,
) -> np.array:
    """Enumerates classes from the rbg format"""
    xs = np.array(im)
    xs = [
        ((xs == color).all(axis=-1)).astype(int) * code
        for color, code in colors.items()
    ]
    xs_sum = xs[0]
    for i in range(1, len(xs)):
        xs_sum = xs_sum + xs[i]
    return xs_sum.astype("uint8")

# Internal Cell


class DolphinsInstanceSegmentationDataset(torch.utils.data.Dataset):
    """Instance segmentation dataset"""

    def __init__(
        self,
        root: Path,
        tensor_transforms: Optional[Callable[[Image.Image], Any]]=None,
        n_samples: int=-1
    ):
        self.root = root
        self.tensor_transforms = tensor_transforms
        # load all image files, sorting them to
        # ensure that they are aligned
        self.img_paths = sorted((root / "JPEGImages").glob("*.*"))[:n_samples]
        self.label_paths = sorted((root / "SegmentationClass").glob("*.*"))[:n_samples]
        self.mask_paths = sorted((root / "SegmentationObject").glob("*.*"))[:n_samples]

        self.class_colors = _enumerate_colors_for_fnames(self.label_paths)

    def __getitem__(self, idx):

        # load images ad masks
        img_path = self.img_paths[idx]
        label_path = self.label_paths[idx]
        mask_path = self.mask_paths[idx]

        # load and transform images and masks
        img = Image.open(img_path).convert("RGB")
        mask_img = Image.open(mask_path)
        label_img = Image.open(label_path)

        # note that we haven't converted the mask to RGB,
        # because each color corresponds to a different instance
        # with 0 being background
        mask = _enumerate_image_for_instances(mask_img)

        # instances are encoded as different colors
        obj_ids = np.unique(mask)

        # first id is the background, so remove it
        obj_ids = obj_ids[1:]

        # split the color-encoded mask into a set
        # of binary masks
        masks = mask == obj_ids[:, None, None]

        label_array = _enumerate_image_for_classes(label_img, self.class_colors)
        # get bounding box coordinates for each mask
        num_objs = len(obj_ids)
        boxes = []
        labels = []
        for i in range(num_objs):
            pos = np.where(masks[i])
            xmin = np.min(pos[1])
            xmax = np.max(pos[1])
            ymin = np.min(pos[0])
            ymax = np.max(pos[0])

            img_width, img_height = img.size
            xmin = xmin/img_width
            xmax = xmax/img_width
            ymin = ymin/img_height
            ymax = ymax/img_height

            boxes.append([xmin, ymin, xmax, ymax])

            class_mask = label_array * masks[i]
            label, count = np.unique(class_mask, return_counts=True)
            assert label.shape[0] <= 2
            label = max(label)
            labels.append(label)

        boxes = torch.as_tensor(boxes, dtype=torch.float32)
        # there WAS multi class
        # labels = torch.as_tensor(labels, dtype=torch.int64)
        labels = torch.ones((num_objs,), dtype=torch.int64)

        masks = torch.as_tensor(masks, dtype=torch.uint8)

        image_id = torch.tensor([idx])
        area = boxes[:, 2] * boxes[:, 3]
        # suppose all instances are not crowd
        iscrowd = torch.zeros((num_objs,), dtype=torch.int64)


        if self.tensor_transforms is not None:
            output = {
                'image': np.array(img)#,
                #'masks': masks,
                #'bboxes': boxes
            }
            self.tensor_transforms(**output)
            img = output['image']
            #masks = img_data['masks']
            #boxes = img_data['bboxes']



        target = {}
        target["boxes"] = boxes
        target["labels"] = labels
        target["masks"] = masks
        target["image_id"] = image_id
        target["area"] = area
        target["iscrowd"] = iscrowd


        return img, target

    def __len__(self):
        return len(self.img_paths)

# Cell

class ToTensor(object):
    """ Transforms an object (image) into a Tensor
    """
    def __call__(self, image, target):
        image = F.to_tensor(image)
        return image, target

# Internal Cell

def _get_tensor_transforms(train: bool):
    return ToTensor()


def _get_instance_segmentation_dataset(
    *,
    get_tensor_transforms: Callable[
        [bool], Callable[[Image.Image], Any]
    ] = _get_tensor_transforms,
    batch_size: int = 4,
    num_workers: int = 4,
    n_samples: int=-1,
) -> Tuple[
    torch.utils.data.dataloader.DataLoader, torch.utils.data.dataloader.DataLoader
]:
    """Get dataset for instance segmentation. Make sure you define get_transform function."""

    # get data if needed
    _download_data_if_needed()
    root_path = Path(dataset_root)
    assert root_path.exists()
    assert root_path.is_dir()
    assert len(list(root_path.glob("**/*"))) >= 600

    # use our dataset and defined transformations
    dataset = DolphinsInstanceSegmentationDataset(
        dataset_root / "Train",
        tensor_transforms=get_tensor_transforms(train=True),
        n_samples=n_samples
    )
    dataset_test = DolphinsInstanceSegmentationDataset(
        dataset_root / "Val",
        tensor_transforms=get_tensor_transforms(train=False),
        n_samples=n_samples
    )

    # define training and validation data loaders
    data_loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=utils.collate_fn,
    )

    data_loader_test = torch.utils.data.DataLoader(
        dataset_test,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        collate_fn=utils.collate_fn,
    )

    return data_loader, data_loader_test

# Cell

def stack_imgs(imgs: List[PIL.Image.Image], width: int=None) -> PIL.Image:
    """ Stacks images horizontaly in one large image. Very useful for debugging purposes.
    """
    print("imgs", imgs)
    height = max([img.size[1] for img in imgs])
    imgs = [np.array(img.resize((img.size[0], height))) for img in imgs]
    imgs = np.hstack(imgs)
    img = Image.fromarray(imgs)
    if width:
        height = int(img.size[1] * width / img.size[0])
        img = img.resize((width, height))
    return img

# Cell

def display_batches(data_loader: torch.utils.data.DataLoader, *, n_batches: int=1, width:int=800, show_y: bool=False):
    """ Displays `n_batches`, one batch per row.
    """
    to_pil_img = ToPILImage()
    for i, (x, y) in enumerate(data_loader):
        if i >= n_batches:
            return
        if isinstance(x[0], torch.Tensor) or isinstance(x[0], np.ndarray):
            x = [to_pil_img(t) for t in x]
        display(stack_imgs(x, width=width))
        if show_y:
            display(y)

# Cell

def get_image2tensor_transforms(train: bool):
    """ Converts image to tensor
    """
    return ToTensor()

def get_dataset(
    name: str,
    *,
    get_tensor_transforms: Callable[[bool], Callable[[Image.Image], Any]] = get_image2tensor_transforms,
    batch_size: int = 4,
    num_workers: int = 4,
    n_samples: int=-1,
) -> Tuple[
    torch.utils.data.dataloader.DataLoader, torch.utils.data.dataloader.DataLoader
]:
    """Get one of two datasets available. The parameter `name` can be one of 'segmentation' and 'classification'"""

    assert name in [
        "segmentation",
        "classification",
    ], f"name should be either 'segmentation' or 'classification', but it is '{name}'."

    if name == "segmentation":
        return _get_instance_segmentation_dataset(
            get_tensor_transforms=get_tensor_transforms,
            batch_size=batch_size,
            num_workers=num_workers,
            n_samples=n_samples,
        )
    elif name == "classification":
        raise NotImplementedError()

# Internal Cell

def _flip_coco_person_keypoints(kps, width):
    flip_inds = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
    flipped_data = kps[:, flip_inds]
    flipped_data[..., 0] = width - flipped_data[..., 0]
    # Maintain COCO convention that if visibility == 0, then x, y = 0
    inds = flipped_data[..., 2] == 0
    flipped_data[inds] = 0
    return flipped_data


# Cell

class Compose(object):
    """ Compose a list of transformations into one transformation
    """
    def __init__(self, transforms: List):
        self.transforms = transforms

    def __call__(self, image, target):
        for t in self.transforms:
            image, target = t(image, target)
        return image, target


class RandomHorizontalFlip(object):
    """ Randomly flips image horizontally
    """
    def __init__(self, prob):
        self.prob = prob

    def __call__(self, image, target):
        if random.random() < self.prob:
            height, width = image.shape[-2:]
            image = image.flip(-1)
            bbox = target["boxes"]
            bbox[:, [0, 2]] = width - bbox[:, [2, 0]]
            target["boxes"] = bbox
            if "masks" in target:
                target["masks"] = target["masks"].flip(-1)
            if "keypoints" in target:
                keypoints = target["keypoints"]
                keypoints = _flip_coco_person_keypoints(keypoints, width)
                target["keypoints"] = keypoints
        return image, target
