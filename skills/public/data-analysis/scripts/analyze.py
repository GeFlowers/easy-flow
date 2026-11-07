'''以 DuckDB 加载 CSV 与 Excel 文件，提供缓存、结构检查、查询、导出和统计摘要。'''

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

try:
    import duckdb
except ImportError:
    logger.error("尚未安装 duckdb，正在安装……")
    subprocess.run([sys.executable, "-m", "pip", "install", "duckdb", "openpyxl", "-q"], check=True)
    import duckdb

try:
    import openpyxl  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl", "-q"], check=True)

# 持久化 DuckDB 数据库的缓存目录。
CACHE_DIR = os.path.join(tempfile.gettempdir(), ".data-analysis-cache")
TABLE_MAP_SUFFIX = ".table_map.json"


def compute_files_hash(files: list[str]) -> str:
    '''计算输入文件内容和路径的组合 SHA256，作为持久化缓存键。'''
    hasher = hashlib.sha256()
    for file_path in sorted(files):
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
        except OSError:
            # 文件读取失败时将路径本身纳入缓存键。
            hasher.update(file_path.encode())
    return hasher.hexdigest()


def get_cache_db_path(files_hash: str) -> str:
    '''根据缓存键返回 DuckDB 数据库文件路径，不创建或打开文件。'''
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{files_hash}.duckdb")


def get_table_map_path(files_hash: str) -> str:
    '''根据缓存键返回原始表名映射 JSON 的路径。'''
    return os.path.join(CACHE_DIR, f"{files_hash}{TABLE_MAP_SUFFIX}")


def save_table_map(files_hash: str, table_map: dict[str, str]) -> None:
    '''将原始名称到安全 SQL 表名的映射保存到缓存数据库旁。'''
    path = get_table_map_path(files_hash)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table_map, f, ensure_ascii=False)


def load_table_map(files_hash: str) -> dict[str, str] | None:
    '''读取缓存表名映射；缓存不存在时返回 ``None``。'''
    path = get_table_map_path(files_hash)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def sanitize_table_name(name: str) -> str:
    '''将工作表或文件名转成合法 SQL 表名，避免特殊字符和首字符非法。'''
    sanitized = re.sub(r"[^\w]", "_", name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"t_{sanitized}"
    return sanitized


def load_files(con: duckdb.DuckDBPyConnection, files: list[str]) -> dict[str, str]:
    '''将 Excel 或 CSV 文件加载为 DuckDB 表，并返回原名到安全表名的映射。'''
    con.execute("INSTALL spatial; LOAD spatial;")
    table_map: dict[str, str] = {}

    for file_path in files:
        if not os.path.exists(file_path):
            logger.error(f"找不到文件：{file_path}")
            continue

        ext = os.path.splitext(file_path)[1].lower()

        if ext in (".xlsx", ".xls"):
            _load_excel(con, file_path, table_map)
        elif ext == ".csv":
            _load_csv(con, file_path, table_map)
        else:
            logger.warning(f"不支持的文件格式：{ext}（{file_path}）")

    return table_map


def _load_excel(
    con: duckdb.DuckDBPyConnection, file_path: str, table_map: dict[str, str]
) -> None:
    '''将 Excel 的所有工作表载入 DuckDB，重名表会加后缀防止覆盖。'''
    import openpyxl

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheet_names = wb.sheetnames
    wb.close()

    for sheet_name in sheet_names:
        table_name = sanitize_table_name(sheet_name)

        # 为重名数据表添加序号，避免覆盖已有表。
        original_table_name = table_name
        counter = 1
        while table_name in table_map.values():
            table_name = f"{original_table_name}_{counter}"
            counter += 1

        try:
            con.execute(
                f"""
                CREATE TABLE "{table_name}" AS
                SELECT * FROM st_read(
                    '{file_path}',
                    layer = '{sheet_name}',
                    open_options = ['HEADERS=FORCE', 'FIELD_TYPES=AUTO']
                )
            """
            )
            table_map[sheet_name] = table_name
            row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[
                0
            ]
            logger.info(
                f"  已加载工作表 '{sheet_name}' → 表 '{table_name}'（{row_count} 行）"
            )
        except Exception as e:
            logger.warning(f"  加载工作表 '{sheet_name}' 失败：{e}")


def _load_csv(
    con: duckdb.DuckDBPyConnection, file_path: str, table_map: dict[str, str]
) -> None:
    '''使用 DuckDB 自动识别 CSV 格式并载入单表，处理表名冲突。'''
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    table_name = sanitize_table_name(base_name)

    # 为重名数据表添加序号，避免覆盖已有表。
    original_table_name = table_name
    counter = 1
    while table_name in table_map.values():
        table_name = f"{original_table_name}_{counter}"
        counter += 1

    try:
        con.execute(
            f"""
            CREATE TABLE "{table_name}" AS
            SELECT * FROM read_csv_auto('{file_path}')
        """
        )
        table_map[base_name] = table_name
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        logger.info(
            f"  已加载逗号分隔值文件 '{base_name}' → 表 '{table_name}'（{row_count} 行）"
        )
    except Exception as e:
        logger.warning(f"  加载逗号分隔值文件 '{base_name}' 失败：{e}")


def action_inspect(con: duckdb.DuckDBPyConnection, table_map: dict[str, str]) -> str:
    '''输出表的行数、字段类型、非空计数和有限样本，辅助数据探索。'''
    output_parts = []

    for original_name, table_name in table_map.items():
        output_parts.append(f"\n{'=' * 60}")
        output_parts.append(f'表：{original_name}（查询名称："{table_name}"）')
        output_parts.append(f"{'=' * 60}")

        # 获取行数。
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        output_parts.append(f"行数：{row_count}")

        # 获取列信息。
        columns = con.execute(f'DESCRIBE "{table_name}"').fetchall()
        output_parts.append(f"\n列（{len(columns)}）：")
        output_parts.append(f"{'名称':<30} {'类型':<15} {'可为空'}")
        output_parts.append(f"{'-' * 30} {'-' * 15} {'-' * 8}")
        for col in columns:
            col_name, col_type, nullable = col[0], col[1], col[2]
            output_parts.append(f"{col_name:<30} {col_type:<15} {nullable}")

        # 统计每列非空值数量。
        col_names = [col[0] for col in columns]
        non_null_parts = []
        for c in col_names:
            non_null_parts.append(f'COUNT("{c}") as "{c}"')
        non_null_sql = f'SELECT {", ".join(non_null_parts)} FROM "{table_name}"'
        try:
            non_null_counts = con.execute(non_null_sql).fetchone()
            output_parts.append("\n非空数量：")
            for i, c in enumerate(col_names):
                output_parts.append(f"  {c}: {non_null_counts[i]} / {row_count}")
        except Exception:
            pass

        # 读取前五行作为样本。
        output_parts.append("\n样本数据（前 5 行）：")
        try:
            sample = con.execute(f'SELECT * FROM "{table_name}" LIMIT 5').fetchdf()
            output_parts.append(sample.to_string(index=False))
        except Exception:
            sample = con.execute(f'SELECT * FROM "{table_name}" LIMIT 5').fetchall()
            header = [col[0] for col in columns]
            output_parts.append("  " + " | ".join(header))
            for row in sample:
                output_parts.append("  " + " | ".join(str(v) for v in row))

    result = "\n".join(output_parts)
    print(result)
    return result


def action_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    table_map: dict[str, str],
    output_file: str | None = None,
) -> str:
    '''执行用户 SQL，并按需要格式化或导出结果；查询前替换原始表名映射。'''
    # 在查询中将原始工作表或文件名替换为安全表名。
    modified_sql = sql
    for original_name, table_name in sorted(
        table_map.items(), key=lambda x: len(x[0]), reverse=True
    ):
        if original_name != table_name:
            # 仅替换尚未加引号的名称。
            modified_sql = re.sub(
                rf"\b{re.escape(original_name)}\b",
                f'"{table_name}"',
                modified_sql,
            )

    try:
        result = con.execute(modified_sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
    except Exception as e:
        error_msg = f"查询错误：{e}\n\n可用表：\n"
        for orig, tbl in table_map.items():
            cols = con.execute(f'DESCRIBE "{tbl}"').fetchall()
            col_names = [c[0] for c in cols]
            error_msg += f'  "{tbl}" ({orig}): {", ".join(col_names)}\n'
        print(error_msg)
        return error_msg

    # 根据指定路径导出结果。
    if output_file:
        return _export_results(columns, rows, output_file)

    # 将结果格式化为表格输出。
    return _format_table(columns, rows)


def _format_table(columns: list[str], rows: list[tuple]) -> str:
    '''将查询列和行转换为限宽的终端可读表格。'''
    if not rows:
        msg = "查询返回 0 行。"
        print(msg)
        return msg

    # 计算各列宽度。
    col_widths = [len(str(c)) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    # 限制最大列宽。
    max_width = 40
    col_widths = [min(w, max_width) for w in col_widths]

    # 组装表格内容。
    parts = []
    header = " | ".join(str(c).ljust(col_widths[i]) for i, c in enumerate(columns))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(columns)))
    parts.append(header)
    parts.append(separator)
    for row in rows:
        row_str = " | ".join(
            str(v)[:max_width].ljust(col_widths[i]) for i, v in enumerate(row)
        )
        parts.append(row_str)

    parts.append(f"\n（{len(rows)} 行）")
    result = "\n".join(parts)
    print(result)
    return result


def _export_results(columns: list[str], rows: list[tuple], output_file: str) -> str:
    '''将结果导出为 CSV、JSON 或 Markdown；不支持的格式会报错。'''
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    ext = os.path.splitext(output_file)[1].lower()

    if ext == ".csv":
        import csv

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)

    elif ext == ".json":
        records = []
        for row in rows:
            record = {}
            for i, col in enumerate(columns):
                val = row[i]
                # 将无法直接序列化为 JSON 的值转换为可写入形式。
                if hasattr(val, "isoformat"):
                    val = val.isoformat()
                elif isinstance(val, (bytes, bytearray)):
                    val = val.hex()
                record[col] = val
            records.append(record)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False, default=str)

    elif ext == ".md":
        with open(output_file, "w", encoding="utf-8") as f:
            # 写入表头。
            f.write("| " + " | ".join(columns) + " |\n")
            f.write("| " + " | ".join("---" for _ in columns) + " |\n")
            # 写入数据行。
            for row in rows:
                f.write(
                    "| " + " | ".join(str(v).replace("|", "\\|") for v in row) + " |\n"
                )
    else:
        msg = f"不支持的输出格式：{ext}。请使用 .csv、.json 或 .md"
        print(msg)
        return msg

    msg = f"结果已导出到 {output_file}（{len(rows)} 行）"
    print(msg)
    return msg


def action_summary(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    table_map: dict[str, str],
) -> str:
    '''按字段类型汇总行数、空值、数值统计和高频类别。'''
    # 将原始表名解析为实际表名。
    resolved = table_map.get(table_name, table_name)

    try:
        columns = con.execute(f'DESCRIBE "{resolved}"').fetchall()
    except Exception:
        available = ", ".join(f'"{t}" ({o})' for o, t in table_map.items())
        msg = f"找不到表 '{table_name}'。可用表：{available}"
        print(msg)
        return msg

    row_count = con.execute(f'SELECT COUNT(*) FROM "{resolved}"').fetchone()[0]

    output_parts = []
    output_parts.append(f"\n统计摘要：{table_name}")
    output_parts.append(f"总行数：{row_count}")
    output_parts.append(f"{'=' * 70}")

    numeric_types = {
        "BIGINT",
        "INTEGER",
        "SMALLINT",
        "TINYINT",
        "DOUBLE",
        "FLOAT",
        "DECIMAL",
        "HUGEINT",
        "REAL",
        "NUMERIC",
    }

    for col in columns:
        col_name, col_type = col[0], col[1].upper()
        output_parts.append(f"\n--- {col_name} ({col[1]}) ---")

        # 去除类型参数，取得基础类型。
        base_type = re.sub(r"\(.*\)", "", col_type).strip()

        if base_type in numeric_types:
            try:
                stats = con.execute(f"""
                    SELECT
                        COUNT("{col_name}") as count,
                        AVG("{col_name}")::DOUBLE as mean,
                        STDDEV("{col_name}")::DOUBLE as std,
                        MIN("{col_name}") as min,
                        QUANTILE_CONT("{col_name}", 0.25) as q25,
                        MEDIAN("{col_name}") as median,
                        QUANTILE_CONT("{col_name}", 0.75) as q75,
                        MAX("{col_name}") as max,
                        COUNT(*) - COUNT("{col_name}") as null_count
                    FROM "{resolved}"
                """).fetchone()
                labels = [
                    "数量",
                    "均值",
                    "标准差",
                    "最小值",
                    "25%",
                    "50%",
                    "75%",
                    "最大值",
                    "空值数",
                ]
                for label, val in zip(labels, stats):
                    if isinstance(val, float):
                        output_parts.append(f"  {label:<8}: {val:,.4f}")
                    else:
                        output_parts.append(f"  {label:<8}: {val}")
            except Exception as e:
                output_parts.append(f"  计算统计量出错：{e}")
        else:
            try:
                stats = con.execute(f"""
                    SELECT
                        COUNT("{col_name}") as count,
                        COUNT(DISTINCT "{col_name}") as unique_count,
                        MODE("{col_name}") as mode_val,
                        COUNT(*) - COUNT("{col_name}") as null_count
                    FROM "{resolved}"
                """).fetchone()
                output_parts.append(f"  数量    ：{stats[0]}")
                output_parts.append(f"  唯一值数：{stats[1]}")
                output_parts.append(f"  最常见值：{stats[2]}")
                output_parts.append(f"  空值数  ：{stats[3]}")

                # 展示出现频率最高的五个值。
                top_vals = con.execute(f"""
                    SELECT "{col_name}", COUNT(*) as freq
                    FROM "{resolved}"
                    WHERE "{col_name}" IS NOT NULL
                    GROUP BY "{col_name}"
                    ORDER BY freq DESC
                    LIMIT 5
                """).fetchall()
                if top_vals:
                    output_parts.append("  高频值：")
                    for val, freq in top_vals:
                        pct = (freq / row_count * 100) if row_count > 0 else 0
                        output_parts.append(f"    {val}: {freq} ({pct:.1f}%)")
            except Exception as e:
                output_parts.append(f"  计算统计量出错：{e}")

    result = "\n".join(output_parts)
    print(result)
    return result


def main():
    '''解析命令行参数，复用或创建缓存数据库，并执行选定的数据分析操作。'''
    parser = argparse.ArgumentParser(description="使用 DuckDB 分析 Excel／CSV（Comma-Separated Values，逗号分隔值）文件")
    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        help="Excel（.xlsx／.xls）或逗号分隔值文件路径",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["inspect", "query", "summary"],
        help="执行操作：inspect（检查）、query（查询）或 summary（汇总）",
    )
    parser.add_argument(
        "--sql",
        type=str,
        default=None,
        help="待执行的 SQL（Structured Query Language，结构化查询语言），query 操作必填",
    )
    parser.add_argument(
        "--table",
        type=str,
        default=None,
        help="汇总表名，summary 操作必填",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default=None,
        help="结果导出路径（.csv／.json／.md）",
    )
    args = parser.parse_args()

    # 校验参数之间的依赖关系。
    if args.action == "query" and not args.sql:
        parser.error("query 操作必须提供 --sql")
    if args.action == "summary" and not args.table:
        parser.error("summary 操作必须提供 --table")

    # 计算文件内容哈希，用于查找缓存。
    files_hash = compute_files_hash(args.files)
    db_path = get_cache_db_path(files_hash)
    cached_table_map = load_table_map(files_hash)

    if cached_table_map and os.path.exists(db_path):
        # 命中缓存：以只读方式连接已有数据库。
        logger.info(f"命中缓存，使用缓存数据库：{db_path}")
        con = duckdb.connect(db_path, read_only=True)
        table_map = cached_table_map
        logger.info(
            f"已从缓存加载 {len(table_map)} 张表：{', '.join(table_map.keys())}"
        )
    else:
        # 未命中缓存：载入文件并将结果保存到数据库。
        logger.info("首次加载文件，之后将使用缓存……")
        con = duckdb.connect(db_path)
        table_map = load_files(con, args.files)

        if not table_map:
            logger.error("未加载任何表，请检查文件路径与格式。")
            # 删除未能载入任何数据的空数据库文件。
            con.close()
            if os.path.exists(db_path):
                os.remove(db_path)
            sys.exit(1)

        # 保存表名映射，供后续缓存查询使用。
        save_table_map(files_hash, table_map)
        logger.info(
            f"\n已加载 {len(table_map)} 张表：{', '.join(table_map.keys())}"
        )
        logger.info(f"缓存数据库已保存到：{db_path}")

    # 执行所选分析操作。
    if args.action == "inspect":
        action_inspect(con, table_map)
    elif args.action == "query":
        action_query(con, args.sql, table_map, args.output_file)
    elif args.action == "summary":
        action_summary(con, args.table, table_map)

    con.close()


if __name__ == "__main__":
    main()
