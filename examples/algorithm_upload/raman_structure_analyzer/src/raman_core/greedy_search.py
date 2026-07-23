import os

import json
import numpy as np
from functools import lru_cache
from scipy.sparse import csc_matrix, diags, eye
from scipy.sparse.linalg import spsolve
import torch
import torch.nn.functional as F
from torch.autograd import Variable
from .resource_config import GLOBAL_CONFIG


class _Logger:
    def warning(self, message, *args):
        print(message % args if args else message)


logger = _Logger()
PARENT_PATH = os.path.dirname(os.path.realpath(__file__))
TOKENIZER_PATH = str(GLOBAL_CONFIG["resources"]["raman_tokenizer_root"])
VOCAB_PATH = os.path.join(TOKENIZER_PATH, 'vocab.json')
BASELINE_MODEL_PATH = os.path.join(
    str(GLOBAL_CONFIG["resources"]["raman_checkpoints_root"]),
    "baseline_removal.pth",
)

def get_smiles(label):
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        tokens = {val: key for key, val in json.load(f).items()}
    smiles = ''
    if type(label) == torch.Tensor: label = label.cpu().detach()
    for l in label:
        smiles += tokens[l.data.item()]
    smiles = smiles.replace('</s>', '')
    smiles = smiles.replace('<s>', '')
    smiles = smiles.replace('<unk>', '')
    smiles = smiles.replace('<pad>', '')
    return smiles


def mol_to_image(mol):
    from rdkit.Chem import Draw

    try:
        img = Draw.MolToImage(mol)
    except:
        img = None
    return img


def collate_fn(batch):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_PATH)
    x = [item[0] for item in batch]
    x = torch.nn.utils.rnn.pad_sequence(x, batch_first=True, padding_value=1).unsqueeze(1)
    y = [item[1] for item in batch]
    y = tokenizer(y, padding=True, truncation=True, return_tensors="pt")
    return x, y


def load_net_state(net, state_dict):
    '''check the keys and load the weight'''
    net_keys = net.state_dict().keys()
    state_dict_keys = state_dict.keys()
    for key in net_keys:
        if key in state_dict_keys:
            # load the weight
            net.state_dict()[key].copy_(state_dict[key])
        else:
            logger.warning("模型权重缺失: %s", key)
    net.load_state_dict(net.state_dict())
    return net


def normalization(data):
    """按最大值归一化一维谱图数据。"""
    data = np.asarray(data, dtype=np.float32)
    max_value = np.max(data)
    if max_value <= 0:
        return data.copy()
    return data / max_value


def distance_reciprocal(a, b):
    """计算两个标量的倒数距离权重。"""
    distance = float((a ** 2 + b ** 2) ** 0.5)
    if distance == 0:
        return 0.0
    return 1.0 / distance


def peer(data, window_size):
    """使用 PEER 方法平滑一维谱图信号。"""
    margin = (window_size - 1) // 2
    point_count = len(data)
    smoothed = [0.0 for _ in range(point_count)]

    for index in range(point_count):
        weight_sum = 0.0
        if index <= margin - 1:
            left_index = 0
            right_index = index + margin
            probability_sum = 0.0
            weight_sum += data[0] * (margin - index)
            weighted_values = [0.0 for _ in range(right_index - left_index + 1)]
            for current in range(left_index, right_index + 1):
                weight_sum += data[current]
            average = weight_sum / window_size
            if average in data[left_index:right_index + 1]:
                smoothed[index] = average
            else:
                for current in range(left_index, right_index + 1):
                    probability_sum += distance_reciprocal(data[current], average)
                for offset, current in enumerate(range(left_index, right_index + 1)):
                    weighted_values[offset] = data[current] * (
                        distance_reciprocal(data[current], average) / probability_sum
                    )
                    smoothed[index] += weighted_values[offset]
        elif index >= point_count - margin:
            left_index = index - margin
            right_index = point_count - 1
            probability_sum = 0.0
            weight_sum += data[point_count - 1] * (margin - point_count + index)
            weighted_values = [0.0 for _ in range(right_index - left_index + 1)]
            for current in range(left_index, right_index + 1):
                weight_sum += data[current]
            average = weight_sum / window_size
            if average in data[left_index:right_index + 1]:
                smoothed[index] = average
            else:
                for current in range(left_index, right_index + 1):
                    probability_sum += distance_reciprocal(data[current], average)
                for offset, current in enumerate(range(left_index, right_index + 1)):
                    weighted_values[offset] = data[current] * (
                        distance_reciprocal(data[current], average) / probability_sum
                    )
                    smoothed[index] += weighted_values[offset]
        else:
            left_index = index - margin
            right_index = index + margin
            probability_sum = 0.0
            weighted_values = [0.0 for _ in range(right_index - left_index + 1)]
            for current in range(left_index, right_index + 1):
                weight_sum += data[current]
            average = weight_sum / window_size
            if average in data[left_index:right_index + 1]:
                smoothed[index] = average
            else:
                for current in range(left_index, right_index + 1):
                    probability_sum += distance_reciprocal(data[current], average)
                for offset, current in enumerate(range(left_index, right_index + 1)):
                    weighted_values[offset] = data[current] * (
                        distance_reciprocal(data[current], average) / probability_sum
                    )
                    smoothed[index] += weighted_values[offset]
    return np.asarray(smoothed, dtype=np.float32)


def whittaker_smooth(signal, weights, lambda_value, differences=2):
    """执行 Whittaker 平滑以拟合基线。"""
    signal_matrix = np.matrix(signal)
    point_count = signal_matrix.size
    diff_matrix = eye(point_count, format="csc")
    for _ in range(differences):
        diff_matrix = diff_matrix[1:] - diff_matrix[:-1]
    weight_matrix = diags(weights, 0, shape=(point_count, point_count))
    system_matrix = csc_matrix(weight_matrix + (lambda_value * diff_matrix.T * diff_matrix))
    rhs = csc_matrix(weight_matrix * signal_matrix.T)
    baseline = spsolve(system_matrix, rhs)
    return np.array(baseline, dtype=np.float32)


@lru_cache(maxsize=1)
def _load_baseline_model(device: str = "cpu"):
    """加载 Raman 基线消除模型。"""
    if not os.path.exists(BASELINE_MODEL_PATH):
        logger.warning("未找到 Raman 基线消除模型: %s", BASELINE_MODEL_PATH)
        raise FileNotFoundError(f"未找到 Raman 基线消除模型: {BASELINE_MODEL_PATH}")

    model = FCN()
    model = load_net_state(
        model,
        torch.load(BASELINE_MODEL_PATH, map_location=device, weights_only=False),
    )
    model = model.to(device)
    model.eval()
    return model


@torch.no_grad()
def remove_baseline(spectrum, itermax=1000):
    """对 Raman 光谱执行基线消除。"""
    spectrum_raw = np.asarray(spectrum, dtype=np.float32).copy()
    if spectrum_raw.ndim != 1:
        logger.warning("基线消除仅支持一维光谱，当前形状: %s", spectrum_raw.shape)
        raise ValueError(f"基线消除仅支持一维光谱，当前形状: {spectrum_raw.shape}")
    if spectrum_raw.size < 3:
        return spectrum_raw
    if not np.isfinite(spectrum_raw).all():
        spectrum_raw = np.nan_to_num(spectrum_raw, copy=False)
    if np.max(spectrum_raw) <= 0:
        return spectrum_raw

    spectrum_input = normalization(spectrum_raw)
    spectrum_smoothed = peer(spectrum_input, 5)
    spectrum_smoothed = peer(spectrum_smoothed, 5)
    spectrum_smoothed = normalization(spectrum_smoothed)

    spectrum_tensor = torch.as_tensor(
        spectrum_smoothed,
        dtype=torch.float32,
    ).reshape(1, 1, -1)
    baseline_model = _load_baseline_model()
    mask = baseline_model(spectrum_tensor).cpu().numpy()[0, 0, :].astype(np.float32)
    weights = np.where(mask > 0.5, 0.0, 1.0).astype(np.float32)
    weights[0] = 1.0
    weights[-1] = 1.0

    for lambda_value in (100000000, 10000000):
        for _ in range(itermax):
            baseline = whittaker_smooth(spectrum_input, weights, lambda_value, 2)
            residual = spectrum_input - baseline
            negative_mask = residual < 0
            if negative_mask.any():
                weights[negative_mask] += (
                    residual[negative_mask] < -0.001
                ).astype(np.float32) * 0.1
            edge_weight = float(np.max(weights))
            weights[0] = edge_weight
            weights[-1] = edge_weight

    baseline = whittaker_smooth(spectrum_input, weights, 10000000, 2)
    return (spectrum_input - baseline).astype(np.float32)


def preprocess_spectrum(x0, x1, intensities,
                        target_range=(400, 4000),
                        target_points=1024,
                        spectype='ir',
                        transmittance=False):
    """
    将输入谱图裁剪到有效范围后重采样为模型所需的固定倒序点列。

    Args:
        x0: 输入谱图第一行对应的 x 值。
        x1: 输入谱图最后一行对应的 x 值。
        intensities: 输入谱图 y 值序列。
        target_range: 算法固定使用的有效 x 范围。
        target_points: 模型要求的固定采样点数。
        spectype: 光谱类型，支持 ``ir`` 或 ``raman``。
        transmittance: IR 模式下是否先将透射率转换为吸光度。

    Returns:
        形状为 ``(1, 1, target_points)`` 的倒序光谱张量。
    """
    intensities = np.asarray(intensities, dtype=np.float32).reshape(-1)
    if intensities.size == 0:
        logger.warning("输入光谱强度不能为空")
        raise ValueError("输入光谱强度不能为空")

    # 把透射率转换为吸光度
    if spectype == 'ir' and transmittance:
        intensities = -np.log10(np.clip(intensities, 0.01, 100) / 100)  # 设置最小0.01%透射率
    max_intensity = np.max(intensities)
    if max_intensity > 0:
        intensities = intensities / max_intensity
    target_min, target_max = target_range
    wavenumbers = np.linspace(x0, x1, intensities.shape[-1])

    # 1. 截断：只保留目标范围内的数据
    mask = (wavenumbers >= target_min) & (wavenumbers <= target_max)
    wavenumbers_clipped = wavenumbers[mask]
    intensities_clipped = intensities[mask]

    if len(wavenumbers_clipped) == 0:
        logger.warning("输入光谱在目标范围 %s 内没有数据", target_range)
        raise ValueError(f"输入光谱在目标范围 {target_range} 内没有数据")

    # 2. 插值前统一为升序，保证 np.interp 的输入单调递增。
    if wavenumbers_clipped[0] > wavenumbers_clipped[-1]:
        wavenumbers_clipped = wavenumbers_clipped[::-1]
        intensities_clipped = intensities_clipped[::-1]

    if len(wavenumbers_clipped) < 2:
        output = np.zeros(target_points, dtype=np.float32)
    else:
        # 3. 创建升序目标波数轴，范围外自动补 0。
        new_wavenumbers = np.linspace(target_min, target_max, target_points)
        output = np.interp(
            new_wavenumbers,
            wavenumbers_clipped,
            intensities_clipped,
            left=0.0,
            right=0.0,
        )

    output = remove_baseline(output)
    output_min = np.min(output)
    output = output - output_min
    output_max = np.max(output)
    if output_max > 0:
        output = output / output_max

    # 4. 模型固定要求倒序输入，即 4000 -> 400。
    output = output[::-1].copy()
    output = torch.FloatTensor(output)
    output = output.reshape(1, 1, output.shape[-1]) if output.dim() != 3 else output
    return output


# def collate_spectrum(input, start, end, x0=400, x1=4000, dim_target=1024):
#     x_target = np.linspace(x0, x1, dim_target)
#     unit_target = (x1-x0) / (dim_target-1)
#     input = np.array(input)
#     unit_input = (end-start) / (input.shape[-1]-1)

#     if start == x0 and end == x1:
#         if input.shape(-1) == 1024:
#             output = input
#         else:
#             f = interp1d(np.linspace(start, end, unit_input), input, kind='slinear')
#             output = f(x_target)
#     else:
#         if start != x0:
#             num_pad_start = int((x0-start) / unit_input)

#     output = torch.FloatTensor(output)
#     output = output.reshape(1, 1, output.shape[-1]) if output.dim() != 3 else output

def greedy_decode(spectrum, spectrum_length, model, device, bos=0, eos=2, pad_idx=1, max_len=70,
                  repetition_penalty=None):
    if type(model) == torch.nn.parallel.DistributedDataParallel:
        model = model.module
    else:
        model = model
    spectrum_mask = Variable(torch.ones(spectrum.shape[0], 1, spectrum_length, device=device))
    ys = torch.ones(spectrum.shape[0], 1, device=device, dtype=torch.long).fill_(bos)
    memory = model.encode(spectrum, spectrum_mask)
    output = torch.zeros(spectrum.shape[0], max_len, device=device)
    for i in range(max_len - 1):
        tgt_mask = torch.ones_like(ys, device=device)
        out = model.decode(memory, spectrum_mask,
                           Variable(ys),
                           Variable(tgt_mask))
        out = out['decoder_output']
        logits = model.generator(out[:, -1])

        if repetition_penalty is not None:
            tok_seen = list(set(ys[0].tolist()))
            for tok in tok_seen:
                logits[:, tok] /= repetition_penalty
        prob = F.softmax(logits, dim=-1)
        _, next_word = torch.max(prob, dim=-1)
        # next_word = next_word.masked_fill(ys[:, -1]==eos, pad_idx)
        ys = torch.cat([ys, next_word.unsqueeze(1)], dim=1)
        for j in range(len(ys)):
            pad_size = max_len - i - 2
            if ys[j][-1] == eos and not output[j].all():
                if pad_size > 0:
                    output[j] = torch.hstack(
                        [ys[j], torch.ones(pad_size, device=device, dtype=torch.long).fill_(pad_idx)])
                else:
                    output[j] = ys[j]
        # ys = ys.masked_fill(ys==eos, pad_idx)
        if not (output[:, 1:] == torch.zeros(max_len - 1, device=device, dtype=torch.long)).any():
            break
    output = [get_smiles(y) for y in output]
    return output


if __name__ == "__main__":
    spec = torch.randn(1024)  ### input spectrum: 长度1024，波数范围400-4000
    from .models.Transformer import make_model

    vocab_size = 181
    model, spectrum_length = make_model(vocab_size, N=4, d_model=512)
    beam_size = 10
    checkpoint = 'spec2mol_1/checkpoints/checkpoint.pth'
    device = torch.device('cpu')
    model = load_net_state(model, torch.load(checkpoint, map_location=device, weights_only=True)['model_state']).to(
        device)

    pred = greedy_decode(model,
                         spec,
                         spectrum_length)
    print(pred)
