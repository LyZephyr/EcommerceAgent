"""应用配置，从环境变量加载。"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ARK_API_KEY = os.environ.get("ARK_API_KEY")
ARK_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/")
ARK_MODEL = os.environ.get("ARK_MODEL", "ep-20260514111645-lmgt2")

CHROMA_PERSIST_DIR = str(Path(__file__).resolve().parent / "chroma_db")
CHROMA_COLLECTION_NAME = os.environ.get("CHROMA_COLLECTION_NAME", "products")
DATASET_DIR = str(Path(__file__).resolve().parent.parent / "ecommerce_agent_dataset")

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "shibing624/text2vec-base-chinese")

TOP_K = int(os.environ.get("TOP_K", "5"))
