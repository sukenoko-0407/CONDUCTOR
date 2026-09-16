#!/usr/bin/env python
"""CONDUCTOR 0.2.1 診断モジュール エントリポイント。

計測専用。Finding は出さない。設計判断に必要な数値だけを返す。

使い方:
    pixi run selftest                       # 合成データで配線を確認（データ不要）
    cp config.example.yaml config.yaml      # 設定を作る
    pixi run run                            # 実データで計測

段階ごとに結果を書き出すため、途中で止まっても手前の段階の結果は残る。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import traceback
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diagnosis import (  # noqa: E402
    confounders, contexts, digest, dryrun, endpoints, fragments, independence,
    inputs, landscape, report, structure, transforms,
)


def _write(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if path.endswith(".json"):
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
        else:
            fh.write(payload)


def _stage(name: str, label: str, fn: Callable[[], Any], results: dict, outdir: str) -> None:
    print(f"[{name}] {label} ...", flush=True)
    t0 = time.time()
    try:
        value = fn()
        results[name] = value
        _write(os.path.join(outdir, "stages", f"{name}.json"), value)
        print(f"[{name}] 完了 ({time.time() - t0:.1f}s)", flush=True)
    except Exception:
        err = traceback.format_exc()
        results[name] = {"error": err.splitlines()[-1]}
        _write(os.path.join(outdir, "stages", f"{name}.error.txt"), err)
        print(f"[{name}] 失敗 — 続行します\n{err}", file=sys.stderr, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="設定 YAML のパス")
    ap.add_argument("--selftest", action="store_true", help="合成データで配線を確認する")
    args = ap.parse_args()

    if not args.selftest and not args.config:
        ap.error("--config か --selftest のどちらかを指定してください")

    if args.selftest:
        ds = inputs.make_synthetic_dataset()
        outdir = "./diagnosis_output_selftest"
        descriptor_set, neighbor_k, clusters, max_cuts, n_jobs = "fast", [5, 10], [5, 10], 300, 1
        n_perm = 3
        print(f"[selftest] 合成データ {ds.n} 化合物で実行します")
    else:
        cfg = inputs.load_config(args.config)
        ds = inputs.load_dataset(cfg)
        outdir = cfg.output_dir
        descriptor_set = cfg.descriptor_set
        neighbor_k = cfg.neighbor_k
        clusters = cfg.n_clusters_grid
        max_cuts = cfg.max_cuts_per_molecule
        n_jobs = cfg.n_jobs
        n_perm = cfg.n_permutations
        print(f"[input] {ds.n} 化合物を読み込みました（並列 {n_jobs}）")

    t_start = time.time()
    results: dict[str, Any] = {"input": ds.input_issues}
    _write(os.path.join(outdir, "stages", "input.json"), ds.input_issues)

    _stage("endpoints", "Endpoint 分布・重なり・選択バイアス",
           lambda: endpoints.run(ds), results, outdir)
    _stage("diversity", "構造多様性（環系・骨格・Tanimoto）",
           lambda: structure.run_diversity(ds), results, outdir)
    _stage("noise", "測定ノイズ床の推定",
           lambda: structure.run_noise_floor(ds), results, outdir)
    _stage("transforms", "変換3クラス・Cliff 抽出率・L7 系列",
           lambda: transforms.run(ds, max_cuts), results, outdir)
    _stage("landscape", "局所平坦性 λ と L1a/L1b",
           lambda: landscape.run(ds, descriptor_set, neighbor_k, clusters, n_jobs),
           results, outdir)
    _stage("independence", "非独立性と実効標本サイズ",
           lambda: independence.run(ds), results, outdir)
    _stage("fragments", "フラグメント統計と λ_frag（L2b の成否）",
           lambda: fragments.run(ds, max_cuts), results, outdir)
    _stage("contexts", "文脈カタログのサイズ・重複度・翻訳可能性",
           lambda: contexts.run(ds, descriptor_set, clusters, n_jobs), results, outdir)
    _stage("confounders", "交絡の強さ",
           lambda: confounders.run(ds), results, outdir)
    _stage("dryrun", f"パイプラインのドライラン（並べ替え {n_perm} 回）",
           lambda: dryrun.run(ds, descriptor_set, clusters, n_jobs, max_cuts, n_perm),
           results, outdir)

    meta = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "descriptor_set": descriptor_set,
        "n_jobs": n_jobs,
        "elapsed_sec": round(time.time() - t_start, 1),
        "module_version": "0.2.1",
    }
    _write(os.path.join(outdir, "diagnosis_report.json"),
           {"meta": meta, "results": results})
    _write(os.path.join(outdir, "diagnosis_report.md"),
           report.render(results, meta))

    digest_text = digest.render(results, meta)
    _write(os.path.join(outdir, "diagnosis_digest.txt"), digest_text)

    failed = [k for k, v in results.items() if isinstance(v, dict) and "error" in v]
    print(f"\n完了: {outdir}/ ({meta['elapsed_sec']}s)")
    if failed:
        print(f"失敗した段階: {failed}（成功分だけが載ります）")

    print("\n" + "=" * 64)
    print("以下の枠内だけを書き写して設計担当へ渡してください。")
    print("数字と行の順序を正確に。ラベルは多少崩れても構いません。")
    print("=" * 64)
    print(digest_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
