import os
import torch
import torchopt
import functools
from torch import optim
from torch.nn.functional import mse_loss
import pytorch_lightning as pl
# import torchvision.utils as vutils
from functorch import vmap, make_functional_with_buffers, grad

from cusanus.pytypes import *
from cusanus.archs import ImplicitNeuralModule, LatentModulation

class ImplicitNeuralField(pl.LightningModule):
    """Implements a generic task implicit neural fields

    Arguments:
        inr: ImplicitNeuralModule, INR architecture
        lr: float = 0.001, learning rate
        weight_decay: float = 0.001
        sched_gamma: float = 0.8
    """

    def __init__(self,
                 inr: ImplicitNeuralModule,
                 inner_steps:int = 5,
                 lr:float = 0.001,
                 lr_inner:float = 0.001,
                 weight_decay:float = 0.001,
                 sched_gamma:float = 0.8) -> None:
        super().__init__()
        self.save_hyperparameters(ignore = 'inr')
        self.inr = inr
        # (tfunc, tparams) = make_functional_with_buffers(inr.theta)
        # self.tfunc = tfunc
        # self.tparms = tparams

    def initialize_modulation(self):
        m = LatentModulation(self.inr.hidden)
        m.to(self.device)
        m.train()
        return make_functional(m)

    def initialize_inner_opt(self, mparams):
        lr = self.hparams.lr_inner
        optim = torchopt.FuncOptimizer(torchopt.sgd(lr))
        return optim
        # optim = torchopt.sgd(lr)
        # opt_state = optim.init(mparams)
        # return (optim, opt_state)

    def training_step(self, batch, batch_idx, optimizer_idx = 0):
        # each task in the batch is a group of queries and outputs
        qs, ys = batch
        # Fitting modulations for current generation
        # In parallel, trains one mod per task.
        outer_opt = self.optimizers()
        outer_opt.zero_grad()
        vloss = functools.partial(inner_modulation_loop,
                                  self)
        # fit modulations on batch - returns averaged loss
        # Compute the maml loss by summing together the returned losses.
        mod_losses = torch.mean(vmap(vloss)(qs, ys))
        # Update theta
        mod_losses.backward()
        outer_opt.step()
        self.log_dict({'loss' : mod_losses.item()}, sync_dist=True)
        torch.cuda.empty_cache()
        return None  # skip the default optimizer steps by PyTorch Lightning

    # def validation_step(self, batch, batch_idx, optimizer_idx = 0):
    #     self.inr.train()
    #     ms, loss = self.outer_loop(batch)
    #     self.log_dict({'val_loss' : loss.item()}, sync_dist = True)
    #     # TODO: add visualization
    #     #
    #     # val_loss = self.decoder.loss_function(pred_gs,
    #     #                                       real_gs,
    #     #                                       optimizer_idx=optimizer_idx,
    #     #                                       batch_idx = batch_idx)
    #     #     results = pred_gs.unsqueeze(1)
    #     # vutils.save_image(results.data,
    #     #                   os.path.join(self.logger.log_dir ,
    #     #                                "reconstructions",
    #     #                                f"recons_{self.logger.name}_Epoch_{self.current_epoch}.png"),
    #     #                   normalize=False,
    #     #                   nrow=6)
    #     # vutils.save_image(real_gs.unsqueeze(1).data,
    #     #                   os.path.join(self.logger.log_dir ,
    #     #                                "reconstructions",
    #     #                                f"gt_{self.logger.name}_Epoch_{self.current_epoch}.png"),
    #     #                   normalize=False,
    #     #                   nrow=6)
    #     # self.log_dict({f"val_{key}": val.item() for key, val in val_loss.items()}, sync_dist=True)
    #     return loss


    def configure_optimizers(self):

        optimizer = optim.Adam(self.inr.theta.parameters(),
                               lr=self.hparams.lr,
                               weight_decay=self.hparams.weight_decay)
        gamma = self.hparams.sched_gamma
        scheduler = optim.lr_scheduler.ExponentialLR(optimizer,
                                                     gamma = gamma)
        return [optimizer], [scheduler]


# https://github.com/metaopt/torchopt/blob/main/examples/FuncTorch/maml_omniglot_vmap.py
# borrowed from above
def fit_modulation(exp, qs: Tensor, ys: Tensor):

    m = LatentModulation(exp.inr.hidden)
    m.to(exp.device)
    m.train()
    (mfunc, mparams, mbuffers) = make_functional_with_buffers(m)

    # init inner loop optimizer
    lr = exp.hparams.lr_inner
    opt = torchopt.sgd(lr=lr)
    opt_state = opt.init(mparams)

    def compute_loss(mparams, qs, ys):
        mod = mfunc(mparams, mbuffers)
        # pred_ys = tfunc(tparams, tbuffers, qs, mod)
        pred_ys = exp.inr(qs, mod)
        loss = mse_loss(pred_ys, ys)
        return loss

    new_mparams = mparams
    for _ in range(exp.hparams.inner_steps):
        grads = grad(compute_loss)(new_mparams, qs, ys)
        updates, opt_state = opt.update(grads, opt_state, inplace=False)
        new_mparams = torchopt.apply_updates(new_mparams, updates, inplace=False)

    return (mfunc, new_mparams, mbuffers)

def inner_modulation_loop(exp, qs: Tensor, ys: Tensor):
    m = fit_modulation(exp, qs, ys)
    # (tfunc, tparams, tbuffers) = t
    (mfunc, mparams, mbuffers) = m
    mod = mfunc(mparams, mbuffers)
    # The final set of adapted parameters will induce some
    # final loss and accuracy on the query dataset.
    # These will be used to update the model's meta-parameters.
    pred_ys = exp.inr(qs, mod)
    loss = mse_loss(pred_ys, ys)
    return loss
