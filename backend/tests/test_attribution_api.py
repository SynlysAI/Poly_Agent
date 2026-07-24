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

        assert len(sources) == 6
        for source_name in ["OpenPoly", "RadonPy PI1070", "PI1M v2", "SMiPoly", "PolyUniverse", "MD-AllAtom 数据集"]:
            assert source_name in sources
            assert sources[source_name]["visibility"] == "prominent"

        assert sources["OpenPoly"]["url"] == "https://doi.org/10.1007/s10118-025-3402-y"
        assert "10.1007/s10118-025-3402-y" in sources["OpenPoly"]["citation_text"]
        assert sources["RadonPy PI1070"]["url"] == "https://github.com/RadonPy/RadonPy"
        assert sources["PI1M v2"]["url"] == "https://doi.org/10.1021/acs.jcim.0c00726"
        assert "10.1021/acs.jcim.0c00726" in sources["PI1M v2"]["citation_text"]
