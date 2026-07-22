"""
FastAPI 应用入口。

定义应用生命周期（日志、图片 OCR 预热）、CORS 与 ``/health``，
并挂载**独立数据转换**与向量化路由。
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from infrastructure.conf import setup_logger
from infrastructure.conf.settings import settings

from .routers.embedding import router as embedding_router
from .routers.recall import router as recall_router


def _setting_enabled(name: str, default: bool) -> bool:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


async def _warmup_image_ocr() -> None:
    """启动时加载 PPStructureV3 单例，避免首次 /convert/image 请求自带模型加载耗时。"""
    if not _setting_enabled("api_enable_convert", False):
        logger.info("已关闭转换接口，跳过图片 OCR 预热")
        return
    if os.environ.get("DISABLE_IMAGE_OCR_WARMUP", "").lower() in ("1", "true", "yes"):
        logger.info("已通过 DISABLE_IMAGE_OCR_WARMUP 跳过 PPStructure 预热")
        return

    def _load() -> None:
        from knowledge.ingestion.file_to_markdown.image_to_markdown import get_image_to_markdown_converter

        get_image_to_markdown_converter()

    try:
        logger.info("正在预热图片 OCR 模型（PPStructureV3）……")
        await asyncio.to_thread(_load)
        logger.info("图片 OCR 模型预热完成")
    except ImportError as e:
        logger.warning("PaddleOCR 依赖缺失，跳过预热（首次调用 /convert/image 会再次尝试）：{}", e)
    except Exception as e:
        logger.warning("图片 OCR 预热失败（首次调用 /convert/image 会再次尝试）：{}", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用启动与关闭钩子。

    Yields:
        控制权交给 FastAPI 运行期；yield 之后执行关闭逻辑。
    """
    setup_logger()
    await _warmup_image_ocr()
    yield


app = FastAPI(
    title="Knowledge Data Pipeline API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(embedding_router, prefix="/embed", tags=["Embed"])
app.include_router(recall_router, prefix="/recall", tags=["Recall"])

if _setting_enabled("api_enable_convert", False):
    from .routers.convert import router as convert_router

    app.include_router(convert_router, prefix="/convert", tags=["Convert"])
else:
    logger.info("已关闭转换接口，仅启用 Embed / Recall / Health")


@app.get("/health")
async def health():
    """存活探针，供负载均衡或运维检测。"""
    return {"status": "ok"}
