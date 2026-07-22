import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from transformers import AutoTokenizer
from .resource_config import GLOBAL_CONFIG


def collate_fn(batch):
    
    tokenizer = AutoTokenizer.from_pretrained(str(GLOBAL_CONFIG["resources"]["raman_tokenizer_root"]))
    x = [item[0] for item in batch]
    x = torch.nn.utils.rnn.pad_sequence(x, batch_first=True, padding_value=1).unsqueeze(1)
    y = [item[1] for item in batch]
    y = tokenizer(y, padding=True, truncation=True, return_tensors="pt")
    return x, y


def load_dataset(spectype):
    
    mols, specs = []
    for m in ['test','train','eval']:
        dataset = pd.read_pickle(f'/home/lyt/projects/spec2mol_1/datasets/{spectype}2mol/{m}.pkl')
        mols.append(dataset['smiles'].values)
        specs.append(dataset['spectrum'].values)
    # dataset = Dataset(np.vstack(specs), np.hstack(mols))
    loader = DataLoader(np.vstack(specs), batch_size=16, shuffle=False, pin_memory=True)
    return loader, mols


def retrieval(spectrum, db, model, device, k=5):

    if type(model) == torch.nn.parallel.DistributedDataParallel:
        model = model.module
    else:
        model = model
    tgt_norm = torch.FloatTensor(np.vstack(db['emb'].values), device=device)
    db_mol = db['structure'].values
    src_emb = model.src_ff_norm(
        model.encode(spectrum, None))
    src_norm = src_emb / src_emb.norm(dim=-1, keepdim=True)
    sims = (src_norm @ tgt_norm.T).squeeze()
    retrieval_scores, retrieval_ids = torch.topk(sims, k)
    structure = [i for i in db_mol[retrieval_ids.cpu().detach().numpy()]]
    score = [j for j in retrieval_scores.cpu().detach().numpy()]

    # 检查数据库是否有 spectrum 列
    result = {'score': score, 'structure': structure}
    if 'spectrum' in db.columns:
        retrieval_spectrum = [k for k in db['spectrum']
                          [retrieval_ids.cpu().detach().numpy()]]
    else:
        retrieval_spectrum = [[retrieval_ids.cpu().detach().numpy()]]
    result['spectrum'] = retrieval_spectrum

    del db
    return result
