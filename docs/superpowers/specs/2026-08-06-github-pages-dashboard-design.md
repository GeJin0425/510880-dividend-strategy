# 510880 红利ETF策略仪表盘 — GitHub Pages 自动化发布 设计文档

- 日期:2026-08-06
- 状态:已批准(brainstorming阶段)

## 背景

现有项目`/Users/ge/Desktop/Stock/红利研究/`已经完成510880上证红利ETF的MA250均值回归策略研究与回测(年化+20.4%,最大回撤-13.9%,夏普1.52,26笔交易),并有一套Python脚本(`update_all.py` + `src/`)每日手动运行生成一张matplotlib静态PNG仪表盘(3218×3942像素)。

目标:把这套策略的仪表盘迁移到一个独立的GitHub仓库,通过GitHub Actions每天自动抓数据、算指标、发布到GitHub Pages,做成一个持续更新的公开网页,并显著提升视觉设计质量。

本设计文档只覆盖**510880单一策略**的发布(V1范围)。512890红利低波和空仓轮动子研究本次不纳入,留作后续独立迭代。

## 范围与非目标

**范围内:**
- 新建独立GitHub仓库`GeJin0425/510880-dividend-strategy`,公开(public)可见
- 每日自动:抓510880+511260行情 → 算MA/RSI/MACD/偏离度/买卖信号 → 生成交易记录 → 导出JSON → 发布静态网页
- 深色终端风交互式仪表盘,替代静态PNG
- GitHub Actions定时任务(cron) + 手动触发

**非目标(本次不做):**
- 512890、空仓轮动子研究的发布
- 用户登录/私有访问控制
- 自定义域名(先用默认`gejin0425.github.io/510880-dividend-strategy`)
- 移动端App或推送通知

## 架构总览

```
GeJin0425/510880-dividend-strategy/
├── .github/workflows/deploy.yml   # 定时+手动触发,抓数据→生成JSON→部署Pages
├── pipeline/
│   ├── Ashare.py                  # 行情接口(从红利研究/src/复用)
│   ├── fetch.py                   # 拉取510880/511260日线 + 前复权处理
│   ├── indicators.py              # MA10/20/60/250、偏离度、RSI14/6、MACD、M3+买卖信号状态机
│   ├── backtest.py                # 2018年至今全历史交易记录生成(含511260空仓期收益)
│   └── export.py                  # 汇总所有计算结果为 site/data.json
├── site/
│   ├── index.html                 # 单页仪表盘
│   ├── style.css                  # 深色终端主题
│   └── app.js                     # ECharts渲染 + 折叠面板交互 + fetch data.json渲染
├── requirements.txt               # pandas, numpy, requests
└── README.md                      # 策略说明(参考红利研究/README.md精简版)
```

数据管线代码是把`红利研究/src/visualize_final.py`、`ma250_tuning.py`里已经跑通、已验证过的指标计算与M3+买卖信号逻辑原样迁移(不重新设计策略),唯一变化是输出目标从"matplotlib PNG"变成"结构化JSON"。

## 部署方式

GitHub Actions每次运行时:

1. `actions/checkout`
2. `actions/setup-python` + `pip install -r requirements.txt`
3. 运行`pipeline/export.py`:抓取最新行情 → 计算指标/信号/回测 → 写出`site/data.json`
4. `actions/upload-pages-artifact`:把`site/`整个目录(含刚生成的`data.json`)打包上传
5. `actions/deploy-pages`:发布到GitHub Pages

**关键决策:不把每日生成的`data.json`提交回git。** 只有代码变更(策略调整、页面改版)才产生commit,数据本身作为部署产物直接发布,main分支历史保持干净。

Pages仓库设置需要:Settings → Pages → Build and deployment → Source选择"GitHub Actions"(而非"Deploy from a branch")。

## 前端设计:深色终端风

**配色**
| 用途 | 颜色 |
|------|------|
| 背景 | `#0d1117` |
| 正文文字 | `#c9d1d9` |
| 多头/买入/正收益 | `#3fb950`(荧光绿) |
| 空头/卖出/负收益 | `#f85149`(红) |
| 强调色(标题/链接/主线) | `#58a6ff` |
| 网格线/分割线 | `#21262d`(低对比度) |

**字体**:数字类内容(指标卡片、表格数值)用等宽字体强化"终端"质感;标题/说明文字用系统UI字体保证可读性。

**页面结构(从上到下)**
1. 顶部:状态点(●持仓 / ○空仓)+ 项目标题 + 数据更新时间戳
2. 核心指标卡片行(6个):年化收益、最大回撤、夏普比率、胜率、平均盈利、510880持仓占比
3. 当前状态大卡片:当前持仓标的、偏离度、RSI、买卖触发价(不复权,与券商一致)、操作信号
4. 主图(默认展开):价格 + MA10/MA20/MA60/MA250,买卖点标注,买卖区间阴影,支持缩放(dataZoom)和hover查看当日全部指标
5. 折叠面板(默认收起,点击展开):
   - 偏离度柱状图
   - RSI(14/6)
   - MACD
   - 策略 vs 买入持有净值曲线(含超额收益填充)
   - 卖出原因分布(横向条形图,替代原饼图——深色小尺寸下饼图辨识度差)
   - 全部交易明细(可排序表格,而非截图)
6. 页脚:数据来源说明 + 更新时间戳 + 免责声明("个人量化研究记录,非投资建议,历史回测不代表未来收益")

**技术选型**:纯HTML/CSS/JS,图表库用Apache ECharts(CDN引入,内置dark主题基础,K线/折线/dataZoom/tooltip/markPoint/markArea均原生支持,无需Node构建步骤)。

**移动端**:单列自适应布局,图表高度随宽度调整,交易明细表格允许横向滚动。

## 自动化调度

- **触发时机**:`schedule` cron设为UTC `07:40`(北京时间15:40,收盘后留出数据源刷新缓冲)+ `workflow_dispatch`支持随时手动触发
- **权限**:workflow需要`permissions: pages: write, id-token: write`

## 已知风险与兜底方案

| 风险 | 兜底方案 |
|------|---------|
| GitHub Actions runner是海外IP,新浪/腾讯行情接口对外部IP的可达性未验证 | 实施阶段第一步就跑一次真实workflow验证连通性;若被限流/封锁,需评估更换数据源或改用代理 |
| 数据抓取当天失败(网络问题/接口临时不可用) | 保留前一天的`data.json`不覆盖,页面显著标注"数据获取失败,当前显示T-1数据",不能让页面挂掉或悄悄显示旧数据而不告知 |
| 非交易日/盘中误触发 | `export.py`内判断:若最新数据日期未变化,则跳过本次发布(或仍发布但时间戳照实显示) |
| 每年1月510880分红记录需要手动更新 | 沿用现有项目的做法:分红记录作为代码里的常量列表,每年1月人工加一行,和现有`红利研究`项目的维护方式一致,本次不做自动化(超出V1范围) |

## 测试与验证

- 本地先跑通`pipeline/export.py`,人工检查`data.json`结构和数值与现有`红利研究/output/510880_dashboard.png`回测结果一致(年化+20.4%等核心指标对得上)
- 本地起个静态服务器预览`site/index.html`渲染效果
- 推送到GitHub后,手动触发一次`workflow_dispatch`,确认Actions能成功抓数据、生成JSON、部署Pages
- 检查移动端(手机浏览器实际打开)布局是否正常
