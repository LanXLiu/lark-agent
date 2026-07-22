"""
FastAPI 路由子模块聚合。

导出数据转换与向量化 ``APIRouter``，供 ``api.main`` 挂载。
"""

from .convert import router as convert_router
from .embedding import router as embedding_router
from .recall import router as recall_router

__all__ = [
    "convert_router",
    "embedding_router",
    "recall_router",
]
