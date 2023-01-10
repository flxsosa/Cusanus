import math
import torch
from torch import nn
from functorch import vmap
from functools import partial

from cusanus.pytypes import *
from cusanus.archs import ImplicitNeuralModule, SirenNet, Sine


def qspline(a: Tensor, b:Tensor, c: Tensor, t: Tensor):
    return (a * (t**2)) + (b * t) + c



def eval_spline_lpdf(loc:Tensor, sigma:Tensor, value:Tensor):
    var = (sigma ** 2)
    log_scale = torch.log(sigma)
    return -((value - loc) ** 2) / (2 * var) - log_scale - math.log(math.sqrt(2 * math.pi))

def _fc_layers(indim:int, outdim:int, hidden:int, depth:int):
        layers = []
        for l in range(depth-1):
            layer = nn.Sequential(
                nn.Linear(indim if l == 0 else hidden,
                          hidden),
                nn.ReLU())
            layers.append(layer)
        layers.append(nn.Linear(hidden, outdim))
        return nn.Sequential(*layers)

def column_vec(x: Tensor):
    v = torch.zeros((2,1),
                    dtype=x.dtype,
                    layout=x.layout,
                    device=x.device)
    return torch.cat([x.reshape(1,1), v]).squeeze()

def rotation_matrix(a:Tensor,b:Tensor,c:Tensor):
    sa = torch.sin(a)
    ca = torch.cos(a)
    sb = torch.sin(b)
    cb = torch.cos(b)
    sc = torch.sin(c)
    cc = torch.cos(c)
    m = torch.stack([
            torch.stack([cb*cc, sa*sb*cc - ca*sc, ca*sb*cc+sa*sc]),
            torch.stack([cb*sc, sa*sb*sc + ca*cc, ca*sb*sc-sa*cc]),
            torch.stack([-sb  , sa*cb,            ca*cb         ])
    ])
    return m


class QSplineModule(nn.Module):

    def __init__(self,
                 kdim:int,
                 hidden:int,
                 abc_params:dict,
                 rot_params:dict,
                 shift_params:dict):

        super().__init__()
        # assert kdim % 3 == 0, f'qspline modulation ({kdim}) not divisible by 3'
        mdim = int(kdim / 3)
        self.mod = kdim
        self.abc = SirenNet(theta_in = mdim,
                            theta_hidden = hidden,
                            theta_out = 3,
                            final_activation = nn.Identity,
                            **abc_params)
        self.rot = SirenNet(theta_in = mdim,
                            theta_hidden = hidden,
                            theta_out = 3,
                            final_activation = Sine,
                            **rot_params)
        self.shift = SirenNet(theta_in = mdim,
                            theta_hidden = hidden,
                            theta_out = 3,
                            final_activation = nn.Identity,
                            **shift_params)

    def forward(self, m):
        # shared = self.shared(m)
        m1, m2, m3 = torch.chunk(m, 3)
        a,b,c = self.abc(m1)
        rx,ry,rz = self.rot(m2)
        sx,sy,sz = self.shift(m3)

        # standardized quadratic
        av = column_vec(a)
        bv = column_vec(b)
        cv = column_vec(c)

        rotm = rotation_matrix(rx,ry,rz)

        # rotated to 3d
        xa, ya, za = torch.matmul(av, rotm)
        xb, yb, zb = torch.matmul(bv, rotm)
        xc, yc, zc = torch.matmul(cv, rotm)

        # and shifted
        xt = partial(qspline, xa,xb,xc + sx)
        yt = partial(qspline, ya,yb,yc + sy)
        zt = partial(qspline, za,zb,zc + sz)
        return (xt,yt,zt)

class PQSplineModule(nn.Module):

    def __init__(self,
                 kdim:int,
                 hidden:int,
                 qspline_params:dict,
                 sigma_params:dict):

        super().__init__()
        # qspline for mean
        self.qspline = QSplineModule(kdim = kdim,
                                     hidden = hidden,
                                     **qspline_params)

        # # variance INR
        # self.sigma = ImplicitNeuralModule(q_in = 1,
        #                                   out = 3,
        #                                   mod = kdim,
        #                                   sigmoid = False,
        #                                   **sigma_params)

    def forward(self, qs:Tensor, mod):
        # b x 1
        xt, yt, zt = self.qspline(mod)
        # b x 3
        loc = torch.cat([xt(qs), yt(qs), zt(qs)],
                        axis = 1)
        # b x 3
        # sigma = self.sigma(qs, mod)
        # std = torch.exp(0.5 * sigma)
        # eps = torch.randn_like(std)
        # ys = eps * std + loc
        # REVIEW: could also return spline partials
        return loc, loc, loc
