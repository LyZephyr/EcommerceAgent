"""离线评估当前商品召回质量。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from config import TOP_K  # noqa: E402
from retriever import retrieve  # noqa: E402

DEFAULT_GROUND_TRUTH_PATH = PROJECT_ROOT / "eval" / "ground_truth.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "eval" / "reports"


def main() -> None:
    args = parse_args()
    top_k = args.top_k
    ground_truth = load_ground_truth(args.ground_truth)
    details = [evaluate_query(item, top_k) for item in ground_truth]
    summary = summarize(details)
    report = {
        "top_k": top_k,
        "ground_truth_path": str(args.ground_truth),
        "query_count": len(details),
        "summary": summary,
        "details": details,
    }

    output_path = args.output or DEFAULT_REPORT_DIR / f"retrieval_eval_top{top_k}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print_summary(summary, top_k, len(details), output_path)
    print_details(details, top_k)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retrieve(query, top_k) against a ground-truth set.")
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GROUND_TRUTH_PATH,
        help=f"Ground truth JSON path. Default: {DEFAULT_GROUND_TRUTH_PATH}",
    )
    parser.add_argument(
        "--top-k",
        type=positive_int,
        default=TOP_K,
        help=f"Evaluation K. Default follows server.config.TOP_K ({TOP_K}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report JSON output path. Default: eval/reports/retrieval_eval_top{K}.json",
    )
    return parser.parse_args()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--top-k must be a positive integer")
    return parsed


def load_ground_truth(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Ground truth must be a JSON list: {path}")

    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Ground truth item #{index} must be an object")

        query_id = require_string(item, "id", index)
        query = require_string(item, "query", index)
        relevant_product_ids = item.get("relevant_product_ids")
        if not isinstance(relevant_product_ids, list) or not all(
            isinstance(product_id, str) for product_id in relevant_product_ids
        ):
            raise ValueError(f"Ground truth item {query_id} must contain string list relevant_product_ids")
        if len(set(relevant_product_ids)) != len(relevant_product_ids):
            raise ValueError(f"Ground truth item {query_id} contains duplicated relevant_product_ids")
        if query_id in seen_ids:
            raise ValueError(f"Duplicated ground truth id: {query_id}")

        seen_ids.add(query_id)
        normalized.append(
            {
                "id": query_id,
                "query": query,
                "relevant_product_ids": relevant_product_ids,
            }
        )
    return normalized


def require_string(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Ground truth item #{index} must contain non-empty string field {key}")
    return value


def evaluate_query(item: dict[str, Any], top_k: int) -> dict[str, Any]:
    products = retrieve(item["query"], top_k=top_k)
    retrieved_product_ids = [str(product["product_id"]) for product in products]
    relevant_product_ids = item["relevant_product_ids"]
    relevant_set = set(relevant_product_ids)
    retrieved_hit_ids = [product_id for product_id in retrieved_product_ids if product_id in relevant_set]
    unique_hit_ids = list(dict.fromkeys(retrieved_hit_ids))
    first_relevant_rank = first_rank(retrieved_product_ids, relevant_set)

    metrics = calculate_metrics(
        retrieved_product_ids=retrieved_product_ids,
        relevant_product_ids=relevant_product_ids,
        unique_hit_ids=unique_hit_ids,
        first_relevant_rank=first_relevant_rank,
        top_k=top_k,
    )
    return {
        "id": item["id"],
        "query": item["query"],
        "relevant_product_ids": relevant_product_ids,
        "retrieved_product_ids": retrieved_product_ids,
        "hit_product_ids": unique_hit_ids,
        "missed_product_ids": [product_id for product_id in relevant_product_ids if product_id not in unique_hit_ids],
        "unexpected_product_ids": [product_id for product_id in retrieved_product_ids if product_id not in relevant_set],
        "first_relevant_rank": first_relevant_rank,
        "metrics": metrics,
        "retrieved_products": [product_summary(product) for product in products],
    }


def first_rank(retrieved_product_ids: list[str], relevant_set: set[str]) -> int | None:
    for rank, product_id in enumerate(retrieved_product_ids, start=1):
        if product_id in relevant_set:
            return rank
    return None


def calculate_metrics(
    retrieved_product_ids: list[str],
    relevant_product_ids: list[str],
    unique_hit_ids: list[str],
    first_relevant_rank: int | None,
    top_k: int,
) -> dict[str, float | None]:
    relevant_count = len(relevant_product_ids)
    hit_count = len(unique_hit_ids)
    recall_at_k = hit_count / relevant_count if relevant_count else None
    mrr = 1.0 / first_relevant_rank if first_relevant_rank else (0.0 if relevant_count else None)
    hit_rate_at_k = 1.0 if hit_count else 0.0
    precision_at_k = hit_count / top_k
    return {
        "recall_at_k": recall_at_k,
        "mrr": mrr,
        "hit_rate_at_k": hit_rate_at_k,
        "precision_at_k": precision_at_k,
        "hit_count": float(hit_count),
        "relevant_count": float(relevant_count),
        "retrieved_count": float(len(retrieved_product_ids)),
    }


def product_summary(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": product.get("product_id"),
        "title": product.get("title"),
        "brand": product.get("brand"),
        "category": product.get("category"),
        "sub_category": product.get("sub_category"),
        "price": product.get("price"),
        "distance": product.get("distance"),
    }


def summarize(details: list[dict[str, Any]]) -> dict[str, float]:
    metric_names = ("recall_at_k", "mrr", "hit_rate_at_k", "precision_at_k")
    return {metric_name: mean_metric(details, metric_name) for metric_name in metric_names}


def mean_metric(details: list[dict[str, Any]], metric_name: str) -> float:
    values = [
        detail["metrics"][metric_name]
        for detail in details
        if detail["metrics"][metric_name] is not None
    ]
    if not values:
        return 0.0
    return sum(values) / len(values)


def print_summary(summary: dict[str, float], top_k: int, query_count: int, output_path: Path) -> None:
    print(f"Evaluated {query_count} queries with K={top_k}")
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
        print(f"  relevant: {', '.join(detail['relevant_product_ids'])}")
        print(f"  retrieved: {', '.join(detail['retrieved_product_ids'])}")
        print(f"  hits: {', '.join(detail['hit_product_ids']) or '-'}")


def format_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


if __name__ == "__main__":
    main()
