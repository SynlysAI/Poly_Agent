"""Raman 基线掩码预测网络。"""

from __future__ import annotations

import torch.nn as nn


class ConvBlock(nn.Module):
    """构建基线预测网络使用的一维卷积块。"""

    def __init__(self, in_channels: int, out_channels: int) -> None:
        """初始化卷积块。

        Args:
            in_channels: 输入通道数。
            out_channels: 输出通道数。
        """
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv1d(
                in_channels,
                out_channels,
                kernel_size=15,
                stride=1,
                padding="same",
                bias=True,
            ),
            nn.BatchNorm1d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, inputs):
        """执行卷积块前向传播。

        Args:
            inputs: 输入光谱张量。

        Returns:
            卷积块输出张量。
        """
        return self.layers(inputs)


class FCN(nn.Module):
    """预测 Raman 光谱基线区域掩码的全卷积网络。"""

    def __init__(self, in_channels: int = 1, out_channels: int = 1) -> None:
        """初始化基线掩码预测网络。

        Args:
            in_channels: 输入通道数。
            out_channels: 输出通道数。
        """
        super().__init__()
        base_channels = 16
        filters = [
            base_channels,
            base_channels * 2,
            base_channels * 4,
            base_channels * 8,
            base_channels * 16,
        ]
        self.conv1 = ConvBlock(in_channels, filters[4])
        self.conv2 = ConvBlock(filters[4], filters[3])
        self.conv3 = ConvBlock(filters[3], filters[2])
        self.conv4 = ConvBlock(filters[2], filters[1])
        self.head = nn.Conv1d(filters[1], out_channels, kernel_size=1, stride=1, padding="same")
        self.activation = nn.Sigmoid()

    def forward(self, inputs):
        """执行基线掩码预测前向传播。

        Args:
            inputs: 输入光谱张量。

        Returns:
            基线区域概率掩码张量。
        """
        features = self.conv1(inputs)
        features = self.conv2(features)
        features = self.conv3(features)
        features = self.conv4(features)
        return self.activation(self.head(features))
