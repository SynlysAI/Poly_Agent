"""来源、引用与机构标注注册表服务。"""

from __future__ import annotations

from fastapi import HTTPException

from app.schemas.attribution import AttributionItem
from app.schemas.attribution import ModuleAttribution
from app.schemas.attribution import ModuleAttributionListData


def prominent_text_badge(name: str, organization: str | None = None) -> AttributionItem:
    """构建无图片资产的醒目文字来源牌。"""
    return AttributionItem(
        name=name,
        role="implementation_source",
        organization=organization,
        logo_alt=organization or name,
        visibility="prominent",
    )


class AttributionService:
    """集中维护系统模块来源标注。"""

    def list_modules(self) -> ModuleAttributionListData:
        """列出全部系统模块来源标注。"""
        items = self._module_attributions()
        return ModuleAttributionListData(items=items, total=len(items))

    def get_module(self, module_id: str) -> ModuleAttribution:
        """按模块 ID 获取来源标注。"""
        for item in self._module_attributions():
            if item.module_id == module_id:
                return item
        raise HTTPException(status_code=404, detail=f"来源标注模块 '{module_id}' 不存在")

    @staticmethod
    def _module_attributions() -> list[ModuleAttribution]:
        """返回内置模块来源矩阵。"""
        chemos = AttributionItem(
            name="ChemOS 2.0",
            role="framework_reference",
            organization="University of Toronto / Aspuru-Guzik Group",
            description="研发流程编排参考 ChemOS 2.0 的自驱实验室架构。",
            url="https://github.com/malcolmsimgithub/ChemOS2.0",
            citation_text="ChemOS 2.0: An orchestration architecture for self-driving laboratories.",
            logo_alt="University of Toronto",
            visibility="prominent",
        )
        alchemist = AttributionItem(
            name="ALchemist",
            role="framework_reference",
            organization="NatLabRockies / NREL / NLR",
            description="实验设计与主动学习方法基于 ALchemist。",
            url="https://github.com/NatLabRockies/ALchemist",
            citation_text="ALchemist active learning and Bayesian optimization toolkit for chemistry and materials experiments.",
            logo_alt="NREL / NLR ALchemist",
            visibility="prominent",
        )
        als_assistant = AttributionItem(
            name="ALS Accelerator Assistant / OSPREY",
            role="framework_reference",
            organization="Lawrence Berkeley National Laboratory / Advanced Light Source",
            description="大装置智能体 Plan-first 编排与受限执行范式参考。",
            url="https://arxiv.org/abs/2509.17255",
            citation_text="Agentic AI for Multi-Stage Physics Experiments at a Large-Scale Scientific User Facility.",
            logo_alt="Lawrence Berkeley National Laboratory / Advanced Light Source",
            visibility="prominent",
        )
        return [
            ModuleAttribution(
                module_id="research_engine",
                title="ResearchEngine 研发引擎",
                page_path="/research-engine",
                summary="研发编排参考 ChemOS 2.0 与 ALS Accelerator Assistant。",
                implementation_boundary="页面仅展示主要方法来源；完整引用见项目文档。",
                attributions=[
                    chemos,
                    als_assistant,
                ],
            ),
            ModuleAttribution(
                module_id="wetlab_optimization",
                title="湿实验优化",
                page_path="/optimization",
                summary="实验设计与优化推荐方法基于 ALchemist，并参考 ChemOS 2.0 编排理念。",
                implementation_boundary="页面仅展示主要方法来源；完整引用见项目文档。",
                attributions=[
                    alchemist,
                    chemos,
                ],
            ),
            ModuleAttribution(
                module_id="alchemist",
                title="Alchemist 实验设计",
                page_path="/optimization/alchemist",
                summary="实验设计与主动学习方法基于 ALchemist。",
                implementation_boundary="页面仅展示主要方法来源；完整引用见项目文档。",
                attributions=[alchemist],
            ),
            ModuleAttribution(
                module_id="experiment_dispatch",
                title="实验方案转发台",
                page_path="/optimization/experiment-dispatch",
                summary="实验清单按版本化实验下发配置生成；目标接口契约与声明式映射由配置管理。",
                implementation_boundary="本模块当前只生成和保存实验清单，不代表目标系统已接收或设备已执行。",
                attributions=[
                    AttributionItem(
                        name="SpecLabOS",
                        role="implementation_source",
                        organization="SpecLabOS",
                        description="未来用于参数化调用实验硬件和工作流。",
                        logo_alt="SpecLabOS",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="声明式映射",
                        role="implementation_source",
                        organization="PolyAgent",
                        description="以 JSON Pointer、受控转换和条件分支生成目标请求参数。",
                        logo_alt="声明式映射",
                        visibility="prominent",
                    ),
                ],
            ),
            ModuleAttribution(
                module_id="computation",
                title="ComputeEngine 计算智能",
                page_path="/computations/submit",
                summary="计算能力由 RDKit、OpenBabel、xTB、CREST、ORCA 等工具支持。",
                implementation_boundary="页面仅展示主要工具来源；完整引用见项目文档。",
                attributions=[
                    AttributionItem(
                        name="RDKit",
                        role="dependency",
                        organization="RDKit project",
                        description="分子结构处理与描述符工具。",
                        url="https://www.rdkit.org/",
                        logo_alt="RDKit",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="OpenBabel",
                        role="dependency",
                        organization="Open Babel project",
                        description="化学文件转换与结构处理工具。",
                        url="https://openbabel.org/",
                        logo_alt="OpenBabel",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="xTB / CREST",
                        role="dependency",
                        organization="Grimme Lab",
                        description="半经验量子化学计算与构象搜索工具。",
                        url="https://xtb-docs.readthedocs.io/",
                        logo_alt="xTB / CREST",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="ORCA",
                        role="dependency",
                        organization="ORCA quantum chemistry program",
                        description="量子化学计算程序。",
                        url="https://orcaforum.kofo.mpg.de/",
                        logo_alt="ORCA",
                        visibility="prominent",
                    ),
                ],
            ),
            ModuleAttribution(
                module_id="vertical_prediction",
                title="垂类预测模型",
                page_path="/vertical-prediction",
                summary="模型页面展示算法开发者、机构和方法来源。",
                implementation_boundary="页面仅展示主要模型来源；完整引用见项目文档。",
                attributions=[
                    AttributionItem(
                        name="算法开发者",
                        role="developer",
                        organization="算法开发者",
                        description="模型由算法开发者或合作机构提供。",
                        logo_alt="算法开发者",
                        visibility="prominent",
                    )
                ],
            ),
            ModuleAttribution(
                module_id="knowledge",
                title="WeKnora 知识库",
                page_path="/knowledge",
                summary="知识库管理、检索问答和引用证据能力由 WeKnora 提供。",
                implementation_boundary="页面仅展示主要服务来源；完整引用见项目文档。",
                attributions=[
                    AttributionItem(
                        name="WeKnora",
                        role="implementation_source",
                        organization="Tencent",
                        description="提供知识库管理、检索、会话问答和引用证据能力。",
                        url="https://github.com/Tencent/WeKnora",
                        logo_alt="Tencent WeKnora",
                        visibility="prominent",
                    )
                ],
            ),
            ModuleAttribution(
                module_id="data_catalog",
                title="数据管理",
                page_path="/database/data-catalog",
                summary="数据管理页展示已登记的公开高分子数据集和结构化导入记录。",
                implementation_boundary="页面仅展示主要数据来源；完整引用见项目文档。",
                attributions=[
                    AttributionItem(
                        name="OpenPoly",
                        role="implementation_source",
                        organization="OpenPoly dataset",
                        description="多来源高分子结构与物性汇总数据。",
                        url="https://doi.org/10.1007/s10118-025-3402-y",
                        citation_text="OpenPoly polymer database. DOI: 10.1007/s10118-025-3402-y.",
                        logo_alt="OpenPoly",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="RadonPy PI1070",
                        role="implementation_source",
                        organization="RadonPy project",
                        description="高分子计算物性数据集。",
                        url="https://github.com/RadonPy/RadonPy",
                        citation_text="RadonPy project repository and PI1070 example dataset.",
                        logo_alt="RadonPy",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="PI1M v2",
                        role="implementation_source",
                        organization="PI1M dataset",
                        description="聚合物结构生成数据集。",
                        url="https://doi.org/10.1021/acs.jcim.0c00726",
                        citation_text="PI1M polymer informatics benchmark dataset. DOI: 10.1021/acs.jcim.0c00726.",
                        logo_alt="PI1M",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="SMiPoly",
                        role="implementation_source",
                        organization="PEJpOhno",
                        description="单体结构库和聚合反应规则项目。",
                        url="https://github.com/PEJpOhno/SMiPoly",
                        citation_text="M. Ohno et al., Journal of Chemical Information and Modeling (2023). DOI: 10.1021/acs.jcim.3c00329.",
                        logo_alt="SMiPoly",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="PolyUniverse",
                        role="implementation_source",
                        organization="Yue, He and Li",
                        description="虚拟聚合物与候选单体生成数据。",
                        url="https://github.com/ytl0410/PolyUniverse",
                        citation_text="T. Yue, J. He and Y. Li, Digital Discovery (2024). DOI: 10.1039/D4DD00196F.",
                        logo_alt="PolyUniverse",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="MD-AllAtom 数据集",
                        role="implementation_source",
                        organization="MD-AllAtom 数据提供方",
                        description="全原子分子动力学原始文件和结构化碳基分析数据。",
                        logo_alt="MD-AllAtom 数据集",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="OMG",
                        role="implementation_source",
                        organization="The Jackson Laboratory",
                        description="Open Macromolecular Genome 聚合物结构数据。",
                        url="https://github.com/TheJacksonLab/OpenMacromolecularGenome",
                        citation_text="Open Macromolecular Genome (OMG), The Jackson Laboratory.",
                        logo_alt="OMG",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="OMG Physical Properties",
                        role="implementation_source",
                        organization="The Jackson Laboratory",
                        description="OMG 聚合物物理性质数据。",
                        url="https://doi.org/10.5281/zenodo.13863778",
                        citation_text="OMG Physical Properties. DOI: 10.1039/D4SC08617A; Zenodo: 10.5281/zenodo.13863778.",
                        logo_alt="OMG Physical Properties",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="polyOne",
                        role="implementation_source",
                        organization="Ramprasad Group",
                        description="与 polyBERT 工作关联的聚合物数据资源。",
                        url="https://doi.org/10.5281/zenodo.7124188",
                        citation_text="polyOne dataset, Zenodo: 10.5281/zenodo.7124188; polyBERT: 10.1038/s41467-023-39868-6.",
                        logo_alt="polyOne",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="ToPoRg",
                        role="implementation_source",
                        organization="ToPoRg dataset",
                        description="聚合物拓扑与回转半径数据。",
                        url="https://doi.org/10.5281/zenodo.10672434",
                        citation_text="ToPoRg dataset. DOI: 10.1038/s41524-024-01328-0; Zenodo: 10.5281/zenodo.10672434.",
                        license="CC BY 4.0",
                        logo_alt="ToPoRg",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="TROPIC",
                        role="implementation_source",
                        organization="TROPIC",
                        description="TROPIC 聚合物数据资源。",
                        url="https://polytropic.org/",
                        citation_text="TROPIC. DOI: 10.1039/D5FD00098J.",
                        logo_alt="TROPIC",
                        visibility="prominent",
                    ),
                    prominent_text_badge("PolySol", "PolySol 数据提供方"),
                    prominent_text_badge("PolyOmics", "PolyOmics 数据提供方"),
                    prominent_text_badge("PPPDB", "PPPDB 数据提供方"),
                    prominent_text_badge("PolyID", "PolyID 数据提供方"),
                    prominent_text_badge("NanoMine", "NanoMine 数据提供方"),
                ],
            ),
            ModuleAttribution(
                module_id="llm",
                title="LLM 模型服务",
                page_path="/tools?tab=llm-models",
                summary="LLM 模型服务由 OpenAI-compatible、Ollama 或自定义 HTTP provider 提供。",
                implementation_boundary="页面只展示 provider 协议和当前配置，不声明具体模型所有权或复制上游实现。",
                attributions=[
                    AttributionItem(
                        name="OpenAI-compatible provider",
                        role="implementation_source",
                        organization="OpenAI-compatible provider",
                        description="通过 OpenAI Chat Completions 协议接入模型服务。",
                        url="https://platform.openai.com/docs/api-reference/chat",
                        logo_alt="OpenAI-compatible provider",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="Ollama",
                        role="dependency",
                        organization="Ollama",
                        description="本地模型运行与 OpenAI 兼容接口。",
                        url="https://ollama.com/",
                        logo_alt="Ollama",
                        visibility="prominent",
                    ),
                    AttributionItem(
                        name="Custom HTTP provider",
                        role="implementation_source",
                        organization="Custom HTTP provider",
                        description="通过自定义 HTTP provider 接入内部模型服务。",
                        logo_alt="Custom HTTP provider",
                        visibility="prominent",
                    ),
                ],
            ),
        ]
