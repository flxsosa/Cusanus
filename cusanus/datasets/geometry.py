import torch
import numpy as np
from torch.utils.data import Dataset
from ffcv.writer import DatasetWriter
from ffcv.fields import NDArrayField
from ffcv.fields.decoders import NDArrayDecoder
from ffcv.transforms import (Convert, NormalizeImage, ToTensor,
    ToDevice)

from cusanus.pytypes import *
from cusanus.utils import grids_along_depth

_pipe = [NDArrayDecoder(),
         ToTensor(),
         Convert(torch.float32)]
_pipelines = {'qs': _pipe, 'ys': _pipe}

class SphericalGeometryDataset(Dataset):

    ffcv_pipelines = _pipelines

    # inheriting pytorch dataset; return vector of object and gstate
    def __init__(self, n_shapes:int = 1000, dim_queries:int = 100,
                 r_min:float = 0.6, r_max:float = 0.7,
                 sigma:float=0.1) -> None:
        self.n_shapes = n_shapes
        self.dim_queries = dim_queries
        self.k_queries = dim_queries ** 3
        self.r_min = r_min
        self.r_max = r_max
        self.sigma = sigma
        self.grid = grids_along_depth(dim_queries, dim_queries).numpy()

    def __len__(self):
        return self.n_shapes

    def __getitem__(self, idx):
        radius = np.random.uniform(low = self.r_min,
                                   high = self.r_max)
        qs = np.random.uniform(low = -self.sigma,
                                high = self.sigma,
                                size = (self.k_queries, 3))
        qs += self.grid
        qs = qs.astype(np.float32)
        ys = spherical_occupancy_field(radius, qs)
        return (qs, ys)

    def write_ffcv(self, path:str):
        qshape = (self.k_queries, 3)
        yshape = (self.k_queries, 1)
        fields = {
            'qs': NDArrayField(dtype = np.dtype('float32'),
                               shape = qshape),
            'ys': NDArrayField(dtype = np.dtype('float32'),
                               shape = yshape),
        }
        writer = DatasetWriter(path, fields)
        writer.from_indexed_dataset(self)


def spherical_occupancy_field(r: float, qs: np.ndarray):
    bs = r >= np.linalg.norm(qs, axis = 1)
    ys = bs.astype(np.float32)
    return ys
