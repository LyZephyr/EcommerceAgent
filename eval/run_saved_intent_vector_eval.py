"""复用已有评估报告中的 search_text/where_filter，重新执行纯向量检索评估。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, TOP_K  # noqa: E402
from embedding import get_embedding_function  # noqa: E402
from run_retrieval_eval import (  # noqa: E402
    calculate_metrics,
    first_rank,
    format_metric,
    positive_int,
    product_summary,
    summarize,
)

DEFAULT_SOURCE_REPORT_PATH = PROJECT_ROOT / "eval" / "reports" / "retrieval_eval_top5_with_intent.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "eval" / "reports"
INTENT_FIELDS = {
    "rewritten_query",
    "category",
    "min_price",
    "max_price",
    "must_have_terms",
    "exclude_terms",
    "exclude_brands",
}


def main() -> None:
    args = parse_args()
    source_report = load_source_report(args.source_report)
    top_k = args.top_k or int(source_report.get("top_k") or TOP_K)
    source_details = source_report["details"]
    if args.limit:
        source_details = source_details[: args.limit]

    collection = get_collection()
    details = []
    total = len(source_details)
    for index, source_detail in enumerate(source_details, start=1):
        products = retrieve_from_saved_search(collection, source_detail, top_k)
        details.append(evaluate_saved_detail(source_detail, products, top_k))
        if index % 10 == 0 or index == total:
            print(f"Progress: {index}/{total}", file=sys.stderr)

    summary = summarize(details)
    report = {
        "top_k": top_k,
        "retrieval_mode": "saved_search_text_where_filter_vector_distance",
        "source_report_path": str(args.source_report),
        "query_count": len(details),
        "summary": summary,
        "details": details,
    }

    output_path = args.output or default_report_path(top_k)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print_summary(summary, top_k, len(details), output_path)
    print_details(details, top_k)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate vector retrieval using cached search_text/where_filter from an existing report.",
    )
    parser.add_argument(
        "--source-report",
        type=Path,
        default=DEFAULT_SOURCE_REPORT_PATH,
        help=f"Source report containing search_text and where_filter. Default: {DEFAULT_SOURCE_REPORT_PATH}",
    )
    parser.add_argument(
        "--top-k",
        type=positive_int,
        default=None,
        help=f"Evaluation K. Default reads source report top_k or server.config.TOP_K ({TOP_K}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report output path. Default: eval/reports/retrieval_eval_top{K}_saved_intent_vector_{timestamp}.json",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        help="Only evaluate the first N source report details.",
    )
    return parser.parse_args()


def load_source_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    details = report.get("details")
    if not isinstance(details, list):
        raise ValueError(f"Source report must contain a details list: {path}")
    return report


def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    collection = client.get_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=get_embedding_function(),
    )
    if collection.count() == 0:
        raise RuntimeError("商品向量库为空，请先运行 `python ingest.py` 导入数据。")
    return collection


def retrieve_from_saved_search(collection, source_detail: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    search_text = source_detail.get("search_text")
    if not isinstance(search_text, str) or not search_text.strip():
        raise ValueError(f"Source detail {source_detail.get('id')} missing non-empty search_text")

    where_filter = source_detail.get("where_filter")
    if where_filter is not None and not isinstance(where_filter, dict):
        raise ValueError(f"Source detail {source_detail.get('id')} has invalid where_filter")

    count = collection.count()
    candidate_count = min(max(top_k * 10, 30), count)
    result = collection.query(
        query_texts=[search_text],
        n_results=candidate_count,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    best: dict[str, dict[str, Any]] = {}
    for chunk_id, document, metadata, distance in zip(
        result["ids"][0],
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
        strict=True,
    ):
        product_id = str(metadata.get("product_id") or chunk_id.split("__")[0])
        if product_id not in best or distance < best[product_id]["distance"]:
            product = dict(metadata)
            product["product_id"] = product_id
            product["document"] = document
            product["distance"] = float(distance)
            best[product_id] = product

    return sorted(best.values(), key=lambda product: product["distance"])[:top_k]


def evaluate_saved_detail(
    source_detail: dict[str, Any],
    products: list[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    retrieved_product_ids = [str(product["product_id"]) for product in products]
    relevant_product_ids = source_detail["relevant_product_ids"]
    relevant_set = set(relevant_product_ids)
    retrieved_hit_ids = [product_id for product_id in retrieved_product_ids if product_id in relevant_set]
    unique_hit_ids = list(dict.fromkeys(retrieved_hit_ids))
    first_relevant_rank = first_rank(retrieved_product_ids, relevant_set)

    result = {
        "id": source_detail["id"],
        "query": source_detail["query"],
        "relevant_product_ids": relevant_product_ids,
        "retrieved_product_ids": retrieved_product_ids,
        "hit_product_ids": unique_hit_ids,
        "missed_product_ids": [product_id for product_id in relevant_product_ids if product_id not in unique_hit_ids],
        "unexpected_product_ids": [product_id for product_id in retrieved_product_ids if product_id not in relevant_set],
        "first_relevant_rank": first_relevant_rank,
        "metrics": calculate_metrics(
            retrieved_product_ids=retrieved_product_ids,
            relevant_product_ids=relevant_product_ids,
            unique_hit_ids=unique_hit_ids,
            first_relevant_rank=first_relevant_rank,
            top_k=top_k,
        ),
        "retrieved_products": [product_summary(product) for product in products],
        "search_text": source_detail["search_text"],
        "where_filter": source_detail.get("where_filter"),
        "source_retrieved_product_ids": source_detail.get("retrieved_product_ids", []),
    }
    if "intent" in source_detail:
        result["intent"] = {
            key: source_detail["intent"].get(key)
            for key in INTENT_FIELDS
            if key in source_detail["intent"]
        }
    return result


def default_report_path(top_k: int) -> Path:
    return DEFAULT_REPORT_DIR / f"retrieval_eval_top{top_k}_saved_intent_vector_{timestamp()}.json"


def print_summary(summary: dict[str, float], top_k: int, query_count: int, output_path: Path) -> None:
    print(f"Evaluated {query_count} cached-intent queries with K={top_k}")
    print(f"Recall@{top_k}: {summary['recall_at_k']:.4f}")
    print(f"MRR: {summary['mrr']:.4f}")
    print(f"Hit Rate@{top_k}: {summary['hit_rate_at_k']:.4f}")
    print(f"Precision@{top_k}: {summary['precision_at_k']:.4f}")
    print(f"Report: {output_path}")
    print()


def print_details(details: list[dict[str, Any]], top_k: int) -> None:
    for detail in details:
        metrics = detail["metrics"]
        first_rank_text = str(detail["first_relevant_rank"]) if detail["first_relevant_rank"] else "-"
        print(
            f"{detail['id']} | hits {int(metrics['hit_count'])}/{int(metrics['relevant_count'])} "
            f"| first_rank {first_rank_text} | R@{top_k} {format_metric(metrics['recall_at_k'])} "
            f"| MRR {format_metric(metrics['mrr'])} | HR@{top_k} {metrics['hit_rate_at_k']:.4f} "
            f"| P@{top_k} {metrics['precision_at_k']:.4f} | query: {detail['query']}"
        )
        print(f"  search_text: {detail['search_text']}")
        print(f"  where_filter: {detail.get('where_filter')}")
        print(f"  relevant: {', '.join(detail['relevant_product_ids'])}")
        print(f"  retrieved: {', '.join(detail['retrieved_product_ids'])}")
        print(f"  hits: {', '.join(detail['hit_product_ids']) or '-'}")


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


if __name__ == "__main__":
    main()
