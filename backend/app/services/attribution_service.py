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
        return [
            ModuleAttribution(
                module_id="research_engine",
                title="ResearchEngine 研发引擎",
                page_path="/research-engine",
                summary="研发编排参考 ChemOS 2.0。",
                implementation_boundary="页面仅展示主要方法来源；完整引用见项目文档。",
                attributions=[
                    chemos,
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
                title="知识库 RAG 与图谱",
                page_path="/knowledge",
                summary="科学文献检索与知识图谱能力由知识服务提供。",
                implementation_boundary="页面仅展示主要服务来源；完整引用见项目文档。",
                attributions=[
                    AttributionItem(
                        name="知识服务",
                        role="implementation_source",
                        organization="知识服务",
                        description="提供文献检索、证据问答与图谱浏览能力。",
                        logo_alt="知识服务",
                        visibility="prominent",
                    )
                ],
            ),
        ]
