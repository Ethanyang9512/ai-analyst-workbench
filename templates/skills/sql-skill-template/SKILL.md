---
name: sql-skill-template
description: （写“什么时候用”，不写“这是什么”。例：要按周、按方案取到期订阅明细算续费率时用；跑之前先读口径与踩坑。）复制后把目录名和 name 一起改成 sql-<主题>。
---

# {{这条 SQL 取什么}}

> 这是“取数技能”的模板：一条常用 SQL 一个技能，口径坑写在最前面，SQL 带 header 注释。
> 复制到 `~/.claude/skills/sql-<主题>/SKILL.md`，把目录名和上面的 `name` 一起改掉。`description` 写成“什么时候用”：模型靠它决定要不要加载这个技能。
> 下面的示例用的是虚构的 `demo.subscription_periods`、`demo.payments` 两张表，换成你自己的。

## 速查

- 输出：一行 = （什么粒度，例：一个到期的订阅周期）
- 主表：`demo.subscription_periods`（订阅周期，本地时间）；关联 `demo.payments`（扣款流水，UTC）
- 时间口径：（按哪个日期筛：购买日 / 扣款日 / 到期日）
- 常改的参数：时间窗、方案、渠道

## 口径与踩坑（先读完再跑）

1. （最容易错的那条放第一。例：扣款流水是 UTC，订阅表是本地时间；先把扣款时间换成本地时间，再判断是否在宽限期内。）
2. （例：一个周期可能有多条重试扣款记录，按周期取最终结果，否则会重复计数。）
3. （例：测试账号、内部赠送的订阅要剔除，字段取值看口径技能。）

## SQL

```sql
-- ============================================================
-- 步骤编号：S01
-- 文件版本：v1
-- 用途：    取到期订阅明细，给续费率分析用
-- 输出粒度：一行 = 一个到期的订阅周期
-- 输入表：  demo.subscription_periods（订阅周期，本地时间）、demo.payments（扣款流水，UTC）
-- 关键口径：
--   · 时间口径：expire_date 是到期日；扣款时间先 +8 小时换成本地时间
--   · 分子 / 分母：到期后 3 天内扣款成功的周期 ÷ 当周到期的全部周期
--   · 剔除规则：剔除测试账号和内部赠送订阅（is_test = 0、is_gift = 0）
-- 输出字段：subscription_id | 订阅号 | -
--           period_no | 第几个付费周期 | -
--           plan | 方案 | -
--           expire_date | 到期日 | 日期
--           renew_time | 续费成功时间（本地时间） | 时间
-- 预聚合程度：明细级（按周、按方案汇总留给 Excel 或分析脚本）
-- 对应 Excel：续费率分析_v1.xlsx → RAW_到期订阅明细
-- 作者 / 创建日期：
-- ============================================================
SELECT
    s.subscription_id,
    s.period_no,
    s.plan,
    s.expire_date,
    MAX(CASE WHEN p.status = 'success' THEN p.paid_at_utc + INTERVAL '8' HOUR END) AS renew_time
FROM demo.subscription_periods s
LEFT JOIN demo.payments p
       ON p.subscription_id = s.subscription_id
      AND p.period_no       = s.period_no
WHERE s.expire_date BETWEEN DATE '${start_date}' AND DATE '${end_date}'
  AND s.is_test = 0
  AND s.is_gift = 0
GROUP BY s.subscription_id, s.period_no, s.plan, s.expire_date;
```

## 常见改法

- 换方案：加 `AND s.plan IN (...)`，输出里保留 `plan` 这一列。
- 换时间窗：只改 `${start_date}`、`${end_date}`，不要改成按购买日筛。
- 要按渠道看：加 `s.channel` 一列，不要在 SQL 里 `GROUP BY` 渠道（聚合留给后面，见 `reproducible-analysis` 的“不过度聚合”）。

## 每期刷新清单

1. 改时间窗参数；最近一周要等宽限期过完再取。
2. 跑完先核对：行数、`subscription_id + period_no` 是否唯一、到期订阅数和上一期的量级是否一致。
3. 新一期出现明显异动时，先查知识库《业务事件日历》有没有对得上的事件。
4. SQL 改了口径或字段，版本号加一，旧版挪进 `sql/_archive/`，在 `sql/_CHANGELOG.md` 记一行。
