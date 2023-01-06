import os
import yaml
import torch
from pathlib import Path
from pytorch_lightning import Trainer
from pytorch_lightning.loggers import CSVLogger
from lightning_lite.utilities.seed import seed_everything
from pytorch_lightning.callbacks import LearningRateMonitor, ModelCheckpoint

from cusanus.archs import ImplicitNeuralModule
from cusanus.tasks import ImplicitNeuralField
from cusanus.datasets import load_ffcv
from cusanus.utils.visualization import RenderKField


task_name = 'kfield'
dataset_name = 'kfield'

def main():
    with open(f"/project/scripts/configs/{task_name}_task.yaml", 'r') as file:
        config = yaml.safe_load(file)

    logger = CSVLogger(save_dir=config['logging_params']['save_dir'],
                       name= task_name)

    # For reproducibility
    seed_everything(config['manual_seed'], True)

    # initialize networks and task
    arch = ImplicitNeuralModule(**config['arch_params'])
    arch.train()
    task = ImplicitNeuralField(arch, **config['task_params'])

    runner = Trainer(logger=logger,
                     callbacks=[
                         LearningRateMonitor(),
                         ModelCheckpoint(save_top_k = 5,
                                         dirpath = os.path.join(logger.log_dir ,
                                                                "checkpoints"),
                                         monitor= "loss",
                                         save_last=True),
                         RenderKField(batch_step = 500)

                     ],
                     accelerator = 'auto',
                     deterministic = True,
                     **config['trainer_params'])

    device = runner.device_ids[0] if torch.cuda.is_available() else None
    arch.to(device)
    task.to(device)

    # CONFIGURE FFCC DATA LOADERS
    dpath_train = f"/spaths/datasets/{dataset_name}_train_dataset.beton"
    train_loader = load_ffcv(dpath_train, device,
                             **config['loader_params'])

    # BEGIN TRAINING
    Path(f"{logger.log_dir}/volumes").mkdir(exist_ok=True, parents=True)
    print(f"======= Training {logger.name} =======")
    runner.fit(task, train_loader)

if __name__ == '__main__':
    main()