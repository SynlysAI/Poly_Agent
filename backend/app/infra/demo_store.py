"""SQLite 本地存储的兼容入口。

历史代码通过 ``demo_store`` 访问本地文档存储；该模块现在代理到
``sqlite_store``，避免大量调用点迁移。旧 JSON store 已移除。
"""

from app.infra.sqlite_store import (
    COLLECTION_NAMES,
    SqliteDocumentStore,
    clone_document,
    demo_store,
)

# 保留旧类名，兼容尚未更新的测试与脚本。
DemoJsonStore = SqliteDocumentStore

__all__ = [
    "COLLECTION_NAMES",
    "DemoJsonStore",
    "SqliteDocumentStore",
    "clone_document",
    "demo_store",
]
