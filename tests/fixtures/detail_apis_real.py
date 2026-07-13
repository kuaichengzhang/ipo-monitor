"""三所详情接口真实返回节选(2026-07-13 浏览器实测),用于解析器测试。"""

# 上交所 GP_COMMON_FILE_SEARCH auditId=2239(思朗科技,5份文件全真实)
SSE_FILES = [
    {"fileTitle": "北京市金杜律师事务所关于上海思朗科技股份有限公司首次公开发行股票并在科创板上市的法律意见书",
     "filePath": "/disclosure/announcement/c/202607/002239_20260707_BTGE.pdf", "fileTypeMap": "I0031", "fileUpdTime": "20260707173007"},
    {"fileTitle": "容诚会计师事务所（特殊普通合伙）关于上海思朗科技股份有限公司首次公开发行股票并在科创板上市的财务报告及审计报告",
     "filePath": "/disclosure/announcement/c/202607/002239_20260707_5EJX.pdf", "fileTypeMap": "I0021", "fileUpdTime": "20260707173007"},
    {"fileTitle": "国泰海通证券股份有限公司关于上海思朗科技股份有限公司首次公开发行股票并在科创板上市的上市保荐书",
     "filePath": "/disclosure/announcement/c/202607/002239_20260707_9XXU.pdf", "fileTypeMap": "I0061", "fileUpdTime": "20260707173007"},
    {"fileTitle": "国泰海通证券股份有限公司关于上海思朗科技股份有限公司首次公开发行股票并在科创板上市的发行保荐书",
     "filePath": "/disclosure/announcement/c/202607/002239_20260707_MZ9S.pdf", "fileTypeMap": "I0051", "fileUpdTime": "20260707173007"},
    {"fileTitle": "上海思朗科技股份有限公司科创板首次公开发行股票招股说明书（申报稿）",
     "filePath": "/disclosure/announcement/c/202607/002239_20260707_M7F6.pdf", "fileTypeMap": "I0011", "fileUpdTime": "20260707173007"},
]

# 深交所 projectrends/details id=1003977(田园生化)disclosureMaterials 节选:招股说明书3版+保荐书
SZSE_DETAIL = {"disclosureMaterials": [
    {"matnm": "招股说明书", "dfnm": "1-1 招股说明书.pdf", "ddt": "2026-06-30",
     "dfpth": "/UpFiles/rasinfodisc1/202606/RAS_202606_301700C477277F838A4961846B5A047E2F655B.pdf"},
    {"matnm": "招股说明书", "dfnm": "1-1 招股说明书.pdf", "ddt": "2025-12-30",
     "dfpth": "/UpFiles/rasinfodisc1/202512/RAS_202512_301655CDC63BF5AF19486699A2914815B9FF0E.pdf"},
    {"matnm": "招股说明书", "dfnm": "1-1 招股说明书.pdf", "ddt": "2025-06-20",
     "dfpth": "/UpFiles/rasinfodisc1/202506/RAS_202506_2022059125626FEC144437B97A8793D962CFD0.pdf"},
    {"matnm": "发行保荐书", "dfnm": "3-1-2 发行保荐书.pdf", "ddt": "2026-06-30",
     "dfpth": "/UpFiles/rasinfodisc1/202606/RAS_202606_301700E9717B9C4DAD4672AF5CA714A6703EB7.pdf"},
], "enquiryResponseAttachment": [
    {"dfnm": "发行人及中介机构回复意见.pdf", "ddt": "2026-07-13",
     "dfpth": "/UpFiles/rasinfodisc1/202607/RAS_202607_131510707B801BBAFA4305B4A0FF16561FED2C.pdf"},
]}

# 北交所 infoDetailResult id=637(德硕科技)xxgkInfo 分组结构节选(真实结构+真实路径,
# 补入一组招股说明书文件以覆盖挑选逻辑;分组名与字段名均为实测)
BSE_DETAIL = {"xxgkInfo": {
    "GPFXBJS": {"SYG": [
        {"companyName": "德硕科技", "disclosureTitle": "德硕科技:发行保荐书（上会稿）",
         "destFilePath": "/disclosure/2026/2026-02-27/1772190374_071900.pdf", "publishDate": "2026-02-27"}],
        "BHG": [
        {"companyName": "德硕科技", "disclosureTitle": "德硕科技:发行保荐书（报会稿）",
         "destFilePath": "/disclosure/2026/2026-07-10/1783695860_165590.pdf", "publishDate": "2026-07-10"}]},
    "GPFXSMS": {"SYG": [
        {"companyName": "德硕科技", "disclosureTitle": "德硕科技:招股说明书（上会稿）",
         "destFilePath": "/disclosure/2026/2026-02-27/1772190374_071901.pdf", "publishDate": "2026-02-27"}],
        "BHG": [
        {"companyName": "德硕科技", "disclosureTitle": "德硕科技:招股说明书（报会稿）",
         "destFilePath": "/disclosure/2026/2026-07-10/1783695860_165591.pdf", "publishDate": "2026-07-10"}]},
}}
