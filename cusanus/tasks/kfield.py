import torch
from torch import optim
import pytorch_lightning as pl
from functorch import make_functional
from torch.nn.functional import mse_loss, l1_loss

from cusanus.pytypes import *
from cusanus.archs import PQSplineModule, LatentModulation
from cusanus.tasks import ImplicitNeuralField

class KSplineField(ImplicitNeuralField):
    """Implements kinematic spline fields

    Arguments:
        inr: ImplicitNeuralModule, INR architecture
        lr: float = 0.001, learning rate
        weight_decay: float = 0.001
        sched_gamma: float = 0.8
    """

    def __init__(self,
                 module: PQSplineModule,
                 inner_steps:int = 5,
                 lr:float = 0.001,
                 lr_inner:float = 0.001,
                 weight_decay:float = 0.001,
                 sched_gamma:float = 0.8) -> None:
        super(ImplicitNeuralField, self).__init__()
        self.save_hyperparameters(ignore = 'module')
        self.module = module

    def initialize_modulation(self):
        # m = LatentModulation(self.module.sigma.mod)
        m = LatentModulation(self.module.qspline.mod)
        m.to(self.device)
        # m.train()
        return make_functional(m)

    def pred_loss(self, qs: Tensor, ys: Tensor, pred):
        # HACK: `ys` is ignored
        xyz = qs[:, 1:]
        pred_ys, loc, std = pred
        rec_loss = torch.mean(l1_loss(xyz, pred_ys))
        var_loss = torch.mean(std)
        # print('losses')
        # print(rec_loss)
        return rec_loss + 0.1 * var_loss

    def configure_optimizers(self):

        params = [{'params': self.module.qspline.parameters()},
                  {'params': self.module.sigma.theta.parameters()}]
        optimizer = optim.Adam(params,
                               lr=self.hparams.lr,
                               weight_decay=self.hparams.weight_decay)
        gamma = self.hparams.sched_gamma
        scheduler = optim.lr_scheduler.ExponentialLR(optimizer,
                                                     gamma = gamma)
        return [optimizer], [scheduler]