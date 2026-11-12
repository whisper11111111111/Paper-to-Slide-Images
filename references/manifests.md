# 清单与脚本

路径相对JSON清单所在目录解析；输出写入指定位置。使用当前环境运行时，不在技能中存储绝对机器路径或安装依赖。

## PDF提取

依赖Python 3和PyMuPDF。页码从1开始；`box`为归一化`[左,上,右,下]`，不填则渲染整页。

```json
{"pdf":"sources/article.pdf","source_id":"S01","text":true,
 "figures":[{"id":"device","page":3,"box":[0.1,0.2,0.9,0.6],"locator":"Figure 2"}]}
```

```bash
python scripts/extract_pdf_assets.py --spec task/pdf-assets.json --out task/figures
```

输出正文、截图及来源清单。查看裁图，防止丢失单位或半张图。

## 图片式PPT

```json
{
 "title":"报告主题","slide_size":{"width":1600,"height":900},"include_notes":false,
 "slides":[{
  "id":"01","title":"封面","image":"slides/01.png","notes":"",
  "citations":[{"id":"S01","title":"原始题名","doi":"实际核验的DOI","locator":"Figure 2"}],
  "editable_text":[{"text":"姓名：________","font_family":"环境中已确认可用的字体","font_size":28,
    "position":{"left":70,"top":730,"width":650,"height":60}}],
  "figures":[]
 }]
}
```

`figures`可填写`{"image":"figures/device.png","alt":"S01 Figure 2","position":{"left":800,"top":250,"width":600,"height":350}}`，将原始截图等比例放进预留位置。

`editable_text`按需填写。`font_family`来自环境核验，不照抄上述说明文本。位置和字号用96 DPI CSS像素。

默认不写演讲稿或来源备注。只有用户要求时，将顶层 `include_notes` 显式设为
`true`，此时才写入每页 `notes` 与 `citations` 对应的备注内容。内部 `id` 与
图片文件名用于管理顺序，不代表允许在页面生成页码或展示性标号。

构建器需要Codex的`@oai/artifact-tool`及本地演示文稿技能。先读当前演示文稿技能并发现真实依赖路径：

```bash
node scripts/build_image_deck.mjs --manifest task/deck.json --out task/deliverables/report.pptx --build-dir task/build --runtime-modules PATH_TO_NODE_MODULES --presentation-skill-dir PATH_TO_PRESENTATIONS_SKILL --python PATH_TO_PYTHON
```

构建器在首次创建前运行该演示文稿技能自带的操作标记一次，调用方不要重复标记。随后导出、逐页渲染、执行结构/布局检查并验证重新导入。输出存在时拒绝覆盖。字体写入`text.style.typeface`，不使用无效的`fontFamily`键。

环境缺少相应能力时说明限制，使用明确可用且用户允许的方案，不假装运行成功或自动安装替代库。

## 支撑包

```json
{"sources":[{"id":"S01","title":"原始题名","authors":"作者","year":2025,
 "doi":"实际核验的DOI","url":"原始URL","version":"出版社全文或作者稿",
 "local_file":"sources/article.pdf","used":true,"slides":[2,5]}]}
```

```bash
python scripts/package_sources.py --manifest task/sources.json --out task/deliverables --max-mib 45
```

仅打包`used`不为false的记录，任一使用资料缺文件时报错。多个ZIP独立解压。单文件超阈值时独立成包并提示；阈值按原文件大小规划，不保证压缩后精确大小。
