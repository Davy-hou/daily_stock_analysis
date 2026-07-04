# 日内量化交易系统设计

> 基于 DSA 项目的日内 T+0 ETF 量化交易系统

**目标**：在现有 DSA 项目上扩展日内量化交易能力，支持历史回测验证 → 模拟交易 → 后续实盘接入

**关键约束**：A 股 ETF T+0（跨境 ETF、债券 ETF、商品 ETF），初期无券商量化接口

---

## 架构概览

```
data_provider/intraday.py ──→ src/trading/data/{loader,realtime}.py
                                       │
                                       ▼
                              strategies/{base,momentum,mean_reversion,grid}.py
                                       │
                                       ▼
                                 engine.py (回测)
                                       │
                                       ▼
                              risk_manager.py → executor.py → simulator.py
                                       │
                                       ▼
                                 reporter.py (绩效)
                                       │
                                       ▼
                    ┌─── 现有通知系统 ──→ 手机推送
                    └─── 现有 Web UI ──→ 回测结果/持仓
```

## 模块说明

### `src/trading/` 核心模块

| 模块 | 职责 |
|------|------|
| `data/loader.py` | 加载历史分钟线/Tick 数据，统一 DataFrame 格式 |
| `data/realtime.py` | 盘中和盘前实时行情接入 |
| `strategies/base.py` | 策略基类，定义 `on_bar`/`on_tick` 接口 |
| `strategies/momentum.py` | 趋势跟踪：突破前 N 根 K 线高点做多，跌破做空 |
| `strategies/mean_reversion.py` | 均值回归：ETF 溢价/折价回归 |
| `strategies/grid.py` | 网格策略：预设价差分层低吸高抛 |
| `engine.py` | 日内回测引擎，支持分钟线、T+0 多轮、费用/滑点 |
| `executor.py` | 信号 → 订单模拟执行（限价/市价 + 滑点） |
| `risk_manager.py` | 风控：仓位上限、单笔止损、日亏损上限、最大持仓时间 |
| `simulator.py` | 模拟交易运行时：实时信号 + 模拟成交 + P&L 跟踪 |
| `reporter.py` | 绩效：逐笔交易、权益曲线、夏普/最大回撤/胜率/盈亏比 |
| `config.py` | 配置：账户、策略参数、风控参数、数据源选择 |

### `data_provider/intraday.py`

统一分钟线/Tick 数据适配层，对接 TickFlow、AkShare 等数据源的分钟线与实时行情接口。

## 数据流

### 回测流程

```
历史数据加载 → 逐根 K 线驱动策略 → 信号 → 风控 → 执行(模拟) → 记录交易 → 绩效统计
```

### 模拟/实盘流程

```
实时行情 → 策略计算 → 信号 → 风控 → 订单 → 成交回报 → 持仓更新 → P&L
```

## 策略设计

### 趋势跟踪（Momentum）
- 参考对应指数期货或底层指数盘中走势
- **做多信号**：3min K 线收盘站上前 5 根 K 线高点
- **做空信号**（底仓）：跌破前 5 根 K 线低点
- **出场**：反向信号 / 固定止盈止损 / 持仓超时

### 均值回归（Mean Reversion）
- 计算实时价格与 IOPV（实时净值）偏差率
- **做多信号**：折价 > threshold（如 0.3%）
- **做空信号**：溢价 > threshold
- **出场**：回归至平水或反向阈值

### 网格（Grid）
- 根据日均波动率设定网格区间和层数
- 每格固定价差，低吸高抛
- 收盘前强制平所有网格

## 实施优先级

**MVP（第 1-2 周）**：数据结构 + 分钟线数据接入 + 回测引擎 + Momentum 策略 + 绩效报告
**V2**：Mean Reversion 策略、Grid 策略、风控模块
**V3**：实时行情 + 模拟交易、通知推送
**V4**：券商 API 对接（QMT/PTrade）

## 项目结构变化

```
src/
├── trading/           # 新增：日内量化交易模块
│   ├── __init__.py
│   ├── engine.py
│   ├── executor.py
│   ├── risk_manager.py
│   ├── simulator.py
│   ├── reporter.py
│   ├── config.py
│   └── strategies/
│       ├── __init__.py
│       ├── base.py
│       ├── momentum.py
│       ├── mean_reversion.py
│       └── grid.py
├── core/
│   └── backtest_engine.py  # 不改动，保持日线回测
data_provider/
├── intraday.py        # 新增：分钟线/Tick 数据适配
tests/
├── trading/           # 新增：日内量化模块测试
│   ├── test_engine.py
│   ├── test_strategies.py
│   └── test_data.py
```
