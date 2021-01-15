# AUTOGENERATED! DO NOT EDIT! File to edit: notebooks/04_Leaderboard.ipynb (unless otherwise specified).

__all__ = ['get_leaderboard']

# Internal Cell

import pandas as pd
import numpy as np
import boto3
from pathlib import Path

# Internal Cell

import zipfile
import shutil
import torch
import tempfile

from .datasets import get_dataset
from .instance_segmentation.model import *

# Internal Cell


def parse_filename(fname):
    tmp = fname.split("-")
    date = pd.to_datetime(tmp[1] + tmp[2] + tmp[3])
    alias = tmp[6]
    email = tmp[7]
    submitted_iou = tmp[5].split("=")[1]

    return {
        "file_name": fname,
        "date": date,
        "alias": alias,
        "email": email,
        "submitted_iou": submitted_iou,
        "calculated_iou": np.nan,
    }

# Internal Cell

s3 = boto3.resource("s3")
my_bucket = s3.Bucket("ai-league.cisex.org")
private_leaderboard_path = Path("private_leaderboard.csv")
public_leaderboard_path = Path("leaderboard.csv")


def get_submissions_from_s3(private_leaderboard_path=private_leaderboard_path):
    """Downloads the zip file from s3 if there is no record of it in the csv file"""
    if private_leaderboard_path.exists():
        private_leaderboard = pd.read_csv(private_leaderboard_path)
    else:
        private_leaderboard = dict(file_name=[])

    # download file into models_for_evaluation directory
    s3_objects = [
        s3_object
        for s3_object in my_bucket.objects.all()
        if Path(s3_object.key).match("*submission*.zip")
        and Path(s3_object.key).name not in list(private_leaderboard["file_name"])
    ]
    if len(s3_objects) > 0:
        for i, s3_object in enumerate(s3_objects):
            print(f"Downloading {i+1}/{len(s3_objects)} from S3...")
            my_bucket.download_file(s3_object.key, f"models_for_evaluation/{Path(s3_object.key).name}")

        # return new entries
        new_entries = pd.Series([Path(s3_object.key).name for s3_object in s3_objects]).apply(parse_filename).apply(pd.Series)
    else:
        x = "uploaded-2020-12-22T15:35:15.513570-submission-iou=0.46613-dolphin123-name.surname@gmail.com-2020-12-22T15:35:04.875962.zip"
        new_entries = pd.Series([x]).apply(parse_filename).apply(pd.Series).iloc[:0, :]

    return new_entries


# Internal Cell

def public(private_leaderboard):
    return private_leaderboard[["alias", "date", "submitted_iou", "calculated_iou"]]

# Internal Cell

def merge_with_private_leaderboard(
    new_entries, private_leaderboard_path=private_leaderboard_path
):
    # merge private leaderboard and new_entries if needed
    new_entries["calculated_iou"] = np.nan
    if private_leaderboard_path.exists():
        private_leaderboard = pd.read_csv(private_leaderboard_path)
        private_leaderboard = pd.concat([private_leaderboard, new_entries], axis=0)
        private_leaderboard = private_leaderboard.drop_duplicates(subset="file_name")
    else:
        private_leaderboard = new_entries

    private_leaderboard.to_csv(private_leaderboard_path, index=False)

    return private_leaderboard

# Internal Cell

def evaluate_model(model_path) -> float:
    # do it
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(model_path, "r") as zip_ref:
            zip_ref.extractall(path=d)
            unzipped_path = [x for x in Path(d).glob("submiss*")][0]

        model = torch.load(unzipped_path / "model.pt")
        data_loader, data_loader_test = get_dataset("segmentation", batch_size=4)
        iou, iou_df = iou_metric(model, data_loader_test.dataset)

    return iou

# Internal Cell

def evaluate_private_leaderboard(private_leaderboard_path=private_leaderboard_path):
    private_leaderboard = pd.read_csv(private_leaderboard_path)
    new_entries = private_leaderboard.loc[private_leaderboard["calculated_iou"].isna()]

    n = new_entries.shape[0]
    for i, ix in enumerate(new_entries.index):
        row = new_entries.loc[ix]
        file_name, alias, dt = row["file_name"], row["alias"], row["date"]
        print(f"Evaluating model {i+1}/{n} for {alias} submitted at {dt}...")
        calculated_iou = evaluate_model(f"models_for_evaluation/{file_name}")
        private_leaderboard.loc[ix, "calculated_iou"] = calculated_iou

    private_leaderboard.to_csv(private_leaderboard_path, index=False)
    return private_leaderboard

# Internal Cell

def save_public_leaderboard(private_leaderboard_path=private_leaderboard_path, public_leaderboard_path=public_leaderboard_path):
    private_leaderboard = pd.read_csv(private_leaderboard_path)
    public_leaderboard = public(private_leaderboard)
    public_leaderboard.to_csv(public_leaderboard_path, index=False)

# Cell


def get_leaderboard(public_leaderboard_path=public_leaderboard_path):
    public_leaderboard = pd.read_csv(public_leaderboard_path)
    public_leaderboard = public_leaderboard[(public_leaderboard.alias != "dolphin123") & (public_leaderboard.alias != "malimedo")]
    public_leaderboard = public_leaderboard.sort_values(by=["calculated_iou"], ascending=False).reset_index(drop=True)
    public_leaderboard.index = public_leaderboard.index + 1
    return public_leaderboard