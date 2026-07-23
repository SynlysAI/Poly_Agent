import os
import json

import numpy as np
import torch
from rdkit import Chem
from rdkit.Chem import rdDistGeom, rdmolops

from .greedy_search import preprocess_spectrum
from .greedy_search import load_net_state
from .resource_config import GLOBAL_CONFIG


class _Logger:
    def warning(self, message, *args):
        print(message % args if args else message)


logger = _Logger()

PARENT_PATH = os.path.dirname(os.path.realpath(__file__))
RAMAN_RESOURCES = GLOBAL_CONFIG["resources"]
RAMAN_FG_CHECKPOINT = os.path.join(RAMAN_RESOURCES["raman_checkpoints_root"], "raman_fg.pth")

def seed_everything(seed):
    import random
    import os
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True

def get_metadata(raw_data):
    # 去掉前缀和换行符，提取 JSON 部分
    json_str = raw_data.replace('capture_settings:', '').strip()

    # 解析 JSON
    data = json.loads(json_str)

    # 定义"基本信息与元数据"相关字段映射
    metadata_fields = {
        'laser': '激光波长 (nm)',
        'fExposure': '曝光时间 (s)',
        'noAccums': '累加次数',
        'nokineticScans': '动力学扫描次数',
        'accumCycleTime': '累加周期时间 (s)',
        'kineticCycleTime': '动力学周期时间 (s)',
        'centerWave': '中心波长 (nm)',
        'shWavelength': '波长设置 (nm)',
        'shGrat': '光栅选择',
        'shGratOffset': '光栅偏移',
        'readMode': '读出模式',
        'acquisitionMode': '采集模式',
        'bStepGlue': '步进拼接'
    }

    # 提取
    metadata = {}
    for key, label in metadata_fields.items():
        if key in data:
            metadata[label] = data[key]
    return metadata 

def smiles_to_graph(smiles, node_vec_len=100, max_atoms=89):
    # Get list of atoms in molecule
    mol = Chem.AddHs(
        Chem.MolFromSmiles(smiles))
    atoms = mol.GetAtoms()

    node_mat = np.zeros((max_atoms, node_vec_len))
    # Iterate over atoms and add to node matrix
    for atom in atoms:
        # Get atom index and atomic number
        atom_index = atom.GetIdx()
        atom_no = atom.GetAtomicNum()

        # Assign to node matrix
        node_mat[atom_index, atom_no] = 1

    # Get adjacency matrix using RDKit
    adj_mat = rdmolops.GetAdjacencyMatrix(mol)
    # Get distance matrix using RDKit
    dist_mat = rdDistGeom.GetMoleculeBoundsMatrix(mol)
    dist_mat[dist_mat == 0.] = 1

    # Get modified adjacency matrix with inverse bond lengths
    adj_mat = adj_mat * (1 / dist_mat)

    # Pad the adjacency matrix with 0s
    dim_add = max_atoms - adj_mat.shape[0]
    adj_mat = np.pad(
        adj_mat, pad_width=((0, dim_add), (0, dim_add)), mode="constant"
    )

    # Add an identity matrix to adjacency matrix
    # This will make an atom its own neighbor
    adj_mat = adj_mat + np.eye(max_atoms)

    # Save both matrices
    node_mat = node_mat
    adj_mat = adj_mat
    return {'node_mat': node_mat, 'adj_mat': adj_mat}


@torch.no_grad()
def main(spectrum, x0, x1, device, smiles=None, spectype='raman', mode='function_groups', k=3, transmittance=False):
    '''
    **Arguments**
    ``spectrum``: 1024-d array / list
    ``x0 & x1``: start and end of input spectrum
    ``spectype``: only 'raman'
    ``mode``: only 'function_groups'
    ``k``: unused by the function group model; kept for platform schema compatibility.
    ``transmittance``: unused by the Raman function group model; kept for platform schema compatibility.

    '''
    if spectype != 'raman' or mode != 'function_groups':
        raise ValueError("This package only supports Raman functional group analysis.")

    spectrum = preprocess_spectrum(x0, x1, spectrum, spectype=spectype, transmittance=transmittance)
    if not isinstance(spectrum, torch.Tensor):
        spectrum = torch.tensor(spectrum)
    spectrum = spectrum.to(device)

    from .models.MLPMixer import resnet
    from .models.fgs import fg_list

    model_params = {
        'depth': 1, 'hidden_size': 1024, 'block_size': 1, 'input_dim': 1024, 'in_channels': 256,
    }
    model = resnet(**model_params).eval()
    model = load_net_state(model, torch.load(RAMAN_FG_CHECKPOINT, map_location=device, weights_only=True)).to(device)
    output = model(spectrum.float())
    output = output.greater_equal(0.5).squeeze()
    output = [fg_list[i] for i in range(len(output)) if output[i]]
    return output


if __name__ == '__main__':
    # seed_everything(2026)
    # df = pd.read_pickle(r'E:\github_project\spec2mol\data\test.pkl')
    # spectrum = df['spectrum'].values[66]#torch.randn(1024)
    # print(df['smiles'].values[66] )
    # #

    # txt_data = pd.read_csv(r"E:\spectrum_files\raman\spectrum\RAMAN_00078.txt", sep=r'\s+', header=None)
    with open('raman_tests/results/218_0.dat', 'r') as f:  # 读取文件
        lines = f.readlines() 
    raw_data = lines[1] # 第二行是采集条件
    txt_data = ... #光谱数据读取方式不变

    metadata = get_metadata(raw_data)
    preprocess_info = {
        '基线校正': 'PEER',
        '平滑算法': 'WhittakerSmooth',
        '归一化': 'Max',
        '信噪比': ''
    }
    model_info = {
        '输入维度': '1024',
        '拉曼位移范围': '400-4000'
    }

    report = {
        "基本信息与元数据": metadata,
        "预处理信息": preprocess_info,
        "模型信息": model_info
    }

    for label, value in report.items():
        print(f"  {label}: {value}")
    # 取第一列首尾作为输入谱图的 x0 / x1，第二列作为强度序列
    x0 = float(txt_data.iloc[0, 0])
    x1 = float(txt_data.iloc[-1, 0])
    print(x0, x1)
    spectrum = txt_data.iloc[:, 1].values
    # # 导出为 x, y 两列的 txt 文件
    # output_dir = r'E:\github_project\Spec_Agent'
    # output_file = os.path.join(output_dir, 'spectrum_test2.txt')
    # x_values = np.linspace(x1, x0, len(spectrum))
    # data_to_save = np.column_stack((x_values, spectrum))
    # np.savetxt(output_file, data_to_save, fmt='%.6f', delimiter='\t')
    # print(f"已导出谱图数据到: {output_file}")
    # print(f"数据点数量: {len(spectrum)}")

    device = torch.device('cpu')
    result = main(spectrum, x0=x0, x1=x1, device=device, spectype='raman', mode='function_groups',)
    print(result, 111)


    # 生成图片
    # if type(result) == dict:
    #     mols = [Chem.MolFromSmiles(s) for s in result['structure']]
    #     legends = [f'{result['structure'][i]}: {result['score'][i]:.4f}' for i in range(len(result['structure']))]
    # elif type(result) == list:
    #     mols = [Chem.MolFromSmarts(i) for i in result]
    #     legends = [None]*len(result)
    # else:
    #     result = [result]
    #     mols = [Chem.MolFromSmiles(s) for s in result]
    #     legends = result
    # result = pd.DataFrame({
    #     'structure': [mol_to_image(m) for m in mols], # 分子结构的图片
    #     'legend:': legends, # 作为分子图片的配字
    # })
    # # 保存分子为图片：
    # i = 1
    # for m in result['structure'].values:
    #     if m: m.save(f'{i}mol.png')
    #     i += 1
