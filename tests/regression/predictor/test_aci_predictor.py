# Copyright (c) 2023-present, SUSTech-ML.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#

import pytest
import torch

from torchcp.regression.predictor import ACIPredictor
from torchcp.regression.score import CQR
from torchcp.regression.utils import build_regression_model


@pytest.fixture
def mock_model():
    return build_regression_model("NonLinearNet")(5, 2, 64, 0.5)


@pytest.fixture
def mock_score_function():
    return CQR()


def test_aci_predictor_workflow(mock_data, mock_model, mock_score_function):
    train_dataloader, _, test_dataloader = mock_data

    with pytest.raises(ValueError, match="gamma must be greater than 0."):
        ACIPredictor(mock_score_function, mock_model, gamma=0)

    # Initialize ACIPredictor
    aci_predictor = ACIPredictor(
        score_function=mock_score_function,
        model=mock_model,
        gamma=0.1
    )

    # Test train method
    alpha = 0.1
    aci_predictor.train(train_dataloader, alpha=alpha)
    assert aci_predictor.alpha == alpha, "Alpha should be set correctly during training."
    assert aci_predictor.alpha_t == alpha, "Adaptive alpha_t should start with initial alpha."

    # Test predict method with x_batch only
    x_batch_1, y_batch_1 = next(iter(test_dataloader))
    prediction_intervals_1 = aci_predictor.predict(x_batch_1)
    assert prediction_intervals_1 is not None, "Prediction intervals should not be None."
    assert prediction_intervals_1.shape[0] == x_batch_1.shape[0], "Prediction intervals should match batch size."
     # Test exception for missing arguments
    with pytest.raises(ValueError):
        aci_predictor.predict(x_batch_1, y_lookback=torch.rand(10), pred_interval_lookback=None)
    with pytest.warns(UserWarning):
            prediction_intervals_1 = aci_predictor.predict(x_batch_1, train=True, update_alpha=True)
    assert prediction_intervals_1 is not None, "Prediction intervals should not be None."
    assert prediction_intervals_1.shape[0] == x_batch_1.shape[0], "Prediction intervals should match batch size."
    # Test predict method with x_batch, x_lookback, y_lookback
    x_batch_2, y_batch_2 = next(iter(test_dataloader))
    prediction_intervals_2 = aci_predictor.predict(x_batch=x_batch_2, x_lookback=x_batch_1, y_lookback=y_batch_1)
    assert prediction_intervals_2 is not None, "Prediction intervals should not be None."
    assert prediction_intervals_2.shape[0] == x_batch_2.shape[0], "Prediction intervals should match batch size."
    # Test predict method with x_batch, x_lookback, y_lookback, pred_interval_lookack
    x_batch_3, y_batch_3 = next(iter(test_dataloader))
    prediction_intervals_3 = aci_predictor.predict(x_batch=x_batch_3, x_lookback=x_batch_2, y_lookback=y_batch_2, pred_interval_lookback=prediction_intervals_2)
    assert prediction_intervals_3 is not None, "Prediction intervals should not be None."
    assert prediction_intervals_3.shape[0] == x_batch_3.shape[0], "Prediction intervals should match batch size."

    # Test evaluate method
    eval_results = aci_predictor.evaluate(test_dataloader)
    assert eval_results["coverage_rate"] > 0, "Average coverage rate should be greater than 0."
    assert eval_results["average_size"] > 0, "Average interval size should be greater than 0."
    # Test evaluate method when lookback is too high
    with pytest.raises(ValueError):
        eval_results = aci_predictor.evaluate(test_dataloader, lookback=10000)
    # Test evaluate method with other arguments
    aci_predictor.evaluate(test_dataloader, retrain_gap=0, update_alpha_gap=0)
    aci_predictor.evaluate(test_dataloader, retrain_gap=2, update_alpha_gap=3)
    
   
def test_aci_predictor_wrong_workflow(mock_data, mock_model, mock_score_function):
    train_dataloader, _, test_dataloader = mock_data

    with pytest.raises(ValueError, match="gamma must be greater than 0."):
        ACIPredictor(mock_score_function, mock_model, gamma=0)

    aci_predictor = ACIPredictor(
        score_function=mock_score_function,
        model=mock_model,
        gamma=0.1
    )

    x_batch, y_batch = next(iter(test_dataloader))
    # predict should used after train
    with pytest.raises(ValueError):
        prediction_intervals = aci_predictor.predict(x_batch)
    

@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_device_support(mock_data, mock_model, mock_score_function, device):
    print(device)
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA is not available.")

    train_dataloader, _, test_dataloader = mock_data
    aci_predictor = ACIPredictor(mock_score_function, mock_model.to(device), gamma=0.1)

    aci_predictor.train(train_dataloader, alpha=0.1)
    x_batch, _ = next(iter(test_dataloader))
    x_batch = x_batch.to(device)

    prediction_intervals = aci_predictor.predict(x_batch)
    assert prediction_intervals.device.type == device, "Prediction intervals should match the specified device."
