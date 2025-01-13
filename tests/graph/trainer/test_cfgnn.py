# Copyright (c) 2023-present, SUSTech-ML.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#

import pytest
import torch
from torch_geometric.data import Data
from torch_geometric.nn import GCNConv

from torchcp.graph.trainer import CFGNNTrainer


@pytest.fixture
def device():
    return torch.device('cuda' if torch.cuda.is_available() else 'cpu')


@pytest.fixture
def mock_graph_data(device):
    num_nodes = 200
    x = torch.randn(num_nodes, 10)

    edge_index = torch.tensor([
        [0, 1, 2, 3, 4],
        [1, 2, 3, 4, 0]
    ])
    y = torch.randint(0, 10, (num_nodes,))
    rand_perm = torch.randperm(num_nodes)
    train_idx = rand_perm[:20]
    val_idx = rand_perm[20:40]
    calib_train_idx = rand_perm[40:60]

    return Data(x=x, edge_index=edge_index, y=y,
                num_nodes=num_nodes,
                train_idx=train_idx,
                val_idx=val_idx,
                calib_train_idx=calib_train_idx).to(device)


@pytest.fixture
def mock_model(device):
    class MockModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.param = torch.nn.Parameter(torch.tensor(1.0))

        def forward(self, x, edge_index=None):
            return x

    return MockModel().to(device)


@pytest.fixture
def mock_cfgnn_model(mock_model, mock_graph_data):
    return CFGNNTrainer(mock_model, mock_graph_data)


def test_initialization(mock_model, mock_graph_data):
    cf_trainer = CFGNNTrainer(mock_model, mock_graph_data)
    assert len(cf_trainer.model.convs) == 2
    assert type(cf_trainer.model.convs[0]) is GCNConv and type(cf_trainer.model.convs[1]) is GCNConv
    assert cf_trainer.model.convs[0].in_channels == 10 and cf_trainer.model.convs[0].out_channels == 64
    assert cf_trainer.model.convs[1].in_channels == 64 and cf_trainer.model.convs[1].out_channels == 10


def test_invalid_initialization(mock_model, mock_graph_data):
    with pytest.raises(ValueError, match="backbone_model cannot be None"):
        CFGNNTrainer(None, mock_graph_data)

    with pytest.raises(ValueError, match="graph_data cannot be None"):
        CFGNNTrainer(mock_model, None)


def test_train_epoch(mock_graph_data, mock_cfgnn_model, device):
    mock_cfgnn_model.train_epoch(500, mock_graph_data.x)
    mock_cfgnn_model.train_epoch(2000, mock_graph_data.x)


def test_validate(mock_graph_data, mock_cfgnn_model, device):
    results = mock_cfgnn_model.validate(mock_graph_data.x)
    assert len(results) == 2
    assert results[1].shape == mock_graph_data.x.shape


def test_train(mock_cfgnn_model):
    model = mock_cfgnn_model.train(10)
    assert model is mock_cfgnn_model.model
