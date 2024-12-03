# Copyright (c) 2023-present, SUSTech-ML.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#
__all__ = ["ConfTr"]

import math
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor
from .confts import ConfTS

class ConfTr(ConfTS):
    """
    Method: Conformal Training  (ConfTr)
    Paper: Learning Optimal Conformal Classifiers (Stutz et al., 2021)
    Link: https://arxiv.org/abs/2110.09192
    Github: https://github.com/google-deepmind/conformal_training
    
    The class implements conformal training for neural networks. It supports
    multiple loss functions and allows for flexible configuration of the training
    process.

    Args:
        weight (float): The weight of each loss function. Must be greater than 0.
        predictor (torchcp.classification.Predictor): An instance of the CP predictor class.
        alpha (float): The significance level for each training batch.
        fraction (float): The fraction of the calibration set in each training batch.
            Must be a value in (0, 1).
        soft_qunatile (bool, optional): Whether to use soft quantile. Default is True.
        epsilon (float, optional): A temperature value. Default is 1e-4.
        loss_type (str): The selected (multi-selected) loss functions, which can be
            "valid", "classification", "probs", "coverage".
        target_size (int, optional): Optional: 0 | 1. Default is 1.
        loss_transform (str, optional): A transform for loss. Default is "square".
            Can be "square", "abs", or "log".
        
        
    Shape:
        - Input: :math:`(N, *)` where :math:`*` means any number of additional dimensions.
        - Output: scalar representing the computed loss.
        
    Examples::
        >>> predictor = torchcp.classification.SplitPredictor()
        >>> conftr = ConfTr(weight=1.0, predictor=predictor, alpha=0.05, fraction=0.2, loss_type="valid")
        >>> logits = torch.randn(100, 10)
        >>> labels = torch.randint(0, 2, (100,))
        >>> loss = conftr(logits, labels)
        >>> loss.backward()
    """

    def __init__(self, weight, predictor, alpha, fraction, soft_qunatile=True, epsilon = 1e-4, loss_type="valid", target_size=1, loss_transform="square", temperature=0.1, soft_quantile=True):

        super(ConfTr, self).__init__(weight,predictor, alpha, fraction)
        
        if loss_type not in ["valid", "classification", "probs", "coverage", "cfgnn"]:
            raise ValueError('loss_type should be a value in ["valid", "classification", "probs", "coverage"].')
        if target_size not in [0, 1]:
            raise ValueError("target_size should be 0 or 1.")
        if loss_transform not in ["square", "abs", "log"]:
            raise ValueError('loss_transform should be a value in ["square", "abs", "log"].')
        if epsilon <= 0:
            raise ValueError("epsilon must be greater than 0.")
        
        
        self.weight = weight
        self.predictor = predictor
        self.alpha = alpha
        self.fraction = fraction
        self.loss_type = loss_type
        self.target_size = target_size
        self.soft_qunatile = soft_qunatile
        self.epsilon= epsilon

        if loss_transform == "square":
            self.transform = torch.square
        elif loss_transform == "abs":
            self.transform = torch.abs
        elif loss_transform == "log":
            self.transform = torch.log
        self.loss_functions_dict = {"valid": self.__compute_hinge_size_loss,
                                    "probs": self.__compute_probabilistic_size_loss,
                                    "coverage": self.__compute_coverage_loss,
                                    "classification": self.__compute_classification_loss,
                                    "cfgnn": self.__compute_conformalized_gnn_loss,
                                    }

    
    
    def compute_loss(self, test_scores, test_labels, tau):
        pred_sets = torch.sigmoid((tau - test_scores)/self.epsilon)
    def forward(self, logits, labels):
        # Compute Size Loss
        val_split = int(self.fraction * logits.shape[0])
        cal_logits = logits[:val_split]
        cal_labels = labels[:val_split]
        test_logits = logits[val_split:]
        test_labels = labels[val_split:]

        cal_scores = self.predictor.score_function(cal_logits, cal_labels)
        # self.predictor.calculate_threshold(cal_logits.detach(), cal_labels.detach(), self.alpha)
        # tau = self.predictor.q_hat
        if self.soft_quantile:
            tau = self.__soft_quantile(cal_scores, self.alpha)
        else:
            n_temp = len(val_split)
            q_level = math.ceil((n_temp + 1) * (1 - self.alpha)) / n_temp
            tau = torch.quantile(cal_scores, q_level, interpolation='higher')
        # breakpoint()
        test_scores = self.predictor.score_function(test_logits)
        # Computing the probability of each label contained in the prediction set.
        if self.loss_type == "cfgnn":
            pred_sets = torch.sigmoid((tau - test_scores) / self.temperature)
        else:
            pred_sets = torch.sigmoid(tau - test_scores)
        loss = self.weight * self.loss_functions_dict[self.loss_type](pred_sets, test_labels)
        return loss

    def __compute_hinge_size_loss(self, pred_sets, labels):
        return torch.mean(
            self.transform(
                torch.maximum(torch.sum(pred_sets, dim=1) - self.target_size, torch.tensor(0).to(pred_sets.device))))

    def __compute_probabilistic_size_loss(self, pred_sets, labels):
        classes = pred_sets.shape[1]
        one_hot_labels = torch.unsqueeze(torch.eye(classes).to(pred_sets.device), dim=0)
        repeated_confidence_sets = pred_sets.unsqueeze(2).repeat(1, 1, classes)
        loss = one_hot_labels * repeated_confidence_sets + \
               (1 - one_hot_labels) * (1 - repeated_confidence_sets)
        loss = torch.prod(loss, dim=1)
        return torch.sum(loss, dim=1)

    def __compute_coverage_loss(self, pred_sets, labels):
        one_hot_labels = F.one_hot(labels, num_classes=pred_sets.shape[1])

        # Compute the mean of the sum of confidence_sets multiplied by one_hot_labels
        loss = torch.mean(torch.sum(pred_sets * one_hot_labels, dim=1)) - (1 - self.alpha)

        # Apply the transform function (you need to define this)
        transformed_loss = self.transform(loss)

        return transformed_loss

    def __compute_classification_loss(self, pred_sets, labels):
        # Convert labels to one-hot encoding
        one_hot_labels = F.one_hot(labels, num_classes=pred_sets.shape[1]).float()
        loss_matrix = torch.eye(pred_sets.shape[1], device=pred_sets.device)
        # Calculate l1 and l2 losses
        l1 = (1 - pred_sets) * one_hot_labels * loss_matrix[labels]
        l2 = pred_sets * (1 - one_hot_labels) * loss_matrix[labels]

        # Calculate the total loss
        loss = torch.sum(torch.maximum(l1 + l2, torch.zeros_like(l1, device=pred_sets.device)), dim=1)

        # Return the mean loss
        return torch.mean(loss)

    def __compute_conformalized_gnn_loss(self, pred_sets, labels):
        return torch.mean(torch.relu(torch.sum(pred_sets, dim=1) - self.target_size))
