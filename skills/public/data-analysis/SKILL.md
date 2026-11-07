---
name: data-analysis
description: 用户上传 Excel（.xlsx／.xls）或逗号分隔值文件，并希望分析数据、生成统计、摘要、透视表、结构化查询或探索结构化数据时使用。支持多工作表工作簿、汇总、筛选、连接，以及导出逗号分隔值、对象表示法或 Markdown 结果。
---

# 数据分析技能

## 概述

此技能使用 DuckDB 进程内分析引擎，分析用户上传的 Excel／CSV（Comma-Separated Values，逗号分隔值）文件。通过单个 Python 脚本支持结构检查、SQL（Structured Query Language，结构化查询语言）查询、统计摘要和结果导出。

## 核心能力

- 检查表格结构：工作表、列、类型、行数。
- 对上传数据执行任意结构化查询。
- 生成统计摘要：均值、中位数、标准差、百分位数、空值。
- 支持多工作表工作簿，每个工作表成为一张表。
- 将查询结果导出为逗号分隔值、JSON（JavaScript Object Notation，JavaScript 对象表示法）或 Markdown。
- 使用 DuckDB 列式引擎高效处理大文件。

## 工作流程

### 第 1 步：理解需求

用户上传数据并要求分析时，识别：

- **文件位置：** `/mnt/user-data/uploads/` 下已上传的表格路径。
- **分析目标：** 用户需要的洞察，例如摘要、筛选、汇总、比较。
- **输出格式：** 结果如何呈现，例如表格或导出文件。
- 无需检查 `/mnt/user-data` 下的文件夹。

### 第 2 步：检查文件结构

先检查上传文件，理解其结构：

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action inspect
```

返回内容：
- 工作表名称或逗号分隔值文件名。
- 列名、数据类型与非空数量。
- 每个工作表／文件的行数。
- 前 5 行样本。

### 第 3 步：执行分析

根据结构构建查询，回答用户问题。

#### 执行查询

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action query \
  --sql "SELECT category, COUNT(*) as count, AVG(amount) as avg_amount FROM Sheet1 GROUP BY category ORDER BY count DESC"
```

#### 生成统计摘要

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action summary \
  --table Sheet1
```

对数值列返回数量、均值、标准差、最小值、25%、50%、75% 分位数、最大值、空值数；对字符串列返回数量、唯一值数、最常见值、频数和空值数。

#### 导出结果

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/data.xlsx \
  --action query \
  --sql "SELECT * FROM Sheet1 WHERE amount > 1000" \
  --output-file /mnt/user-data/outputs/filtered-results.csv
```

支持以下输出格式，按扩展名自动识别：
- `.csv`：逗号分隔值。
- `.json`：记录数组。
- `.md`：Markdown 表格。

### 参数

| 参数 | 必填 | 说明 |
|-----------|----------|-------------|
| `--files` | 是 | 空格分隔的表格文件路径 |
| `--action` | 是 | `inspect`、`query`、`summary` 三选一 |
| `--sql` | `query` 时 | 待执行查询 |
| `--table` | `summary` 时 | 待汇总的表／工作表名称 |
| `--output-file` | 否 | 导出结果路径，支持 .csv／.json／.md |

> [!NOTE]
> 不要阅读 Python 文件，直接传入参数调用。

## 表命名规则

- **工作簿：** 每个工作表成为同名表，例如 `Sheet1`、`Sales`、`Revenue`。
- **逗号分隔值文件：** 表名为不含扩展名的文件名，例如 `data.csv` → `data`。
- **多个文件：** 所有文件的表在同一查询上下文中可用，可跨文件连接。
- **特殊字符：** 工作表／文件名含空格或特殊字符时会自动规范化，空格替换为下划线。数字开头或包含特殊字符的名称使用双引号，例如 `"2024_Sales"`。

## 分析模式

### 基础探索
```sql
-- 行数
SELECT COUNT(*) FROM Sheet1

-- 列中不同值
SELECT DISTINCT category FROM Sheet1

-- 数值分布
SELECT category, COUNT(*) as cnt FROM Sheet1 GROUP BY category ORDER BY cnt DESC

-- 日期范围
SELECT MIN(date_col), MAX(date_col) FROM Sheet1
```

### 汇总与分组
```sql
-- 按类别和月份统计收入
SELECT category, DATE_TRUNC('month', order_date) as month,
       SUM(revenue) as total_revenue
FROM Sales
GROUP BY category, month
ORDER BY month, total_revenue DESC

-- 消费最多的前 10 位客户
SELECT customer_name, SUM(amount) as total_spend
FROM Orders GROUP BY customer_name
ORDER BY total_spend DESC LIMIT 10
```

### 跨文件连接
```sql
-- 连接不同文件中的销售与客户信息
SELECT s.order_id, s.amount, c.customer_name, c.region
FROM sales s
JOIN customers c ON s.customer_id = c.id
WHERE s.amount > 500
```

### 窗口函数
```sql
-- 累计值与排名
SELECT order_date, amount,
       SUM(amount) OVER (ORDER BY order_date) as running_total,
       RANK() OVER (ORDER BY amount DESC) as amount_rank
FROM Sales
```

### 透视分析
```sql
-- 透视：按类别统计月收入
SELECT category,
       SUM(CASE WHEN MONTH(date) = 1 THEN revenue END) as Jan,
       SUM(CASE WHEN MONTH(date) = 2 THEN revenue END) as Feb,
       SUM(CASE WHEN MONTH(date) = 3 THEN revenue END) as Mar
FROM Sales
GROUP BY category
```

## 完整示例

用户上传 `sales_2024.xlsx`，包含 `Orders`、`Products`、`Customers` 工作表，并要求：“分析销售数据，展示收入最高的产品和月度趋势。”

### 第 1 步：检查文件

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action inspect
```

### 第 2 步：按收入排名的产品

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action query \
  --sql "SELECT p.product_name, SUM(o.quantity * o.unit_price) as total_revenue, SUM(o.quantity) as total_units FROM Orders o JOIN Products p ON o.product_id = p.id GROUP BY p.product_name ORDER BY total_revenue DESC LIMIT 10"
```

### 第 3 步：月收入趋势

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action query \
  --sql "SELECT DATE_TRUNC('month', order_date) as month, SUM(quantity * unit_price) as revenue FROM Orders GROUP BY month ORDER BY month" \
  --output-file /mnt/user-data/outputs/monthly-trends.csv
```

### 第 4 步：统计摘要

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/sales_2024.xlsx \
  --action summary \
  --table Orders
```

向用户展示结果，清楚解释发现、趋势和可执行洞察。

## 多文件示例

用户上传 `orders.csv` 和 `customers.xlsx`，询问：“哪个地区的平均订单金额最高？”

```bash
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/orders.csv /mnt/user-data/uploads/customers.xlsx \
  --action query \
  --sql "SELECT c.region, AVG(o.amount) as avg_order_value, COUNT(*) as order_count FROM orders o JOIN Customers c ON o.customer_id = c.id GROUP BY c.region ORDER BY avg_order_value DESC"
```

## 输出处理

分析后：

- 在对话中以格式化表格直接展示查询结果。
- 大量结果导出为文件，并用 `present_files` 分享。
- 始终用通俗语言解释发现并指出要点。
- 模式值得关注时，提出后续分析。
- 用户希望保留时，提供结果导出。

## 缓存

脚本自动缓存加载数据，避免每次调用都重新解析：

- 首次加载时，解析文件并保存到 `/mnt/user-data/workspace/.data-analysis-cache/` 下的持久 DuckDB 数据库。
- 缓存键为全部输入文件内容的 SHA256（Secure Hash Algorithm 256-bit，二百五十六位安全散列算法）散列；文件变化时创建新缓存。
- 相同文件的后续调用直接使用缓存数据库，几乎立即启动。
- 缓存透明，无需额外参数。

这对同一数据多次查询尤其有用，例如检查 → 查询 → 汇总。

## 注意事项

- DuckDB 支持完整查询语言，包括窗口函数、CTE（Common Table Expression，公用表表达式）、子查询和高级汇总。
- 自动解析工作簿日期列，可使用 DuckDB 日期函数，如 `DATE_TRUNC`、`EXTRACT`。
- 对超过 100 兆字节的大文件，DuckDB 无需全部加载到内存也能高效处理。
- 含空格列名使用双引号访问：`"Column Name"`。
