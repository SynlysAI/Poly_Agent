import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from copy import deepcopy

'''class GraphormerAttention(nn.Module):
    def __init__(self, dim, num_heads=8, dropout=0.1):
        super().__init__()
        if dim % num_heads != 0:
            raise ValueError("dim must be divisible by num_heads")

        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.scale = self.head_dim ** -0.5

        self.q_proj = nn.Linear(dim, dim)
        self.k_proj = nn.Linear(dim, dim)
        self.v_proj = nn.Linear(dim, dim)
        self.out_proj = nn.Linear(dim, dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, attn_bias=None, attn_mask=None):
        batch_size, num_tokens, dim = x.shape

        q = self.q_proj(x).view(batch_size, num_tokens, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(batch_size, num_tokens, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(batch_size, num_tokens, self.num_heads, self.head_dim).transpose(1, 2)

        attn_scores = torch.matmul(q, k.transpose(-1, -2)) * self.scale
        if attn_bias is not None:
            attn_scores = attn_scores + attn_bias

        if attn_mask is not None:
            key_mask = ~attn_mask[:, None, None, :]
            attn_scores = attn_scores.masked_fill(key_mask, torch.finfo(attn_scores.dtype).min)

        attn = F.softmax(attn_scores, dim=-1)
        attn = self.dropout(attn)

        out = torch.matmul(attn, v)
        out = out.transpose(1, 2).contiguous().view(batch_size, num_tokens, dim)
        out = self.out_proj(out)

        if attn_mask is not None:
            out = out * attn_mask.unsqueeze(-1).to(out.dtype)

        return out


class GraphormerEncoderLayer(nn.Module):
    def __init__(self, dim, num_heads, mlp_ratio=4.0, dropout=0.1):
        super().__init__()
        hidden_dim = int(dim * mlp_ratio)
        self.norm1 = nn.LayerNorm(dim)
        self.attn = GraphormerAttention(dim, num_heads=num_heads, dropout=dropout)
        self.norm2 = nn.LayerNorm(dim)
        self.ffn = nn.Sequential(
            nn.Linear(dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, dim),
            nn.Dropout(dropout),
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, attn_bias, attn_mask):
        x = x + self.dropout(self.attn(self.norm1(x), attn_bias=attn_bias, attn_mask=attn_mask))
        x = x + self.ffn(self.norm2(x))
        x = x * attn_mask.unsqueeze(-1).to(x.dtype)
        return x


class Graphormer(nn.Module):
    def __init__(
        self,
        nfeat=100,
        hidden_dim=256,
        nclass=1024,
        num_heads=8,
        num_layers=8,
        mlp_ratio=4.0,
        dropout=0,
        max_degree=512,
        spatial_pos_max=16,
    ):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.num_heads = num_heads
        self.max_degree = max_degree
        self.spatial_pos_max = spatial_pos_max

        self.node_encoder = nn.Linear(nfeat, hidden_dim)
        self.in_degree_encoder = nn.Embedding(max_degree + 1, hidden_dim)
        self.out_degree_encoder = nn.Embedding(max_degree + 1, hidden_dim)
        self.spatial_encoder = nn.Embedding(spatial_pos_max + 2, num_heads)
        self.edge_encoder = nn.Linear(1, num_heads, bias=False)

        self.graph_token = nn.Parameter(torch.zeros(1, 1, hidden_dim))
        self.graph_token_bias = nn.Parameter(torch.zeros(num_heads))

        self.input_dropout = nn.Dropout(dropout)
        self.layers = nn.ModuleList(
            [
                GraphormerEncoderLayer(
                    dim=hidden_dim,
                    num_heads=num_heads,
                    mlp_ratio=mlp_ratio,
                    dropout=dropout,
                )
                for _ in range(num_layers)
            ]
        )
        self.final_norm = nn.LayerNorm(hidden_dim)
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, nclass),
        )
        self.head_1 = nn.Linear(400, 400)

        self.reset_parameters()

    def reset_parameters(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, std=0.02)

        nn.init.normal_(self.graph_token, std=0.02)
        nn.init.zeros_(self.graph_token_bias)

    @staticmethod
    @torch.no_grad()
    def shortest_path_distance(adj_bool, node_mask, spatial_pos_max):
        batch_size, num_nodes, _ = adj_bool.shape
        unreachable = spatial_pos_max + 1
        distances = torch.full(
            (batch_size, num_nodes, num_nodes),
            fill_value=unreachable,
            dtype=torch.long,
            device=adj_bool.device,
        )

        for batch_idx in range(batch_size):
            valid_idx = node_mask[batch_idx].nonzero(as_tuple=False).flatten()
            num_valid = valid_idx.numel()
            if num_valid == 0:
                continue

            sub_adj = adj_bool[batch_idx].index_select(0, valid_idx).index_select(1, valid_idx)
            sub_dist = torch.full(
                (num_valid, num_valid),
                fill_value=num_valid + 1,
                dtype=torch.long,
                device=adj_bool.device,
            )
            sub_dist.fill_diagonal_(0)
            sub_dist[sub_adj] = 1

            for k in range(num_valid):
                via_k = sub_dist[:, k:k + 1] + sub_dist[k:k + 1, :]
                sub_dist = torch.minimum(sub_dist, via_k)

            sub_dist = sub_dist.clamp(max=unreachable)
            distances[batch_idx][valid_idx[:, None], valid_idx[None, :]] = sub_dist

        return distances

    def build_attention_bias(self, node_mat, adj_mat, node_mask):
        batch_size, num_nodes, _ = node_mat.shape
        attn_bias = node_mat.new_zeros(batch_size, self.num_heads, num_nodes + 1, num_nodes + 1)

        eye = torch.eye(num_nodes, device=adj_mat.device, dtype=torch.bool).unsqueeze(0)
        pair_mask = node_mask.unsqueeze(1) & node_mask.unsqueeze(2)
        neighbor_mask = (adj_mat > 0) & ~eye & pair_mask

        distances = self.shortest_path_distance(neighbor_mask, node_mask, self.spatial_pos_max)
        spatial_bias = self.spatial_encoder(distances).permute(0, 3, 1, 2)

        edge_bias = self.edge_encoder(adj_mat.unsqueeze(-1)).permute(0, 3, 1, 2)
        edge_bias = edge_bias * neighbor_mask.unsqueeze(1).to(edge_bias.dtype)

        node_bias = (spatial_bias + edge_bias) * pair_mask.unsqueeze(1).to(spatial_bias.dtype)
        attn_bias[:, :, 1:, 1:] = node_bias

        token_bias = self.graph_token_bias.view(1, self.num_heads, 1).expand(batch_size, -1, num_nodes)
        token_bias = token_bias * node_mask.unsqueeze(1).to(token_bias.dtype)
        attn_bias[:, :, 0, 1:] = token_bias
        attn_bias[:, :, 1:, 0] = token_bias
        return attn_bias, neighbor_mask

    def forward(self, node_mat, adj_mat):
        node_mask = node_mat.abs().sum(dim=-1) > 0

        attn_bias, neighbor_mask = self.build_attention_bias(node_mat, adj_mat, node_mask)
        in_degree = neighbor_mask.sum(dim=-1).clamp(max=self.max_degree)
        out_degree = neighbor_mask.sum(dim=-2).clamp(max=self.max_degree)

        x = self.node_encoder(node_mat)
        x = x + self.in_degree_encoder(in_degree) + self.out_degree_encoder(out_degree)
        x = x * node_mask.unsqueeze(-1).to(x.dtype)

        graph_token = self.graph_token.expand(node_mat.size(0), -1, -1)
        x = torch.cat([graph_token, x], dim=1)

        attn_mask = torch.cat(
            [
                torch.ones(node_mat.size(0), 1, dtype=torch.bool, device=node_mat.device),
                node_mask,
            ],
            dim=1,
        )

        x = self.input_dropout(x)
        for layer in self.layers:
            x = layer(x, attn_bias=attn_bias, attn_mask=attn_mask)

        x = self.final_norm(x)
        graph_repr = x[:, 0]
        out = self.head(graph_repr)
        out_1 = self.head_1(out[:, 200:600])
        return out.relu(), out_1.relu()


def model_profile(model):
    from thop import profile

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = model.to(device)

    batch_size = 8
    num_nodes = 64
    node_mat = torch.randn(batch_size, num_nodes, 100, device=device)
    adj_mat = torch.zeros(batch_size, num_nodes, num_nodes, device=device)

    for batch_idx in range(batch_size):
        rand_adj = torch.randint(0, 2, (num_nodes, num_nodes), device=device)
        rand_adj = torch.triu(rand_adj, diagonal=1)
        rand_adj = rand_adj + rand_adj.transpose(0, 1)
        rand_adj.fill_diagonal_(1)
        adj_mat[batch_idx] = rand_adj.float()

    start_time = time.time()
    flops, params = profile(model, inputs=(node_mat, adj_mat), verbose=False)
    inference_time = time.time() - start_time
    return f"GFLOPs: {flops / 1e9:.3f}, params: {params / 1e6:.3f} M, Inference time: {inference_time:.3f} s"


if __name__ == "__main__":
    model = Graphormer()
    example_node_mat = torch.randn(4, 32, 100)
    example_adj_mat = torch.zeros(4, 32, 32)

    for batch_idx in range(example_adj_mat.size(0)):
        rand_adj = torch.randint(0, 2, (32, 32))
        rand_adj = torch.triu(rand_adj, diagonal=1)
        rand_adj = rand_adj + rand_adj.transpose(0, 1)
        rand_adj.fill_diagonal_(1)
        example_adj_mat[batch_idx] = rand_adj.float()

    out = model(example_node_mat, example_adj_mat)
    print("Output shape:", tuple(out.shape))

    try:
        print("Graphormer:", model_profile(model))
    except ImportError:
        print("Install thop to run the profiling example in __main__.")'''

import time

import torch
import torch.nn as nn
import torch.nn.functional as F


class GraphormerAttention(nn.Module):
    def __init__(self, dim, num_heads=8, dropout=0.1):
        super().__init__()
        if dim % num_heads != 0:
            raise ValueError("dim must be divisible by num_heads")

        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.scale = self.head_dim ** -0.5

        self.q_proj = nn.Linear(dim, dim)
        self.k_proj = nn.Linear(dim, dim)
        self.v_proj = nn.Linear(dim, dim)
        self.out_proj = nn.Linear(dim, dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, attn_bias=None, attn_mask=None):
        batch_size, num_tokens, dim = x.shape

        q = self.q_proj(x).view(batch_size, num_tokens, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(batch_size, num_tokens, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(batch_size, num_tokens, self.num_heads, self.head_dim).transpose(1, 2)

        attn_scores = torch.matmul(q, k.transpose(-1, -2)) * self.scale
        if attn_bias is not None:
            attn_scores = attn_scores + attn_bias

        if attn_mask is not None:
            key_mask = ~attn_mask[:, None, None, :]
            attn_scores = attn_scores.masked_fill(key_mask, torch.finfo(attn_scores.dtype).min)

        attn = F.softmax(attn_scores, dim=-1)
        attn = self.dropout(attn)

        out = torch.matmul(attn, v)
        out = out.transpose(1, 2).contiguous().view(batch_size, num_tokens, dim)
        out = self.out_proj(out)

        if attn_mask is not None:
            out = out * attn_mask.unsqueeze(-1).to(out.dtype)

        return out


class GraphormerEncoderLayer(nn.Module):
    def __init__(self, dim, num_heads, mlp_ratio=4.0, dropout=0.1):
        super().__init__()
        hidden_dim = int(dim * mlp_ratio)
        self.norm1 = nn.LayerNorm(dim)
        self.attn = GraphormerAttention(dim, num_heads=num_heads, dropout=dropout)
        self.norm2 = nn.LayerNorm(dim)
        self.ffn = nn.Sequential(
            nn.Linear(dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, dim),
            nn.Dropout(dropout),
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, attn_bias, attn_mask):
        x = x + self.dropout(self.attn(self.norm1(x), attn_bias=attn_bias, attn_mask=attn_mask))
        x = x + self.ffn(self.norm2(x))
        x = x * attn_mask.unsqueeze(-1).to(x.dtype)
        return x


class RegressionHead(nn.Module):
    def __init__(self, wavenumber_intervals, hidden_dim, dropout):
        super().__init__()
        self.intervals = wavenumber_intervals
        for i in range(len(wavenumber_intervals) - 1):
            setattr(self, f'head_{i}', nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, wavenumber_intervals[i + 1] - wavenumber_intervals[i]),
            ))

    def forward(self, graph_repr):
        output_list = []
        for i in range(len(self._modules)):
            head = getattr(self, f'head_{i}')
            output_list.append(head(graph_repr))
        return torch.cat(output_list, dim=-1)
    
    
class Graphormer(nn.Module):
    def __init__(
        self,
        nfeat=100,
        hidden_dim=256,
        nclass=1024,
        num_heads=8,
        num_layers=8,
        mlp_ratio=4.0,
        dropout=0,
        max_degree=512,
        spatial_pos_max=16,
        wavenumber_intervals=[300,600]
    ):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.num_heads = num_heads
        self.max_degree = max_degree
        self.spatial_pos_max = spatial_pos_max
        if wavenumber_intervals:
            self.wavenumber_intervals = [0] + wavenumber_intervals + [nclass]
        else:
            self.wavenumber_intervals = None
        self.node_encoder = nn.Linear(nfeat, hidden_dim)
        self.in_degree_encoder = nn.Embedding(max_degree + 1, hidden_dim)
        self.out_degree_encoder = nn.Embedding(max_degree + 1, hidden_dim)
        self.spatial_encoder = nn.Embedding(spatial_pos_max + 2, num_heads)
        self.edge_encoder = nn.Linear(1, num_heads, bias=False)

        self.graph_token = nn.Parameter(torch.zeros(1, 1, hidden_dim))
        self.graph_token_bias = nn.Parameter(torch.zeros(num_heads))

        self.input_dropout = nn.Dropout(dropout)
        self.layers = nn.ModuleList(
            [
                GraphormerEncoderLayer(
                    dim=hidden_dim,
                    num_heads=num_heads,
                    mlp_ratio=mlp_ratio,
                    dropout=dropout,
                )
                for _ in range(num_layers)
            ]
        )
        self.final_norm = nn.LayerNorm(hidden_dim)
        if self.wavenumber_intervals is not None:
            self.head = RegressionHead(self.wavenumber_intervals, hidden_dim, dropout)
        else:
            self.head = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, nclass),
            )
        self.reset_parameters()

    def reset_parameters(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, std=0.02)
        nn.init.normal_(self.graph_token, std=0.02)
        nn.init.zeros_(self.graph_token_bias)

    @staticmethod
    @torch.no_grad()
    def shortest_path_distance(adj_bool, node_mask, spatial_pos_max):
        batch_size, num_nodes, _ = adj_bool.shape
        unreachable = spatial_pos_max + 1
        distances = torch.full(
            (batch_size, num_nodes, num_nodes),
            fill_value=unreachable,
            dtype=torch.long,
            device=adj_bool.device,
        )

        for batch_idx in range(batch_size):
            valid_idx = node_mask[batch_idx].nonzero(as_tuple=False).flatten()
            num_valid = valid_idx.numel()
            if num_valid == 0:
                continue

            sub_adj = adj_bool[batch_idx].index_select(0, valid_idx).index_select(1, valid_idx)
            sub_dist = torch.full(
                (num_valid, num_valid),
                fill_value=num_valid + 1,
                dtype=torch.long,
                device=adj_bool.device,
            )
            sub_dist.fill_diagonal_(0)
            sub_dist[sub_adj] = 1

            for k in range(num_valid):
                via_k = sub_dist[:, k:k + 1] + sub_dist[k:k + 1, :]
                sub_dist = torch.minimum(sub_dist, via_k)

            sub_dist = sub_dist.clamp(max=unreachable)
            distances[batch_idx][valid_idx[:, None], valid_idx[None, :]] = sub_dist
        return distances

    def build_attention_bias(self, node_mat, adj_mat, node_mask):
        batch_size, num_nodes, _ = node_mat.shape
        attn_bias = node_mat.new_zeros(batch_size, self.num_heads, num_nodes + 1, num_nodes + 1)

        eye = torch.eye(num_nodes, device=adj_mat.device, dtype=torch.bool).unsqueeze(0)
        pair_mask = node_mask.unsqueeze(1) & node_mask.unsqueeze(2)
        neighbor_mask = (adj_mat > 0) & ~eye & pair_mask

        distances = self.shortest_path_distance(neighbor_mask, node_mask, self.spatial_pos_max)
        spatial_bias = self.spatial_encoder(distances).permute(0, 3, 1, 2)

        edge_bias = self.edge_encoder(adj_mat.unsqueeze(-1)).permute(0, 3, 1, 2)
        edge_bias = edge_bias * neighbor_mask.unsqueeze(1).to(edge_bias.dtype)

        node_bias = (spatial_bias + edge_bias) * pair_mask.unsqueeze(1).to(spatial_bias.dtype)
        attn_bias[:, :, 1:, 1:] = node_bias

        token_bias = self.graph_token_bias.view(1, self.num_heads, 1).expand(batch_size, -1, num_nodes)
        token_bias = token_bias * node_mask.unsqueeze(1).to(token_bias.dtype)
        attn_bias[:, :, 0, 1:] = token_bias
        attn_bias[:, :, 1:, 0] = token_bias
        return attn_bias, neighbor_mask

    def forward(self, node_mat, adj_mat):
        node_mask = node_mat.abs().sum(dim=-1) > 0

        attn_bias, neighbor_mask = self.build_attention_bias(node_mat, adj_mat, node_mask)
        in_degree = neighbor_mask.sum(dim=-1).clamp(max=self.max_degree)
        out_degree = neighbor_mask.sum(dim=-2).clamp(max=self.max_degree)

        x = self.node_encoder(node_mat)
        x = x + self.in_degree_encoder(in_degree) + self.out_degree_encoder(out_degree)
        x = x * node_mask.unsqueeze(-1).to(x.dtype)

        graph_token = self.graph_token.expand(node_mat.size(0), -1, -1)
        x = torch.cat([graph_token, x], dim=1)

        attn_mask = torch.cat(
            [
                torch.ones(node_mat.size(0), 1, dtype=torch.bool, device=node_mat.device),
                node_mask,
            ],
            dim=1,
        )

        x = self.input_dropout(x)
        for layer in self.layers:
            x = layer(x, attn_bias=attn_bias, attn_mask=attn_mask)

        x = self.final_norm(x)
        graph_repr = x[:, 0]
        return self.head(graph_repr)


def model_profile(model):
    from thop import profile

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = model.to(device)

    batch_size = 8
    num_nodes = 64
    node_mat = torch.randn(batch_size, num_nodes, 100, device=device)
    adj_mat = torch.zeros(batch_size, num_nodes, num_nodes, device=device)

    for batch_idx in range(batch_size):
        rand_adj = torch.randint(0, 2, (num_nodes, num_nodes), device=device)
        rand_adj = torch.triu(rand_adj, diagonal=1)
        rand_adj = rand_adj + rand_adj.transpose(0, 1)
        rand_adj.fill_diagonal_(1)
        adj_mat[batch_idx] = rand_adj.float()

    start_time = time.time()
    flops, params = profile(model, inputs=(node_mat, adj_mat), verbose=False)
    inference_time = time.time() - start_time
    return f"GFLOPs: {flops / 1e9:.3f}, params: {params / 1e6:.3f} M, Inference time: {inference_time:.3f} s"


if __name__ == "__main__":
    model = Graphormer()
    example_node_mat = torch.randn(4, 32, 100)
    example_adj_mat = torch.zeros(4, 32, 32)

    for batch_idx in range(example_adj_mat.size(0)):
        rand_adj = torch.randint(0, 2, (32, 32))
        rand_adj = torch.triu(rand_adj, diagonal=1)
        rand_adj = rand_adj + rand_adj.transpose(0, 1)
        rand_adj.fill_diagonal_(1)
        example_adj_mat[batch_idx] = rand_adj.float()

    out = model(example_node_mat, example_adj_mat)
    print("Output shape:", tuple(out.shape))

    try:
        print("Graphormer:", model_profile(model))
    except ImportError:
        print("Install thop to run the profiling example in __main__.")