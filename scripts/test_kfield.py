import os
import yaml
import torch
import argparse
from pathlib import Path
from pytorch_lightning import Trainer
from pytorch_lightning.loggers import CSVLogger
from lightning_lite.utilities.seed import seed_everything
from pytorch_lightning.callbacks import LearningRateMonitor, ModelCheckpoint

from cusanus.archs import KModule
from cusanus.tasks import KField
from cusanus.datasets import load_ffcv
from cusanus.utils.visualization import RenderKFieldVolumes


task_name = 'kfield'
dataset_name = 'kfield'

def main():
    parser = argparse.ArgumentParser(
        description = 'Tests kfield',
        formatter_class = argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('version', type = int,
                        help = 'Exp version number')
    args = parser.parse_args()
    version = args.version

    with open(f"/project/scripts/configs/{task_name}_task.yaml", 'r') as file:
        config = yaml.safe_load(file)

    logger = CSVLogger(save_dir=config['logging_params']['save_dir'],
                       name= task_name,
                       version = version,
                       prefix = 'test')

    # For reproducibility
    seed_everything(config['manual_seed'], True)

    # initialize networks and task
    arch = KModule(**config['arch_params'])
    task = KField(arch, **config['task_params'])

    runner = Trainer(logger=logger,
                     callbacks=[
                         RenderKFieldVolumes(trange=(0., 3.0))
                     ],
                     accelerator = 'auto',
                     inference_mode = False,
                     )

    # CONFIGURE FFCC DATA LOADERS
    dpath_test = f"/spaths/datasets/{dataset_name}_test_dataset.beton"
    device = runner.device_ids[0] if torch.cuda.is_available() else None
    test_loader = load_ffcv(dpath_test, device, batch_size = 1)

    # BEGIN TESTING
    Path(f"{logger.log_dir}/test_volumes").mkdir(exist_ok=True, parents=True)
    print(f"======= Testing {logger.name} =======")
    ckpt_path = Path(f'{logger.log_dir}/checkpoints/last.ckpt')
    ckpt_path = str(ckpt_path)
    runner.test(task, test_loader, ckpt_path = ckpt_path)

if __name__ == '__main__':
    main()
