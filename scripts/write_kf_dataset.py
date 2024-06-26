#!/usr/bin/env python

import os
import yaml
import argparse
import torch

from cusanus.datasets import write_ffcv, RunningStats
from cusanus.datasets import KFieldDataset, SceneDataset, SimDataset

name = 'kfield'

def main():
    parser = argparse.ArgumentParser(
        description = 'Generates occupancy field dataset via ffcv',
        formatter_class = argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--num_workers', type = int,
                        help = 'Number of write workers',
                        default = -1)
    parser.add_argument('--num_steps', type = int,
                        help = 'Number of steps for running stats',
                        default = 5000)
    args = parser.parse_args()


    with open(f"/project/scripts/configs/{name}_dataset.yaml", 'r') as file:
        config = yaml.safe_load(file)

    physics = config['physics']
    sim = config['simulations']
    kfield = config['kfield']

    for dname in ['train', 'val', 'test']:
        c = config[dname]
        scenes = SceneDataset(**c, **physics)
        simulations = SimDataset(scenes, **sim,
                                 )
        if dname == 'train':
            d = KFieldDataset(simulations, **kfield,
                              add_noise=False)
            stats = RunningStats(d.qsize-1)
            for i in range(min(len(d), args.num_steps)):
                print('step',i)
                qs, ys = d[i]
                for q in qs:
                    stats.push(q[1:])
            mean = stats.mean()
            stdev = stats.standard_deviation()
            with open(f'/spaths/datasets/{name}_running_stats.yaml', 'w') as f:
                yaml.safe_dump({'mean': mean.tolist(), 'std':stdev.tolist()}, f)

            print(f'Mean: {mean}, Std. Dev.: {stdev}')
        d = KFieldDataset(simulations, **kfield,
                          mean = mean,
                          std = stdev,
                          add_noise=True)
        dpath = f"/spaths/datasets/{name}_{dname}_dataset.beton"
        d.write_ffcv(dpath, num_workers = args.num_workers)

if __name__ == '__main__':
    main()
