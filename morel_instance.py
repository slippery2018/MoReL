""" 
    File Name:          MoReL/morel_instance.py
    Author:             Xiaotian Duan (xduan7)
    Email:              xduan7@uchicago.edu
    Date:               3/3/19
    Python Version:     3.5.4
    File Description:   
        This file contains the training, testing, and the looping function
        for a MoReL instance.
"""
import json
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from argparse import Namespace
import mmap
from multiprocessing.managers import DictProxy

from torch.optim import Optimizer
from torch.utils.data import DataLoader

import utils.data_prep.config as c
from networks.combo_model import ComboModel
from utils.datasets.combo_dataset import ComboDataset
from utils.misc.optimizer import get_optimizer
from utils.misc.random_seeding import seed_random_state


def train(args: Namespace,
          model: nn.Module,
          optim: Optimizer,
          dataloader: DataLoader):

    start_ms = int(round(time.time() * 1000))
    model.train()
    for batch_index, (feature, target) in enumerate(dataloader):

        feature, target = \
            feature.to(args.device, dtype=torch.float32), \
            target.to(args.device, dtype=torch.float32)

        optim.zero_grad()
        prediction = model(feature)
        loss = F.mse_loss(input=prediction, target=target)
        loss.backward()
        optim.step(closure=None)

        # TODO: some training log here
        gpu_util = 100 * (1 - (dataloader.dataset.getitem_time_ms
                               / (int(round(time.time() * 1000)) - start_ms)))
        print('Batch %i \t Loss = %f. GPU utilization %.2f%%'
              % (batch_index, loss.item(), gpu_util))


def test(args: Namespace,
         model: nn.Module,
         dataloader: DataLoader):

    model.eval()
    with torch.no_grad():
        for feature, target in dataloader:

            feature, target = \
                feature.to(args.device, dtype=torch.float32), \
                target.to(args.device, dtype=torch.float32)

            prediction = model(feature)
            loss = F.mse_loss(input=prediction, target=target)

            # TODO: other metrics here, like R2 scores, MAE, etc.


def start(args: Namespace,
          shared_dict: DictProxy or mmap = None):

    print('MoReL Instance Arguments:\n' + json.dumps(vars(args), indent=4))

    # Setting up random seed for reproducible and deterministic results
    seed_random_state(args.rand_state)

    # Computation device config (gpu # or 'cpu')
    use_cuda = (args.device != 'cpu') and torch.cuda.is_available()
    args.device = torch.device(args.device if use_cuda else 'cpu')

    # Data loaders for training/testing #######################################
    dataloader_kwargs = {
        'timeout': 1,
        'shuffle': True,
        'pin_memory': True if use_cuda else False,
        'num_workers': c.NUM_DATALOADER_WORKERS if use_cuda else 0}

    train_dataloader = DataLoader(
        ComboDataset(args=args, training=True, shared_dict=shared_dict),
        batch_size=args.train_batch_size,
        **dataloader_kwargs)

    test_dataloader = DataLoader(
        ComboDataset(args=args, training=False, shared_dict=shared_dict),
        batch_size=args.test_batch_size,
        **dataloader_kwargs)

    # Constructing neural network and optimizer ###############################
    model = ComboModel(args=args).to(args.device)
    optim = get_optimizer(args=args, model=model)

    # TODO: weight decay and other learning rate manipulation here

    # Training/testing loops ##################################################
    for epoch in range(args.max_num_epochs):
        train(args=args,
              model=model,
              optim=optim,
              dataloader=train_dataloader)
        test(args=args,
             model=model,
             dataloader=test_dataloader)

    # TODO: summary here? Might have to think about where to put the output


if __name__ == '__main__':

    test_args_dict = {
        'rand_state': 0,
        'device': 'cuda:0',

        # Dataloader parameters
        'feature_type': 'ecfp',
        'featurization': 'computing',
        'dict_timeout_ms': 60000,
        'target_dscrptr_name': 'CIC5',

        # Model parameters
        'model_type': 'dense',
        'dense_num_layers': 4,
        'dense_feature_dim': 2048,
        'dense_emb_dim': 4096,
        'dense_dropout': 0.2,

        # Optimizer and other parameters
        'train_batch_size': 32,
        'test_batch_size': 2048,
        'max_num_epochs': 10,
        'optimizer': 'sgd',
        'learing_rate': 1e-3,
        'l2_regularization': 1e-5,
    }

    test_args = Namespace(**test_args_dict)

    # Configure data loading (featurization) strategy
    # Create shared dict (mmap)
    # shared_dict = mmap.mmap(fileno=-1, length=c.MMAP_BYTE_SIZE,
    #                         access=mmap.ACCESS_WRITE)
    # args.featurization = 'mmap'

    start(args=test_args, shared_dict=None)



