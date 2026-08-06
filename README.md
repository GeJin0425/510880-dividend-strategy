# 510880 红利ETF · MA250策略仪表盘

上证红利ETF(510880)的MA250均值回归策略研究，每日自动更新的公开仪表盘。

**策略摘要**：价格接近MA250时买入，远离MA250时卖出；空仓期配置511260十年国债ETF。2018年至今回测年化约+20%，最大回撤-13.9%，26笔交易全部盈利（历史数据，不代表未来收益）。

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

## 免责声明

本仓库是个人量化研究记录，不构成投资建议。历史回测结果不代表未来收益。
