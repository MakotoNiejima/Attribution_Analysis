"""常量定义"""

SUPPORTED_METRIC = "order_conversion_rate"
MARKET_METRIC = "market_performance"

_METRIC_ALIASES = {
    "order_conversion_rate": SUPPORTED_METRIC,
    "conversion_rate": SUPPORTED_METRIC,
    "下单转化率": SUPPORTED_METRIC,
    "有效下单转化率": SUPPORTED_METRIC,
    "market_performance": MARKET_METRIC,
    "roi": MARKET_METRIC,
    "投放效率": MARKET_METRIC,
    "广告效率": MARKET_METRIC,
    "渠道效率": MARKET_METRIC,
    "市场表现": MARKET_METRIC,
}

_UNSUPPORTED_METRIC_KEYWORDS = {
    "客单价": "客单价",
    "复购": "复购率",
    "库存": "库存",
    "周转率": "周转率",
    "周转": "周转率",
}
