import numpy as np
import torch, math, copy
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
from functools import partial


class MultiHeadedAttention(nn.Module):
    def __init__(self, h, d_model, dropout=0.1):
        "Take in model size and number of heads."
        super(MultiHeadedAttention, self).__init__()
        assert d_model % h == 0
        # We assume d_v always equals d_k
        self.d_k = d_model // h
        self.h = h
        self.linears = clones(nn.Linear(d_model, d_model), 4)
        self.attn = None
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, query, key, value, mask=None, past=None):
        "Implements Figure 2"
        if mask is not None:
            # Same mask applied to all h heads.
            mask = mask.unsqueeze(1)
        nbatches = query.size(0)

        # 1) Do all the linear projections in batch from d_model => h x d_k
        query, key, value = \
            [l(x).view(nbatches, -1, self.h, self.d_k).transpose(1, 2)
             for l, x in zip(self.linears, (query, key, value))]
        if past is not None:
            past_k, past_v = past
            key = torch.cat([past_k, key], dim=2)  # 沿 seq 维度拼
            value = torch.cat([past_v, value], dim=2)
            new_kv = (key, value)
        else:
            new_kv = (key, value)
        # 2) Apply attention on all the projected vectors in batch.
        x, self.attn = attention(query, key, value, mask=mask,
                                 dropout=self.dropout)

        # 3) "Concat" using a view and apply a final linear.
        x = x.transpose(1, 2).contiguous().view(
            nbatches, -1, self.h * self.d_k)
        return self.linears[-1](x), new_kv


class CLIP_ff(nn.Module):

    def __init__(self, d_model, if_norm=False):
        super(CLIP_ff, self).__init__()
        self.norm = LayerNorm(d_model) if if_norm else nn.Identity()
        self.proj = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Linear(d_model, d_model))

    def forward(self, x):
        return self.proj(self.norm(x)[:, 0])


class EncoderDecoder(nn.Module):
    """
    A standard Encoder-Decoder architecture. Base for this and many
    other models.
    """

    def __init__(self, encoder, decoder, src_embed, tgt_embed, generator, tgt_ff_norm, src_ff_norm, mode='train'):
        super(EncoderDecoder, self).__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.src_embed = src_embed
        self.tgt_embed = tgt_embed
        self.generator = generator
        self.mode = mode
        self.tgt_ff_norm = tgt_ff_norm
        self.src_ff_norm = src_ff_norm

        if mode == 'pretrain_spec':
            for p in self.decoder.parameters():
                p.requires_grad = False
            for p in self.tgt_embed.parameters():
                p.requires_grad = False

        if mode == 'pretrain_mol':
            self.mask_token = nn.Parameter(torch.randn(self.tgt_embed[0].named_parameters()['d_model']))
            for p in self.encoder.parameters():
                p.requires_grad = False
            for p in self.src_embed.parameters():
                p.requires_grad = False
            for layer in self.decoder.layers:
                for sublayer in layer.sublayer[1:]:
                    for p in sublayer.parameters():
                        p.requires_grad = False

        if 'retrieval' in mode:
            self.logit_scale = nn.Parameter(torch.rand([]))
            for layer in self.decoder.layers:
                for sublayer in layer.sublayer[1:]:
                    for p in sublayer.parameters():
                        p.requires_grad = False
            for p in self.generator.parameters():
                p.requires_grad = False

        # if 'mlm' in mode:
        #     self.logit_scale = nn.Parameter(torch.rand([]))
        #     for layer in self.encoder.layers:
        #         for p in layer.parameters():
        #             p.requires_grad = False
        #     for p in encoder.norm.parameters():
        #         p.requires_grad = False

    def argue(self):
        make_argue()

    def forward(self, src=None, tgt=None, src_mask=None, tgt_mask=None, past_key_values=None):
        # if 'train' or 'test' in self.mode:
        # if 'mlm' in self.mode:
        #     src_emb = None
        # print(torch.unique(tgt))
        # print(Embeddings(181,512)(tgt.cpu().detach()))
        #     decoder_out = self.decode(src, src_mask, tgt, tgt_mask)
        #     tgt_emb = decoder_out['tgt_emb']
        #     output = self.generator(tgt_emb)
        #     output[~mlm_mask] = -100
        # else:
        src_emb = self.encode(src, src_mask)
        decoder_out = self.decode(src_emb, src_mask,
                                  tgt, tgt_mask, past_key_values=past_key_values)
        tgt_emb = self.tgt_ff_norm(decoder_out['tgt_emb'])
        src_emb = self.src_ff_norm(src_emb)
        if 'retrieval' in self.mode:
            output = decoder_out['decoder_output']
        else:
            output = self.generator(decoder_out['decoder_output'])
            # if mlm_mask is not None:
            #     output[~mlm_mask] = -100
        return {'decoder_output': output,
                'tgt_emb': tgt_emb,
                'src_emb': src_emb, }
        # elif self.mode == 'pretrain_spec':
        #     return self.generator(self.encode(src, None))
        # elif self.mode == 'pretrain_mol':
        #     tgt = self.tgt_embed(tgt)
        #     for layer in self.decoder.layers:
        #         x = layer.sublayer[0](tgt, lambda x: layer.self_attn(x, x, x, tgt_mask))
        #     return self.generator(x[:, 0])

    def encode(self, src, src_mask):
        return self.encoder(self.src_embed(src), src_mask)

    def decode(self, memory, src_mask, tgt, tgt_mask, past_key_values=None):
        # if 'mlm' in self.mode:
        #     tgt, self.mlm_mask_positions = mlm_mask(tgt, tgt_mask, mask_prob, mask_token_id)
        # mask_positions = (tgt == mask_token_id).unsqueeze(-1)
        # tgt = torch.where(mask_positions, self.mask_token, tgt)
        tgt = self.tgt_embed[0](tgt)
        tgt_mask = std_mask(tgt, tgt_mask) if tgt_mask is not None else None
        for emb_module in self.tgt_embed[1:]:
            tgt = emb_module(tgt)
        return self.decoder(tgt, memory, src_mask, tgt_mask, past_key_values=past_key_values)


class SpecEncoder(nn.Module):

    def __init__(self, encoder, src_embed, generator):
        super().__init__()
        self.encoder = encoder
        self.src_embed = src_embed
        self.generator = generator

    def forward(self, src, src_mask):
        return self.generator(self.encoder(self.src_embed(src), src_mask)[:, 0])


class MolEncoder(nn.Module):
    """
    只保留 DecoderLayer 的第一层：Masked Self-Attention
    输入：  tgt      [batch, tgt_len, d_model]
           tgt_mask [batch, 1, tgt_len, tgt_len]  # 下三角 0/1 掩码
    输出：  out      [batch, tgt_len, d_model]
    """

    def __init__(self, d_model, n_heads, dropout=0.1):
        super().__init__()
        # 复制原结构的 Norm + Dropout + Residual
        self.norm = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)

        # 重新创建一个 MultiHeadAttention（与原 DecoderLayer 的 self_attn 同配置）
        self.self_attn = MultiHeadedAttention(
            embed_dim=d_model,
            num_heads=n_heads,
            dropout=dropout,
            batch_first=True  # PyTorch ≥1.9
        )

    def forward(self, x, tgt_mask=None):
        # Norm
        normed = self.norm(x)
        # 带掩码的自注意力
        attn_out, _ = self.self_attn(normed, normed, normed,
                                     attn_mask=tgt_mask)  # tgt_mask 就是下三角
        # Residual + Dropout
        out = x + self.dropout(attn_out)
        return out


class Generator(nn.Module):
    "Define standard linear + softmax generation step."

    def __init__(self, d_model, vocab):
        super(Generator, self).__init__()
        self.proj = nn.Sequential(nn.Linear(d_model, d_model), nn.Tanh(), nn.Linear(d_model, vocab))

    def forward(self, x):
        return self.proj(x)  # F.log_softmax(self.proj(x), dim=-1)


def clones(module, N):
    "Produce N identical layers."
    return nn.ModuleList([copy.deepcopy(module) for _ in range(N)])


class Encoder(nn.Module):
    "Core encoder is a stack of N layers"

    def __init__(self, layer, N):
        super(Encoder, self).__init__()
        self.layers = clones(layer, N)
        self.norm = LayerNorm(layer.size)

    def forward(self, x, mask):
        "Pass the input (and mask) through each layer in turn."
        for layer in self.layers:
            x = layer(x, mask)
        return self.norm(x)


class LayerNorm(nn.Module):
    "Construct a layernorm module (See citation for details)."

    def __init__(self, features, eps=1e-6):
        super(LayerNorm, self).__init__()
        self.a_2 = nn.Parameter(torch.ones(features))
        self.b_2 = nn.Parameter(torch.zeros(features))
        self.eps = eps

    def forward(self, x):
        mean = x.mean(-1, keepdim=True)
        std = x.std(-1, keepdim=True)
        return self.a_2 * (x - mean) / (std + self.eps) + self.b_2


class SublayerConnection(nn.Module):
    """
    A residual connection followed by a layer norm.
    Note for code simplicity the norm is first as opposed to last.
    """

    def __init__(self, size, dropout):
        super(SublayerConnection, self).__init__()
        self.norm = LayerNorm(size)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, sublayer):
        "Apply residual connection to any sublayer with the same size."
        layer_out = sublayer(self.norm(x))
        if type(layer_out) == tuple:
            return x + self.dropout(layer_out[0]), layer_out[1]
        else:
            return x + self.dropout(layer_out)


class EncoderLayer(nn.Module):
    "Encoder is made up of self-attn and feed forward (defined below)"

    def __init__(self, size, self_attn, feed_forward, dropout):
        super(EncoderLayer, self).__init__()
        self.self_attn = self_attn
        self.feed_forward = feed_forward
        self.sublayer = clones(SublayerConnection(size, dropout), 2)
        self.size = size

    def forward(self, x, mask):
        "Follow Figure 1 (left) for connections."
        x, _ = self.sublayer[0](x, lambda x: self.self_attn(x, x, x, mask))
        return self.sublayer[1](x, self.feed_forward)


class Decoder(nn.Module):
    "Generic N layer decoder with masking."

    def __init__(self, layer, N):
        super(Decoder, self).__init__()
        self.layers = clones(layer, N)
        self.norm = LayerNorm(layer.size)

    def forward(self, x, memory, src_mask=None, tgt_mask=None, past_key_values=None):
        if past_key_values is None:
            past_key_values = [None] * len(self.layers)
        new_past = []
        for i in range(len(self.layers)):
            out = self.layers[i](x, memory, src_mask, tgt_mask, past_key_values[i])
            new_past.append(out['new_past'])
            if out['tgt_emb'] is None:
                x = out['decoder_output']
                if i == len(self.layers) - 1:
                    decoder_output = self.norm(x)
            else:
                x = out['tgt_emb']
                decoder_output = out['decoder_output']

        return {'decoder_output': decoder_output,
                'past': new_past,
                'tgt_emb': out['tgt_emb']}


class DecoderLayer(nn.Module):
    "Decoder is made of self-attn, src-attn, and feed forward (defined below)"

    def __init__(self, size, self_attn, src_attn, feed_forward, dropout, mode):
        super(DecoderLayer, self).__init__()
        self.size = size
        self.self_attn = self_attn
        self.src_attn = src_attn
        self.feed_forward = feed_forward
        self.mode = mode
        if 'retrieval' in self.mode:
            self.clip_sublayer = SublayerConnection(size, dropout)
            self.clip_ff = copy.deepcopy(feed_forward)
        self.sublayer = clones(SublayerConnection(size, dropout), 3)

    def forward(self, x, memory, src_mask=None, tgt_mask=None, past=None):
        "Follow Figure 1 (right) for connections."
        m = memory
        tgt_emb, new_kv = self.sublayer[0](x, lambda x: self.self_attn(x, x, x, tgt_mask, past))
        if 'retrieval' in self.mode:
            tgt_emb = self.clip_sublayer(tgt_emb, self.clip_ff)
            decoder_output = None
        else:
            tgt_emb, _ = self.sublayer[1](tgt_emb, lambda x: self.src_attn(x, m, m, src_mask))
            decoder_output = self.sublayer[2](tgt_emb, self.feed_forward)
        return {
            'decoder_output': decoder_output,
            'new_past': new_kv,
            'tgt_emb': tgt_emb}


def subsequent_mask(size):
    "Mask out subsequent positions."
    attn_shape = (1, size, size)
    subsequent_mask = np.triu(np.ones(attn_shape), k=1).astype('uint8')
    return torch.from_numpy(subsequent_mask) == 0


def attention(query, key, value, mask=None, dropout=None):
    "Compute 'Scaled Dot Product Attention'"
    d_k = query.size(-1)
    scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(d_k)
    if mask is not None:
        # print(scores.shape, mask.shape)
        scores = scores.masked_fill(mask == 0, -1e9)
        # torch.save({'mask':mask[0].cpu().detach(), 'q':query[0].cpu().detach(),
        #             'k':key[0].cpu().detach(), 'v':value[0].cpu().detach()}, '/home/lyt/projects/spec2mol_1/data.pt')
    p_attn = F.softmax(scores, dim=-1)
    if dropout is not None:
        p_attn = dropout(p_attn)
    return torch.matmul(p_attn, value), p_attn


class PositionwiseFeedForward(nn.Module):
    "Implements FFN equation."

    def __init__(self, d_model, d_ff, dropout=0.1):
        super(PositionwiseFeedForward, self).__init__()
        self.w_1 = nn.Linear(d_model, d_ff)
        self.w_2 = nn.Linear(d_ff, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        return self.w_2(self.dropout(F.relu(self.w_1(x))))


class Embeddings(nn.Module):
    def __init__(self, d_model, vocab=512):
        super(Embeddings, self).__init__()
        self.lut = nn.Embedding(vocab, d_model, 0)
        self.d_model = d_model

    def forward(self, x):
        return self.lut(x) * math.sqrt(self.d_model)


class PositionalEncoding(nn.Module):
    "Implement the PE function."

    def __init__(self, d_model, dropout, max_len=5000):
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        # Compute the positional encodings once in log space.
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) *
                             -(math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        self.register_buffer('pe', pe)

    def forward(self, x):
        x = x + Variable(self.pe[:, :x.size(1)],
                         requires_grad=False)
        return self.dropout(x)


class LearnablePositionalEncoding(nn.Module):
    "Implement the PE function."

    def __init__(self, d_model, dropout, max_len=5000):
        super(LearnablePositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        # Create the learnable positional embeddings
        self.pe = nn.Parameter(torch.randn(max_len, d_model))

    def forward(self, x):
        x = x + self.pe[:x.size(1)]
        return self.dropout(x)


class LearnableClassEmbedding(nn.Module):
    "Implement the class and distillation embeddings."

    def __init__(self, d_model, dropout, dist=False):
        super(LearnableClassEmbedding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        # Create the learnable embeddings
        self.ce = nn.Parameter(torch.randn(1, d_model))
        self.de = nn.Parameter(torch.randn(1, d_model)) if dist else None

    def forward(self, x):
        # concatenate the class and distillation embeddings
        if self.de is not None:
            x = torch.cat((self.ce.repeat(x.size(0), 1).unsqueeze(1), x,
                           self.de.repeat(x.size(0), 1).unsqueeze(1)), dim=1)
        else:
            x = torch.cat((self.ce.repeat(x.size(0), 1).unsqueeze(1), x), dim=1)
        return x


class LearnableClassEmbedding(nn.Module):
    "Implement the class and distillation embeddings."

    def __init__(self, d_model, dropout, dist=False):
        super(LearnableClassEmbedding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        # Create the learnable embeddings
        self.ce = nn.Parameter(torch.randn(1, d_model))
        self.de = nn.Parameter(torch.randn(1, d_model)) if dist else None

    def forward(self, x):
        # concatenate the class and distillation embeddings
        if self.de is not None:
            x = torch.cat((self.ce.repeat(x.size(0), 1).unsqueeze(1), x,
                           self.de.repeat(x.size(0), 1).unsqueeze(1)), dim=1)
        else:
            x = torch.cat((self.ce.repeat(x.size(0), 1).unsqueeze(1), x), dim=1)
        return x


class DataGenerator:

    def __init__(self, batch, src_length, device=torch.device('cpu'), mode='test', mlm_mask_id=4, mask_prob=0.15):
        self.device = device
        self.src, tgt, tgt_mask = [i.to(self.device) for i in self.collate(batch, src_length)]
        self.batch_size = self.src.size(0)
        self.true_seq = [seq[torch.where(seq != 1)[0]][1:] for seq in tgt]
        self.src_length = src_length
        # self.padding_idx = padding_value
        # self.tokenizer = AutoTokenizer.from_pretrained("../models/moltokenizer")
        if 'mlm' in mode:
            tgt_y = tgt.clone()
            self.tgt_mask = tgt_mask
            tgt, self.mlm_mask = mlm_mask(tgt, self.tgt_mask, mask_prob, mlm_mask_id)
            self.tgt = tgt
            tgt_y[~self.mlm_mask] = -100
            self.tgt_y = tgt_y
            self.ntokens = self.mlm_mask.sum()
        else:
            self.tgt = tgt[:, :-1]
            self.tgt_y = tgt[:, 1:]
            ntokens = sum([(y != y[-1]).sum() for y in self.tgt_y])
            self.tgt_mask = tgt_mask[:, :-1]
            self.mlm_mask = None
            self.ntokens = ntokens

    def make_pad_mask(self, lengths: torch.Tensor, max_len: int = None):

        # batch_size = lengths.size(0)
        max_len = lengths.max()
        # [batch, max_len]
        mask = torch.arange(max_len).unsqueeze(0) >= lengths.unsqueeze(1)
        return mask.unsqueeze(1).to(self.device)

    def make_causal_mask(self, sz: int):
        return torch.triu(torch.ones(sz, sz, dtype=torch.int, device=self.device), diagonal=0)

    def collate(self, batch, src_length=None):
        # if src_length is None:
        #     src_lengths = torch.tensor([k.shape[-1] for k in batch[0]])
        # else:
        #     src_lengths = torch.tensor([src_length for _ in batch[0]])
        #     src_mask=None
        #     src = batch[0]
        # else:
        src = batch[0]  # torch.nn.utils.rnn.pad_sequence(batch[0], batch_first=True, padding_value=self.padding_idx)
        # src_mask = None self.make_pad_mask(src_lengths, src.size(-1))   # [B,1,1,Ls]
        tgt = batch[1]['input_ids']
        tgt_pad_mask = batch[1]['attention_mask']
        return src, tgt, tgt_pad_mask
        # tgt_y = tgt[:,1:]
        # tgt = torch.where(tgt==2, 1, tgt)#torch.vstack([t[:torch.where(t==2)[0]:] for t in tgt])
        # print(tgt[0], tgt_y[0] )
        # tgt = tgt[:, :-1]
        # seq[torch.where(seq!=1)[0]][1:]
        # for i in range(len(tgt)):
        #     eos_id = torch.where(tgt[i]==2)[0]
        #     tgt[i][eos_id] = 1
        #     tgt_pad_mask[i][eos_id] = 0
        # ntokens = sum([(y!=y[-1]).sum() for y in tgt_y])
        # tgt = torch.nn.utils.rnn.pad_sequence(tgt, batch_first=True, padding_value=padding_value)
        # tgt_y = torch.nn.utils.rnn.pad_sequence(tgt_y, batch_first=True, padding_value=padding_value)
        # tgt_lengths = torch.tensor([j.shape[-1] for j in tgt])
        # tgt_pad_mask = self.make_pad_mask(tgt_lengths, tgt.size(-1))  # [B,1,1,Lt]
        # causal_mask = self.make_causal_mask(tgt.size(1))  # [Lt,Lt]
        # tgt_mask = tgt_pad_mask | causal_mask #tgt_pad_mask  .unsqueeze(0).unsqueeze(0)


class Batch:
    "Object for holding a batch of data with mask during training."

    def __init__(self, src, tgt=None, pad=0):
        self.src = src
        self.src_mask = (src != pad).unsqueeze(-2)
        if tgt is not None:
            self.tgt = tgt[:, :-1]
            self.tgt_y = tgt[:, 1:]
            self.tgt_mask = self.make_std_mask(self.tgt, pad)
            self.ntokens = (self.tgt_y != pad).data.sum()

    @staticmethod
    def make_std_mask(tgt, pad):
        "Create a mask to hide padding and future words."
        tgt_mask = (tgt != pad).unsqueeze(-2)
        tgt_mask = tgt_mask & Variable(
            subsequent_mask(tgt.size(-1)).type_as(tgt_mask.data))
        return tgt_mask


def run_epoch(data_iter, model, criterion, mode='train'):
    "Standard Training and Logging Function"
    if type(model) == torch.nn.parallel.DistributedDataParallel:
        model = model.module

    if 'retrieval' in mode:
        out = model.forward(data_iter.src, data_iter.tgt,
                            None, None)
        if type(out) == dict:
            loss = criterion(out['src_emb'], out['tgt_emb'], model.logit_scale)

    else:
        out = model.forward(data_iter.src, data_iter.tgt,
                            None, data_iter.tgt_mask)
        if type(out) == dict:
            out = out['decoder_output']
        loss = criterion(out.contiguous().view(-1, out.size(-1)),
                         data_iter.tgt_y.contiguous().view(-1))
        loss = loss.sum() / data_iter.ntokens
    return out, loss


class NoamOpt:
    "Optim wrapper that implements rate."

    def __init__(self, model_size, factor, warmup, optimizer):
        self.optimizer = optimizer
        self._step = 0
        self.warmup = warmup
        self.factor = factor
        self.model_size = model_size
        self._rate = 0

    def step(self):
        "Update parameters and rate"
        self._step += 1
        rate = self.rate()
        for p in self.optimizer.param_groups:
            p['lr'] = rate
        self._rate = rate
        self.optimizer.step()

    def rate(self, step=None):
        "Implement `lrate` above"
        if step is None:
            step = self._step
        return self.factor * \
            (self.model_size ** (-0.5) *
             min(step ** (-0.5), step * self.warmup ** (-1.5)))


def make_argue(state='🤖 I May be Paranoid, but not an Agent.'):
    print(state)


def get_std_opt(model):
    return NoamOpt(model.src_embed[0].d_model, 2, 4000,
                   torch.optim.Adam(model.parameters(), lr=0, betas=(0.9, 0.98), eps=1e-9))


class LabelSmoothing(nn.Module):
    "Implement label smoothing."

    def __init__(self, size, padding_idx, criterion, smoothing=0.0):
        super(LabelSmoothing, self).__init__()
        self.criterion = criterion  # nn.KLDivLoss(reduction='sum')
        self.padding_idx = padding_idx
        self.confidence = 1.0 - smoothing
        self.smoothing = smoothing
        self.size = size
        self.true_dist = None

    def forward(self, x, target):
        # assert x.size(1) == self.size
        true_dist = x.data.clone()
        true_dist.fill_(self.smoothing / (self.size - 2))
        true_dist.scatter_(1, target.data.unsqueeze(1), self.confidence)
        true_dist[:, self.padding_idx] = 0
        mask = torch.nonzero(target.data == self.padding_idx)
        if mask.dim() > 0:
            true_dist.index_fill_(0, mask.squeeze(), 0.0)
        self.true_dist = true_dist.argmax(dim=-1).long()
        return self.criterion(x, Variable(self.true_dist, requires_grad=False))


def data_gen(src, tgt, nbatches):
    "Generate random data for a src-tgt copy task."
    for i in range(nbatches):
        # data = torch.from_numpy(np.random.randint(1, V, size=(batch, 10)))
        # data[:, 0] = 1
        # src = src if src is not None else Variable(data, requires_grad=False)
        # tgt = Variable(data, requires_grad=False)
        yield Batch(src, tgt, 0)


class LossCompute:
    "A simple loss compute and train function."

    def __init__(self, criterion, opt=None):
        self.criterion = criterion
        self.opt = opt

    def __call__(self, x, y, norm):
        print(x.contiguous().view(-1, x.size(-1)).shape, y.contiguous().view(-1).shape)
        loss = self.criterion(x.contiguous().view(-1, x.size(-1)),
                              y.contiguous().view(-1)).sum() / norm
        if self.opt is not None:
            self.opt.step()
            self.opt.optimizer.zero_grad()
        return loss * norm


def std_mask(tgt, attn_mask):
    seq_len = tgt.shape[-2]
    # attn_mask = attn_mask.unsqueeze(1).expand(-1, seq_len, -1)
    causal_mask = torch.triu(torch.ones(seq_len, seq_len, dtype=torch.int, device=tgt.device), diagonal=1).type_as(
        attn_mask)
    if attn_mask is not None:
        pad_mask = attn_mask.unsqueeze(-2) == 0
        std_mask = Variable(causal_mask) | pad_mask
    else:
        std_mask = causal_mask
    # torch.save({'casual_mask':causal_mask.cpu().detach(), 'attn_mask':pad_mask[0].cpu().detach(),
    #                 'std_mask':std_mask[0].cpu().detach(), },'/home/lyt/projects/spec2mol_1/mask.pt')
    return std_mask.logical_not()


def mlm_mask(input_ids, attention_mask, mask_prob=0.15, mlm_mask_id=4):
    rand = torch.rand(input_ids.shape, device=input_ids.device)
    mask_positions = rand <= (mask_prob * attention_mask)
    input_ids[mask_positions] = mlm_mask_id
    return input_ids, mask_positions


def generate_mask(query_padding_matrix, key_padding_matrix):
    query_padding_matrix = query_padding_matrix.unsqueeze(-1)
    key_padding_matrix = key_padding_matrix.unsqueeze(1)
    mask = query_padding_matrix | key_padding_matrix
    return mask

if __name__ == "__main__":
    seed_everything(624)
    # Train the simple copy task.
    V = 11
    criterion = LabelSmoothing(size=V, padding_idx=0, smoothing=0.0)
    model = make_model(V, V, N=2)
    model_opt = NoamOpt(model.src_embed[0].d_model, 1, 400,
                        torch.optim.Adam(model.parameters(), lr=0, betas=(0.9, 0.98), eps=1e-9))

    for epoch in range(10):
        model.train()
        run_epoch(data_gen(V, 30, 20), model,
                  LossCompute(model.generator, criterion, model_opt))
        model.eval()
        print(run_epoch(data_gen(V, 30, 5), model,
                        LossCompute(model.generator, criterion, None)))

    model.eval()
    src = Variable(torch.LongTensor([[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]))
    src_mask = Variable(torch.ones(1, 1, 10))
