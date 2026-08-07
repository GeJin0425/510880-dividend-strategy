# 510880 红利ETF · MA250策略仪表盘

上证红利ETF(510880)的MA250均值回归策略研究，每日自动更新的公开仪表盘。

**策略摘要**：价格接近MA250时买入，远离MA250时卖出；空仓期配置511260十年国债ETF。2018年至今回测年化约+22%，最大回撤-13.9%，23笔交易全部盈利（历史数据，不代表未来收益）。

- 在线仪表盘：https://gejin0425.github.io/510880-dividend-strategy/
- 每日北京时间15:40自动抓取行情、重新计算指标并发布（GitHub Actions）
- 详细设计文档：[docs/superpowers/specs/2026-08-06-github-pages-dashboard-design.md](docs/superpowers/specs/2026-08-06-github-pages-dashboard-design.md)

## 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.export        # 生成 site/data.json
python -m http.server 8000 --directory site   # 本地预览
```

## 维护：每年1月更新分红列表

`pipeline/fetch.py` 中的 `DIVIDENDS_510880` 列表记录了510880历年的（除息日，每份分红金额）。510880每年1月都会分红一次，**分红公告后需要在列表最前面新增一条 `(ex_date, amount)` 记录**——具体除息日和每份分红金额可在东方财富查询：搜索"510880" → 分红送配。

如果漏更新，前复权价格序列（以及由此派生的MA250、偏离度等全部策略信号）会从下一次除息日起悄悄产生偏差，且不会有任何报错提示——只有信号逐渐"跑偏"，很难第一时间察觉。

## 维护：keepalive 工作流

`.github/workflows/keepalive.yml` 每月对仓库做一次无意义提交，目的是防止 GitHub 在60天无提交后自动停用 `deploy.yml` 里的每日定时任务（`schedule` 触发器的平台规则，与本项目逻辑无关）。

## 免责声明

本仓库是个人量化研究记录，不构成投资建议。历史回测结果不代表未来收益。
