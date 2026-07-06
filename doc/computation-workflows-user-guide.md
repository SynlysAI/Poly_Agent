# 计算 Workflow 使用指南：本地结构生成、xTB/CREST 粗优化、ORCA 精加工

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | 正式文档 |
| 日期 | 2026-07-06 |
| 关联文档 | `doc/compute-engine-computation-product-design.md`、`doc/compute-engine-computation-progress-and-plan.md` |
| 代码范围 | `backend/app/computation_adapters/local_structure.py`、`backend/app/computation_adapters/local_xtb.py`、`backend/app/computation_adapters/orca_compute_engine_laser.py` |
| 适用对象 | 平台使用者、新用户入门 |

本文档面向平台用户，用通俗易懂的语言解释三条计算 Workflow 分别做了什么、产出什么、怎么选、怎么用。不要求读者具备量子化学背景。

---

## 2. 概览：三条 Workflow 是什么关系？

在开始之前，先理解一个核心概念：

> 一个分子不是一张平面的结构图，而是一个立体的、可以"扭来扭去"的三维物体。同一个分子（同样的原子、同样的连接方式），键可以旋转、环可以翻转，产生无数种三维形态——这些叫**构象**（conformer）。不同构象的**能量**不一样，能量越低的构象越稳定，在现实中出现的概率越大。

Poly Agent 的计算智能模块提供了三条由浅入深、**互相包含**的计算路径：

```
本地结构生成 ────────────────────────────────────────► 得到一个"大概的三维草图"
    │
    └──► xTB/CREST 粗优化 ──────────────────────────► 找最稳定构象 + 算半经验能量
              │
              └──► ORCA 精加工 ──────────────────────► 高精度 DFT 能量 + 全套分析
```

**它们是递进关系，后者包含前者：**

- **ORCA 精加工**里面已经包含了"结构生成 → CREST 构象搜索 → ORCA DFT 计算"的完整流程。你不需要先跑一个 xTB/CREST 粗优化再把结果喂给 ORCA。
- **xTB/CREST 粗优化**里面包含了"结构生成 → CREST → xTB"。
- **本地结构生成**就是最基础的纯结构生成，不含任何能量计算。

打个比方：

| Workflow | 比喻 |
|---|---|
| 本地结构生成 | 建筑师画户型草图——墙在哪、门在哪、大概多大，画出来就行 |
| xTB/CREST 粗优化 | 装修师傅把所有家具摆放方案试一遍，找到最合理的那种，结构工程师用快速方法评估承重采光——够用，但不算最精确 |
| ORCA 精加工 | 顶尖教授带精密仪器做最终验算——精度最高，耗时长，发论文级别 |

---

## 3. 本地结构生成（LOCAL_STRUCTURE）

### 3.1 它是什么？

把你输入的一个分子（用 SMILES 表达式描述），变成一个**可视化的三维结构文件**——告诉你每个原子在空间里的 X、Y、Z 坐标。

### 3.2 它做了什么？

```
你输入: 分子名="乙醇", SMILES="CCO"
           ↓
第一步 — 输入校验:
  检查 SMILES 是否为空
  
第二步 — 生成本地结构:
  1) RDKit 解析 SMILES → 构建分子图
  2) 加氢原子（SMILES 里通常省略氢）
  3) 用 ETKDGv3 算法生成初始 3D 坐标
  4) 用 MMFF 力场优化（让键长键角接近合理值）
  5) 写出 structure.xyz（原子坐标）和 structure.sdf（含键级信息）
  
  (如果 RDKit 不可用，自动 fallback 到 OpenBabel)
  
第三步 — 收集结构产物:
  打包所有输出文件，登记为 artifact，供你下载
```

### 3.3 代码中的执行步骤

| 步骤标签 | 英文 key | 实际动作 |
|---|---|---|
| 输入校验 | `LOCAL_VALIDATE_INPUT` | 检查 SMILES 非空 |
| 生成本地结构 | `LOCAL_GENERATE_STRUCTURE` | RDKit/OpenBabel 生成 3D 坐标 |
| 收集结构产物 | `LOCAL_COLLECT_ARTIFACTS` | 登记 artifact 元数据 |

### 3.4 产出的文件

| 文件名 | 格式 | 内容说明 |
|---|---|---|
| `structure.xyz` | XYZ 文本 | 每行一个原子，含元素符号和 x/y/z 坐标 |
| `structure.sdf` | SDF 文本 | MDL 格式，含原子坐标 + 键级信息 + 分子属性 |
| `structure.json` | JSON | 结构化数据：atoms 数组（元素、坐标）、bonds 数组（成键原子对、键级） |
| `structure.log` | 文本 | 运行日志，记录用了哪个后端（rdkit/openbabel） |

### 3.5 支持的方法（Engine）

| Engine | 实际工具 | 说明 |
|---|---|---|
| `LOCAL` | 优先 RDKit，不可用则 OpenBabel | **推荐**，自动选择最佳可用工具 |
| `RDKit` | 仅 RDKit | RDKit 不可用则直接失败 |
| `OPENBABEL` | 仅 OpenBabel | 调用 `obabel` 命令行 |

### 3.6 前置依赖

至少满足一项：
- Python 环境中安装了 RDKit（`from rdkit import Chem` 可用）
- 系统 PATH 中有 `obabel` 命令

### 3.7 典型用时：几秒到几十秒

### 3.8 什么时候选它？

- 你只想**看一眼分子的三维结构**
- 你需要一个初始 XYZ 文件，后续用其他软件自己算
- 你在做分子库的可视化展示

---

## 4. xTB/CREST 粗优化（LOCAL_XTB）

### 4.1 它是什么？

在"三维草图"的基础上做两件事：

1. **CREST 构象搜索**：把分子所有能转的单键都转一遍，找到能量最低、最稳定的那个构象（以及一批次优构象）
2. **xTB 能量计算**：对这个最优构象，用半经验量子化学方法精确算出电子能量

> **半经验方法**是什么？简单理解：做精确的量子化学计算需要解薛定谔方程，很慢。半经验方法用大量实验数据拟合出近似公式，速度快 100-1000 倍，精度在大多数场景下够用。xTB (extended Tight Binding) 是其中比较先进的一种，由 Grimme 组开发。

### 4.2 它做了什么？

```
你输入: 分子名="乙醇", SMILES="CCO", method="GFN2-xTB", solvent="WATER"
           ↓
第一步 — 输入校验:
  - 检查 method 是不是在支持列表里（GFN2-xTB / GFN1-xTB / GFN0-xTB）
  - 检查系统是否安装了 xtb 可执行文件
  - 检查系统是否安装了 CREST 可执行文件
           ↓
第二步 — 准备 xTB 输入结构:
  - 调用"本地结构生成"流程（和 LOCAL_STRUCTURE 一样）
  - 用 RDKit 生成初始 3D 坐标 → input.xyz
           ↓
第三步 — CREST 构象搜索:
  执行命令: crest input.xyz --gfn 2 --chrg 0 --uhf 0
  
  CREST 的工作方式（通俗版）：
  1) 从初始结构出发，沿着所有可旋转的键，系统地扭转
  2) 每扭一个角度，用 GFN-xTB 快速算一下能量
  3) 保留低能量的构象，扔掉高能量的
  4) 对保留的构象聚类，合并相似的
  5) 最终给出 crest_best.xyz（最优）和 crest_conformers.xyz（全部）
  
  此步骤可能耗时较长（分钟到几十分钟，取决于分子大小和柔性）
           ↓
第四步 — 运行本地 xTB:
  拿 crest_best.xyz（CREST 找到的最优构象），用 xTB 做正式计算:
  
  执行命令: xtb crest_best.xyz --gfn 2 --chrg 0 --uhf 0 --parallel 2 --alpb WATER
  
  参数含义:
  --gfn 2:   用 GFN2-xTB 方法（精度最高）
  --chrg 0:  分子净电荷 = 0
  --uhf 0:   自旋多重度 = 1（uhf = multiplicity - 1）
  --parallel 2: 用 2 个 CPU 核并行
  --alpb WATER: 隐式溶剂模型，模拟水中环境
  
  在此过程中，Worker 每 5 秒发一次心跳，检测两件事:
  - 是否超时？
  - 用户是否在网页点了"取消"？
           ↓
第五步 — 解析 xTB 结果:
  从 xtb.stdout.log / xtb.out 中提取:
  - 总能量（energy_hartree，单位 Hartree）
  - 是否正常终止
  - xTB 版本
  - 总运行时间
  → 写入 result.json
```

### 4.3 代码中的执行步骤

| 步骤标签 | 英文 key | 实际动作 |
|---|---|---|
| 输入校验 | `XTB_VALIDATE_INPUT` | 检查 method 白名单、xtb/crest 可执行文件 |
| 准备 xTB 输入结构 | `XTB_PREPARE_STRUCTURE` | RDKit 生成初始 3D 结构 |
| CREST 构象搜索 | `XTB_CREST_SEARCH` | `crest` 命令行运行构象搜索 |
| 运行本地 xTB | `XTB_RUN` | `xtb` 命令行计算能量 |
| 解析 xTB 结果 | `XTB_PARSE_RESULT` | 从日志提取能量、版本、终止状态 |

### 4.4 产出的文件

**CREST 阶段产物：**

| 文件名 | 格式 | 内容说明 |
|---|---|---|
| `crest_best.xyz` | XYZ 文本 | CREST 找到的最低能量构象 |
| `crest_conformers.xyz` | XYZ 文本 | CREST 找到的所有构象（多个 XYZ 连在一起） |
| `crest.energies` | 文本 | 各构象的相对能量列表 |
| `crest.stdout.log` | 文本 | CREST 运行的标准输出 |
| `crest.stderr.log` | 文本 | CREST 运行的标准错误 |

**xTB 阶段产物：**

| 文件名 | 格式 | 内容说明 |
|---|---|---|
| `xtbopt.xyz` | XYZ 文本 | xTB 优化后的最终结构 |
| `xtb.out` | 文本 | xTB 运行的详细输出 |
| `xtb.stdout.log` | 文本 | xTB 运行的标准输出 |
| `xtb.stderr.log` | 文本 | xTB 运行的标准错误 |
| `charges` | 文本 | 原子的 Mulliken 电荷 |
| `wbo` | 文本 | Wiberg 键级（Mayer 键级） |

**汇总产物：**

| 文件名 | 格式 | 内容说明 |
|---|---|---|
| `result.json` | JSON | 解析后的结果摘要：能量、方法、版本、运行时间 |

### 4.5 支持的方法

| Method | GFN 级别 | 精度 | 速度 | 适用场景 |
|---|---|---|---|---|
| `GFN2-XTB` | GFN2 | 最高 | 中等 | **推荐**，主流应用 |
| `GFN1-XTB` | GFN1 | 中等 | 较快 | 快速筛选 |
| `GFN0-XTB` | GFN0 | 基础 | 最快 | 超大体系初筛 |

### 4.6 支持的溶剂

在提交时设置 `solvent` 参数，xTB 会用 ALPB 隐式溶剂模型模拟该溶剂环境：

`WATER`, `ACETONITRILE`, `TOLUENE`, `ETHANOL`, `METHANOL`, `DCM`, `THF`

如果不填溶剂，则默认在气相中计算。

### 4.7 前置依赖

- 系统安装了 **xTB**（可执行文件，通常为 `xtb`）
- 系统安装了 **CREST**（可执行文件，通常为 `crest`）
- Python 环境有 RDKit 或系统有 OpenBabel
- 配置路径在 `backend/app/core/config.py` 中：
  - `XTB_EXECUTABLE`（默认 `xtb`）
  - `CREST_EXECUTABLE`（默认 `crest`）

### 4.8 典型用时：几分钟到几十分钟

取决于：
- 分子大小（原子数越多越慢）
- 分子柔性（可旋转单键越多，CREST 搜索空间越大，越慢）
- CPU 配置

### 4.9 什么时候选它？

- 你想知道一个分子的**稳定构象长什么样**
- 你想快速评估一个分子的**能量**（精度要求不是发论文级别）
- 你有一批候选分子需要**粗筛**——先淘汰能量明显偏高的
- 你要为 ORCA 精加工准备一个好的初始结构（但建议直接用 ORCA 精加工 Workflow，它内置了这一步）

---

## 5. ORCA 精加工（ORCA_COMPUTE_ENGINE_LASER）

### 5.1 它是什么？

用 **ORCA**（专业量子化学软件）做 **DFT（密度泛函理论）**级别的高精度计算。这是三条 Workflow 中最精确的，也是唯一能产出**发论文数据**的。

> **DFT 是什么？** 密度泛函理论是量子化学的主流方法，它不依赖实验参数拟合（不像半经验方法），而是从电子密度的角度直接求解。精度远高于半经验方法（如 xTB），现代化学研究中大量使用 DFT 计算结果。

一条龙流程：结构生成 → CREST 构象搜索 → ORCA DFT 计算，全程自动。

### 5.2 它做了什么？

```
你输入: 分子名="乙醇", SMILES="CCO", method="ORCA_B3LYP_DEF2_SVP"
           ↓
第一步 — 结构准备:
  - 检查 ORCA_EXECUTION_MODE=local
  - 检查 method 在白名单中
  - 检查 ORCA license 是否可用
  - 检查 ORCA / xTB / CREST 三个可执行文件都存在
  - 用 RDKit 生成初始 3D 结构 → input.xyz
           ↓
第二步 — xTB/CREST 构象搜索:
  和 LOCAL_XTB 的 CREST 步骤完全一样:
  crest input.xyz --gfn 2 --chrg 0 --uhf 0
  → 拿到 crest_best.xyz（最优构象）
           ↓
第三步 — 运行本机 ORCA:
  自动生成 ORCA 输入文件（orca.inp），大致长这样:
  
  ┌─────────────────────────────────────────────┐
  │ ! B3LYP def2-SVP TightSCF                   │  ← DFT 方法 + 基组 + 收敛标准
  │ %pal nprocs 4 end                           │  ← 并行核数
  │ %maxcore 2048                               │  ← 每核内存 (MB)
  │ * xyz 0 1                                   │  ← 电荷 0，自旋多重度 1
  │ C   -1.23456789   0.12345678   0.00000000   │
  │ C    0.23456789  -0.12345678   0.89012345   │  ← crest_best.xyz 的坐标
  │ O    1.45678901   0.34567890  -0.56789012   │
  │ H   ...                                     │
  │ *                                            │
  └─────────────────────────────────────────────┘
  
  然后执行: orca orca.inp
  
  这是一个真正的 DFT 计算！ORCA 会：
  1) 基于 B3LYP 泛函和 def2-SVP 基组构建电子哈密顿量
  2) 用 SCF (自洽场) 迭代求解电子结构
  3) TightSCF 保证收敛到高精度
  4) 输出 FINAL SINGLE POINT ENERGY
           ↓
第四步 — 解析 ORCA 结果:
  从 orca.stdout.log 中提取:
  - FINAL SINGLE POINT ENERGY（最终单点能）
  - 是否正常终止（"ORCA TERMINATED NORMALLY"）
  → 写入 result.json
```

### 5.3 代码中的执行步骤

| 步骤标签 | 英文 key | 实际动作 |
|---|---|---|
| 结构准备 | `ORCA_PREPARE_STRUCTURE` | 验证依赖、RDKit 生成 3D 结构 |
| xTB/CREST 构象搜索 | `ORCA_XTB_CREST` | 同 LOCAL_XTB 的 CREST 步骤 |
| 运行本机 ORCA | `ORCA_RUN` | 生成 orca.inp，执行 ORCA |
| 解析 ORCA 结果 | `ORCA_PARSE_RESULT` | 提取能量和终止状态 |

### 5.4 产出的文件

**结构/CREST 阶段：**

| 文件名 | 内容说明 |
|---|---|
| `input.xyz` | 初始 3D 结构 |
| `crest_best.xyz` | CREST 最优构象 |
| `crest.stdout.log` / `crest.stderr.log` | CREST 运行日志 |

**ORCA 阶段：**

| 文件名 | 格式 | 内容说明 |
|---|---|---|
| `orca.inp` | 文本 | ORCA 输入文件（可以看到用了什么方法和参数） |
| `orca.stdout.log` | 文本 | ORCA 运行的标准输出（包含 SCF 迭代过程、最终能量） |
| `orca.stderr.log` | 文本 | ORCA 运行的标准错误 |
| `result.json` | JSON | 解析后的结果摘要：能量、终止状态、方法 |

### 5.5 支持的方法（预设）

| Method | 泛函 | 基组 | 说明 |
|---|---|---|---|
| `ORCA_B3LYP_DEF2_SVP` | B3LYP | def2-SVP | **推荐**，经典泛函 + 中等级别基组 |
| `ORCA_PBE0_DEF2_SVP` | PBE0 | def2-SVP | 无经验参数泛函，适合主族和过渡金属 |

> 注意：方法是后端白名单控制的，用户不能自定义输入文件、不能写任意 ORCA 关键字。这是安全设计——防止恶意命令注入。

### 5.6 前置依赖

- 系统安装了 **ORCA**（`orca` 可执行文件）
- 系统安装了 **xTB** 和 **CREST**
- Python 环境有 RDKit 或系统有 OpenBabel
- ORCA license 可用（配置 `ORCA_LICENSE_AVAILABLE=true`）
- ORCA 执行模式设置为 `local`（配置 `ORCA_EXECUTION_MODE=local`）
- 配置路径：
  - `ORCA_EXECUTABLE`（默认 `orca`）
  - `ORCA_EXECUTION_MODE`（需设为 `local`）
  - `ORCA_LICENSE_AVAILABLE`（需设为 `true`）

### 5.7 典型用时：几十分钟到几天

取决于：
- 分子大小（DFT 的计算量随电子数指数增长）
- 基组大小
- CPU 核数和内存
- SCF 收敛难度

### 5.8 什么时候选它？

- 你需要**发论文级别的精确能量数据**
- 你需要精确的反应热、活化能等
- 你在做机理研究，需要可靠的电子结构信息
- 你已经用 xTB 粗筛过一批分子，现在要对最有潜力的几个做最终评估

---

## 6. 三者对比一览

| 维度 | 本地结构生成 | xTB/CREST 粗优化 | ORCA 精加工 |
|---|---|---|---|
| **Workflow 标识** | `LOCAL_STRUCTURE` | `LOCAL_XTB` | `ORCA_COMPUTE_ENGINE_LASER` |
| **Engine** | `LOCAL` / `RDKit` / `OPENBABEL` | `XTB` | `ORCA` |
| **核心工具** | RDKit, OpenBabel | CREST, xTB | CREST, xTB, ORCA |
| **计算级别** | 经典力场（MMFF/UFF） | 半经验量子化学（GFN-xTB） | DFT 第一性原理（B3LYP/PBE0） |
| **精度** | ★☆☆☆☆（仅结构合理） | ★★★☆☆（半经验精度） | ★★★★★（DFT 级别） |
| **速度** | ★★★★★（秒级） | ★★★☆☆（分钟-几十分钟） | ★☆☆☆☆（几十分钟-几天） |
| **构象搜索** | ❌ 没有 | ✅ CREST 全面搜索 | ✅ CREST 全面搜索 |
| **能量计算** | ❌ 没有 | ✅ xTB 半经验能量 | ✅ ORCA DFT 精确能量 |
| **溶剂模型** | ❌ 不支持 | ✅ ALPB 隐式溶剂 | ✅ 取决于 ORCA 方法 |
| **前置依赖** | RDKit 或 OpenBabel | RDKit/OB + xTB + CREST | RDKit/OB + xTB + CREST + ORCA |
| **包含前置步骤** | 否（自己就是第一步） | 是（内置结构生成） | 是（内置结构生成 + CREST） |
| **CPU/内存消耗** | 极低 | 低-中 | 高-极高 |
| **适用阶段** | 初始结构可视化 | 高通量筛选、粗评 | 最终精确评估、发表数据 |

---

## 7. 如何选择——决策流程

```
你手头的任务是什么？
│
├─ "我只需要看一眼分子长什么样"
│  └─► 选 本地结构生成 (LOCAL_STRUCTURE)
│
├─ "我想大概知道这个分子的能量，精度不用太高"
│  └─► 选 xTB/CREST 粗优化 (LOCAL_XTB)
│
├─ "我有一批分子要先粗筛，淘汰能量太高的"
│  └─► 选 xTB/CREST 粗优化 (LOCAL_XTB)
│     对一批分子分别提交，比较结果中的 energy_hartree
│
├─ "我要做构象分析，想知道分子的所有低能构象"
│  └─► 选 xTB/CREST 粗优化 (LOCAL_XTB)
│     产出的 crest_conformers.xyz 包含所有构象
│
├─ "我需要精确的能量数据发论文/做机理研究"
│  └─► 选 ORCA 精加工 (ORCA_COMPUTE_ENGINE_LASER)
│
└─ "我要最精确的结果，一步到位"
   └─► 选 ORCA 精加工 (ORCA_COMPUTE_ENGINE_LASER)
       它内置了前面的所有步骤，全自动
```

**一个实际的推荐工作流：**

```
第一阶段（筛选）: 10 个候选分子 → 全部提交 LOCAL_XTB → 筛出能量最低的 3 个
第二阶段（精算）: 3 个入围分子 → 提交 ORCA_COMPUTE_ENGINE_LASER → 拿到精确能量数据
```

先粗后精，节省计算资源。

---

## 8. 操作指南

### 8.1 在网页上提交计算任务

1. 打开平台 Dashboard
2. 点击 **"新建任务"**，找到 **"计算智能"** 模块，点击 **"提交计算任务"**
3. 填写以下表单：

| 表单字段 | 填什么 | 示例 |
|---|---|---|
| **分子名** | 给你的分子起个名字 | `乙醇` |
| **SMILES** | 分子的 SMILES 表达式 | `CCO` |
| **Workflow 类型** | 按决策流程图选择 | `LOCAL_XTB` |
| **Engine** | 随 Workflow 类型自动匹配 | `XTB`（自动） |
| **Charge** | 分子的净电荷 | `0`（中性分子） |
| **Multiplicity** | 自旋多重度（2S+1，S=总自旋） | `1`（单重态，所有电子配对） |
| **Method** | 计算方法 | `GFN2-xTB`（LOCAL_XTB）或 `ORCA_B3LYP_DEF2_SVP`（ORCA） |
| **Solvent** | 溶剂（可留空 = 气相） | `WATER` |
| **CPU 核数** | 分配给计算任务的 CPU 核数 | `2` |
| **内存 (MB)** | 分配给计算任务的内存 | `4096` |
| **超时时间 (s)** | 最大允许运行时间 | `1800`（30 分钟） |

4. 点击 **"提交计算任务"**
5. 自动跳转到 **计算任务中心**，可以看到你的任务状态为 `queued`
6. Worker 领取任务后 `queued → running → completed`，完成后可以查看和下载产物

### 8.2 表单填写注意事项

**SMILES 怎么获取？**

- 如果你知道分子的 SMILES，直接填入
- 如果不知道，可以用 PubChem（https://pubchem.ncbi.nlm.nih.gov/）、ChemDraw 或其他工具画出来导出
- 常见示例：水 `O`、乙醇 `CCO`、苯 `c1ccccc1`、乙酸 `CC(=O)O`、咖啡因 `CN1C=NC2=C1C(=O)N(C(=O)N2C)C`

**Charge 和 Multiplicity 怎么填？**

| 分子类型 | Charge | Multiplicity | 说明 |
|---|---|---|---|
| 中性闭壳层分子（大多数有机分子） | `0` | `1` | 所有电子配对 |
| 带一个正电荷的阳离子 | `1` | `1` | NH₄⁺ 等 |
| 带一个负电荷的阴离子 | `-1` | `1` | Cl⁻, CH₃COO⁻ 等 |
| 三重态氧气 O₂ | `0` | `3` | 有两个未成对电子 |
| 自由基 | `0` | `2` | 有一个未成对电子 |

> 如果不确定，中性有机分子默认为 `charge=0, multiplicity=1` 即可。

**超时设置建议：**

| Workflow | 推荐超时 | 说明 |
|---|---|---|
| LOCAL_STRUCTURE | 300s (5 min) | 很快，一般几秒就好 |
| LOCAL_XTB | 1800s (30 min) | 小分子几分钟，柔性大分子可能更久 |
| ORCA_COMPUTE_ENGINE_LASER | 7200s (2 h) | 看分子大小和 CPU |

### 8.3 查看任务进度

在**计算任务中心**（`/computations/runs`），你可以看到：

- **任务列表**：所有提交的任务，按时间排序
- **状态**：`queued`（排队中）→ `running`（运行中）→ `completed`（成功）/ `failed`（失败）/ `cancelled`（已取消）
- **时间线（Timeline）**：点击某个任务查看详情，可以看到每个步骤的执行状态和时间
- **产物（Artifacts）**：完成后，可以预览 XYZ 结构、下载 SDF 文件、查看结果 JSON

### 8.4 取消和重试

- **取消**：在任务详情页点击"取消"，Worker 会在下一次心跳检测时（5 秒内）终止子进程
- **重试**：失败或取消的任务可以重试，系统会创建一个新的 run 重新排队

---

## 9. 常见问题

### Q1: 我提交了任务，一直卡在 `queued` 状态？

**原因**：ComputationWorker 没有在运行。Web 后端只负责接收和展示任务，执行计算需要一个独立运行的 Worker 进程。

**解决**：在服务器上启动 Worker：

```bash
cd backend
python -m app.workers.computation_worker --worker-id worker-1 --interval 1.0
```

### Q2: 任务报错 "未检测到 xtb 可执行文件"？

**原因**：服务器上没有安装 xTB 或 PATH 中没有配置。

**解决**：
1. 安装 xTB：从 https://github.com/grimme-lab/xtb/releases 下载
2. 确保 `xtb` 在系统 PATH 中，或者在配置文件中设置 `XTB_EXECUTABLE` 为完整路径

### Q3: CREST 和 xTB 有什么区别？

简单说：**CREST 负责"找"构象，xTB 负责"算"能量**。

- CREST (Conformer–Rotamer Ensemble Sampling Tool) 是一个构象搜索工具，它基于 GFN-xTB 做能量计算，但核心目的是生成和筛选构象
- xTB (extended Tight Binding) 是半经验量子化学方法本身，用于计算给定构象的电子能量

在 `LOCAL_XTB` 这个 Workflow 里，两者配合使用：先用 CREST 找到最优构象，再用 xTB 对最优构象做精确能量计算。

### Q4: 为什么不直接用 ORCA，还要 xTB？

- **速度**：xTB 比 ORCA 快 100-1000 倍
- **场景**：高通量筛选时，100 个分子用 ORCA 全算可能算几周，用 xTB 几小时就搞定了
- **分工**：xTB 做粗筛 → ORCA 做精选，效率最高

### Q5: ORCA 精加工和 xTB/CREST 粗优化的输出格式一样吗？

不完全一样。两者的结果都是 `result.json`，包含 `energy_hartree`，但精度和含义不同：

- xTB 的 `energy_hartree` 是 GFN-xTB 半经验能量
- ORCA 的 `energy_hartree` 是 DFT 能量

**能量不能直接跨方法比较**。xTB 和 DFT 算出来的数虽然都是 Hartree 单位，但绝对值不同。只在**同一种方法内部**比较才有意义。

### Q6: 计算资源怎么设置？

- **小分子（< 30 原子）**：2-4 核，4 GB 内存足够
- **中等分子（30-100 原子）**：4-8 核，8-16 GB 内存
- **大分子（> 100 原子）**：8+ 核，16+ GB 内存，建议先用 xTB

ORCA 的 `%maxcore` 会自动按 `memory_mb / num_cores` 计算，所以设置合适的核数和内存比例很重要。

### Q7: 我可以一次批量提交吗？

目前页面上是单个提交。如果需要批量，可以：

1. 通过 API 批量调用 `POST /api/v1/computations`
2. 使用优化 Campaign 模块，它能自动为一批候选分子提交计算

### Q8: 产物文件能下载到本地吗？

可以，在任务详情页的 Artifacts 区域，每个文件都有 **下载**、**预览** 和 **查看结构** 的按钮。支持的预览格式包括 XYZ 结构查看、JSON 结果查看等。

---

## 10. 技术附录：Workflow/Engine 组合清单

以下是从代码 `registry.py` 中直接提取的当前支持的合法组合：

| Workflow | Engine | Adapter 类 | 用途 |
|---|---|---|---|
| `LOCAL_STRUCTURE` | `LOCAL` | `LocalStructureAdapter` | 自动选择 RDKit/OpenBabel 生成结构 |
| `LOCAL_STRUCTURE` | `RDKit` | `LocalStructureAdapter` | 只使用 RDKit 生成结构 |
| `LOCAL_STRUCTURE` | `OPENBABEL` | `LocalStructureAdapter` | 只使用 OpenBabel 生成结构 |
| `LOCAL_XTB` | `XTB` | `LocalXtbAdapter` | CREST → xTB 半经验计算 |
| `ORCA_COMPUTE_ENGINE_LASER` | `ORCA` | `OrcaComputeEngineLaserAdapter` | CREST → xTB → ORCA DFT 计算 |

任何不在以上列表中的组合会在提交时被直接拒绝（400 错误）。

---

## 11. 附录：方法白名单

以下是从 schema 中提取的当前支持的方法：

**xTB 方法：**
- `GFN2-XTB` — Geometry, Frequency, Noncovalent 2nd generation（推荐）
- `GFN1-XTB` — 第一代
- `GFN0-XTB` — 第零代（最快、精度最低）

**ORCA 方法：**
- `ORCA_B3LYP_DEF2_SVP` — B3LYP 泛函 + def2-SVP 基组（推荐）
- `ORCA_PBE0_DEF2_SVP` — PBE0 泛函 + def2-SVP 基组

**支持的溶剂：**
`WATER`、`ACETONITRILE`、`TOLUENE`、`ETHANOL`、`METHANOL`、`DCM`、`THF`

---

---

## 12. 在 ResearchEngine 中使用计算 Workflow

当 ResearchEngine 研发引擎部署后，三条计算 Workflow 将作为 AlgorithmRegistry 的算法条目接入，可在人工算法工作台和 AutoResearch 自动编排中调用。

### 12.1 人工通道使用

在 ResearchEngine 人工算法工作台中：

1. 从算法清单中选择 `local_structure_adapter`、`local_xtb_adapter` 或 `orca_compute_engine_laser_adapter`
2. 填写输入表单（与当前计算任务提交表单字段一致：SMILES、charge、multiplicity、method、solvent 等）
3. 运行后生成 AlgorithmRun 记录（含 input_snapshot、output_summary、artifact refs）
4. AlgorithmRun 自动关联到当前 ProblemSpec 和 Campaign

### 12.2 AutoResearch 通道使用

在 AutoResearch 自动编排中：

- `STRUCTURE_FEATURE` 阶段可配置使用 `local_structure_adapter`
- `COMPUTE_PREDICT` 阶段可配置使用 `local_xtb_adapter` 或 `orca_compute_engine_laser_adapter`
- AutoResearch orchestrator 自动提交计算任务，computation 完成后通过现有 observation 回填路径生成 Observation

### 12.3 与直接使用计算模块的区别

| 维度 | 直接使用计算模块 | 通过 ResearchEngine 使用 |
| --- | --- | --- |
| 入口 | `/computations/submit` | ResearchEngine 人工算法工作台 |
| 关联对象 | campaign_id, suggestion_id | 额外关联 problem_spec_id, research_run_id, stage_run_id |
| 触发记录 | ComputationRun | AlgorithmRun（含 trigger_source）+ 关联的 ComputationRun |
| 审计追溯 | 计算任务级 | 计算任务级 + 研发阶段级（可追溯到 AutoResearch 的哪个 stage） |
| 结果消费 | 直接下载 artifact | artifact 可被后续 AutoResearch stage 消费，也可通过 observation 回填到 campaign |

两种方式的计算结果一致，选择哪种入口取决于你的工作模式：独立探索用计算模块，系统性研发用 ResearchEngine。

### 12.4 相关文档

- ResearchEngine 技术方案：`doc/research-engine-and-auto-research-design.md`
- 部署工具链与 ResearchEngine 的关系：`doc/poly-agent-toolchain-deployment-pack.md` §"工具链与 ResearchEngine 算法注册表的映射"

---

> 如有其他问题，请查阅关联设计文档或联系平台管理员。
