"""来源与引用标注 API 测试。"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


class TestAttributionApi:
    """覆盖模块来源标注 API。"""

    def test_data_catalog_attributions_include_public_source_links(self) -> None:
        """数据管理来源条目提供侧栏可展示的链接和引用。"""
        with TestClient(app) as client:
            response = client.get("/api/v1/attributions/modules/data_catalog")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        sources = {item["name"]: item for item in data["attributions"]}

        assert len(sources) == 16
        for source_name in [
            "OpenPoly",
            "RadonPy PI1070",
            "PI1M v2",
            "SMiPoly",
            "PolyUniverse",
            "MD-AllAtom 数据集",
            "OMG",
            "OMG Physical Properties",
            "polyOne",
            "ToPoRg",
            "PolySol",
            "PolyOmics",
            "PPPDB",
            "PolyID",
            "TROPIC",
            "NanoMine",
        ]:
            assert source_name in sources
            assert sources[source_name]["visibility"] == "prominent"

        assert sources["OpenPoly"]["url"] == "https://doi.org/10.1007/s10118-025-3402-y"
        assert "10.1007/s10118-025-3402-y" in sources["OpenPoly"]["citation_text"]
        assert sources["RadonPy PI1070"]["url"] == "https://github.com/RadonPy/RadonPy"
        assert sources["PI1M v2"]["url"] == "https://doi.org/10.1021/acs.jcim.0c00726"
        assert "10.1021/acs.jcim.0c00726" in sources["PI1M v2"]["citation_text"]
        assert sources["OMG"]["url"] == "https://github.com/TheJacksonLab/OpenMacromolecularGenome"
        assert sources["OMG Physical Properties"]["url"] == "https://doi.org/10.5281/zenodo.13863778"
        assert sources["polyOne"]["url"] == "https://doi.org/10.5281/zenodo.7124188"
        assert sources["ToPoRg"]["license"] == "CC BY 4.0"
        assert sources["TROPIC"]["url"] == "https://polytropic.org/"
        for source_name in ["PolySol", "PolyOmics", "PPPDB", "PolyID", "NanoMine"]:
            assert sources[source_name]["url"] is None
            assert sources[source_name]["logo_asset"] is None

    def test_experiment_dispatch_attribution_exposes_external_source_only(self) -> None:
        """实验下发公开来源牌只展示外部目标系统，不展示 PolyAgent 自身。"""
        with TestClient(app) as client:
            response = client.get("/api/v1/attributions/modules/experiment_dispatch")

        assert response.status_code == 200, response.text
        attributions = response.json()["data"]["attributions"]
        assert [item["name"] for item in attributions] == ["SpecLabOS"]

    def test_capability_center_attribution_covers_external_sources_only(self) -> None:
        """能力中心来源牌覆盖原模块外部来源，不新增 PolyAgent 自身来源。"""
        with TestClient(app) as client:
            response = client.get("/api/v1/attributions/modules/capability_center")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        sources = {item["name"]: item for item in data["attributions"]}
        assert set(sources) == {
            "ALchemist",
            "Codex CLI",
            "OpenAI-compatible provider",
            "Ollama",
            "Custom HTTP provider",
        }
        assert sources["ALchemist"]["organization"] == "NatLabRockies / NREL / NLR"
        assert sources["Codex CLI"]["organization"] == "OpenAI"
        assert all(item["visibility"] == "prominent" for item in sources.values())
