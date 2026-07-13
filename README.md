# IPO 监控系统 · 港交所采集器(proof of concept)

三棱镜自动化管线的第一块:每天扫港交所,列出"谁在管线里、招股书在哪",
产出结构化记录喂给后续的分诊卡 + 骨架草稿。

## 这一版能做什么

- 抓港交所「New Listing Information」(主板 + GEM),解析出:股份代号、公司名、
  标记位(W/B/Z/P/S)、上市公告 / 招股书 / 配发结果 PDF 直链、状态、页面更新日。
- 去重与状态跟踪:每天跑一次,只报**今日新增**和**状态变化**("谁递了表 / 谁过会了")。
- 导出 `data/filings.json`(全量)和 `data/state.json`(带首次见到时间)。

解析逻辑已用 2026-07-07 从港交所真实抓到的数据测过(见 `tests/`),`python tests/test_parse.py` 可复现。

## 怎么跑

```bash
pip install -r requirements.txt
python run.py
```

> 注意:必须在**能访问 hkexnews.hk 的网络环境**里跑(开发沙箱屏蔽了该域名,所以是在
> 你自己的服务器 / 本机跑,不是在对话里跑)。

每周一到五自动跑,加一条 cron:

```
0 9 * * 1-5  cd /path/to/ipo_monitor && python run.py >> data/run.log 2>&1
```

## 港交所两个源都已接通

- **招股/发行阶段**:New Listing Information HTML 表(`HKEXNewListingInfoCollector`)。
- **申请版本 / 聆讯后资料集(PHIP)阶段**(你真正的触发点):`HKEXAppProofCollector`,
  实测接口 `https://www1.hkexnews.hk/ncms/json/eds/appactive_app_sehk_c.json`(主板中文,
  另有 gem 版)。纯 JSON,记录在 `.app`;`id`=文件夹号、`a`=公司名、`hasPhip`=是否已发 PHIP。
  **`hasPhip==true` 即过会/PHIP已发 = 触发选题**,自动打 `★可选题`。PDF 链接 =
  `https://www1.hkexnews.hk/app/` + 文档相对路径。


### A股招股说明书直链(v4 已接通,三所详情接口均实测)
- 上交所:`query.sse.com.cn/commonSoaQuery.do?sqlId=GP_COMMON_FILE_SEARCH&auditId={审核编号}`(Referer必带);
  文件类型码 I0011申报稿/I0012上会稿/I0013注册稿,直链 = `static.sse.com.cn`+filePath(运行时HEAD自检兜底)
- 深交所:`www.szse.cn/api/ras/projectrends/details?id={prjid}`;disclosureMaterials 里 matnm=招股说明书取最新,
  直链 = `reportdocs.static.szse.cn`+dfpth;enquiryResponseAttachment 为问询回复PDF(留给问询监控)
- 北交所:`POST www.bse.cn/projectNewsController/infoDetailResult.do?id={记录id}`;xxgkInfo 递归扫
  disclosureTitle 含"招股说明书"取最新,直链 = `www.bse.cn`+destFilePath
- 接入点:`collectors/resolve.py`;dossier_runner 对 A股★可选题公司自动解析直链后建档

## 阶段归一化(架子的核心)

四所的审核状态叫法各不相同(港交所"招股/配发",上交所"已受理/上市委会议通过/提交注册/
注册生效")。`stages.py` 把它们统一映射到一套阶段词汇,于是:
- Paodekuai 的触发点「过会 + PHIP」在四所是同一个概念(=`过会/通过` 阶段),输出里自动打 `★可选题`;
- 分诊卡/网站可按统一阶段筛选、排序、上色。

加一个交易所 = 加一张 {原始状态 -> 统一阶段} 映射表。这就是"扩得动"。

## 四所路线图

`collectors/base.py` 定义统一接口。加一个交易所 = 写一个 `BaseCollector` 子类、
实现 `collect() -> list[Filing]`、在 `stages.py` 加一张状态映射、加进 `run.py` 的 `COLLECTORS`。
- ✅ 港交所 New Listing Information(已接通,真实数据测通)
- ✅ 港交所 申请版本 / PHIP(已接通,hasPhip 触发)
- ✅ 上交所 科创板+主板(已接通:commonSoaQuery.do / SH_XM_LB,实测 1281 项目)
- ✅ 深交所 创业板+主板(已接通:api/ras/projectrends/query?bizType=1,实测 1461 项目;官方状态字典取自接口 stageList,16 态全映射)
- ✅ 北交所(已接通:projectNewsController/infoResult.do,实测 871 项目;P码字典取自官方筛选器,日期为 Java Date 毫秒需转换,已处理)

四所要点备忘:
- 深交所:GET,pageIndex 0起,头带 Referer + X-Requested-With;返回 {totalSize, data}
- 北交所:POST 表单 page(0起)/shzt/sortfield/sorttype/keyword,返回 callback([{countsInfo, listInfo:{content,totalPages}}])
- 统一触发:PHIP(港)= 上市委会议通过(沪深北)= 「过会/通过」→ ★可选题

## 目录

```
ipo_monitor/
  models.py            # Filing 数据模型 + 港交所标记位解析
  stages.py            # 阶段归一化(四所状态词 -> 统一阶段 + 触发判定)
  state.py             # 去重 / 状态跟踪
  run.py               # CLI 入口
  collectors/
    base.py            # 采集器基类(统一接口)
    hkex.py            # 港交所采集器(已实现 + PHIP 占位)
    sse.py             # 上交所采集器(逻辑就绪 + 接口 URL 待确认)
  tests/
    test_parse.py      # 港交所:解析/去重(对真实数据)
    test_sse.py        # 上交所/架子:状态归一化 + 映射 + 跨所统一
    fixtures/          # 真实抓取样本
  data/                # 运行时产出(filings.json / state.json / run.log)
```
