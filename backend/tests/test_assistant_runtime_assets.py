"""Assistant 受管运行时附件服务测试。"""

from __future__ import annotations

from pathlib import Path

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.infra.research_engine_repositories import AssistantRuntimeAssetRepository
from app.services.assistant_runtime_asset_service import assistant_runtime_asset_service


class AssistantRuntimeAssetServiceTest(ComputationTestCase):
    def test_store_read_and_release_managed_asset(self) -> None:
        stored = assistant_runtime_asset_service.store(
            call_id="atc_runtime_asset",
            chat_id="chat_runtime_asset",
            created_by="asset-user",
            asset_key="structure",
            filename="polymer.cif",
            content_type="chemical/x-cif",
            content=b"polymer structure",
        )

        self.assertEqual(stored["status"], "active")
        self.assertTrue(Path(stored["path"]).is_file())
        self.assertEqual(
            assistant_runtime_asset_service.read(
                call_id="atc_runtime_asset",
                asset_id=stored["asset_id"],
            ),
            b"polymer structure",
        )

        released = assistant_runtime_asset_service.release_call_assets("atc_runtime_asset")
        self.assertEqual(released, 1)
        self.assertFalse(Path(stored["path"]).exists())
        document = AssistantRuntimeAssetRepository.find_one({"asset_id": stored["asset_id"]})
        self.assertEqual(document["status"], "released")

