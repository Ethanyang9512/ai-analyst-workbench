-- ============================================================
-- 步骤编号：S01
-- 文件版本：v1
-- 用途：    取 W1–W8 到期的订阅周期明细，给续费率分析用（本例为虚构）
-- 输出粒度：一行 = 一个到期的订阅周期（subscription_id + period_no）
-- 输入表：  demo.subscription_periods（订阅周期，一行一个付费周期，时间为本地时间）
--           demo.payments（扣款流水，一个周期可能多行重试，时间为 UTC）
-- 关键口径：
--   · 时间口径：expire_date 是到期日（本地时间）；扣款流水先从 UTC 换成本地时间（+8 小时）再比较
--   · 分子：到期后 3 天内（含第 3 天）扣款成功；分母：当周到期的全部周期，不用活跃订阅数
--   · 过滤条件：只要已到期的周期（expire_date 在时间窗内），新购不在本步范围
--   · 剔除规则：剔除测试账号和内部赠送订阅，这两类不会真实扣款
-- 输出字段：subscription_id | 订阅号 | -
--           period_no | 第几个付费周期 | -
--           plan | 方案（月付 / 年付） | -
--           channel | 购买渠道 | -
--           expire_date | 到期日 | 日期
--           renew_status | 续费成功 / 主动取消 / 扣款失败 | -
--           renew_time | 续费成功时间（本地时间） | 时间
--           price_paid | 本次续费实付金额 | 元
-- 预聚合程度：明细级（按周、按方案汇总留给分析脚本）
-- 对应 Excel：续费率分析_v1.xlsx → RAW_到期订阅明细
-- 作者 / 创建日期：取数助手 / 2026-03-10
-- ============================================================
WITH pay AS (
    SELECT subscription_id,
           period_no,
           MAX(CASE WHEN status = 'success' THEN paid_at_utc + INTERVAL '8' HOUR END) AS renew_time,  -- 重试多次时取成功那次
           MAX(CASE WHEN status = 'success' THEN amount END)                          AS price_paid
    FROM demo.payments
    GROUP BY subscription_id, period_no
)
SELECT
    s.subscription_id,
    s.period_no,
    s.plan,
    s.channel,
    s.expire_date,
    CASE
        WHEN p.renew_time IS NOT NULL
         AND p.renew_time < s.expire_date + INTERVAL '4' DAY THEN '续费成功'   -- 到期后 3 天内
        WHEN s.auto_renew_off_at IS NOT NULL
         AND s.auto_renew_off_at < s.expire_date               THEN '主动取消'
        ELSE '扣款失败'
    END AS renew_status,
    p.renew_time,
    p.price_paid
FROM demo.subscription_periods s
LEFT JOIN pay p
       ON p.subscription_id = s.subscription_id
      AND p.period_no       = s.period_no
WHERE s.expire_date BETWEEN DATE '${w1_monday}' AND DATE '${w8_sunday}'
  AND s.is_test     = 0
  AND s.is_gift     = 0;
