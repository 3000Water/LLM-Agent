"""
动态分点（章节单元）构建：
- 对每个大章节判断是否需要分点
- 并行评估关键词聚类与 embedding 聚类
- 输出可写作的单元结构与对比指标
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


DEFAULT_OPTIONS = {
    "enabled": True,
    "method": "auto",  # auto | keyword | embedding
    "min_bullets_to_split": 8,
    "min_chars_to_split": 600,
    "max_units": 8,
    "min_units": 2,
}


@dataclass
class ClusterEval:
    method: str
    k: int
    labels: list[int]
    silhouette: float
    intra_similarity: float


def build_dynamic_units(
    sections: list[dict],
    aggregated: dict[str, object],
    options: dict | None = None,
) -> tuple[dict[str, dict], dict]:
    opts = dict(DEFAULT_OPTIONS)
    if options:
        opts.update(options)

    plan: dict[str, dict] = {}
    report = {
        "options": opts,
        "sections": {},
    }

    for section in sections:
        key = section["key"]
        raw = aggregated.get(key, [])
        bullets = _flatten_bullets(raw)
        total_chars = sum(_count_chars(b) for b in bullets)
        should_split = bool(opts.get("enabled", True)) and _should_split(bullets, total_chars, opts)

        sec_report = {
            "section_id": section["id"],
            "section_title": section["title"],
            "bullet_count": len(bullets),
            "total_chars": total_chars,
            "mode": "flat",
            "candidates": {},
            "selected": {},
        }

        if not should_split:
            plan[key] = {"mode": "flat", "bullets": bullets}
            report["sections"][key] = sec_report
            continue

        k_candidates = _k_candidates(len(bullets), opts["min_units"], opts["max_units"])
        keyword_best = _best_eval_for_method("keyword", bullets, k_candidates)
        embedding_best = _best_eval_for_method("embedding", bullets, k_candidates)
        selected_eval = _select_eval(keyword_best, embedding_best, opts["method"])

        units = _labels_to_units(bullets, selected_eval.labels)
        plan[key] = {
            "mode": "split",
            "method": selected_eval.method,
            "k": selected_eval.k,
            "units": units,
        }

        sec_report["mode"] = "split"
        sec_report["candidates"] = {
            "keyword": _eval_to_dict(keyword_best),
            "embedding": _eval_to_dict(embedding_best),
        }
        sec_report["selected"] = _eval_to_dict(selected_eval)
        report["sections"][key] = sec_report

    return plan, report


def _flatten_bullets(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, dict):
        out: list[str] = []
        for _, vals in raw.items():
            if isinstance(vals, list):
                out.extend([str(x).strip() for x in vals if str(x).strip()])
        return out
    return []


def _count_chars(text: str) -> int:
    return len(text.replace("\n", "").replace(" ", ""))


def _should_split(bullets: list[str], total_chars: int, opts: dict) -> bool:
    return (
        len(bullets) >= int(opts["min_bullets_to_split"])
        and total_chars >= int(opts["min_chars_to_split"])
    )


def _k_candidates(n: int, min_units: int, max_units: int) -> list[int]:
    high = min(max_units, max(min_units, n // 3 if n >= 6 else 2))
    return list(range(min_units, high + 1)) or [2]


def _best_eval_for_method(method: str, bullets: list[str], k_candidates: list[int]) -> ClusterEval:
    best: ClusterEval | None = None
    sim = _similarity_matrix(bullets, method)
    for k in k_candidates:
        labels = _kmedoids(sim, k, max_iter=8)
        sil = _silhouette(sim, labels)
        intra = _avg_intra_similarity(sim, labels)
        cur = ClusterEval(method=method, k=k, labels=labels, silhouette=sil, intra_similarity=intra)
        if best is None or cur.silhouette > best.silhouette:
            best = cur
    assert best is not None
    return best


def _select_eval(keyword_best: ClusterEval, embedding_best: ClusterEval, prefer: str) -> ClusterEval:
    if prefer == "keyword":
        return keyword_best
    if prefer == "embedding":
        return embedding_best
    # auto: 先比 silhouette，再比簇内相似度
    if embedding_best.silhouette > keyword_best.silhouette:
        return embedding_best
    if embedding_best.silhouette < keyword_best.silhouette:
        return keyword_best
    return embedding_best if embedding_best.intra_similarity >= keyword_best.intra_similarity else keyword_best


def _labels_to_units(bullets: list[str], labels: list[int]) -> list[dict]:
    groups: dict[int, list[str]] = {}
    for b, lb in zip(bullets, labels):
        groups.setdefault(lb, []).append(b)
    units = []
    for i, lb in enumerate(sorted(groups.keys()), start=1):
        title = _auto_title(groups[lb], i)
        units.append(
            {
                "key": f"dynamic_unit_{i}",
                "index": i,
                "title": title,
                "bullets": groups[lb],
            }
        )
    return units


def _auto_title(bullets: list[str], idx: int) -> str:
    text = "；".join(bullets)
    # 取高频 2~4 字中文片段做弱命名
    grams: dict[str, int] = {}
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
    for n in (2, 3, 4):
        for i in range(0, max(len(cjk) - n + 1, 0)):
            g = cjk[i : i + n]
            if len(set(g)) == 1:
                continue
            grams[g] = grams.get(g, 0) + 1
    top = sorted(grams.items(), key=lambda x: x[1], reverse=True)[:3]
    if top:
        return f"（{_zh_num(idx)}）{top[0][0]}相关工作"
    return f"（{_zh_num(idx)}）重点工作"


def _zh_num(n: int) -> str:
    nums = "一二三四五六七八九十"
    if 1 <= n <= 10:
        return nums[n - 1]
    return str(n)


def _similarity_matrix(bullets: list[str], method: str) -> list[list[float]]:
    n = len(bullets)
    feats = [_feature(b, method) for b in bullets]
    sim = [[0.0 for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            s = _sim(feats[i], feats[j], method)
            sim[i][j] = s
            sim[j][i] = s
    return sim


def _feature(text: str, method: str):
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)
    if method == "keyword":
        # 关键词法：字符 bigram 集合
        return {cleaned[i : i + 2] for i in range(max(0, len(cleaned) - 1))}
    # embedding 法：hash trigram 稀疏向量（最小可运行实现）
    dim = 256
    vec = [0.0] * dim
    grams = [cleaned[i : i + 3] for i in range(max(0, len(cleaned) - 2))]
    if not grams and cleaned:
        grams = [cleaned]
    for g in grams:
        idx = hash(g) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _sim(a, b, method: str) -> float:
    if method == "keyword":
        if not a and not b:
            return 1.0
        inter = len(a & b)
        union = len(a | b) or 1
        return inter / union
    # cosine
    return sum(x * y for x, y in zip(a, b))


def _kmedoids(sim: list[list[float]], k: int, max_iter: int = 8) -> list[int]:
    n = len(sim)
    if n <= k:
        return list(range(n))
    step = max(1, n // k)
    medoids = [min(i * step, n - 1) for i in range(k)]
    labels = [0] * n

    for _ in range(max_iter):
        # assign
        for i in range(n):
            best = 0
            best_sim = -1.0
            for m_idx, m in enumerate(medoids):
                if sim[i][m] > best_sim:
                    best_sim = sim[i][m]
                    best = m_idx
            labels[i] = best

        # update
        changed = False
        for c in range(k):
            members = [i for i, lb in enumerate(labels) if lb == c]
            if not members:
                continue
            best_member = members[0]
            best_score = -1.0
            for cand in members:
                score = sum(sim[cand][o] for o in members)
                if score > best_score:
                    best_score = score
                    best_member = cand
            if medoids[c] != best_member:
                medoids[c] = best_member
                changed = True
        if not changed:
            break
    return labels


def _silhouette(sim: list[list[float]], labels: list[int]) -> float:
    n = len(labels)
    clusters = sorted(set(labels))
    if n <= 1 or len(clusters) <= 1:
        return 0.0
    vals = []
    for i in range(n):
        same = [j for j in range(n) if labels[j] == labels[i] and j != i]
        a = 1.0 - (sum(sim[i][j] for j in same) / len(same)) if same else 0.0
        b_vals = []
        for c in clusters:
            if c == labels[i]:
                continue
            others = [j for j in range(n) if labels[j] == c]
            if others:
                b_vals.append(1.0 - (sum(sim[i][j] for j in others) / len(others)))
        b = min(b_vals) if b_vals else 0.0
        denom = max(a, b, 1e-9)
        vals.append((b - a) / denom)
    return sum(vals) / len(vals)


def _avg_intra_similarity(sim: list[list[float]], labels: list[int]) -> float:
    n = len(labels)
    if n <= 1:
        return 1.0
    total = 0.0
    cnt = 0
    for i in range(n):
        for j in range(i + 1, n):
            if labels[i] == labels[j]:
                total += sim[i][j]
                cnt += 1
    return total / cnt if cnt else 0.0


def _eval_to_dict(ev: ClusterEval) -> dict:
    return {
        "method": ev.method,
        "k": ev.k,
        "silhouette": round(ev.silhouette, 4),
        "intra_similarity": round(ev.intra_similarity, 4),
    }
