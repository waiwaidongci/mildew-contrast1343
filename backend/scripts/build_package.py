"""在库房本地把巡检 CSV 汇总成可上交的计数包。

只输出两组样本数、六项条件命中数和查重凭据；巡检原表、单号和架位不写入包。
用法：
    python -m scripts.build_package 巡检.csv --room 东一库 --reference PKG-20261120-东一库 \
        [--version 1] [--humidity-threshold 65] > package.json
"""

import argparse
import json
from pathlib import Path

from src.domain.merge import build_package
from src.domain.spec import SPEC
from src.services.validation import normalize_params, parse_rows


def main():
    parser = argparse.ArgumentParser(description='把库房本地巡检 CSV 汇总为计数包')
    parser.add_argument('csv', type=Path, help='库房本地巡检 CSV 路径')
    parser.add_argument('--room', required=True, help='本库房名称，须与合并参数一致')
    parser.add_argument('--reference', required=True, help='包编号，便于交接核对')
    parser.add_argument('--version', type=int, default=1, help='包版本，换包时递增')
    parser.add_argument('--humidity-threshold', type=float, default=65, help='高湿切分点，须与合并冻结参数一致')
    parser.add_argument('--smoothing', type=float, default=0.5)
    parser.add_argument('--min-positive-count', type=int, default=3)
    parser.add_argument('--min-total-count', type=int, default=5)
    parser.add_argument('--min-growth', type=float, default=1.5)
    args = parser.parse_args()

    params = normalize_params({
        'humidity_threshold': args.humidity_threshold,
        'smoothing': args.smoothing,
        'min_positive_count': args.min_positive_count,
        'min_total_count': args.min_total_count,
        'min_growth': args.min_growth,
    })
    rows = parse_rows(args.csv.read_text(encoding='utf-8-sig'))
    package = build_package(rows, args.room, params, args.reference, args.version)
    package['params'] = params
    package['original_rows_kept_local'] = True
    package['field_note'] = '本包不含巡检单号、架位或原始行；查重凭据为巡检单号摘要。'
    print(json.dumps(package, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
