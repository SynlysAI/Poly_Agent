"""ResearchEngine API 集成测试。

覆盖 ProblemSpec API 和 AlgorithmRegistry API 的所有端点。
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.services.research_engine_service import ResearchEngineService
from app.services.algorithm_resource_service import AlgorithmManagedResourceService
from app.infra.research_engine_repositories import AlgorithmRegistryRepository, AlgorithmVersionRepository
from app.core.auth import get_current_user
from app.core.config import settings
from app.main import app
from app.schemas.knowledge import KnowledgeHealthData


def problem_spec_payload(**overrides) -> dict:
    """构建最小 ProblemSpec 创建请求。"""
    payload = {
        "name": "氟基高分子测试任务",
        "material_family": "fluoropolymer",
        "problem_type": "formulation_process_optimization",
        "objectives": [
            {"name": "dielectric_constant", "direction": "maximize", "unit": "dimensionless"},
        ],
    }
    payload.update(overrides)
    return payload


# =============================================================================
# ProblemSpec API 测试
# =============================================================================


class ProblemSpecApiTest(ComputationTestCase):
    """覆盖 ProblemSpec REST API。"""

    @classmethod
    def setUpClass(cls) -> None:
        """填充算法种子数据。"""
        # 不在此处初始化，由 setUp 处理
        pass

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"

    def test_create_problem_spec(self) -> None:
        """POST /problem-specs 创建 ProblemSpec 成功。"""
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertTrue(data["data"]["problem_spec_id"].startswith("ps_"))
        self.assertEqual(data["data"]["status"], "draft")
        self.assertEqual(data["data"]["schema_version"], "0.4")
        self.assertEqual(data["data"]["decision_status"], "pending_execution_decision")
        self.assertEqual(data["data"]["allowed_execution_modes"], ["manual_workbench", "autoresearch"])

    def test_create_with_full_fields(self) -> None:
        """包含完整字段的 ProblemSpec 创建成功。"""
        payload = problem_spec_payload(
            variables=[
                {"name": "fluorine_content", "type": "continuous", "role": "formulation", "unit": "percent", "bounds": [0, 100]},
                {"name": "monomer_smiles", "type": "categorical", "role": "structure", "categories": ["C=CF", "C=C(F)F"]},
            ],
            constraints=[
                {"name": "synthesizable", "type": "hard"},
                {"name": "temp_limit", "type": "hard", "expression": "temperature <= 180"},
            ],
            measurements=[
                {"name": "dielectric_constant", "condition": "room_temperature", "method": "impedance"},
            ],
            description="氟基高分子电解质优化演示",
        )
        resp = self.client.post(f"{self.base_url}/problem-specs", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(len(data["data"]["variables"]), 2)
        self.assertEqual(len(data["data"]["constraints"]), 2)
        self.assertEqual(len(data["data"]["measurements"]), 1)

    def test_create_rejects_empty_name(self) -> None:
        """空名称被拒绝（422 校验错误）。"""
        payload = problem_spec_payload(name="   ")
        resp = self.client.post(f"{self.base_url}/problem-specs", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_empty_objectives(self) -> None:
        """空目标列表被拒绝（422 校验错误）。"""
        payload = problem_spec_payload(objectives=[])
        resp = self.client.post(f"{self.base_url}/problem-specs", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_list_problem_specs(self) -> None:
        """GET /problem-specs 查询列表成功。"""
        # 先创建几条数据
        for i in range(3):
            self.client.post(
                f"{self.base_url}/problem-specs",
                json=problem_spec_payload(name=f"任务{i}"),
            )

        resp = self.client.get(f"{self.base_url}/problem-specs?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertLessEqual(len(data["data"]["items"]), 2)
        self.assertGreaterEqual(data["data"]["total"], 3)

    def test_archive_problem_spec_hides_from_default_list(self) -> None:
        """归档 ProblemSpec 后默认列表隐藏，按 archived 状态可查。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(name="待归档研发任务"),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        archive_resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}:archive",
            json={"reason": "API 测试归档"},
        )
        self.assertEqual(archive_resp.status_code, 200)
        self.assertEqual(archive_resp.json()["data"]["status"], "archived")

        default_resp = self.client.get(f"{self.base_url}/problem-specs")
        default_ids = [item["problem_spec_id"] for item in default_resp.json()["data"]["items"]]
        self.assertNotIn(ps_id, default_ids)

        archived_resp = self.client.get(f"{self.base_url}/problem-specs?status=archived")
        archived_ids = [item["problem_spec_id"] for item in archived_resp.json()["data"]["items"]]
        self.assertIn(ps_id, archived_ids)

    def test_readiness_reports_optional_demo_fallbacks_before_start(self) -> None:
        """AutoResearch 启动前可见 RAG/Alchemist/LLM 和阶段运行模式。"""
        rag_unavailable = KnowledgeHealthData(
            status="unavailable",
            configured=False,
            demo_available=False,
            message="WeKnora 服务未配置。",
            systems=[],
        )
        original_llm_model = settings.llm_model
        original_llm_base_url = settings.llm_base_url
        original_llm_api_key = settings.llm_api_key
        original_llm_default_provider = settings.llm_default_provider
        original_llm_default_model = settings.llm_default_model
        original_llm_provider_configs_file = getattr(settings, "llm_provider_configs_file", "")
        original_llm_provider_configs_json = settings.llm_provider_configs_json
        settings.llm_model = "gpt-test"
        settings.llm_base_url = "http://llm.local/v1"
        settings.llm_api_key = "test-key"
        settings.llm_default_provider = ""
        settings.llm_default_model = ""
        settings.llm_provider_configs_file = ""
        settings.llm_provider_configs_json = ""
        try:
            with patch("app.services.integration_status_service.IntegrationStatusService._can_connect", return_value=False), \
                 patch("app.services.knowledge_service.KnowledgeService.health", return_value=rag_unavailable), \
                 patch("app.services.llm_model_service.LLMRoutingRepository.find_one", return_value=None):
                resp = self.client.get(f"{self.base_url}/readiness")
        finally:
            settings.llm_model = original_llm_model
            settings.llm_base_url = original_llm_base_url
            settings.llm_api_key = original_llm_api_key
            settings.llm_default_provider = original_llm_default_provider
            settings.llm_default_model = original_llm_default_model
            settings.llm_provider_configs_file = original_llm_provider_configs_file
            settings.llm_provider_configs_json = original_llm_provider_configs_json

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        by_service = {item["service"]: item for item in data["items"]}

        self.assertFalse(data["ready"])
        self.assertTrue(data["can_start"])
        self.assertEqual(by_service["weknora"]["status"], "warning")
        self.assertEqual(by_service["weknora"]["level"], "not_configured")
        self.assertFalse(by_service["weknora"]["demo_fallback"])
        self.assertFalse(by_service["weknora"]["blocking"])
        self.assertEqual(by_service["artifact-store"]["status"], "ready")
        self.assertEqual(by_service["computation-engine"]["status"], "ready")
        self.assertEqual(by_service["alchemist-backend"]["status"], "ready")
        self.assertEqual(by_service["research-llm"]["provider"], "default_openai")
        self.assertEqual(by_service["research-llm"]["model"], "gpt-test")
        self.assertEqual(by_service["research-llm"]["level"], "configured_pending_verification")
        stage_modes = {item["stage_key"]: item for item in data["stage_modes"]}
        self.assertEqual(stage_modes["KNOWLEDGE_RETRIEVAL"]["capability_id"], "weknora")
        self.assertEqual(stage_modes["STRUCTURE_FEATURE"]["execution_mode"], "mock_fallback")
        self.assertEqual(stage_modes["MODEL_UPDATE"]["provider"], "default_openai")

    def test_capabilities_endpoint_reports_truth_levels(self) -> None:
        """平台能力接口返回统一真实性等级和模型配置摘要。"""
        rag_demo = KnowledgeHealthData(
            status="warning",
            configured=False,
            demo_available=True,
            message="WeKnora 服务未配置。",
            systems=["demo"],
            backend="weknora",
        )
        with patch("app.services.integration_status_service.IntegrationStatusService._can_connect", return_value=False), \
             patch("app.services.knowledge_service.KnowledgeService.health", return_value=rag_demo):
            resp = self.client.get("/api/v1/capabilities")

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        items = {(item["module_id"], item["capability_id"]): item for item in data["items"]}
        self.assertIn(("knowledge", "weknora"), items)
        self.assertIn(("research-engine", "research-llm"), items)
        self.assertEqual(items[("knowledge", "weknora")]["level"], "demo_fallback")
        self.assertTrue(items[("knowledge", "weknora")]["demo_fallback"])
        self.assertIn(
            items[("research-engine", "research-llm")]["level"],
            {"not_configured", "configured_pending_verification", "production_ready", "unavailable"},
        )


class AttributionApiTest(ComputationTestCase):
    """覆盖模块来源标注 API。"""

    def test_list_and_get_module_attributions(self) -> None:
        """模块来源注册表返回机构、引用和实现边界。"""
        list_resp = self.client.get("/api/v1/attributions/modules")
        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        list_data = list_resp.json()["data"]
        module_ids = {item["module_id"] for item in list_data["items"]}
        self.assertIn("research_engine", module_ids)
        self.assertIn("wetlab_optimization", module_ids)

        detail_resp = self.client.get("/api/v1/attributions/modules/research_engine")
        self.assertEqual(detail_resp.status_code, 200, detail_resp.text)
        detail = detail_resp.json()["data"]
        self.assertIn("ChemOS", detail["summary"])
        self.assertTrue(detail["implementation_boundary"])
        prominent = [item for item in detail["attributions"] if item["visibility"] == "prominent"]
        self.assertTrue(prominent)
        self.assertTrue(prominent[0]["logo_alt"])


class AlgorithmPackageApiTest(ComputationTestCase):
    """覆盖用户上传算法包 P0 生命周期。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    @staticmethod
    def _login_as(user_id: str, role: str = "user") -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": user_id,
            "username": user_id,
            "role": role,
            "status": "active",
        }

    def _pack_activate_simple_algorithm(
        self,
        algorithm_id: str,
        *,
        visibility: str | None = None,
        contributors: list[dict] | None = None,
    ) -> str:
        handler_source = b"""
def predict(inputs, context=None, model=None):
    return {"prediction": {"value": inputs.get("smiles", "")}}
"""
        data = {
            "algorithm_id": algorithm_id,
            "name": f"{algorithm_id} Demo",
            "version": "0.1.0",
            "entrypoint": "src.handler:predict",
            "developer": "Demo Developer",
            "developer_organization": "Demo Institute",
            "input_schema": '{"fields":{"smiles":"string"},"required":["smiles"]}',
            "output_schema": '{"fields":{"prediction":"object"},"required":["prediction"]}',
            "sample_input": '{"smiles":"CCO"}',
        }
        if visibility is not None:
            data["visibility"] = visibility
        if contributors is not None:
            data["contributors"] = json.dumps(contributors, ensure_ascii=False)
        pack_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:pack",
            data=data,
            files=[("files", ("handler.py", handler_source, "text/x-python"))],
        )
        self.assertEqual(pack_resp.status_code, 200, pack_resp.text)
        package = pack_resp.json()["data"]
        package_id = package["package_id"]
        version_id = package["version_id"]
        build_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:build")
        self.assertEqual(build_resp.status_code, 200, build_resp.text)
        deploy_resp = self.client.post(f"{self.base_url}/algorithms/{algorithm_id}/versions/{version_id}:deploy")
        self.assertEqual(deploy_resp.status_code, 200, deploy_resp.text)
        activate_resp = self.client.post(f"{self.base_url}/algorithms/{algorithm_id}/versions/{version_id}:activate")
        self.assertEqual(activate_resp.status_code, 200, activate_resp.text)
        return version_id

    @staticmethod
    def _template_zip_with_version(template_content: bytes, version: str) -> bytes:
        """基于官方模板生成指定 version 的标准 ZIP。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(template_content)) as source_zip:
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                for member in source_zip.infolist():
                    if member.is_dir():
                        continue
                    content = source_zip.read(member.filename)
                    if member.filename == "polyagent.algorithm.yaml":
                        contract = yaml.safe_load(content)
                        contract["version"] = version
                        content = yaml.safe_dump(
                            contract, allow_unicode=True, sort_keys=False
                        ).encode("utf-8")
                    target_zip.writestr(member, content)
        return buffer.getvalue()

    @staticmethod
    def _managed_resource_package_zip(algorithm_id: str = "managed_resource_demo") -> bytes:
        """Build a minimal package that requires a platform-managed resource."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "polyagent.algorithm.yaml",
                f"""contract_version: "0.2"
algorithm_id: {algorithm_id}
name: Managed Resource Demo
version: 0.1.0
algorithm_family: vertical_prediction
type: predictor
material_scope:
  - universal
task_scope:
  - COMPUTE_PREDICT
trigger_modes:
  - human_workflow
entrypoint: src.handler:predict
runtime:
  python: "3.11"
  resources:
    cpu: 1
    memory: 1Gi
    gpu: false
  timeout_seconds: 30
input_schema:
  fields: {{}}
  required: []
output_schema:
  fields:
    resource_ready: boolean
    resource_id: string
  required:
    - resource_ready
resource_assets:
  - key: model_weights
    required: true
    binding_required: true
    resource_type: checkpoints
    required_files:
      - ready.txt
sample_input_path: tests/sample_input.json
""",
            )
            zf.writestr(
                "src/handler.py",
                """
from pathlib import Path


def predict(inputs, context=None, model=None):
    context = context or {}
    resource = context["resource_assets"]["model_weights"]
    path = Path(resource["path"])
    return {
        "resource_ready": (path / "ready.txt").is_file(),
        "resource_id": resource.get("resource_id", ""),
    }
""",
            )
            zf.writestr("tests/sample_input.json", "{}")
        return buffer.getvalue()

    def test_requirement_document_template_download_and_parse(self) -> None:
        template_resp = self.client.get(f"{self.base_url}/algorithm-requirement-docs/template")
        self.assertEqual(template_resp.status_code, 200, template_resp.text)
        if template_resp.headers["content-type"].startswith("text/markdown"):
            template_text = template_resp.content.decode("utf-8")
            self.assertIn("developer_organization:", template_text)
            self.assertIn("mentor_team:", template_text)
            self.assertIn("visibility: private", template_text)
        else:
            self.assertEqual(
                template_resp.headers["content-type"],
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            self.assertIn("PolyAgent_%E6%A8%A1%E5%9E%8B%E6%95%B0%E6%8D%AE%E9%9B%86%E6%88%90%E9%9C%80%E6%B1%82%E6%94%B6%E9%9B%86_%E5%A1%AB%E5%86%99%E6%A8%A1%E6%9D%BF.docx", template_resp.headers["content-disposition"])
            self.assertTrue(template_resp.content.startswith(b"PK"))
            with zipfile.ZipFile(io.BytesIO(template_resp.content)) as template_zip:
                template_xml = template_zip.read("word/document.xml").decode("utf-8")
            self.assertIn("导师课题组", template_xml)

        document = """---
template_version: "0.1"
algorithm_id: vertical_tg_predictor
name: Polymer Tg Predictor
version: 0.1.0
developer_organization: Revised Institute
mentor_team: Revised Mentor Group
visibility: public
description: 预测聚合物玻璃化转变温度。
material_scope:
  - universal
requirements_hint:
  - scikit-learn
  - joblib
input_schema:
  fields:
    smiles: string
  required:
    - smiles
output_schema:
  fields:
    prediction: object
  required:
    - prediction
sample_input:
  smiles: C=C(F)F
---

# Poly Agent 需求文档

## 目标
预测聚合物玻璃化转变温度。
"""
        parse_resp = self.client.post(
            f"{self.base_url}/algorithm-requirement-docs:parse",
            files={"file": ("requirement.md", document.encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(parse_resp.status_code, 200, parse_resp.text)
        data = parse_resp.json()["data"]
        self.assertEqual(data["source_filename"], "requirement.md")
        self.assertEqual(data["draft"]["algorithm_id"], "vertical_tg_predictor")
        self.assertEqual(data["draft"]["name"], "Polymer Tg Predictor")
        self.assertEqual(data["draft"]["example_id"], "smiles_property_predictor")
        self.assertEqual(data["draft"]["developer_organization"], "Revised Institute")
        self.assertEqual(data["draft"]["mentor_team"], "Revised Mentor Group")
        self.assertEqual(data["draft"]["visibility"], "public")
        self.assertEqual(data["draft"]["input_schema"]["fields"]["smiles"], "string")
        self.assertEqual(data["draft"]["sample_input"]["smiles"], "C=C(F)F")
        self.assertIn("owner_name", data["missing_fields"])
        self.assertIn("owner_contact", data["missing_fields"])

    def test_requirement_document_docx_parse(self) -> None:
        document = self._build_requirement_docx(
            paragraphs=[
                "PolyAgent 模型与数据集成需求收集表",
                "输入 JSON 示例：",
                '{\n  "smiles": "C=C(F)F",\n  "temperature": 298\n}',
                "输出 JSON 示例：",
                '{\n  "prediction": 123.4,\n  "unit": "K"\n}',
            ],
            tables=[
                [
                    ["字段", "填写内容"],
                    ["算法名称 / 代号", "Polymer Tg Predictor / vertical_tg_predictor"],
                    ["负责人", "张三 / zhangsan@example.com"],
                    ["导师课题组", "李四教授课题组"],
                    ["算法功能介绍", "预测聚合物玻璃化转变温度。"],
                    ["适用体系", "通用"],
                    ["依赖（附 requirements.txt）", "scikit-learn, joblib"],
                ],
            ],
        )
        parse_resp = self.client.post(
            f"{self.base_url}/algorithm-requirement-docs:parse",
            files={
                "file": (
                    "requirement.docx",
                    document,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        self.assertEqual(parse_resp.status_code, 200, parse_resp.text)
        data = parse_resp.json()["data"]
        self.assertEqual(data["source_filename"], "requirement.docx")
        self.assertEqual(data["draft"]["algorithm_id"], "vertical_tg_predictor")
        self.assertEqual(data["draft"]["name"], "Polymer Tg Predictor")
        self.assertEqual(data["draft"]["owner_contact"], "zhangsan@example.com")
        self.assertEqual(data["draft"]["mentor_team"], "李四教授课题组")
        self.assertEqual(data["draft"]["input_schema"]["fields"]["smiles"], "string")
        self.assertEqual(data["draft"]["input_schema"]["fields"]["temperature"], "integer")
        self.assertEqual(data["draft"]["output_schema"]["fields"]["prediction"], "number")
        self.assertEqual(data["draft"]["sample_input"]["temperature"], 298)

    def test_requirement_document_docx_parse_file_based_raman(self) -> None:
        document = self._build_requirement_docx(
            paragraphs=[
                "PolyAgent 模型与数据集成需求收集表",
                "运行时通过 multipart 上传 spectrum_file，平台按 input_assets 解析为 series_json。",
                "2.2 算法运行方式",
                "输入 JSON 示例：",
                '{\n  "spectype": "raman",\n  "mode": "function_groups",\n  "k": 3\n}',
                "输出 JSON 示例：",
                '{\n  "candidates": [],\n  "point_count": 8,\n  "metadata": {},\n  "preprocessing": {}\n}',
            ],
            tables=[
                [
                    ["字段", "填写内容"],
                    ["算法名称 / 代号", "Raman Structure Analyzer / raman_structure_analyzer"],
                    ["负责人", "Raman Structure Analyzer 模型团队 / raman-demo@example.local"],
                    ["算法功能介绍", "输入 Raman/IR 光谱 x-y 序列和 JSON 参数，输出候选结构。"],
                    ["适用体系", "通用"],
                    ["依赖（附 requirements.txt）", "numpy, scipy, torch"],
                ],
                [
                    ["字段", "填写内容"],
                    ["文件类型 / 数量 / 大小", ".txt/.dat/.csv/.xlsx，运行时上传 1 个 spectrum_file"],
                    ["提交方式", "AlgorithmRun multipart 上传"],
                ],
            ],
        )
        parse_resp = self.client.post(
            f"{self.base_url}/algorithm-requirement-docs:parse",
            files={
                "file": (
                    "raman-requirement.docx",
                    document,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        self.assertEqual(parse_resp.status_code, 200, parse_resp.text)
        data = parse_resp.json()["data"]
        self.assertEqual(data["draft"]["algorithm_id"], "raman_structure_analyzer")
        self.assertEqual(data["draft"]["example_id"], "file_based_predictor")
        self.assertEqual(data["draft"]["input_schema"]["fields"]["spectype"], "string")
        self.assertEqual(data["draft"]["output_schema"]["fields"]["candidates"], "list")
        self.assertNotIn("文档正文较短，建议补充依赖和上线约束", data["warnings"])

    @staticmethod
    def _build_requirement_docx(*, paragraphs: list[str], tables: list[list[list[str]]]) -> bytes:
        def text_nodes(value: str) -> str:
            return "".join(f"<w:t>{line}</w:t>{'<w:br/>' if index < len(value.splitlines()) - 1 else ''}" for index, line in enumerate(value.splitlines()))

        paragraph_xml = "".join(f"<w:p><w:r>{text_nodes(item)}</w:r></w:p>" for item in paragraphs)
        table_xml = ""
        for table in tables:
            rows_xml = ""
            for row in table:
                cells_xml = "".join(f"<w:tc><w:p><w:r>{text_nodes(cell)}</w:r></w:p></w:tc>" for cell in row)
                rows_xml += f"<w:tr>{cells_xml}</w:tr>"
            table_xml += f"<w:tbl>{rows_xml}</w:tbl>"
        document_xml = (
            "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{paragraph_xml}{table_xml}</w:body></w:document>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("word/document.xml", document_xml)
        return buffer.getvalue()

    def test_template_upload_validate_build_deploy_activate_and_run(self) -> None:
        """模板 ZIP 可完整进入 active，并被 AlgorithmRun 调用。"""
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        self.assertEqual(template_resp.status_code, 200)
        self.assertEqual(template_resp.headers["content-type"], "application/zip")

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("demo.zip", template_resp.content, "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package_id = upload_resp.json()["data"]["package_id"]
        self.assertEqual(upload_resp.json()["data"]["status"], "uploaded")
        self.assertTrue(upload_resp.json()["data"]["created_at"].endswith("Z"))

        download_resp = self.client.get(f"{self.base_url}/algorithm-packages/{package_id}/download")
        self.assertEqual(download_resp.status_code, 200, download_resp.text)
        self.assertEqual(download_resp.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(download_resp.content)) as downloaded_zip:
            self.assertIn("polyagent.algorithm.yaml", downloaded_zip.namelist())
        reupload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("downloaded-demo.zip", download_resp.content, "application/zip")},
        )
        self.assertEqual(reupload_resp.status_code, 200, reupload_resp.text)
        self.assertEqual(reupload_resp.json()["data"]["package_sha256"], upload_resp.json()["data"]["package_sha256"])

        validate_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:validate")
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        package_data = validate_resp.json()["data"]
        self.assertEqual(package_data["status"], "validated")
        version_id = package_data["version_id"]

        build_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:build")
        self.assertEqual(build_resp.status_code, 200, build_resp.text)
        self.assertEqual(build_resp.json()["data"]["status"], "built")
        self.assertTrue(build_resp.json()["data"]["image_digest"].startswith("sha256:"))
        self.assertTrue(build_resp.json()["data"]["runtime_digest"].startswith("sha256:"))
        self.assertTrue(build_resp.json()["data"]["environment_digest"].startswith("sha256:"))

        deploy_resp = self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{version_id}:deploy"
        )
        self.assertEqual(deploy_resp.status_code, 200, deploy_resp.text)
        self.assertEqual(deploy_resp.json()["data"]["status"], "deployed_staging")
        self.assertTrue(deploy_resp.json()["data"]["created_at"].endswith("Z"))
        self.assertTrue(deploy_resp.json()["data"]["updated_at"].endswith("Z"))
        self.assertEqual(deploy_resp.json()["data"]["deployment"]["backend"], "local_sandbox_runtime")
        self.assertEqual(deploy_resp.json()["data"]["deployment"]["endpoint_type"], "subprocess")

        health_resp = self.client.get(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{version_id}/health"
        )
        self.assertEqual(health_resp.status_code, 200, health_resp.text)
        self.assertEqual(health_resp.json()["data"]["health"]["health"], "ready")

        logs_resp = self.client.get(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{version_id}/logs"
        )
        self.assertEqual(logs_resp.status_code, 200, logs_resp.text)
        self.assertIn("runtime_logs", logs_resp.json()["data"])

        activate_resp = self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{version_id}:activate"
        )
        self.assertEqual(activate_resp.status_code, 200, activate_resp.text)
        self.assertEqual(activate_resp.json()["data"]["status"], "active")

        redeploy_resp = self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{version_id}:redeploy"
        )
        self.assertEqual(redeploy_resp.status_code, 200, redeploy_resp.text)
        self.assertEqual(redeploy_resp.json()["data"]["status"], "active")

        algorithm_resp = self.client.get(f"{self.base_url}/algorithms/vertical_tg_predictor_demo")
        self.assertEqual(algorithm_resp.status_code, 200)
        self.assertEqual(algorithm_resp.json()["data"]["active_version_id"], version_id)
        self.assertEqual(algorithm_resp.json()["data"]["source"], "uploaded_package")
        self.assertIsNone(algorithm_resp.json()["data"]["developer_attribution"])

        run_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "vertical_tg_predictor_demo",
                "trigger_source": "human_workflow",
                "input_snapshot": {"smiles": "C=C(F)F", "temperature_c": 25},
            },
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        run_data = run_resp.json()["data"]
        self.assertEqual(run_data["status"], "completed")
        self.assertTrue(run_data["created_at"].endswith("Z"))
        self.assertTrue(run_data["started_at"].endswith("Z"))
        self.assertTrue(run_data["finished_at"].endswith("Z"))
        self.assertEqual(run_data["algorithm_version_id"], version_id)
        self.assertIn("prediction", run_data["output_summary"])
        self.assertIn("feature_summary", run_data["output_summary"])
        self.assertEqual(run_data["runtime_snapshot"]["backend"], "local_sandbox_runtime")
        self.assertTrue(run_data["runtime_digest"].startswith("sha256:"))
        self.assertIn("worker_pid", run_data["runtime_snapshot"])

    def test_algorithm_package_visibility_defaults_to_private(self) -> None:
        """未显式选择发布范围时，上传模型默认为非公开。"""
        version_id = self._pack_activate_simple_algorithm("private_default_demo")

        algorithm_resp = self.client.get(f"{self.base_url}/algorithms/private_default_demo")
        self.assertEqual(algorithm_resp.status_code, 200, algorithm_resp.text)
        self.assertEqual(algorithm_resp.json()["data"]["visibility"], "private")

        versions_resp = self.client.get(f"{self.base_url}/algorithms/private_default_demo/versions")
        version = next(item for item in versions_resp.json()["data"]["items"] if item["version_id"] == version_id)
        self.assertEqual(version["visibility"], "private")

    def test_private_uploaded_algorithm_is_hidden_and_not_callable_by_other_users(self) -> None:
        """普通用户不能看到或调用他人的非公开上传模型。"""
        self._login_as("user-a")
        self._pack_activate_simple_algorithm("private_access_demo", visibility="private")

        self._login_as("user-b")
        list_resp = self.client.get(
            f"{self.base_url}/algorithms",
            params={"algorithm_family": "vertical_prediction", "page": 1, "page_size": 100},
        )
        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        algorithm_ids = {item["algorithm_id"] for item in list_resp.json()["data"]["items"]}
        self.assertNotIn("private_access_demo", algorithm_ids)

        detail_resp = self.client.get(f"{self.base_url}/algorithms/private_access_demo")
        self.assertEqual(detail_resp.status_code, 403, detail_resp.text)

        run_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "private_access_demo",
                "trigger_source": "human_workflow",
                "input_snapshot": {"smiles": "CCO"},
            },
        )
        self.assertEqual(run_resp.status_code, 403, run_resp.text)

    def test_public_uploaded_algorithm_is_visible_callable_but_not_governable(self) -> None:
        """公开上传模型对平台用户可见可调用，但版本治理仍限 owner/admin。"""
        self._login_as("user-a")
        version_id = self._pack_activate_simple_algorithm("public_access_demo", visibility="public")

        self._login_as("user-b")
        list_resp = self.client.get(
            f"{self.base_url}/algorithms",
            params={"algorithm_family": "vertical_prediction", "page": 1, "page_size": 100},
        )
        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        algorithm_ids = {item["algorithm_id"] for item in list_resp.json()["data"]["items"]}
        self.assertIn("public_access_demo", algorithm_ids)

        detail_resp = self.client.get(f"{self.base_url}/algorithms/public_access_demo")
        self.assertEqual(detail_resp.status_code, 200, detail_resp.text)
        self.assertEqual(detail_resp.json()["data"]["visibility"], "public")

        run_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "public_access_demo",
                "trigger_source": "human_workflow",
                "input_snapshot": {"smiles": "CCO"},
            },
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        self.assertEqual(run_resp.json()["data"]["status"], "completed")
        self.assertEqual(run_resp.json()["data"]["algorithm_version_id"], version_id)

        logs_resp = self.client.get(f"{self.base_url}/algorithms/public_access_demo/versions/{version_id}/logs")
        self.assertEqual(logs_resp.status_code, 403, logs_resp.text)

    def test_credit_summary_aggregates_existing_records_without_exposing_runs(self) -> None:
        """Credit 汇总只返回贡献构成和运行计数，不泄露运行输入或项目内容。"""
        self._login_as("user-a")
        contributors = [
            {
                "user_id": "student-1",
                "name": "学生开发者",
                "role": "developer",
                "organization": "Demo Institute",
                "mentor_relation": "课题组指导",
                "description": "实现模型推理入口",
            },
            {
                "name": "导师审核",
                "role": "reviewer",
                "organization": "Demo Institute",
                "description": "验证模型适用边界",
            },
        ]
        self._pack_activate_simple_algorithm(
            "credit_summary_demo",
            visibility="public",
            contributors=contributors,
        )
        for user_id in ("user-a", "user-b"):
            self._login_as(user_id)
            run_resp = self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": "credit_summary_demo",
                    "trigger_source": "human_workflow",
                    "problem_spec_id": None,
                    "research_run_id": "rr-credit-demo" if user_id == "user-b" else None,
                    "input_snapshot": {"smiles": "CCO"},
                },
            )
            self.assertEqual(run_resp.status_code, 200, run_resp.text)

        summary_resp = self.client.get(f"{self.base_url}/algorithms/credit_summary_demo/credit-summary")
        self.assertEqual(summary_resp.status_code, 200, summary_resp.text)
        summary = summary_resp.json()["data"]
        self.assertEqual(summary["visibility"], "public")
        self.assertEqual(summary["metrics"]["version_count"], 1)
        self.assertEqual(summary["metrics"]["validated_version_count"], 1)
        self.assertEqual(summary["metrics"]["run_count"], 2)
        self.assertEqual(summary["metrics"]["success_run_count"], 2)
        self.assertEqual(summary["metrics"]["caller_count"], 2)
        self.assertEqual(summary["metrics"]["reused_project_count"], 1)
        self.assertEqual(summary["metrics"]["contributor_count"], 2)
        self.assertEqual(summary["metrics"]["role_breakdown"]["developer"], 1)
        self.assertEqual(summary["metrics"]["role_breakdown"]["reviewer"], 1)
        self.assertNotIn("input_snapshot", json.dumps(summary, ensure_ascii=False))
        self.assertNotIn("CCO", json.dumps(summary, ensure_ascii=False))

    def test_private_credit_summary_is_not_visible_to_other_users(self) -> None:
        """普通用户不能查看他人私有上传算法的 Credit 汇总。"""
        self._login_as("user-a")
        self._pack_activate_simple_algorithm("private_credit_demo", visibility="private")

        self._login_as("user-b")
        summary_resp = self.client.get(f"{self.base_url}/algorithms/private_credit_demo/credit-summary")
        self.assertEqual(summary_resp.status_code, 403, summary_resp.text)

    def test_admin_can_correct_credit_summary_and_audit_is_recorded(self) -> None:
        """管理员可修正当前贡献关系，且修正原因进入审计记录。"""
        self._login_as("user-a")
        self._pack_activate_simple_algorithm("credit_correction_demo", visibility="public")

        self._login_as("normal_user")
        forbidden_resp = self.client.patch(
            f"{self.base_url}/algorithms/credit_correction_demo/credit-summary",
            json={
                "contributors": [],
                "mentor_team": "普通用户尝试修正",
                "reason": "not allowed",
            },
        )
        self.assertEqual(forbidden_resp.status_code, 403, forbidden_resp.text)

        self._login_as("admin", role="admin")
        patch_resp = self.client.patch(
            f"{self.base_url}/algorithms/credit_correction_demo/credit-summary",
            json={
                "contributors": [
                    {
                        "name": "更正作者",
                        "role": "developer",
                        "organization": "更正机构",
                    }
                ],
                "developer_attribution": {
                    "name": "更正作者",
                    "role": "developer",
                    "organization": "更正机构",
                    "visibility": "prominent",
                },
                "mentor_team": "更正课题组",
                "reason": "管理员核对上传登记后修正",
            },
        )
        self.assertEqual(patch_resp.status_code, 200, patch_resp.text)
        summary = patch_resp.json()["data"]
        self.assertEqual(summary["contributors"][0]["name"], "更正作者")
        self.assertEqual(summary["developer_attribution"]["organization"], "更正机构")
        self.assertEqual(summary["mentor_team"], "更正课题组")

        audit_resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_type": "algorithm", "entity_id": "credit_correction_demo"},
        )
        self.assertEqual(audit_resp.status_code, 200, audit_resp.text)
        event_types = {item["event_type"] for item in audit_resp.json()["data"]["items"]}
        self.assertIn("credit_corrected", event_types)

    def test_owner_can_update_algorithm_metadata_and_reactivation_preserves_it(self) -> None:
        """上传者可维护展示信息，后续激活不会恢复旧包元数据。"""
        self._login_as("metadata-owner")
        version_id = self._pack_activate_simple_algorithm("metadata_update_demo", visibility="private")

        patch_resp = self.client.patch(
            f"{self.base_url}/algorithms/metadata_update_demo/metadata",
            json={
                "name": "在线修订模型名称",
                "description": "在线修订后的算法介绍",
                "visibility": "public",
                "developer": "在线修订作者",
                "developer_organization": "在线修订机构",
                "mentor_team": "在线修订导师课题组",
                "source_url": "https://example.org/model",
                "citation": "Online metadata citation",
                "contributors": [
                    {
                        "name": "在线修订作者",
                        "role": "developer",
                        "organization": "在线修订机构",
                    }
                ],
                "reason": "部署后补充展示信息",
            },
        )
        self.assertEqual(patch_resp.status_code, 200, patch_resp.text)
        updated = patch_resp.json()["data"]
        self.assertEqual(updated["name"], "在线修订模型名称")
        self.assertEqual(updated["description"], "在线修订后的算法介绍")
        self.assertEqual(updated["visibility"], "public")
        self.assertEqual(updated["developer_attribution"]["name"], "在线修订作者")
        self.assertEqual(updated["developer_attribution"]["organization"], "在线修订机构")
        self.assertEqual(updated["developer_attribution"]["url"], "https://example.org/model")
        self.assertEqual(updated["developer_attribution"]["citation_text"], "Online metadata citation")
        self.assertEqual(updated["mentor_team"], "在线修订导师课题组")

        self._login_as("metadata-viewer")
        public_detail_resp = self.client.get(f"{self.base_url}/algorithms/metadata_update_demo")
        self.assertEqual(public_detail_resp.status_code, 200, public_detail_resp.text)
        self._login_as("metadata-owner")

        audit_resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_type": "algorithm", "entity_id": "metadata_update_demo"},
        )
        self.assertEqual(audit_resp.status_code, 200, audit_resp.text)
        events = audit_resp.json()["data"]["items"]
        metadata_event = next(item for item in events if item["event_type"] == "algorithm_metadata_updated")
        self.assertEqual(metadata_event["actor_user_id"], "metadata-owner")
        self.assertEqual(metadata_event["reason"], "部署后补充展示信息")
        self.assertEqual(metadata_event["after"]["name"], "在线修订模型名称")
        self.assertIn("name", metadata_event["before"])

        AlgorithmVersionRepository.update_fields(version_id, {"status": "deployed_staging"})
        reactivate_resp = self.client.post(
            f"{self.base_url}/algorithms/metadata_update_demo/versions/{version_id}:activate"
        )
        self.assertEqual(reactivate_resp.status_code, 200, reactivate_resp.text)
        detail_resp = self.client.get(f"{self.base_url}/algorithms/metadata_update_demo")
        persisted = detail_resp.json()["data"]
        self.assertEqual(persisted["name"], "在线修订模型名称")
        self.assertEqual(persisted["description"], "在线修订后的算法介绍")
        self.assertEqual(persisted["visibility"], "public")
        self.assertEqual(persisted["developer_attribution"]["name"], "在线修订作者")

        clear_resp = self.client.patch(
            f"{self.base_url}/algorithms/metadata_update_demo/metadata",
            json={
                "description": None,
                "developer": None,
                "developer_organization": None,
                "mentor_team": None,
                "source_url": None,
                "citation": None,
                "contributors": [],
                "reason": "清空不再适用的展示信息",
            },
        )
        self.assertEqual(clear_resp.status_code, 200, clear_resp.text)
        cleared = clear_resp.json()["data"]
        self.assertIsNone(cleared["description"])
        self.assertIsNone(cleared["developer_attribution"])
        self.assertIsNone(cleared["mentor_team"])
        self.assertEqual(cleared["contributors"], [])

    def test_algorithm_metadata_update_requires_owner_or_admin(self) -> None:
        """公开可见不等于可编辑；管理员仍可代管上传算法。"""
        self._login_as("metadata-owner")
        self._pack_activate_simple_algorithm("metadata_permission_demo", visibility="public")

        self._login_as("other-user")
        forbidden_resp = self.client.patch(
            f"{self.base_url}/algorithms/metadata_permission_demo/metadata",
            json={"description": "无权修改"},
        )
        self.assertEqual(forbidden_resp.status_code, 403, forbidden_resp.text)

        self._login_as("admin-user", role="admin")
        admin_resp = self.client.patch(
            f"{self.base_url}/algorithms/metadata_permission_demo/metadata",
            json={"description": "管理员修订"},
        )
        self.assertEqual(admin_resp.status_code, 200, admin_resp.text)
        self.assertEqual(admin_resp.json()["data"]["description"], "管理员修订")

        null_visibility_resp = self.client.patch(
            f"{self.base_url}/algorithms/metadata_permission_demo/metadata",
            json={"visibility": None},
        )
        self.assertEqual(null_visibility_resp.status_code, 422, null_visibility_resp.text)

        AlgorithmRegistryRepository.save(
            "algorithm_id",
            {
                "algorithm_id": "builtin_metadata_demo",
                "name": "Builtin Metadata Demo",
                "source": "builtin",
            },
        )
        builtin_resp = self.client.patch(
            f"{self.base_url}/algorithms/builtin_metadata_demo/metadata",
            json={"description": "不应允许"},
        )
        self.assertEqual(builtin_resp.status_code, 409, builtin_resp.text)

    def test_pack_algorithm_package_persists_developer_attribution(self) -> None:
        """网页打包入口会把开发者来源写入 AlgorithmVersion。"""
        handler_source = b"""
def predict(inputs, context=None, model=None):
    return {"prediction": {"value": 1.0, "unit": "demo"}}
"""
        pack_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:pack",
            data={
                "algorithm_id": "vertical_source_demo",
                "name": "Vertical Source Demo",
                "version": "0.1.0",
                "entrypoint": "src.handler:predict",
                "developer": "Demo Developer",
                "developer_organization": "Demo Institute",
                "mentor_team": "Demo Mentor Group",
                "source_url": "https://example.org/model",
                "citation": "Demo Developer, Vertical Source Demo.",
                "input_schema": '{"fields":{"smiles":"string"},"required":["smiles"]}',
                "output_schema": '{"fields":{"prediction":"object"},"required":["prediction"]}',
                "sample_input": '{"smiles":"CCO"}',
            },
            files=[("files", ("handler.py", handler_source, "text/x-python"))],
        )
        self.assertEqual(pack_resp.status_code, 200, pack_resp.text)
        version_id = pack_resp.json()["data"]["version_id"]

        versions_resp = self.client.get(f"{self.base_url}/algorithms/vertical_source_demo/versions")
        self.assertEqual(versions_resp.status_code, 200, versions_resp.text)
        version = next(item for item in versions_resp.json()["data"]["items"] if item["version_id"] == version_id)
        self.assertEqual(version["developer_attribution"]["name"], "Demo Developer")
        self.assertEqual(version["developer_attribution"]["organization"], "Demo Institute")
        self.assertEqual(version["mentor_team"], "Demo Mentor Group")
        self.assertEqual(version["developer_attribution"]["url"], "https://example.org/model")
        self.assertIn("overview", version["algorithm_summary"])
        self.assertTrue(version["algorithm_summary"]["highlights"])
        self.assertTrue(version["algorithm_summary"]["practices"])

    def test_multipart_algorithm_run_registers_input_and_output_artifacts(self) -> None:
        """v0.2 文件型算法可通过 multipart 输入文件并登记输出 artifact。"""
        buffer = io.BytesIO()
        contract = """contract_version: "0.2"
algorithm_id: spectrum_file_demo
name: Spectrum File Demo
version: 0.1.0
algorithm_family: vertical_prediction
type: predictor
material_scope:
  - universal
task_scope:
  - COMPUTE_PREDICT
trigger_modes:
  - human_workflow
entrypoint: src.handler:predict
runtime:
  python: "3.11"
  resources:
    cpu: 1
    memory: 1Gi
    gpu: false
  timeout_seconds: 30
input_schema:
  fields:
    x0: number
    x1: number
  required:
    - x0
    - x1
output_schema:
  fields:
    candidates: list
  required:
    - candidates
input_assets:
  - key: spectrum_file
    label: Spectrum file
    required: true
    data_kind: series
    parser: series_xy.v1
    mime_types:
      - text/plain
      - text/csv
    extensions:
      - .txt
      - .csv
      - .dat
    max_size_bytes: 2048
    sample_path: tests/sample_assets/spectrum.txt
output_assets:
  - key: parsed_spectrum
    artifact_type: spectrum_json
    mime_type: application/json
result_envelope: polyagent_run_result.v1
sample_input_path: tests/sample_input.json
developer: Demo Developer
developer_organization: Demo Institute
"""
        handler = b"""
from __future__ import annotations

import json
from pathlib import Path


def predict(inputs, context=None, model=None):
    context = context or {}
    parsed = context["parsed_inputs"]["spectrum_file"]
    points = parsed["data"]["points"]
    output_dir = Path(context["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed_path = output_dir / "parsed_spectrum.json"
    parsed_path.write_text(json.dumps({
        "kind": "xy",
        "x_label": "Raman shift",
        "y_label": "Intensity",
        "points": points,
    }, ensure_ascii=False), encoding="utf-8")
    return {
        "output_summary": {
            "candidates": [{"structure": "CCO", "score": 0.91}],
            "point_count": len(points),
        },
        "artifacts": [
            {
                "key": "parsed_spectrum",
                "path": "parsed_spectrum.json",
                "artifact_type": "spectrum_json",
                "mime_type": "application/json",
            }
        ],
    }
"""
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("polyagent.algorithm.yaml", contract)
            zf.writestr("requirements.txt", "")
            zf.writestr("src/handler.py", handler)
            zf.writestr("tests/sample_input.json", '{"x0": 100, "x1": 1800}')
            zf.writestr("tests/sample_assets/spectrum.txt", "100 0.1\n200 0.8\n300 0.3\n")

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("spectrum-demo.zip", buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package_id = upload_resp.json()["data"]["package_id"]
        validate_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:validate")
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        version_id = validate_resp.json()["data"]["version_id"]
        version_resp = self.client.get(f"{self.base_url}/algorithms/spectrum_file_demo/versions")
        version = next(item for item in version_resp.json()["data"]["items"] if item["version_id"] == version_id)
        self.assertEqual(version["input_assets"][0]["key"], "spectrum_file")
        self.assertEqual(version["output_assets"][0]["artifact_type"], "spectrum_json")

        self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:build")
        self.client.post(f"{self.base_url}/algorithms/spectrum_file_demo/versions/{version_id}:deploy")
        self.client.post(f"{self.base_url}/algorithms/spectrum_file_demo/versions/{version_id}:activate")

        run_resp = self.client.post(
            f"{self.base_url}/algorithm-runs:multipart",
            data={
                "payload": json.dumps(
                    {
                        "algorithm_id": "spectrum_file_demo",
                        "trigger_source": "human_workflow",
                        "algorithm_version_id": version_id,
                        "input_snapshot": {"x0": 100, "x1": 1800},
                    }
                )
            },
            files={"spectrum_file": ("run_spectrum.txt", b"100 0.2\n200 0.9\n", "text/plain")},
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        run = run_resp.json()["data"]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["output_summary"]["point_count"], 2)
        self.assertEqual(len(run["artifact_refs"]), 3)
        artifact_types = {item["artifact_type"] for item in run["artifact_refs"]}
        self.assertEqual(artifact_types, {"input_file", "series_json", "spectrum_json"})

        artifacts_resp = self.client.get(f"{self.base_url}/algorithm-runs/{run['run_id']}/artifacts")
        self.assertEqual(artifacts_resp.status_code, 200, artifacts_resp.text)
        artifacts = artifacts_resp.json()["data"]["items"]
        parsed_artifact = next(item for item in artifacts if item["artifact_type"] == "series_json")
        self.assertEqual(parsed_artifact["owner_type"], "algorithm_run")
        parsed_preview_resp = self.client.get(f"/api/v1/artifacts/{parsed_artifact['artifact_id']}/preview")
        self.assertEqual(parsed_preview_resp.status_code, 200, parsed_preview_resp.text)
        self.assertEqual(parsed_preview_resp.json()["data"]["preview"]["data_kind"], "series")
        parsed_spectrum_resp = self.client.get(f"/api/v1/artifacts/{parsed_artifact['artifact_id']}/spectrum")
        self.assertEqual(parsed_spectrum_resp.status_code, 200, parsed_spectrum_resp.text)
        self.assertEqual(len(parsed_spectrum_resp.json()["data"]["spectrum"]["points"]), 2)
        spectrum_artifact = next(item for item in artifacts if item["artifact_type"] == "spectrum_json")
        self.assertEqual(spectrum_artifact["owner_type"], "algorithm_run")
        self.assertEqual(spectrum_artifact["owner_id"], run["run_id"])

        preview_resp = self.client.get(f"/api/v1/artifacts/{spectrum_artifact['artifact_id']}/preview")
        self.assertEqual(preview_resp.status_code, 200, preview_resp.text)
        self.assertEqual(preview_resp.json()["data"]["preview"]["kind"], "xy")

        spectrum_resp = self.client.get(f"/api/v1/artifacts/{spectrum_artifact['artifact_id']}/spectrum")
        self.assertEqual(spectrum_resp.status_code, 200, spectrum_resp.text)
        self.assertEqual(len(spectrum_resp.json()["data"]["spectrum"]["points"]), 2)

    def test_v02_package_validation_requires_declared_sample_asset(self) -> None:
        """required input asset 没有 sample 文件时校验失败。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "polyagent.algorithm.yaml",
                """contract_version: "0.2"
algorithm_id: missing_sample_asset_demo
name: Missing Sample Asset Demo
version: 0.1.0
algorithm_family: vertical_prediction
type: predictor
material_scope:
  - universal
task_scope:
  - COMPUTE_PREDICT
trigger_modes:
  - human_workflow
entrypoint: src.handler:predict
runtime:
  python: "3.11"
  resources:
    cpu: 1
    memory: 1Gi
    gpu: false
  timeout_seconds: 30
input_schema:
  fields: {}
  required: []
output_schema:
  fields:
    ok: boolean
  required:
    - ok
input_assets:
  - key: spectrum_file
    required: true
    sample_path: tests/sample_assets/spectrum.txt
sample_input_path: tests/sample_input.json
""",
            )
            zf.writestr("src/handler.py", "def predict(inputs, context=None, model=None):\n    return {'ok': True}\n")
            zf.writestr("tests/sample_input.json", "{}")

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("missing-sample.zip", buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        validate_resp = self.client.post(
            f"{self.base_url}/algorithm-packages/{upload_resp.json()['data']['package_id']}:validate"
        )
        self.assertEqual(validate_resp.status_code, 422)
        self.assertIn("sample asset", validate_resp.text)

    def test_v02_resource_asset_requires_env_binding(self) -> None:
        """resource_assets.env_var 缺失时校验失败且不创建版本。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "polyagent.algorithm.yaml",
                """contract_version: "0.2"
algorithm_id: missing_resource_env_demo
name: Missing Resource Env Demo
version: 0.1.0
algorithm_family: vertical_prediction
type: predictor
material_scope:
  - universal
task_scope:
  - COMPUTE_PREDICT
trigger_modes:
  - human_workflow
entrypoint: src.handler:predict
runtime:
  python: "3.11"
  resources:
    cpu: 1
    memory: 1Gi
    gpu: false
  timeout_seconds: 30
input_schema:
  fields: {}
  required: []
output_schema:
  fields:
    ok: boolean
  required:
    - ok
resource_assets:
  - key: model_weights
    required: true
    env_var: MODEL_WEIGHTS_ROOT
sample_input_path: tests/sample_input.json
""",
            )
            zf.writestr("src/handler.py", "def predict(inputs, context=None, model=None):\n    return {'ok': True}\n")
            zf.writestr("tests/sample_input.json", "{}")

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("missing-resource-env.zip", buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        with patch.dict("os.environ", {}, clear=True):
            validate_resp = self.client.post(
                f"{self.base_url}/algorithm-packages/{upload_resp.json()['data']['package_id']}:validate"
            )
        self.assertEqual(validate_resp.status_code, 422)
        self.assertIn("MODEL_WEIGHTS_ROOT", validate_resp.text)

    def test_algorithm_resource_registers_mounted_path_and_lists_it(self) -> None:
        """可登记合法 mounted_path 算法大资源并按 key 查询。"""
        resource_dir = self.runtime_root / "algorithm-resources" / "managed-resource-demo"
        resource_dir.mkdir(parents=True)
        (resource_dir / "ready.txt").write_text("ok", encoding="utf-8")

        create_resp = self.client.post(
            f"{self.base_url}/algorithm-resources",
            json={
                "algorithm_id": "managed_resource_demo",
                "asset_key": "model_weights",
                "name": "Managed Resource Demo Weights",
                "path": str(resource_dir),
                "resource_type": "checkpoints",
                "required_files": ["ready.txt"],
            },
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        resource = create_resp.json()["data"]
        self.assertTrue(resource["resource_id"].startswith("ares_"))
        self.assertEqual(resource["status"], "active")

        list_resp = self.client.get(
            f"{self.base_url}/algorithm-resources",
            params={"algorithm_id": "managed_resource_demo", "asset_key": "model_weights"},
        )
        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        self.assertEqual(list_resp.json()["data"]["total"], 1)
        self.assertEqual(list_resp.json()["data"]["items"][0]["resource_id"], resource["resource_id"])

    def test_raman_runtime_resource_uses_service_default_path(self) -> None:
        """Raman 包未显式绑定时可使用服务机器上的默认 mounted resource 根目录。"""
        resource_root = self.runtime_root / "raman-service-resources" / "raman"
        (resource_root / "checkpoints").mkdir(parents=True)
        (resource_root / "checkpoints" / "baseline_removal.pth").write_text("ok", encoding="utf-8")
        (resource_root / "checkpoints" / "raman_fg.pth").write_text("ok", encoding="utf-8")

        contract = {
            "algorithm_id": "raman_structure_analyzer",
            "resource_assets": [
                {
                    "key": "raman_runtime_resources",
                    "required": True,
                    "binding_required": True,
                    "env_var": "RAMAN_RESOURCES_ROOT",
                    "required_files": [
                        "checkpoints/baseline_removal.pth",
                        "checkpoints/raman_fg.pth",
                    ],
                }
            ],
        }
        with patch(
            "app.services.algorithm_resource_service.RAMAN_RUNTIME_RESOURCE_DEFAULT_PATHS",
            (resource_root,),
        ), patch.dict("os.environ", {}, clear=True):
            resource_context, bindings = AlgorithmManagedResourceService().resolve_resource_context(contract)

        self.assertEqual(bindings, [])
        self.assertEqual(resource_context["raman_runtime_resources"]["path"], str(resource_root.resolve()))
        self.assertEqual(resource_context["raman_runtime_resources"]["storage_mode"], "mounted_path")

    def test_raman_runtime_resource_uses_default_env_without_contract_env_var(self) -> None:
        """Raman 新契约未写 env_var 时仍可用 RAMAN_RESOURCES_ROOT 覆盖坏默认路径。"""
        broken_default_root = self.runtime_root / "broken-raman-service-resources" / "raman"
        (broken_default_root / "checkpoints").mkdir(parents=True)
        (broken_default_root / "checkpoints" / "baseline_removal.pth").write_text("ok", encoding="utf-8")

        resource_root = self.runtime_root / "env-raman-service-resources" / "raman"
        (resource_root / "checkpoints").mkdir(parents=True)
        (resource_root / "checkpoints" / "baseline_removal.pth").write_text("ok", encoding="utf-8")
        (resource_root / "checkpoints" / "raman_fg.pth").write_text("ok", encoding="utf-8")

        contract = {
            "algorithm_id": "raman_structure_analyzer",
            "resource_assets": [
                {
                    "key": "raman_runtime_resources",
                    "required": False,
                    "binding_required": False,
                    "required_files": [
                        "checkpoints/baseline_removal.pth",
                        "checkpoints/raman_fg.pth",
                    ],
                }
            ],
        }
        with patch(
            "app.services.algorithm_resource_service.RAMAN_RUNTIME_RESOURCE_DEFAULT_PATHS",
            (broken_default_root,),
        ), patch.dict(
            "os.environ",
            {
                "RAMAN_RESOURCES_ROOT": str(resource_root),
                "POLYAGENT_ALGORITHM_RESOURCE_ROOTS": str(self.runtime_root),
            },
            clear=True,
        ):
            resource_context, bindings = AlgorithmManagedResourceService().resolve_resource_context(contract)

        self.assertEqual(bindings, [])
        self.assertEqual(resource_context["raman_runtime_resources"]["path"], str(resource_root.resolve()))
        self.assertEqual(resource_context["raman_runtime_resources"]["storage_mode"], "env_var")

    def test_algorithm_resource_rejects_invalid_path_missing_files_and_non_admin_create(self) -> None:
        """路径越界、必需文件缺失和非管理员登记都会被拒绝。"""
        outside = self.runtime_root / "outside-resource-root"
        outside.mkdir(parents=True)
        outside_resp = self.client.post(
            f"{self.base_url}/algorithm-resources",
            json={
                "algorithm_id": "managed_resource_demo",
                "asset_key": "model_weights",
                "name": "Outside Resource",
                "path": str(outside),
            },
        )
        self.assertEqual(outside_resp.status_code, 422)
        self.assertIn("允许的资源目录", outside_resp.text)

        resource_dir = self.runtime_root / "algorithm-resources" / "missing-required"
        resource_dir.mkdir(parents=True)
        missing_file_resp = self.client.post(
            f"{self.base_url}/algorithm-resources",
            json={
                "algorithm_id": "managed_resource_demo",
                "asset_key": "model_weights",
                "name": "Missing Required File",
                "path": str(resource_dir),
                "required_files": ["ready.txt"],
            },
        )
        self.assertEqual(missing_file_resp.status_code, 422)
        self.assertIn("缺少必需文件", missing_file_resp.text)

        try:
            app.dependency_overrides[get_current_user] = lambda: {
                "user_id": "normal_user",
                "username": "normal_user",
                "role": "user",
            }
            forbidden_resp = self.client.post(
                f"{self.base_url}/algorithm-resources",
                json={
                    "algorithm_id": "managed_resource_demo",
                    "asset_key": "model_weights",
                    "name": "User Resource",
                    "path": str(resource_dir),
                },
            )
            self.assertEqual(forbidden_resp.status_code, 403)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_package_validate_and_active_run_use_version_resource_binding(self) -> None:
        """正式校验保存资源绑定，active 运行不依赖 env var 也能注入大资源路径。"""
        resource_dir = self.runtime_root / "algorithm-resources" / "managed-resource-demo"
        resource_dir.mkdir(parents=True)
        (resource_dir / "ready.txt").write_text("ok", encoding="utf-8")
        resource_resp = self.client.post(
            f"{self.base_url}/algorithm-resources",
            json={
                "algorithm_id": "managed_resource_demo",
                "asset_key": "model_weights",
                "name": "Managed Resource Demo Weights",
                "path": str(resource_dir),
                "resource_type": "checkpoints",
                "required_files": ["ready.txt"],
            },
        )
        self.assertEqual(resource_resp.status_code, 200, resource_resp.text)
        resource_id = resource_resp.json()["data"]["resource_id"]

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={
                "file": (
                    "managed-resource-demo.zip",
                    self._managed_resource_package_zip(),
                    "application/zip",
                )
            },
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        upload_data = upload_resp.json()["data"]
        package_id = upload_data["package_id"]
        self.assertEqual(upload_data["algorithm_id"], "managed_resource_demo")
        self.assertEqual(upload_data["version"], "0.1.0")
        self.assertEqual(upload_data["resource_assets"][0]["key"], "model_weights")
        self.assertTrue(upload_data["resource_assets"][0]["binding_required"])
        with patch.dict("os.environ", {}, clear=True):
            validate_resp = self.client.post(
                f"{self.base_url}/algorithm-packages/{package_id}:validate",
                json={"resource_bindings": [{"asset_key": "model_weights", "resource_id": resource_id}]},
            )
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        version_id = validate_resp.json()["data"]["version_id"]

        version_resp = self.client.get(f"{self.base_url}/algorithms/managed_resource_demo/versions")
        self.assertEqual(version_resp.status_code, 200, version_resp.text)
        self.assertEqual(
            version_resp.json()["data"]["items"][0]["resource_bindings"],
            [{"asset_key": "model_weights", "resource_id": resource_id}],
        )

        build_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:build")
        self.assertEqual(build_resp.status_code, 200, build_resp.text)
        deploy_resp = self.client.post(
            f"{self.base_url}/algorithms/managed_resource_demo/versions/{version_id}:deploy"
        )
        self.assertEqual(deploy_resp.status_code, 200, deploy_resp.text)
        activate_resp = self.client.post(
            f"{self.base_url}/algorithms/managed_resource_demo/versions/{version_id}:activate"
        )
        self.assertEqual(activate_resp.status_code, 200, activate_resp.text)

        with patch.dict("os.environ", {}, clear=True):
            run_resp = self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": "managed_resource_demo",
                    "trigger_source": "human_workflow",
                    "input_snapshot": {},
                },
            )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        run_data = run_resp.json()["data"]
        self.assertEqual(run_data["status"], "completed")
        self.assertTrue(run_data["output_summary"]["resource_ready"])
        self.assertEqual(run_data["output_summary"]["resource_id"], resource_id)

    def test_handoff_self_test_accepts_platform_resource_binding_without_env(self) -> None:
        """handoff 自测可通过 resource_bindings 使用平台已登记大资源。"""
        resource_dir = self.runtime_root / "algorithm-resources" / "managed-handoff-resource"
        resource_dir.mkdir(parents=True)
        (resource_dir / "ready.txt").write_text("ok", encoding="utf-8")
        resource_resp = self.client.post(
            f"{self.base_url}/algorithm-resources",
            json={
                "algorithm_id": "managed_resource_handoff_demo",
                "asset_key": "model_weights",
                "name": "Managed Handoff Weights",
                "path": str(resource_dir),
                "required_files": ["ready.txt"],
            },
        )
        self.assertEqual(resource_resp.status_code, 200, resource_resp.text)
        resource_id = resource_resp.json()["data"]["resource_id"]

        create_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs",
            json={
                "algorithm_id": "managed_resource_handoff_demo",
                "name": "Managed Resource Handoff Demo",
                "version": "0.1.0",
                "example_id": "generic_python_predictor",
                "input_schema": {"fields": {}, "required": []},
                "output_schema": {
                    "fields": {"resource_ready": "boolean", "resource_id": "string"},
                    "required": ["resource_ready"],
                },
                "sample_input": {},
            },
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        handoff_id = create_resp.json()["data"]["handoff_id"]

        with patch.dict("os.environ", {}, clear=True):
            validate_resp = self.client.post(
                f"{self.base_url}/algorithm-handoffs/{handoff_id}:validate",
                data={
                    "resource_bindings": json.dumps([
                        {"asset_key": "model_weights", "resource_id": resource_id}
                    ])
                },
                files={
                    "file": (
                        "managed-resource-handoff.zip",
                        self._managed_resource_package_zip("managed_resource_handoff_demo"),
                        "application/zip",
                    )
                },
            )
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        validation = validate_resp.json()["data"]
        self.assertTrue(validation["ok"], validation)
        self.assertEqual(validation["output_preview"]["resource_id"], resource_id)

    def test_v02_resource_asset_rejects_path_outside_allowed_roots(self) -> None:
        """resource_assets.env_var 指向非允许目录时校验失败。"""
        outside = self.runtime_root / "outside-resources"
        outside.mkdir(parents=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "polyagent.algorithm.yaml",
                """contract_version: "0.2"
algorithm_id: outside_resource_env_demo
name: Outside Resource Env Demo
version: 0.1.0
algorithm_family: vertical_prediction
type: predictor
material_scope:
  - universal
task_scope:
  - COMPUTE_PREDICT
trigger_modes:
  - human_workflow
entrypoint: src.handler:predict
runtime:
  python: "3.11"
  resources:
    cpu: 1
    memory: 1Gi
    gpu: false
  timeout_seconds: 30
input_schema:
  fields: {}
  required: []
output_schema:
  fields:
    ok: boolean
  required:
    - ok
resource_assets:
  - key: model_weights
    required: true
    env_var: MODEL_WEIGHTS_ROOT
sample_input_path: tests/sample_input.json
""",
            )
            zf.writestr("src/handler.py", "def predict(inputs, context=None, model=None):\n    return {'ok': True}\n")
            zf.writestr("tests/sample_input.json", "{}")

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("outside-resource-env.zip", buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        with patch.dict("os.environ", {"MODEL_WEIGHTS_ROOT": str(outside)}, clear=True):
            validate_resp = self.client.post(
                f"{self.base_url}/algorithm-packages/{upload_resp.json()['data']['package_id']}:validate"
            )
        self.assertEqual(validate_resp.status_code, 422)
        self.assertIn("允许的资源目录", validate_resp.text)

    def test_upload_rejects_zip_path_traversal_on_validate(self) -> None:
        """ZIP 路径穿越在校验阶段被拒绝。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("../evil.py", "print('bad')")
            zf.writestr("polyagent.algorithm.yaml", "contract_version: '0.1'\n")

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("bad.zip", buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package_id = upload_resp.json()["data"]["package_id"]

        validate_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:validate")
        self.assertEqual(validate_resp.status_code, 422)

        detail_resp = self.client.get(f"{self.base_url}/algorithm-packages/{package_id}")
        self.assertEqual(detail_resp.json()["data"]["status"], "validation_failed")

    def test_targeted_version_upload_rejects_mismatched_algorithm_id(self) -> None:
        self._pack_activate_simple_algorithm("vertical_tg_predictor_demo")
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        mismatched_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(template_resp.content)) as source_zip:
            with zipfile.ZipFile(
                mismatched_buffer, "w", compression=zipfile.ZIP_DEFLATED
            ) as target_zip:
                for member in source_zip.infolist():
                    if member.is_dir():
                        continue
                    content = source_zip.read(member.filename)
                    if member.filename == "polyagent.algorithm.yaml":
                        contract = yaml.safe_load(content)
                        contract["algorithm_id"] = "another_algorithm"
                        content = yaml.safe_dump(
                            contract, allow_unicode=True, sort_keys=False
                        ).encode("utf-8")
                    target_zip.writestr(member, content)
        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "vertical_tg_predictor_demo"},
            files={
                "file": (
                    "mismatch.zip",
                    mismatched_buffer.getvalue(),
                    "application/zip",
                )
            },
        )

        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package_id = upload_resp.json()["data"]["package_id"]
        validate_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:validate")

        self.assertEqual(validate_resp.status_code, 409)
        self.assertIn("目标算法 ID", validate_resp.text)

    def test_targeted_version_upload_requires_an_active_target(self) -> None:
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "missing_algorithm"},
            files={"file": ("missing.zip", template_resp.content, "application/zip")},
        )

        self.assertEqual(upload_resp.status_code, 409)
        self.assertIn("活动版本", upload_resp.text)

    def test_targeted_version_upload_rejects_explicit_visibility(self) -> None:
        """新版本 ZIP 上传显式传 visibility 时返回 422，YAML 为唯一来源且不落库。"""
        self._pack_activate_simple_algorithm("vertical_tg_predictor_demo")
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        before_resp = self.client.get(
            f"{self.base_url}/algorithm-packages", params={"page_size": 100}
        )
        before_total = before_resp.json()["data"]["total"]

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={
                "target_algorithm_id": "vertical_tg_predictor_demo",
                "visibility": "public",
            },
            files={"file": ("first.zip", template_resp.content, "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 422, upload_resp.text)
        self.assertIn("不允许单独指定", upload_resp.text)

        after_resp = self.client.get(
            f"{self.base_url}/algorithm-packages", params={"page_size": 100}
        )
        self.assertEqual(after_resp.json()["data"]["total"], before_total)

    def test_targeted_version_upload_registers_zip_yaml_version(self) -> None:
        """新版 ZIP 上传以包内 YAML 的 version 登记，不再被表单值覆盖。"""
        self._pack_activate_simple_algorithm("vertical_tg_predictor_demo")
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "vertical_tg_predictor_demo"},
            files={
                "file": (
                    "first.zip",
                    self._template_zip_with_version(template_resp.content, "0.1.1"),
                    "application/zip",
                )
            },
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package = upload_resp.json()["data"]
        self.assertEqual(package["version"], "0.1.1")
        download_resp = self.client.get(
            f"{self.base_url}/algorithm-packages/{package['package_id']}/download"
        )
        with zipfile.ZipFile(io.BytesIO(download_resp.content)) as archive:
            contract = yaml.safe_load(archive.read("polyagent.algorithm.yaml"))
        self.assertEqual(contract["version"], "0.1.1")
        validate_resp = self.client.post(
            f"{self.base_url}/algorithm-packages/{package['package_id']}:validate"
        )
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)

    def test_targeted_zip_upload_visibility_comes_from_yaml(self) -> None:
        """新版本 ZIP 上传的 visibility 以包内 YAML 为准：public 生效，缺失默认 private。"""
        self._pack_activate_simple_algorithm("vertical_tg_predictor_demo")
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")

        def zip_with_visibility(value: str | None, version: str = "0.1.1") -> bytes:
            buffer = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(template_resp.content)) as source_zip:
                with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                    for member in source_zip.infolist():
                        if member.is_dir():
                            continue
                        content = source_zip.read(member.filename)
                        if member.filename == "polyagent.algorithm.yaml":
                            contract = yaml.safe_load(content)
                            contract["version"] = version
                            if value is None:
                                contract.pop("visibility", None)
                            else:
                                contract["visibility"] = value
                            content = yaml.safe_dump(
                                contract, allow_unicode=True, sort_keys=False
                            ).encode("utf-8")
                        target_zip.writestr(member, content)
            return buffer.getvalue()

        public_upload = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "vertical_tg_predictor_demo"},
            files={"file": ("public.zip", zip_with_visibility("public"), "application/zip")},
        )
        self.assertEqual(public_upload.status_code, 200, public_upload.text)
        public_package = public_upload.json()["data"]
        self.assertEqual(public_package["visibility"], "public")
        public_validate = self.client.post(
            f"{self.base_url}/algorithm-packages/{public_package['package_id']}:validate"
        )
        self.assertEqual(public_validate.status_code, 200, public_validate.text)
        self.assertEqual(public_validate.json()["data"]["visibility"], "public")

        private_upload = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "vertical_tg_predictor_demo"},
            files={
                "file": (
                    "missing.zip",
                    zip_with_visibility(None, version="0.1.2"),
                    "application/zip",
                )
            },
        )
        self.assertEqual(private_upload.status_code, 200, private_upload.text)
        private_package = private_upload.json()["data"]
        self.assertEqual(private_package["visibility"], "private")
        private_validate = self.client.post(
            f"{self.base_url}/algorithm-packages/{private_package['package_id']}:validate"
        )
        self.assertEqual(private_validate.status_code, 200, private_validate.text)
        self.assertEqual(private_validate.json()["data"]["visibility"], "private")

    def test_targeted_version_upload_rejects_duplicate_semantic_version(self) -> None:
        """相同 YAML version 的 ZIP 二次上传在校验阶段返回 409。"""
        self._pack_activate_simple_algorithm("vertical_tg_predictor_demo")
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        first_upload = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "vertical_tg_predictor_demo"},
            files={
                "file": (
                    "first.zip",
                    self._template_zip_with_version(template_resp.content, "0.1.1"),
                    "application/zip",
                )
            },
        )
        first_package_id = first_upload.json()["data"]["package_id"]
        first_validate = self.client.post(
            f"{self.base_url}/algorithm-packages/{first_package_id}:validate"
        )
        self.assertEqual(first_validate.status_code, 200, first_validate.text)

        second_upload = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "vertical_tg_predictor_demo"},
            files={
                "file": (
                    "second.zip",
                    self._template_zip_with_version(template_resp.content, "0.1.1"),
                    "application/zip",
                )
            },
        )
        second_package_id = second_upload.json()["data"]["package_id"]
        second_validate = self.client.post(
            f"{self.base_url}/algorithm-packages/{second_package_id}:validate"
        )

        self.assertEqual(second_validate.status_code, 409)
        self.assertIn("语义版本", second_validate.text)

    def test_inspect_algorithm_package_returns_contract_metadata(self) -> None:
        """只读 inspect 返回契约元数据，不落库。"""
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        inspect_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("template.zip", template_resp.content, "application/zip")},
        )
        self.assertEqual(inspect_resp.status_code, 200, inspect_resp.text)
        data = inspect_resp.json()["data"]
        self.assertEqual(data["algorithm_id"], "vertical_tg_predictor_demo")
        self.assertEqual(data["name"], "Polymer Tg Predictor Demo")
        self.assertEqual(data["version"], "0.1.0")
        self.assertEqual(data["contract_version"], "0.1")
        self.assertEqual(data["visibility"], "private")

    def test_inspect_algorithm_package_returns_yaml_visibility(self) -> None:
        """inspect 返回 YAML 中 visibility：public 正常返回、缺失为 null、非法值 422。"""
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")

        def zip_with_visibility(value: str | None) -> bytes:
            buffer = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(template_resp.content)) as source_zip:
                with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                    for member in source_zip.infolist():
                        if member.is_dir():
                            continue
                        content = source_zip.read(member.filename)
                        if member.filename == "polyagent.algorithm.yaml":
                            contract = yaml.safe_load(content)
                            if value is None:
                                contract.pop("visibility", None)
                            else:
                                contract["visibility"] = value
                            content = yaml.safe_dump(
                                contract, allow_unicode=True, sort_keys=False
                            ).encode("utf-8")
                        target_zip.writestr(member, content)
            return buffer.getvalue()

        public_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("public.zip", zip_with_visibility("public"), "application/zip")},
        )
        self.assertEqual(public_resp.status_code, 200, public_resp.text)
        self.assertEqual(public_resp.json()["data"]["visibility"], "public")

        missing_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("missing.zip", zip_with_visibility(None), "application/zip")},
        )
        self.assertEqual(missing_resp.status_code, 200, missing_resp.text)
        self.assertIsNone(missing_resp.json()["data"]["visibility"])

        invalid_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("invalid.zip", zip_with_visibility("foo"), "application/zip")},
        )
        self.assertEqual(invalid_resp.status_code, 422, invalid_resp.text)
        self.assertIn("visibility", invalid_resp.text)

    def test_inspect_algorithm_package_rejects_invalid_packages(self) -> None:
        """非法 ZIP、缺契约、缺 version、超限与非 zip 后缀返回明确错误。"""
        missing_yaml = io.BytesIO()
        with zipfile.ZipFile(missing_yaml, "w") as zf:
            zf.writestr("src/handler.py", "def predict():\n    return {}\n")
        missing_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("missing.yaml.zip", missing_yaml.getvalue(), "application/zip")},
        )
        self.assertEqual(missing_resp.status_code, 422)
        self.assertIn("缺少", missing_resp.text)

        missing_version = io.BytesIO()
        with zipfile.ZipFile(missing_version, "w") as zf:
            zf.writestr(
                "polyagent.algorithm.yaml",
                'contract_version: "0.1"\nalgorithm_id: demo\nname: Demo\n',
            )
        missing_version_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("no-version.zip", missing_version.getvalue(), "application/zip")},
        )
        self.assertEqual(missing_version_resp.status_code, 422)
        self.assertIn("version", missing_version_resp.text)

        bad_zip_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("bad.zip", b"not-a-real-zip", "application/zip")},
        )
        self.assertEqual(bad_zip_resp.status_code, 422)
        self.assertIn("无法读取算法包契约", bad_zip_resp.text)

        wrong_suffix_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("package.txt", b"x", "text/plain")},
        )
        self.assertEqual(wrong_suffix_resp.status_code, 422)
        self.assertIn("仅支持 .zip", wrong_suffix_resp.text)

        oversize_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:inspect",
            files={"file": ("huge.zip", b"0" * (20 * 1024 * 1024 + 1), "application/zip")},
        )
        self.assertEqual(oversize_resp.status_code, 413)
        self.assertIn("20MB", oversize_resp.text)

    def test_existing_model_id_requires_dedicated_version_upload(self) -> None:
        """其他用户不能借首次上传入口覆盖已有模型 ID。"""
        self._login_as("original-owner")
        self._pack_activate_simple_algorithm("owned_model_demo", visibility="public")
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        replacement = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(template_resp.content)) as source_zip:
            with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                for member in source_zip.infolist():
                    if member.is_dir():
                        continue
                    content = source_zip.read(member.filename)
                    if member.filename == "polyagent.algorithm.yaml":
                        contract = yaml.safe_load(content)
                        contract["algorithm_id"] = "owned_model_demo"
                        contract["version"] = "0.2.0"
                        content = yaml.safe_dump(
                            contract, allow_unicode=True, sort_keys=False
                        ).encode("utf-8")
                    target_zip.writestr(member, content)

        self._login_as("other-user")
        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("duplicate-id.zip", replacement.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)

        validate_resp = self.client.post(
            f"{self.base_url}/algorithm-packages/{upload_resp.json()['data']['package_id']}:validate"
        )
        self.assertEqual(validate_resp.status_code, 409, validate_resp.text)
        validate_body = validate_resp.json()
        self.assertEqual(validate_body["code"], 40901)
        self.assertEqual(validate_body["message"], "conflict")
        self.assertIn("模型 ID", validate_body["data"]["detail"])
        self.assertIn("上传新版本", validate_body["data"]["detail"])

    def test_admin_release_preserves_owner_and_owner_can_rollback(self) -> None:
        """管理员代发新版本不转移归属，原上传者仍可管理并看到回滚状态。"""
        self._login_as("original-owner")
        first_version_id = self._pack_activate_simple_algorithm(
            "admin_release_demo", visibility="public"
        )

        self._login_as("system-admin", role="admin")
        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:pack-version",
            data={"target_algorithm_id": "admin_release_demo", "version": "0.1.1"},
            files={
                "files": (
                    "handler.py",
                    b"def predict(inputs, context=None, model=None):\n    return {'prediction': {'value': 2}}\n",
                    "text/x-python",
                )
            },
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package = upload_resp.json()["data"]
        self.assertEqual(package["created_by"], "original-owner")
        self.assertEqual(package["uploaded_by"], "system-admin")
        self.assertEqual(package["visibility"], "public")

        release_resp = self.client.post(
            f"{self.base_url}/algorithm-packages/{package['package_id']}:release"
        )
        self.assertEqual(release_resp.status_code, 200, release_resp.text)
        released = release_resp.json()["data"]
        self.assertEqual(released["status"], "active")
        self.assertEqual(released["activation_kind"], "release")
        self.assertEqual(released["previous_active_version_id"], first_version_id)
        self.assertEqual(released["created_by"], "original-owner")
        self.assertEqual(released["uploaded_by"], "system-admin")

        registry_resp = self.client.get(f"{self.base_url}/algorithms/admin_release_demo")
        self.assertEqual(registry_resp.json()["data"]["owner"], "original-owner")

        self._login_as("original-owner")
        versions_resp = self.client.get(
            f"{self.base_url}/algorithms/admin_release_demo/versions",
            params={"page_size": 20},
        )
        self.assertEqual(versions_resp.status_code, 200, versions_resp.text)
        self.assertEqual(versions_resp.json()["data"]["total"], 2)

        rollback_resp = self.client.post(
            f"{self.base_url}/algorithms/admin_release_demo/versions/{first_version_id}:rollback"
        )
        self.assertEqual(rollback_resp.status_code, 200, rollback_resp.text)
        rolled_back = rollback_resp.json()["data"]
        self.assertEqual(rolled_back["status"], "active")
        self.assertEqual(rolled_back["activation_kind"], "rollback")
        self.assertEqual(rolled_back["rollback_status"], "completed")
        self.assertEqual(rolled_back["previous_active_version_id"], released["version_id"])

        self._login_as("other-user")
        forbidden_resp = self.client.post(
            f"{self.base_url}/algorithms/admin_release_demo/versions/{released['version_id']}:rollback"
        )
        self.assertEqual(forbidden_resp.status_code, 403, forbidden_resp.text)

    def test_script_version_upload_inherits_active_package_contract(self) -> None:
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        source_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(template_resp.content)) as source_zip:
            with zipfile.ZipFile(source_buffer, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                for member in source_zip.infolist():
                    if not member.is_dir():
                        target_zip.writestr(member, source_zip.read(member.filename))
                target_zip.writestr("models/weights.bin", b"old-weights")
        first_upload = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("first.zip", source_buffer.getvalue(), "application/zip")},
        )
        first_package_id = first_upload.json()["data"]["package_id"]
        first_validate = self.client.post(
            f"{self.base_url}/algorithm-packages/{first_package_id}:validate"
        )
        version_id = first_validate.json()["data"]["version_id"]
        self.client.post(f"{self.base_url}/algorithm-packages/{first_package_id}:build")
        self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{version_id}:deploy"
        )
        self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{version_id}:activate"
        )

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:pack-version",
            data={
                "target_algorithm_id": "vertical_tg_predictor_demo",
                "version": "0.1.1",
            },
            files=[
                (
                    "files",
                    (
                        "handler.py",
                        b"def predict(inputs, context=None, model=None):\n    return {'prediction': {'value': 321}}\n",
                        "text/x-python",
                    ),
                ),
                ("files", ("weights.bin", b"new-weights", "application/octet-stream")),
            ],
        )

        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package = upload_resp.json()["data"]
        self.assertEqual(package["status"], "uploaded")
        self.assertEqual(package["target_algorithm_id"], "vertical_tg_predictor_demo")
        download_resp = self.client.get(
            f"{self.base_url}/algorithm-packages/{package['package_id']}/download"
        )
        with zipfile.ZipFile(io.BytesIO(download_resp.content)) as archive:
            contract = yaml.safe_load(archive.read("polyagent.algorithm.yaml"))
            source = archive.read("src/handler.py")
            weights = archive.read("models/weights.bin")
            self.assertNotIn("weights.bin", archive.namelist())

        self.assertEqual(contract["algorithm_id"], "vertical_tg_predictor_demo")
        self.assertEqual(contract["name"], "Polymer Tg Predictor Demo")
        self.assertEqual(contract["version"], "0.1.1")
        self.assertEqual(contract["visibility"], "private")
        self.assertEqual(contract["input_schema"]["required"], ["smiles"])
        self.assertIn(b"321", source)
        self.assertEqual(weights, b"new-weights")

        self._login_as("other-user", role="user")
        forbidden_resp = self.client.post(
            f"{self.base_url}/algorithm-packages:pack-version",
            data={
                "target_algorithm_id": "vertical_tg_predictor_demo",
                "version": "0.1.2",
            },
            files={
                "files": (
                    "handler.py",
                    b"def predict(inputs, context=None, model=None):\n    return {'prediction': 1}\n",
                    "text/x-python",
                )
            },
        )
        self.assertEqual(forbidden_resp.status_code, 403)

        forbidden_zip_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "vertical_tg_predictor_demo"},
            files={"file": ("forbidden.zip", template_resp.content, "application/zip")},
        )
        self.assertEqual(forbidden_zip_resp.status_code, 403)

    def test_upload_rejects_zip_symlink_on_validate(self) -> None:
        """ZIP 符号链接在校验阶段被拒绝。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            link = zipfile.ZipInfo("src/link.py")
            link.external_attr = (0o120777 << 16)
            zf.writestr(link, "target.py")
            zf.writestr("polyagent.algorithm.yaml", "contract_version: '0.1'\n")

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("symlink.zip", buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package_id = upload_resp.json()["data"]["package_id"]

        validate_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:validate")
        self.assertEqual(validate_resp.status_code, 422)
        self.assertIn("符号链接", validate_resp.text)

    def test_build_rejects_unauthorized_requirements_source(self) -> None:
        """requirements.txt 外部 URL/可编辑来源在构建阶段被拒绝。"""
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(template_resp.content)) as source_zip:
            with zipfile.ZipFile(buffer, "w") as target_zip:
                for member in source_zip.infolist():
                    content = source_zip.read(member.filename)
                    if member.filename == "requirements.txt":
                        content = b"demo @ https://example.invalid/demo.tar.gz\n"
                    target_zip.writestr(member, content)

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("bad-requirements.zip", buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        package_id = upload_resp.json()["data"]["package_id"]
        validate_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:validate")
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)

        build_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:build")
        self.assertEqual(build_resp.status_code, 422)
        self.assertIn("未授权依赖来源", build_resp.text)

    def test_version_activation_freeze_and_decommission_govern_new_runs(self) -> None:
        """版本切换保持单一 active，冻结和下线版本不能再被显式调用。"""
        template_resp = self.client.get(f"{self.base_url}/algorithm-packages/template")

        first_upload = self.client.post(
            f"{self.base_url}/algorithm-packages",
            files={"file": ("first.zip", template_resp.content, "application/zip")},
        )
        first_package_id = first_upload.json()["data"]["package_id"]
        first_validate = self.client.post(f"{self.base_url}/algorithm-packages/{first_package_id}:validate")
        first_version_id = first_validate.json()["data"]["version_id"]
        self.client.post(f"{self.base_url}/algorithm-packages/{first_package_id}:build")
        self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{first_version_id}:deploy"
        )
        self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{first_version_id}:activate"
        )

        second_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(template_resp.content)) as source_zip:
            with zipfile.ZipFile(second_buffer, "w") as target_zip:
                for member in source_zip.infolist():
                    content = source_zip.read(member.filename)
                    if member.filename == "polyagent.algorithm.yaml":
                        content = content.replace(b"version: 0.1.0", b"version: 0.2.0")
                    target_zip.writestr(member, content)

        second_upload = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"target_algorithm_id": "vertical_tg_predictor_demo"},
            files={"file": ("second.zip", second_buffer.getvalue(), "application/zip")},
        )
        second_package_id = second_upload.json()["data"]["package_id"]
        second_validate = self.client.post(f"{self.base_url}/algorithm-packages/{second_package_id}:validate")
        second_version_id = second_validate.json()["data"]["version_id"]
        self.client.post(f"{self.base_url}/algorithm-packages/{second_package_id}:build")
        self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{second_version_id}:deploy"
        )
        activate_resp = self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{second_version_id}:activate"
        )
        self.assertEqual(activate_resp.status_code, 200, activate_resp.text)

        versions_resp = self.client.get(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions",
            params={"page_size": 20},
        )
        versions = {item["version_id"]: item for item in versions_resp.json()["data"]["items"]}
        self.assertEqual(versions[second_version_id]["status"], "active")
        self.assertEqual(versions[first_version_id]["status"], "deployed_staging")

        freeze_resp = self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{first_version_id}:freeze"
        )
        self.assertEqual(freeze_resp.status_code, 200, freeze_resp.text)
        self.assertEqual(freeze_resp.json()["data"]["status"], "frozen")

        frozen_run = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "vertical_tg_predictor_demo",
                "algorithm_version_id": first_version_id,
                "trigger_source": "human_workflow",
                "input_snapshot": {"smiles": "C=C(F)F"},
            },
        )
        self.assertEqual(frozen_run.status_code, 409, frozen_run.text)

        decommission_resp = self.client.post(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{first_version_id}:decommission"
        )
        self.assertEqual(decommission_resp.status_code, 200, decommission_resp.text)
        self.assertEqual(decommission_resp.json()["data"]["status"], "decommissioned")

        decommissioned_run = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "vertical_tg_predictor_demo",
                "algorithm_version_id": first_version_id,
                "trigger_source": "human_workflow",
                "input_snapshot": {"smiles": "C=C(F)F"},
            },
        )
        self.assertEqual(decommissioned_run.status_code, 409, decommissioned_run.text)

        delete_resp = self.client.delete(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions/{first_version_id}"
        )
        self.assertEqual(delete_resp.status_code, 200, delete_resp.text)
        self.assertTrue(delete_resp.json()["data"]["deleted"])
        self.assertFalse(delete_resp.json()["data"]["registry_deleted"])
        self.assertEqual(delete_resp.json()["data"]["remaining_versions"], 1)

        after_delete_versions_resp = self.client.get(
            f"{self.base_url}/algorithms/vertical_tg_predictor_demo/versions",
            params={"page_size": 20},
        )
        after_delete_versions = {
            item["version_id"]: item for item in after_delete_versions_resp.json()["data"]["items"]
        }
        self.assertNotIn(first_version_id, after_delete_versions)
        self.assertEqual(after_delete_versions[second_version_id]["status"], "active")

        deleted_package_resp = self.client.get(f"{self.base_url}/algorithm-packages/{first_package_id}")
        self.assertEqual(deleted_package_resp.status_code, 404, deleted_package_resp.text)

        active_algorithm_resp = self.client.get(f"{self.base_url}/algorithms/vertical_tg_predictor_demo")
        self.assertEqual(active_algorithm_resp.status_code, 200, active_algorithm_resp.text)
        self.assertEqual(active_algorithm_resp.json()["data"]["active_version_id"], second_version_id)

    def test_algorithm_handoff_generates_prefilled_package_and_self_tests(self) -> None:
        """算法接入任务可生成预填包，并在不正式部署的情况下完成自测。"""
        examples_resp = self.client.get(f"{self.base_url}/algorithm-package-examples")
        self.assertEqual(examples_resp.status_code, 200, examples_resp.text)
        example_ids = [item["example_id"] for item in examples_resp.json()["data"]["items"]]
        self.assertIn("batch_formulation_predictor", example_ids)

        create_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs",
            json={
                "algorithm_id": "electrolyte_formulation_predictor",
                "name": "含氟电解液配方性能预测",
                "version": "0.1.0",
                "example_id": "batch_formulation_predictor",
                "material_scope": ["fluoropolymer"],
                "input_schema": {"fields": {"formulations": "list"}, "required": ["formulations"]},
                "output_schema": {"fields": {"results": "list"}, "required": ["results"]},
                "sample_input": {
                    "formulations": [
                        {
                            "formula_id": "TEST-001",
                            "task_type": "electrolyte",
                            "lithium_salt": "LiTFSI",
                            "lithium_salt_mol_L": 1.0,
                            "electrolyte_component_1": "FEC",
                            "electrolyte_component_1_mol_ratio": 1,
                            "electrolyte_component_2": "DME",
                            "electrolyte_component_2_mol_ratio": 1,
                        }
                    ]
                },
                "requirements_hint": ["rdkit", "scikit-learn", "joblib"],
            },
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        handoff = create_resp.json()["data"]
        handoff_id = handoff["handoff_id"]
        self.assertEqual(handoff["status"], "draft")
        self.assertIsNone(handoff["developer_organization"])
        self.assertEqual(handoff["visibility"], "private")
        self.assertIn(handoff_id, handoff["handoff_url"])

        package_resp = self.client.get(f"{self.base_url}/algorithm-handoffs/{handoff_id}/package")
        self.assertEqual(package_resp.status_code, 200, package_resp.text)
        with zipfile.ZipFile(io.BytesIO(package_resp.content)) as handoff_zip:
            names = set(handoff_zip.namelist())
            self.assertIn("polyagent.algorithm.yaml", names)
            self.assertIn("src/handler.py", names)
            self.assertIn("src/predictor_service.py", names)
            sample_input = handoff_zip.read("tests/sample_input.json").decode("utf-8")
            self.assertIn("TEST-001", sample_input)
            contract = yaml.safe_load(handoff_zip.read("polyagent.algorithm.yaml").decode("utf-8"))
            self.assertEqual(contract["algorithm_id"], "electrolyte_formulation_predictor")
            self.assertEqual(contract["visibility"], "private")
            self.assertNotIn("developer_organization", contract)

        detail_resp = self.client.get(f"{self.base_url}/algorithm-handoffs/{handoff_id}")
        self.assertEqual(detail_resp.json()["data"]["status"], "package_downloaded")

        validate_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs/{handoff_id}:validate",
            files={"file": ("handoff.zip", package_resp.content, "application/zip")},
        )
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        validation = validate_resp.json()["data"]
        self.assertTrue(validation["ok"])
        self.assertEqual(validation["status"], "self_test_passed")
        self.assertIn("results", validation["output_preview"])

        packages_resp = self.client.get(f"{self.base_url}/algorithm-packages")
        self.assertEqual(packages_resp.json()["data"]["total"], 0)

    def test_handoff_form_overrides_uploaded_zip_registration_metadata(self) -> None:
        """正式部署登记信息使用已确认草案，而不是上传 ZIP 中的旧契约信息。"""
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs",
            json={
                "algorithm_id": "revised_handoff_registration_demo",
                "name": "修订后的登记名称",
                "version": "0.3.0",
                "example_id": "batch_formulation_predictor",
                "owner_name": "修订负责人",
                "owner_contact": "revised@example.local",
                "developer_organization": "修订机构",
                "mentor_team": "修订导师课题组",
                "visibility": "public",
                "description": "修订后的登记说明",
                "material_scope": ["fluoropolymer"],
                "input_schema": {"fields": {"formulations": "list"}, "required": ["formulations"]},
                "output_schema": {"fields": {"results": "list"}, "required": ["results"]},
                "sample_input": {
                    "formulations": [
                        {
                            "formula_id": "REVISED-001",
                            "task_type": "electrolyte",
                            "lithium_salt": "LiTFSI",
                            "lithium_salt_mol_L": 1.0,
                            "electrolyte_component_1": "FEC",
                            "electrolyte_component_1_mol_ratio": 1,
                        }
                    ]
                },
            },
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        handoff_id = create_resp.json()["data"]["handoff_id"]
        package_resp = self.client.get(f"{self.base_url}/algorithm-handoffs/{handoff_id}/package")
        self.assertEqual(package_resp.status_code, 200, package_resp.text)

        stale_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(package_resp.content)) as source_zip:
            with zipfile.ZipFile(stale_buffer, "w") as target_zip:
                for member in source_zip.infolist():
                    content = source_zip.read(member.filename)
                    if member.filename == "polyagent.algorithm.yaml":
                        contract = yaml.safe_load(content.decode("utf-8"))
                        contract["algorithm_id"] = "document_stale_algorithm_id"
                        contract["name"] = "文档旧名称"
                        contract["version"] = "0.1.0"
                        contract["description"] = "文档旧说明"
                        contract["developer"] = "文档旧负责人"
                        contract["developer_organization"] = "文档旧机构"
                        contract["mentor_team"] = "文档旧课题组"
                        contract["visibility"] = "private"
                        content = yaml.safe_dump(contract, allow_unicode=True, sort_keys=False).encode("utf-8")
                    elif member.filename == "tests/sample_input.json":
                        content = b'{"smiles":"STALE"}'
                    target_zip.writestr(member, content)

        self_test_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs/{handoff_id}:validate",
            files={"file": ("stale-handoff.zip", stale_buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(self_test_resp.status_code, 200, self_test_resp.text)
        self.assertTrue(self_test_resp.json()["data"]["ok"])
        self.assertIn("REVISED-001", json.dumps(self_test_resp.json()["data"]["output_preview"], ensure_ascii=False))

        upload_resp = self.client.post(
            f"{self.base_url}/algorithm-packages",
            data={"handoff_id": handoff_id},
            files={"file": ("stale-handoff.zip", stale_buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        self.assertEqual(upload_resp.json()["data"]["visibility"], "public")
        package_id = upload_resp.json()["data"]["package_id"]
        validate_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:validate")
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        self.assertEqual(validate_resp.json()["data"]["algorithm_id"], "revised_handoff_registration_demo")
        self.assertEqual(validate_resp.json()["data"]["version"], "0.3.0")

        version_id = validate_resp.json()["data"]["version_id"]
        build_resp = self.client.post(f"{self.base_url}/algorithm-packages/{package_id}:build")
        self.assertEqual(build_resp.status_code, 200, build_resp.text)
        self.client.post(f"{self.base_url}/algorithms/revised_handoff_registration_demo/versions/{version_id}:deploy")
        activate_resp = self.client.post(
            f"{self.base_url}/algorithms/revised_handoff_registration_demo/versions/{version_id}:activate"
        )
        self.assertEqual(activate_resp.status_code, 200, activate_resp.text)

        algorithm_resp = self.client.get(f"{self.base_url}/algorithms/revised_handoff_registration_demo")
        self.assertEqual(algorithm_resp.status_code, 200, algorithm_resp.text)
        algorithm = algorithm_resp.json()["data"]
        self.assertEqual(algorithm["name"], "修订后的登记名称")
        self.assertEqual(algorithm["version"], "0.3.0")
        self.assertEqual(algorithm["visibility"], "public")
        self.assertEqual(algorithm["description"], "修订后的登记说明")
        self.assertEqual(algorithm["developer_attribution"]["name"], "修订负责人")
        self.assertEqual(algorithm["developer_attribution"]["organization"], "修订机构")
        self.assertEqual(algorithm["mentor_team"], "修订导师课题组")
        self.assertNotEqual(algorithm["algorithm_id"], "document_stale_algorithm_id")

    def test_file_based_handoff_generates_raman_asset_package(self) -> None:
        """文件型 Raman 对接包应使用 v0.2 asset 契约，而不是 SMILES 默认模板。"""
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs",
            json={
                "algorithm_id": "raman_structure_analyzer",
                "name": "Raman Structure Analyzer",
                "version": "0.1.0",
                "example_id": "file_based_predictor",
                "material_scope": ["universal"],
                "input_schema": {
                    "fields": {
                        "spectype": "string",
                        "mode": "string",
                        "x0": "number",
                        "x1": "number",
                        "k": "integer",
                        "transmittance": "boolean",
                        "device": "string",
                    },
                    "required": ["spectype", "mode"],
                },
                "output_schema": {
                    "fields": {
                        "candidates": "list",
                        "point_count": "integer",
                        "metadata": "object",
                        "preprocessing": "object",
                    },
                    "required": ["candidates"],
                },
                "sample_input": {
                    "spectype": "raman",
                    "mode": "function_groups",
                    "x0": 400,
                    "x1": 1800,
                    "k": 3,
                    "transmittance": False,
                    "device": "cpu",
                },
                "requirements_hint": ["numpy", "scipy", "torch"],
                "description": "输入 Raman/IR 光谱 x-y 序列和 JSON 参数，输出候选结构。",
            },
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        handoff_id = create_resp.json()["data"]["handoff_id"]

        package_resp = self.client.get(f"{self.base_url}/algorithm-handoffs/{handoff_id}/package")
        self.assertEqual(package_resp.status_code, 200, package_resp.text)
        with zipfile.ZipFile(io.BytesIO(package_resp.content)) as handoff_zip:
            names = set(handoff_zip.namelist())
            self.assertIn("src/raman_core/main.py", names)
            self.assertIn("tests/sample_assets/sample_spectrum.dat", names)
            self.assertNotIn("model/.gitkeep", names)
            requirements = handoff_zip.read("requirements.txt").decode("utf-8")
            self.assertNotIn("scikit-learn", requirements)
            self.assertNotIn("rdkit", requirements)
            self.assertNotIn("transformers", requirements)
            main_source = handoff_zip.read("src/raman_core/main.py").decode("utf-8")
            greedy_source = handoff_zip.read("src/raman_core/greedy_search.py").decode("utf-8")
            self.assertNotIn("from rdkit", main_source)
            self.assertNotIn("from rdkit", "\n".join(greedy_source.splitlines()[:20]))
            self.assertNotIn("from transformers", "\n".join(greedy_source.splitlines()[:20]))
            contract = handoff_zip.read("polyagent.algorithm.yaml").decode("utf-8")
            contract_data = yaml.safe_load(contract)
            self.assertEqual(contract_data["contract_version"], "0.2")
            self.assertNotIn("developer_organization", contract_data)
            self.assertEqual(contract_data["input_assets"][0]["key"], "spectrum_file")
            self.assertEqual(len(contract_data["resource_assets"]), 1)
            self.assertEqual(contract_data["resource_assets"][0]["key"], "raman_runtime_resources")
            self.assertFalse(contract_data["resource_assets"][0]["required"])
            self.assertFalse(contract_data["resource_assets"][0]["binding_required"])
            self.assertIsNone(contract_data["resource_assets"][0]["env_var"])
            self.assertEqual(
                contract_data["resource_assets"][0]["required_files"],
                [
                    "checkpoints/baseline_removal.pth",
                    "checkpoints/raman_fg.pth",
                ],
            )
            sample_input = json.loads(handoff_zip.read("tests/sample_input.json").decode("utf-8"))
            self.assertEqual(sample_input["spectype"], "raman")
            self.assertEqual(sample_input["mode"], "function_groups")
            self.assertEqual(contract_data["input_schema"]["field_options"]["mode"], ["function_groups"])
            self.assertEqual(contract_data["result_envelope"], "polyagent_run_result.v1")

    def test_file_based_handoff_self_test_reports_missing_raman_resources(self) -> None:
        """Raman 对接包自测缺资源时应给出 managed resource 环境变量修复线索。"""
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs",
            json={
                "algorithm_id": "raman_structure_analyzer",
                "name": "Raman Structure Analyzer",
                "version": "0.1.0",
                "example_id": "file_based_predictor",
                "input_schema": {
                    "fields": {"spectype": "string", "mode": "string"},
                    "required": ["spectype", "mode"],
                },
                "output_schema": {
                    "fields": {"candidates": "list"},
                    "required": ["candidates"],
                },
                "sample_input": {"spectype": "raman", "mode": "function_groups"},
                "requirements_hint": ["numpy", "scipy", "torch"],
            },
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        handoff_id = create_resp.json()["data"]["handoff_id"]
        package_resp = self.client.get(f"{self.base_url}/algorithm-handoffs/{handoff_id}/package")
        self.assertEqual(package_resp.status_code, 200, package_resp.text)

        with patch.dict("os.environ", {}, clear=True):
            validate_resp = self.client.post(
                f"{self.base_url}/algorithm-handoffs/{handoff_id}:validate",
                files={"file": ("raman-handoff.zip", package_resp.content, "application/zip")},
            )
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        validation = validate_resp.json()["data"]
        self.assertFalse(validation["ok"])
        self.assertEqual(validation["status"], "self_test_failed")
        messages = " ".join([item["message"] for item in validation["checks"]] + validation["fixes"])
        self.assertIn("missing Raman service resources", messages)
        self.assertIn("RAMAN_RESOURCES_ROOT", messages)
        self.assertNotIn("RAMAN_CHECKPOINTS_ROOT", messages)

    def test_handoff_self_test_uses_v02_file_and_resource_context(self) -> None:
        """handoff 自测应与正式校验一样注入 sample 文件、解析结果和受管资源。"""
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs",
            json={
                "algorithm_id": "resource_file_handoff_demo",
                "name": "Resource File Handoff Demo",
                "version": "0.1.0",
                "example_id": "generic_python_predictor",
                "input_schema": {"fields": {"x0": "number"}, "required": ["x0"]},
                "output_schema": {"fields": {"candidates": "list"}, "required": ["candidates"]},
                "sample_input": {"x0": 100},
            },
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        handoff_id = create_resp.json()["data"]["handoff_id"]

        contract = """contract_version: "0.2"
algorithm_id: resource_file_handoff_demo
name: Resource File Handoff Demo
version: 0.1.0
algorithm_family: vertical_prediction
type: predictor
material_scope:
  - universal
task_scope:
  - COMPUTE_PREDICT
trigger_modes:
  - human_workflow
entrypoint: src.handler:predict
runtime:
  python: "3.11"
  resources:
    cpu: 1
    memory: 1Gi
    gpu: false
  timeout_seconds: 30
input_schema:
  fields:
    x0: number
  required:
    - x0
output_schema:
  fields:
    candidates: list
  required:
    - candidates
input_assets:
  - key: spectrum_file
    required: true
    data_kind: series
    parser: series_xy.v1
    extensions:
      - .dat
    sample_path: tests/sample_assets/sample_spectrum.dat
output_assets:
  - key: parsed_series
    artifact_type: series_json
    mime_type: application/json
resource_assets:
  - key: demo_resource
    required: true
    env_var: DEMO_RESOURCE_ROOT
result_envelope: polyagent_run_result.v1
sample_input_path: tests/sample_input.json
"""
        handler = b"""
from __future__ import annotations

import json
from pathlib import Path


def predict(inputs, context=None, model=None):
    context = context or {}
    resource_path = Path(context["resource_assets"]["demo_resource"]["path"])
    if not (resource_path / "ready.txt").is_file():
        raise RuntimeError("demo resource was not injected")
    points = context["parsed_inputs"]["spectrum_file"]["data"]["points"]
    output_dir = Path(context["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "parsed_series.json").write_text(
        json.dumps({"points": points}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "output_summary": {"candidates": [{"structure": "CCO", "score": 1.0}]},
        "artifacts": [
            {
                "key": "parsed_series",
                "path": "parsed_series.json",
                "artifact_type": "series_json",
                "mime_type": "application/json",
            }
        ],
    }
"""
        package_buffer = io.BytesIO()
        with zipfile.ZipFile(package_buffer, "w") as zf:
            zf.writestr("polyagent.algorithm.yaml", contract)
            zf.writestr("requirements.txt", "")
            zf.writestr("src/handler.py", handler)
            zf.writestr("tests/sample_input.json", '{"x0": 100}')
            zf.writestr("tests/sample_assets/sample_spectrum.dat", "100 0.2\n200 0.9\n")
        package_content = package_buffer.getvalue()

        resource_dir = self.runtime_root / "algorithm-resources" / "resource-file-handoff-demo"
        resource_dir.mkdir(parents=True)
        (resource_dir / "ready.txt").write_text("ok", encoding="utf-8")
        with patch.dict("os.environ", {"DEMO_RESOURCE_ROOT": str(resource_dir)}):
            validate_resp = self.client.post(
                f"{self.base_url}/algorithm-handoffs/{handoff_id}:validate",
                files={"file": ("resource-file-handoff.zip", package_content, "application/zip")},
            )
            upload_resp = self.client.post(
                f"{self.base_url}/algorithm-packages",
                files={"file": ("resource-file-handoff.zip", package_content, "application/zip")},
            )
            formal_validate_resp = self.client.post(
                f"{self.base_url}/algorithm-packages/{upload_resp.json()['data']['package_id']}:validate"
            )

        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        validation = validate_resp.json()["data"]
        self.assertTrue(validation["ok"], validation)
        self.assertEqual(validation["output_preview"]["candidates"][0]["structure"], "CCO")
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        self.assertEqual(formal_validate_resp.status_code, 200, formal_validate_resp.text)

    def test_algorithm_handoff_validation_rewrites_missing_sample_input_from_draft(self) -> None:
        """对接包缺 sample_input 时，自测使用已确认草案补齐。"""
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs",
            json={
                "algorithm_id": "bad_handoff_predictor",
                "name": "Bad Handoff Predictor",
                "example_id": "generic_python_predictor",
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"prediction": "object"}, "required": ["prediction"]},
                "sample_input": {"smiles": "C=C(F)F"},
            },
        )
        handoff_id = create_resp.json()["data"]["handoff_id"]
        package_resp = self.client.get(f"{self.base_url}/algorithm-handoffs/{handoff_id}/package")

        broken_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(package_resp.content)) as source_zip:
            with zipfile.ZipFile(broken_buffer, "w") as target_zip:
                for member in source_zip.infolist():
                    if member.filename == "tests/sample_input.json":
                        continue
                    target_zip.writestr(member, source_zip.read(member.filename))

        validate_resp = self.client.post(
            f"{self.base_url}/algorithm-handoffs/{handoff_id}:validate",
            files={"file": ("broken.zip", broken_buffer.getvalue(), "application/zip")},
        )
        self.assertEqual(validate_resp.status_code, 200, validate_resp.text)
        validation = validate_resp.json()["data"]
        self.assertTrue(validation["ok"], validation)
        self.assertEqual(validation["status"], "self_test_passed")
        self.assertIn("prediction", validation["output_preview"])


class ResearchEngineAccessControlApiTest(ComputationTestCase):
    """覆盖 ResearchEngine ID 直连访问的所有权校验。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        ResearchEngineService().seed_default_algorithms()

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    @staticmethod
    def _login_as(user_id: str, role: str = "user") -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": user_id,
            "username": user_id,
            "role": role,
            "status": "active",
        }

    def _create_owned_research_run(self) -> tuple[str, str, str]:
        self._login_as("user-a")
        ps_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(
                name="用户 A 的 AutoResearch",
                allowed_execution_modes=["autoresearch"],
            ),
        )
        self.assertEqual(ps_resp.status_code, 200)
        ps_id = ps_resp.json()["data"]["problem_spec_id"]

        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "访问控制测试"},
        )
        self.assertEqual(decision_resp.status_code, 200)
        decision_id = decision_resp.json()["data"]["decision_id"]

        run_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": ps_id,
                "execution_decision_id": decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 1,
                "batch_size": 5,
            },
        )
        self.assertEqual(run_resp.status_code, 200)
        run_id = run_resp.json()["data"]["run_id"]
        return ps_id, decision_id, run_id

    def test_id_based_operations_require_owner_or_admin(self) -> None:
        ps_id, _decision_id, run_id = self._create_owned_research_run()

        self._login_as("user-b")
        forbidden_requests = [
            self.client.get(f"{self.base_url}/problem-specs/{ps_id}"),
            self.client.post(f"{self.base_url}/problem-specs/{ps_id}:archive", json={"reason": "try"}),
            self.client.get(f"{self.base_url}/research-runs/{run_id}"),
            self.client.post(f"{self.base_url}/research-runs/{run_id}:archive", json={"reason": "try"}),
            self.client.post(f"{self.base_url}/research-runs/{run_id}/start", json={"target_status": "running", "reason": "try"}),
            self.client.post(f"{self.base_url}/research-runs/{run_id}/advance", json={"target_status": "running", "reason": "try"}),
            self.client.post(f"{self.base_url}/research-runs/{run_id}/pause", json={"target_status": "paused", "reason": "try"}),
            self.client.post(f"{self.base_url}/research-runs/{run_id}/fail", json={"target_status": "failed", "reason": "try"}),
            self.client.get(f"{self.base_url}/research-runs/{run_id}/traceability"),
        ]
        for response in forbidden_requests:
            self.assertEqual(response.status_code, 403, response.text)

        audit_resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_type": "research_run", "entity_id": run_id},
        )
        self.assertEqual(audit_resp.status_code, 200)
        self.assertEqual(audit_resp.json()["data"]["total"], 0)

        self._login_as("user-a")
        start_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "owner start"},
        )
        self.assertEqual(start_resp.status_code, 200)
        gate = next(
            stage
            for stage in start_resp.json()["data"]["stage_runs"]
            if stage["status"] == "blocked_approval"
        )

        self._login_as("user-b")
        approve_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/stages/{gate['stage_run_id']}/approve",
            json={"stage_key": gate["stage_key"], "decision": "approved", "reason": "try"},
        )
        reject_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/stages/{gate['stage_run_id']}/reject",
            json={"stage_key": gate["stage_key"], "decision": "rejected", "reason": "try"},
        )
        self.assertEqual(approve_resp.status_code, 403)
        self.assertEqual(reject_resp.status_code, 403)

        self._login_as("admin", role="admin")
        admin_detail = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        self.assertEqual(admin_detail.status_code, 200)

    def test_list_with_filters(self) -> None:
        """按状态和材料体系过滤。"""
        # 创建一条数据
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(material_family="fluoropolymer"),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        # 查询 fluoropolymer
        resp = self.client.get(f"{self.base_url}/problem-specs?material_family=fluoropolymer")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["data"]["total"], 1)

    def test_get_problem_spec(self) -> None:
        """GET /problem-specs/{id} 获取详情成功。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        resp = self.client.get(f"{self.base_url}/problem-specs/{ps_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["problem_spec_id"], ps_id)

    def test_get_nonexistent_returns_404(self) -> None:
        """不存在的 ProblemSpec 返回 404。"""
        resp = self.client.get(f"{self.base_url}/problem-specs/ps_nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_update_problem_spec(self) -> None:
        """PATCH /problem-specs/{id} 更新草稿成功。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        update_payload = problem_spec_payload(
            name="更新后的任务名",
            allowed_execution_modes=["manual_workbench"],
        )
        resp = self.client.patch(
            f"{self.base_url}/problem-specs/{ps_id}",
            json=update_payload,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["name"], "更新后的任务名")
        self.assertEqual(data["data"]["allowed_execution_modes"], ["manual_workbench"])

    def test_freeze_problem_spec(self) -> None:
        """POST /problem-specs/{id}/freeze 冻结成功。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        resp = self.client.post(f"{self.base_url}/problem-specs/{ps_id}/freeze")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "frozen")
        self.assertEqual(data["data"]["frozen_version"], 1)

    def test_freeze_nonexistent_returns_404(self) -> None:
        """冻结不存在的 ProblemSpec 返回 404。"""
        resp = self.client.post(f"{self.base_url}/problem-specs/ps_nonexistent/freeze")
        self.assertEqual(resp.status_code, 404)

    def test_update_frozen_returns_409(self) -> None:
        """已冻结的 ProblemSpec 不可修改（409）。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        # 冻结
        self.client.post(f"{self.base_url}/problem-specs/{ps_id}/freeze")

        # 尝试更新
        update_payload = problem_spec_payload(name="尝试更新")
        resp = self.client.patch(
            f"{self.base_url}/problem-specs/{ps_id}",
            json=update_payload,
        )
        self.assertEqual(resp.status_code, 409)

    def test_create_with_campaign_id(self) -> None:
        """创建时可关联已有 campaign_id。"""
        payload = problem_spec_payload(campaign_id="camp_001")
        resp = self.client.post(f"{self.base_url}/problem-specs", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["data"]["campaign_id"], "camp_001")

    def test_execution_mode_field_is_rejected(self) -> None:
        """v0.4 不再接受旧 execution_mode 字段。"""
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(execution_mode="hybrid", name="旧字段"),
        )
        self.assertEqual(resp.status_code, 422)


# =============================================================================
# AlgorithmRegistry API 测试
# =============================================================================


class AlgorithmRegistryAutoSeedApiTest(ComputationTestCase):
    """覆盖算法清单 API 的默认种子化行为。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"

    def test_list_algorithms_auto_seeds_empty_registry_with_family(self) -> None:
        """空库首次请求算法清单时自动返回默认算法族。"""
        resp = self.client.get(f"{self.base_url}/algorithms")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 8)
        families = {item.get("algorithm_family") for item in data["data"]["items"]}
        self.assertIn("computation", families)
        self.assertIn("wetlab_optimization", families)
        self.assertIn("vertical_prediction", families)

        filtered = self.client.get(f"{self.base_url}/algorithms?algorithm_family=computation")
        self.assertEqual(filtered.status_code, 200)
        filtered_items = filtered.json()["data"]["items"]
        self.assertGreaterEqual(len(filtered_items), 1)
        self.assertTrue(all(item.get("algorithm_family") == "computation" for item in filtered_items))


class AlgorithmRegistryApiTest(ComputationTestCase):
    """覆盖 AlgorithmRegistry REST API。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        # 写入种子数据
        service = ResearchEngineService()
        service.seed_default_algorithms()

    def test_list_algorithms(self) -> None:
        """GET /algorithms 查询列表成功。"""
        resp = self.client.get(f"{self.base_url}/algorithms")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 8)
        self.assertEqual(data["data"]["page"], 1)

    def test_list_with_type_filter(self) -> None:
        """按类型过滤算法。"""
        resp = self.client.get(f"{self.base_url}/algorithms?type=simulator")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        for item in data["data"]["items"]:
            self.assertEqual(item["type"], "simulator")

    def test_list_with_trigger_mode_filter(self) -> None:
        """按触发方式过滤算法。"""
        resp = self.client.get(f"{self.base_url}/algorithms?trigger_mode=human_workflow")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for item in data["data"]["items"]:
            self.assertIn("human_workflow", item["trigger_modes"])

    def test_list_with_status_filter(self) -> None:
        """按状态过滤算法。"""
        resp = self.client.get(f"{self.base_url}/algorithms?status=active")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for item in data["data"]["items"]:
            self.assertEqual(item["status"], "active")

    def test_list_with_pagination(self) -> None:
        """分页查询算法。"""
        resp = self.client.get(f"{self.base_url}/algorithms?page=1&page_size=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLessEqual(len(data["data"]["items"]), 5)

    def test_get_algorithm_detail(self) -> None:
        """GET /algorithms/{id} 获取详情成功。"""
        resp = self.client.get(f"{self.base_url}/algorithms/literature_mock")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["algorithm_id"], "literature_mock")
        self.assertEqual(data["data"]["type"], "retriever")
        self.assertEqual(data["data"]["name"], "文献检索")
        # 必须有 input_schema 和 output_schema
        self.assertIn("fields", data["data"]["input_schema"])
        self.assertIn("required", data["data"]["input_schema"])
        self.assertIn("fields", data["data"]["output_schema"])

    def test_get_nonexistent_algorithm_returns_404(self) -> None:
        """不存在的算法返回 404。"""
        resp = self.client.get(f"{self.base_url}/algorithms/nonexistent_algo")
        self.assertEqual(resp.status_code, 404)

    def test_all_mock_algorithms_returned(self) -> None:
        """所有 5 个 mock 算法均被返回。"""
        mock_ids = [
            "literature_mock",
            "polymer_descriptor_mock",
            "property_predictor_mock",
            "mobo_mock",
            "computation_submit_adapter",
        ]
        for algo_id in mock_ids:
            resp = self.client.get(f"{self.base_url}/algorithms/{algo_id}")
            self.assertEqual(resp.status_code, 200, f"算法 {algo_id} 未找到")
            self.assertEqual(resp.json()["data"]["algorithm_id"], algo_id)

    def test_all_adapter_algorithms_returned(self) -> None:
        """所有 3 个计算 adapter 算法均被返回。"""
        adapter_ids = [
            "local_structure_adapter",
            "local_xtb_adapter",
            "orca_compute_engine_laser_adapter",
        ]
        for algo_id in adapter_ids:
            resp = self.client.get(f"{self.base_url}/algorithms/{algo_id}")
            self.assertEqual(resp.status_code, 200, f"算法 {algo_id} 未找到")
            self.assertEqual(resp.json()["data"]["algorithm_id"], algo_id)

    def test_algorithm_has_required_display_fields(self) -> None:
        """算法响应包含前端渲染算法卡所需的字段。"""
        resp = self.client.get(f"{self.base_url}/algorithms/property_predictor_mock")
        data = resp.json()["data"]

        required_fields = [
            "algorithm_id", "name", "type", "material_scope",
            "task_scope", "trigger_modes", "status", "version",
            "description", "input_schema", "output_schema",
        ]
        for field in required_fields:
            self.assertIn(field, data, f"缺少字段: {field}")

    def test_literature_mock_schema(self) -> None:
        """文献检索 mock 的 input_schema 包含 keywords 必填字段。"""
        resp = self.client.get(f"{self.base_url}/algorithms/literature_mock")
        data = resp.json()["data"]
        self.assertIn("keywords", data["input_schema"]["required"])
        self.assertIn("knowledge_cards", data["output_schema"]["required"])

    def test_mobo_mock_schema(self) -> None:
        """BO/MOBO mock 的 input_schema 包含 problem_spec_id 必填字段。"""
        resp = self.client.get(f"{self.base_url}/algorithms/mobo_mock")
        data = resp.json()["data"]
        self.assertIn("problem_spec_id", data["input_schema"]["required"])
        self.assertIn("top_k_candidates", data["output_schema"]["required"])

    def test_computation_submit_adapter_schema(self) -> None:
        """计算提交 adapter 的 input_schema 包含 workflow_type 必填字段。"""
        resp = self.client.get(f"{self.base_url}/algorithms/computation_submit_adapter")
        data = resp.json()["data"]
        self.assertIn("workflow_type", data["input_schema"]["required"])
        self.assertIn("computation_run_id", data["output_schema"]["required"])


# =============================================================================
# ExecutionDecision / ManualWorkflow API 测试
# =============================================================================


class ManualWorkflowApiTest(ComputationTestCase):
    """覆盖 v0.4 执行决策和人工 Workflow API。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        service = ResearchEngineService()
        service.seed_default_algorithms()
        ps_resp = self.client.post(f"{self.base_url}/problem-specs", json=problem_spec_payload())
        self.assertEqual(ps_resp.status_code, 200)
        self.ps_id = ps_resp.json()["data"]["problem_spec_id"]

    def test_create_and_get_active_execution_decision(self) -> None:
        """ProblemSpec 可显式选择 manual_workbench。"""
        resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "API 测试人工编排"},
        )
        self.assertEqual(resp.status_code, 200)
        decision = resp.json()["data"]
        self.assertEqual(decision["mode"], "manual_workbench")

        active = self.client.get(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions/active"
        )
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["data"]["decision_id"], decision["decision_id"])

    def test_manual_workflow_run_creates_algorithm_run(self) -> None:
        """单节点人工 WorkflowRun 会创建关联 AlgorithmRun。"""
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "API 测试单节点 workflow"},
        )
        decision_id = decision_resp.json()["data"]["decision_id"]

        workflow_resp = self.client.post(
            f"{self.base_url}/manual-workflows",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": decision_id,
                "name": "API 单节点文献检索",
                "steps": [
                    {
                        "step_id": "s1",
                        "algorithm_id": "literature_mock",
                        "input_bindings": {
                            "keywords": {
                                "source": "manual_input",
                                "value": "氟基高分子 介电常数",
                            }
                        },
                    }
                ],
            },
        )
        self.assertEqual(workflow_resp.status_code, 200)
        workflow_id = workflow_resp.json()["data"]["workflow_id"]

        run_resp = self.client.post(f"{self.base_url}/manual-workflows/{workflow_id}/runs")
        self.assertEqual(run_resp.status_code, 200)
        workflow_run = run_resp.json()["data"]
        self.assertEqual(workflow_run["status"], "completed")
        self.assertEqual(len(workflow_run["step_runs"]), 1)

        aruns = self.client.get(
            f"{self.base_url}/algorithm-runs",
            params={"workflow_run_id": workflow_run["workflow_run_id"]},
        )
        self.assertEqual(aruns.status_code, 200)
        self.assertEqual(aruns.json()["data"]["total"], 1)
        self.assertEqual(aruns.json()["data"]["items"][0]["trigger_source"], "human_workflow")

    def test_archive_manual_workflow_hides_from_default_list(self) -> None:
        """归档人工 Workflow 后默认列表隐藏，按 archived 状态可查。"""
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "API 测试归档 workflow"},
        )
        workflow_resp = self.client.post(
            f"{self.base_url}/manual-workflows",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": decision_resp.json()["data"]["decision_id"],
                "name": "待归档 Workflow",
                "steps": [
                    {
                        "step_id": "s1",
                        "algorithm_id": "literature_mock",
                        "input_bindings": {
                            "keywords": {"source": "manual_input", "value": "polymer"}
                        },
                    }
                ],
            },
        )
        workflow_id = workflow_resp.json()["data"]["workflow_id"]

        archive_resp = self.client.post(
            f"{self.base_url}/manual-workflows/{workflow_id}:archive",
            json={"reason": "API 测试归档"},
        )
        self.assertEqual(archive_resp.status_code, 200)
        self.assertEqual(archive_resp.json()["data"]["status"], "archived")

        default_resp = self.client.get(f"{self.base_url}/manual-workflows")
        default_ids = [item["workflow_id"] for item in default_resp.json()["data"]["items"]]
        self.assertNotIn(workflow_id, default_ids)

        archived_resp = self.client.get(f"{self.base_url}/manual-workflows?status=archived")
        archived_ids = [item["workflow_id"] for item in archived_resp.json()["data"]["items"]]
        self.assertIn(workflow_id, archived_ids)


# =============================================================================
# 现有路由不受影响测试
# =============================================================================


class ExistingRoutesUnaffectedTest(ComputationTestCase):
    """确保新增 ResearchEngine 路由不影响现有 API 端点。"""

    def test_health_endpoint_still_works(self) -> None:
        """Health 端点仍正常响应。"""
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)

    def test_optimization_campaigns_endpoint_still_works(self) -> None:
        """优化 campaign 端点仍正常响应。"""
        resp = self.client.get("/api/v1/optimization/campaigns?page=1&page_size=5")
        self.assertEqual(resp.status_code, 200)

    def test_computations_endpoint_still_works(self) -> None:
        """计算任务端点仍正常响应。"""
        resp = self.client.get("/api/v1/computations?page=1&page_size=5")
        self.assertEqual(resp.status_code, 200)

    def test_integrations_endpoint_still_works(self) -> None:
        """集成配置端点仍正常响应。"""
        resp = self.client.get("/api/v1/integrations/status")
        self.assertEqual(resp.status_code, 200)


# =============================================================================
# AlgorithmRun API 测试
# =============================================================================


class AlgorithmRunApiTest(ComputationTestCase):
    """覆盖 AlgorithmRun REST API。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        # 写入算法种子数据
        service = ResearchEngineService()
        service.seed_default_algorithms()

    def test_create_algorithm_run(self) -> None:
        """POST /algorithm-runs 创建 AlgorithmRun 成功。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "氟基高分子 介电常数"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "completed")
        self.assertTrue(data["data"]["run_id"].startswith("arun_"))
        self.assertIn("knowledge_cards", data["data"]["output_summary"])

    def test_create_all_five_mock_runs(self) -> None:
        """所有 5 个 mock 算法均可通过 API 创建运行。"""
        test_cases = [
            {
                "algorithm_id": "literature_mock",
                "input_snapshot": {"keywords": "氟基高分子"},
            },
            {
                "algorithm_id": "polymer_descriptor_mock",
                "input_snapshot": {"smiles": "C=CF"},
            },
            {
                "algorithm_id": "property_predictor_mock",
                "input_snapshot": {
                    "smiles": "C=C(F)F",
                    "target_properties": ["dielectric_constant", "thermal_stability"],
                },
            },
            {
                "algorithm_id": "mobo_mock",
                "input_snapshot": {
                    "problem_spec_id": "ps_test_001",
                    "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
                },
            },
            {
                "algorithm_id": "computation_submit_adapter",
                "input_snapshot": {
                    "workflow_type": "LOCAL_STRUCTURE",
                    "smiles": "CCO",
                    "name": "ethanol",
                },
            },
        ]

        for tc in test_cases:
            resp = self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": tc["algorithm_id"],
                    "trigger_source": "human_workflow",
                    "input_snapshot": tc["input_snapshot"],
                },
            )
            self.assertEqual(
                resp.status_code, 200,
                f"算法 {tc['algorithm_id']} 创建失败: {resp.json()}",
            )
            data = resp.json()
            self.assertEqual(data["code"], 0)
            self.assertEqual(data["data"]["algorithm_id"], tc["algorithm_id"])
            self.assertEqual(data["data"]["status"], "completed")

    def test_create_with_problem_spec_and_campaign(self) -> None:
        """创建 AlgorithmRun 时关联 problem_spec_id 和 campaign_id。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "problem_spec_id": "ps_demo_001",
                "campaign_id": "camp_demo_001",
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["data"]["problem_spec_id"], "ps_demo_001")
        self.assertEqual(data["data"]["campaign_id"], "camp_demo_001")

    def test_create_with_reason(self) -> None:
        """创建 AlgorithmRun 时提供操作原因。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
                "reason": "验证人工算法通道闭环",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["data"]["status"], "completed")

    def test_create_nonexistent_algorithm_returns_404(self) -> None:
        """不存在的 algorithm_id 返回 404。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "nonexistent_algo",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_create_unsupported_trigger_returns_400(self) -> None:
        """不支持的 trigger_source 返回 400。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "system",  # 不支持
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_missing_required_input_returns_error(self) -> None:
        """缺少必填输入字段时返回错误（500 或 422，取决于校验时机）。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"material_family": "fluoropolymer"},  # 缺少 keywords
            },
        )
        self.assertIn(resp.status_code, [400, 422, 500])

    def test_list_algorithm_runs(self) -> None:
        """GET /algorithm-runs 查询列表成功。"""
        # 创建几条数据
        for i in range(3):
            self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": "literature_mock",
                    "trigger_source": "human_workflow",
                    "input_snapshot": {"keywords": f"test{i}"},
                },
            )

        resp = self.client.get(f"{self.base_url}/algorithm-runs?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertLessEqual(len(data["data"]["items"]), 2)
        self.assertGreaterEqual(data["data"]["total"], 3)

    def test_list_by_algorithm_id(self) -> None:
        """按 algorithm_id 过滤列表。"""
        # 创建不同类型的数据
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "polymer_descriptor_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"smiles": "C=CF"},
            },
        )

        resp = self.client.get(f"{self.base_url}/algorithm-runs?algorithm_id=polymer_descriptor_mock")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["data"]["total"], 1)
        for item in data["data"]["items"]:
            self.assertEqual(item["algorithm_id"], "polymer_descriptor_mock")

    def test_list_by_status(self) -> None:
        """按 status 过滤列表。"""
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )

        resp = self.client.get(f"{self.base_url}/algorithm-runs?status=completed")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["data"]["total"], 1)
        for item in data["data"]["items"]:
            self.assertEqual(item["status"], "completed")

    def test_list_by_trigger_source(self) -> None:
        """按 trigger_source 过滤列表。"""
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )

        resp = self.client.get(f"{self.base_url}/algorithm-runs?trigger_source=human_workflow")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["data"]["total"], 1)
        for item in data["data"]["items"]:
            self.assertEqual(item["trigger_source"], "human_workflow")

    def test_list_with_empty_filters(self) -> None:
        """无过滤条件时返回所有记录。"""
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )

        resp = self.client.get(f"{self.base_url}/algorithm-runs")
        self.assertEqual(resp.status_code, 200)

    def test_get_algorithm_run_detail(self) -> None:
        """GET /algorithm-runs/{run_id} 获取详情成功。"""
        # 先创建
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "property_predictor_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {
                    "smiles": "C=C(F)F",
                    "target_properties": ["dielectric_constant"],
                },
            },
        )
        run_id = create_resp.json()["data"]["run_id"]

        # 查询详情
        resp = self.client.get(f"{self.base_url}/algorithm-runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["run_id"], run_id)
        self.assertEqual(data["data"]["algorithm_id"], "property_predictor_mock")
        self.assertEqual(data["data"]["trigger_source"], "human_workflow")
        self.assertIn("predictions", data["data"]["output_summary"])
        self.assertIn("input_snapshot", data["data"])
        self.assertIsInstance(data["data"]["artifact_refs"], list)

    def test_get_algorithm_run_has_required_fields(self) -> None:
        """AlgorithmRun 详情包含所有必要字段。"""
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "mobo_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {
                    "problem_spec_id": "ps_test_001",
                    "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
                },
            },
        )
        run_id = create_resp.json()["data"]["run_id"]

        resp = self.client.get(f"{self.base_url}/algorithm-runs/{run_id}")
        data = resp.json()["data"]

        required_fields = [
            "run_id", "algorithm_id", "trigger_source", "status",
            "input_snapshot", "output_summary", "artifact_refs",
            "created_by", "created_at", "updated_at",
        ]
        for field in required_fields:
            self.assertIn(field, data, f"缺少字段: {field}")

    def test_get_nonexistent_run_returns_404(self) -> None:
        """不存在的 AlgorithmRun 返回 404。"""
        resp = self.client.get(f"{self.base_url}/algorithm-runs/arun_nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_create_empty_algorithm_id_returns_422(self) -> None:
        """空的 algorithm_id 被拒绝（422）。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "   ",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.assertEqual(resp.status_code, 422)


# =============================================================================
# ResearchRun API 测试 (Plan 04)
# =============================================================================


class ResearchRunApiTest(ComputationTestCase):
    """覆盖 ResearchRun REST API 的创建、启动、推进、暂停、恢复。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        # 写入算法种子数据，并创建 ProblemSpec
        from app.services.research_engine_service import ResearchEngineService
        svc = ResearchEngineService()
        svc.seed_default_algorithms()

        # 创建 ProblemSpec
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "ResearchRun API 测试",
                "material_family": "fluoropolymer",
                "objectives": [
                    {"name": "dielectric_constant", "direction": "maximize"},
                ],
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        self.ps_id = create_resp.json()["data"]["problem_spec_id"]
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "API 测试进入 AutoResearch"},
        )
        self.assertEqual(decision_resp.status_code, 200)
        self.execution_decision_id = decision_resp.json()["data"]["decision_id"]

    def _create_research_run(self, **overrides) -> dict:
        """创建 ResearchRun 草稿的辅助方法。"""
        payload = {
            "problem_spec_id": self.ps_id,
            "execution_decision_id": self.execution_decision_id,
            "profile_id": "fluoropolymer",
        }
        payload.update(overrides)
        resp = self.client.post(f"{self.base_url}/research-runs", json=payload)
        self.assertEqual(resp.status_code, 200)
        return resp.json()["data"]

    def test_create_research_run(self) -> None:
        """POST /research-runs 创建 ResearchRun 成功。"""
        data = self._create_research_run()
        self.assertEqual(data["status"], "draft")
        self.assertTrue(data["run_id"].startswith("rr_"))
        self.assertEqual(data["problem_spec_id"], self.ps_id)
        self.assertEqual(len(data["stage_runs"]), 10)

    def test_create_with_campaign(self) -> None:
        """创建 ResearchRun 时关联 campaign。"""
        data = self._create_research_run(campaign_id="camp_001")
        self.assertEqual(data["campaign_id"], "camp_001")

    def test_create_with_profile(self) -> None:
        """创建时使用指定 profile。"""
        data = self._create_research_run(profile_id="carbon_polymer")
        self.assertEqual(data["profile_id"], "carbon_polymer")

    def test_get_research_run(self) -> None:
        """GET /research-runs/{id} 获取详情成功。"""
        created = self._create_research_run()
        resp = self.client.get(f"{self.base_url}/research-runs/{created['run_id']}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["run_id"], created["run_id"])
        self.assertIn("stage_runs", data["data"])

    def test_get_nonexistent_research_run_returns_404(self) -> None:
        """不存在的 ResearchRun 返回 404。"""
        resp = self.client.get(f"{self.base_url}/research-runs/rr_nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_list_research_runs(self) -> None:
        """GET /research-runs 查询列表成功。"""
        for i in range(3):
            self._create_research_run()

        resp = self.client.get(f"{self.base_url}/research-runs?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertLessEqual(len(data["data"]["items"]), 2)
        self.assertGreaterEqual(data["data"]["total"], 3)

    def test_archive_research_run_hides_from_default_list(self) -> None:
        """归档 ResearchRun 后默认列表隐藏，按 archived 状态可查。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        archive_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}:archive",
            json={"reason": "API 测试归档"},
        )
        self.assertEqual(archive_resp.status_code, 200)
        self.assertEqual(archive_resp.json()["data"]["status"], "archived")

        default_resp = self.client.get(f"{self.base_url}/research-runs")
        default_ids = [item["run_id"] for item in default_resp.json()["data"]["items"]]
        self.assertNotIn(run_id, default_ids)

        archived_resp = self.client.get(f"{self.base_url}/research-runs?status=archived")
        archived_ids = [item["run_id"] for item in archived_resp.json()["data"]["items"]]
        self.assertIn(run_id, archived_ids)

    def test_list_by_status(self) -> None:
        """按状态过滤 ResearchRun。"""
        self._create_research_run()
        resp = self.client.get(f"{self.base_url}/research-runs?status=draft")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["data"]["total"], 1)

    def test_start_research_run(self) -> None:
        """POST /research-runs/{id}/start 启动并推进到 gate。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动测试"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "blocked_approval")
        problem_stage = next(
            sr for sr in data["data"]["stage_runs"]
            if sr["stage_key"] == "PROBLEM_SPEC"
        )
        self.assertEqual(problem_stage["status"], "blocked_approval")

    def test_start_requires_reason(self) -> None:
        """启动时缺少 reason 返回 422。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": ""},
        )
        self.assertEqual(resp.status_code, 422)

    def test_start_nonexistent_run_returns_404(self) -> None:
        """启动不存在的 ResearchRun 返回 404。"""
        resp = self.client.post(
            f"{self.base_url}/research-runs/rr_nonexistent/start",
            json={"target_status": "running", "reason": "启动"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_pause_research_run(self) -> None:
        """POST /research-runs/{id}/pause 暂停成功。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        # 先启动
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动"},
        )

        # 暂停
        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/pause",
            json={"target_status": "paused", "reason": "测试暂停"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "paused")

    def test_resume_research_run(self) -> None:
        """POST /research-runs/{id}/resume 恢复成功。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        # 启动 → 暂停
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动"},
        )
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/pause",
            json={"target_status": "paused", "reason": "暂停"},
        )

        # 恢复
        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/resume",
            json={"target_status": "running", "reason": "测试恢复"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "running")

    def test_fail_research_run(self) -> None:
        """POST /research-runs/{id}/fail 标记失败。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动"},
        )

        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/fail",
            json={"target_status": "failed", "reason": "手动标记失败"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "failed")


# =============================================================================
# Stage/Gate 审批 API 测试 (Plan 04 Task 3)
# =============================================================================


class StageGateApiTest(ComputationTestCase):
    """覆盖 Stage/Gate 审批 REST API。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        from app.services.research_engine_service import ResearchEngineService
        svc = ResearchEngineService()
        svc.seed_default_algorithms()

        # 创建 ProblemSpec
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "Gate 审批测试",
                "material_family": "fluoropolymer",
                "objectives": [
                    {"name": "dielectric_constant", "direction": "maximize"},
                ],
            },
        )
        self.ps_id = create_resp.json()["data"]["problem_spec_id"]
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "Gate API 测试进入 AutoResearch"},
        )
        self.execution_decision_id = decision_resp.json()["data"]["decision_id"]

        # 创建 ResearchRun 并启动以到达 gate
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={"problem_spec_id": self.ps_id, "execution_decision_id": self.execution_decision_id},
        )
        self.run_id = rr_resp.json()["data"]["run_id"]

        start_resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/start",
            json={"target_status": "running", "reason": "启动以到达 gate"},
        )
        self.started_data = start_resp.json()["data"]

    def test_approve_gate(self) -> None:
        """POST .../stages/{stage_run_id}/approve 批准 gate。"""
        # 找到 PROBLEM_SPEC gate（第一个 blocked_approval）
        blocked_sr = None
        for sr in self.started_data["stage_runs"]:
            if sr["status"] == "blocked_approval":
                blocked_sr = sr
                break
        self.assertIsNotNone(blocked_sr, "应有 blocked_approval 阶段")

        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/{blocked_sr['stage_run_id']}/approve",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "approved",
                "reason": "审批通过测试",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "blocked_approval")
        knowledge_stage = next(
            sr for sr in data["data"]["stage_runs"]
            if sr["stage_key"] == "KNOWLEDGE_RETRIEVAL"
        )
        self.assertEqual(knowledge_stage["status"], "completed")
        self.assertGreater(len(knowledge_stage["linked_algorithm_runs"]), 0)

    def test_reject_gate(self) -> None:
        """POST .../stages/{stage_run_id}/reject 拒绝 gate。"""
        blocked_sr = None
        for sr in self.started_data["stage_runs"]:
            if sr["status"] == "blocked_approval":
                blocked_sr = sr
                break
        self.assertIsNotNone(blocked_sr)

        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/{blocked_sr['stage_run_id']}/reject",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "rejected",
                "reason": "拒绝测试-不满足需求",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "failed")

    def test_approve_requires_reason(self) -> None:
        """审批缺少 reason 返回 422。"""
        blocked_sr = None
        for sr in self.started_data["stage_runs"]:
            if sr["status"] == "blocked_approval":
                blocked_sr = sr
                break
        self.assertIsNotNone(blocked_sr)

        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/{blocked_sr['stage_run_id']}/approve",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "approved",
                "reason": "   ",  # 空白被拒绝
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_reject_requires_reason(self) -> None:
        """拒绝缺少 reason 返回 422。"""
        blocked_sr = None
        for sr in self.started_data["stage_runs"]:
            if sr["status"] == "blocked_approval":
                blocked_sr = sr
                break
        self.assertIsNotNone(blocked_sr)

        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/{blocked_sr['stage_run_id']}/reject",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "rejected",
                "reason": "",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_approve_nonexistent_stage_returns_404(self) -> None:
        """审批不存在的 StageRun 返回 404。"""
        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/srun_nonexistent/approve",
            json={
                "stage_key": "PROBLEM_SPEC",
                "decision": "approved",
                "reason": "审批不存在的 stage",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_full_approve_flow(self) -> None:
        """完整审批流程：逐个审批所有 gate。"""
        run_id = self.run_id

        # 获取初始状态
        rr_resp = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        run_data = rr_resp.json()["data"]

        max_loops = 10
        while run_data["status"] in ("blocked_approval",) and max_loops > 0:
            max_loops -= 1
            blocked_sr = None
            for sr in run_data["stage_runs"]:
                if sr["status"] == "blocked_approval":
                    blocked_sr = sr
                    break
            if blocked_sr is None:
                break

            approve_resp = self.client.post(
                f"{self.base_url}/research-runs/{run_id}/stages/{blocked_sr['stage_run_id']}/approve",
                json={
                    "stage_key": blocked_sr["stage_key"],
                    "decision": "approved",
                    "reason": f"审批 {blocked_sr['stage_key']}",
                },
            )
            self.assertEqual(approve_resp.status_code, 200)
            run_data = approve_resp.json()["data"]

        self.assertIn(run_data["status"], ["completed", "blocked_approval", "failed"])

    def test_full_pause_resume_flow(self) -> None:
        """完整暂停-恢复流程 API 测试。"""
        run_id = self.run_id

        # 暂停
        pause_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/pause",
            json={"target_status": "paused", "reason": "API 测试暂停"},
        )
        self.assertEqual(pause_resp.status_code, 200)
        self.assertEqual(pause_resp.json()["data"]["status"], "paused")

        # 恢复
        resume_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/resume",
            json={"target_status": "running", "reason": "API 测试恢复"},
        )
        self.assertEqual(resume_resp.status_code, 200)
        self.assertIn(
            resume_resp.json()["data"]["status"],
            ["running", "blocked_approval"],
        )

    def test_advance_endpoint(self) -> None:
        """POST /research-runs/{id}/advance 推进阶段。"""
        run_id = self.run_id

        # advance 要求 status 为 running 或 blocked_approval
        # 从 running 或 blocked_approval 直接调用 advance
        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/advance",
            json={"target_status": "running", "reason": "手动继续推进"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn(data["data"]["status"], ["running", "blocked_approval", "completed"])


# =============================================================================
# Traceability API 测试（Plan 06 Task 1）
# =============================================================================


class TraceabilityApiTest(ComputationTestCase):
    """覆盖追溯聚合 API。"""

    @classmethod
    def setUpClass(cls) -> None:
        pass

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        self.svc = ResearchEngineService()

        # 创建 ProblemSpec
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        self.ps_id = resp.json()["data"]["problem_spec_id"]

        # 填充算法种子
        self.svc.seed_default_algorithms()
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "Traceability 测试进入 AutoResearch"},
        )
        self.autoresearch_decision_id = decision_resp.json()["data"]["decision_id"]

    def test_query_audit_by_entity(self) -> None:
        """按 entity_type 和 entity_id 查询审计事件。"""
        resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_type": "problem_spec", "entity_id": self.ps_id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 1)
        # 确认有 "created" 事件
        event_types = [e["event_type"] for e in data["data"]["items"]]
        self.assertIn("created", event_types)

    def test_query_audit_filter_by_event_type(self) -> None:
        """按事件类型过滤审计事件。"""
        resp = self.client.get(
            f"{self.base_url}/audit",
            params={
                "entity_type": "problem_spec",
                "entity_id": self.ps_id,
                "event_type": "created",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 1)
        for item in data["data"]["items"]:
            self.assertEqual(item["event_type"], "created")

    def test_audit_returns_sanitized_data(self) -> None:
        """审计事件不暴露敏感路径。"""
        resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_id": self.ps_id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for item in data["data"]["items"]:
            item_str = str(item)
            # 不暴露本地文件系统路径
            self.assertNotIn("/home/", item_str)
            self.assertNotIn("storage_uri", item_str)

    def test_algorithm_run_traceability_without_computation(self) -> None:
        """AlgorithmRun 追溯链：无关联 computation 的情况。"""
        # 运行 mock predictor
        arun_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "problem_spec_id": self.ps_id,
                "input_snapshot": {"keywords": "fluoropolymer"},
                "reason": "测试追溯链",
            },
        )
        self.assertEqual(arun_resp.status_code, 200)
        run_id = arun_resp.json()["data"]["run_id"]

        # 获取追溯链
        resp = self.client.get(
            f"{self.base_url}/algorithm-runs/{run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        # 验证 algorithm_run 字段存在
        self.assertIsNotNone(data["algorithm_run"])
        self.assertEqual(data["algorithm_run"]["run_id"], run_id)
        self.assertEqual(data["algorithm_run"]["trigger_source"], "human_workflow")

        # 无关联 computation 时应为 None
        self.assertIsNone(data["linked_computation"])

        # 应有审计事件
        self.assertGreater(len(data["audit_events"]), 0)
        event_types = [e["event_type"] for e in data["audit_events"]]
        self.assertIn("created", event_types)

    def test_algorithm_run_traceability_with_computation(self) -> None:
        """AlgorithmRun 追溯链：关联 computation 的情况。"""
        # 运行 computation adapter
        arun_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "computation_submit_adapter",
                "trigger_source": "human_workflow",
                "problem_spec_id": self.ps_id,
                "input_snapshot": {
                    "workflow_type": "LOCAL_STRUCTURE",
                    "smiles": "CCO",
                    "name": "test_structure",
                },
                "reason": "测试 computation 追溯链",
            },
        )
        self.assertEqual(arun_resp.status_code, 200)
        run_id = arun_resp.json()["data"]["run_id"]

        # 获取追溯链
        resp = self.client.get(
            f"{self.base_url}/algorithm-runs/{run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        # 验证关联 computation
        if data["linked_computation"] is not None:
            self.assertIsNotNone(data["linked_computation"]["run_id"])
            self.assertIsNotNone(data["linked_computation"]["workflow_type"])
            # 验证不暴露本地路径
            comp_str = str(data["linked_computation"])
            self.assertNotIn("/home/", comp_str)

    def test_research_run_traceability(self) -> None:
        """ResearchRun 追溯链：完整聚合。"""
        # 创建 ResearchRun
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": self.autoresearch_decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 3,
                "batch_size": 5,
            },
        )
        self.assertEqual(rr_resp.status_code, 200)
        run_id = rr_resp.json()["data"]["run_id"]

        # 启动以生成审计事件
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "追溯链测试启动"},
        )

        # 获取追溯链
        resp = self.client.get(
            f"{self.base_url}/research-runs/{run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        # 验证 research_run 字段
        self.assertIsNotNone(data["research_run"])
        self.assertEqual(data["research_run"]["run_id"], run_id)

        # 验证 stage_runs 在 research_run 中
        self.assertGreater(len(data["research_run"]["stage_runs"]), 0)

        # 验证审计事件（至少包含 created）
        self.assertGreater(len(data["audit_events"]), 0)
        event_types = [e["event_type"] for e in data["audit_events"]]
        self.assertIn("created", event_types)

    def test_stage_run_traceability(self) -> None:
        """StageRun 追溯链：单个阶段聚合。"""
        # 创建并启动 ResearchRun
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": self.autoresearch_decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 3,
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]

        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "StageRun 追溯链测试"},
        )

        # 获取 stage_run_id
        rr_detail = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        stage_runs = rr_detail.json()["data"]["stage_runs"]
        self.assertGreater(len(stage_runs), 0)

        stage_run_id = stage_runs[0]["stage_run_id"]

        # 获取阶段追溯链
        resp = self.client.get(
            f"{self.base_url}/research-runs/{run_id}/stages/{stage_run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        # 验证 stage_run 字段
        self.assertIsNotNone(data["stage_run"])
        self.assertEqual(data["stage_run"]["stage_run_id"], stage_run_id)

        # 验证审计事件（至少包含 blocked_approval 或 completed）
        stage_status = data["stage_run"]["status"]
        if stage_status == "completed":
            event_types = [e["event_type"] for e in data["audit_events"]]
            self.assertIn("completed", event_types)

    def test_traceability_no_sensitive_paths(self) -> None:
        """追溯链不暴露敏感路径。"""
        # 创建 ResearchRun 并启动
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": self.autoresearch_decision_id,
                "profile_id": "fluoropolymer",
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "测试"},
        )

        # 获取追溯链
        resp = self.client.get(
            f"{self.base_url}/research-runs/{run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        response_text = resp.text

        # 不暴露本地文件路径
        self.assertNotIn("/home/", response_text)
        self.assertNotIn("storage_uri", response_text)
        self.assertNotIn("/tmp/", response_text)
        self.assertNotIn("password", response_text.lower())
        self.assertNotIn("secret", response_text.lower())
