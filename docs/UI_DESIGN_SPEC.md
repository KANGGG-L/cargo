# UI 设计稿:HKG Cargo Control Tower 界面重构(v2)

> 基准:shadcn/ui 经典 zinc 浅色主题 + Tremor KPI 卡范式 + Grafana/Superset 状态色纪律 + Lucide 图标库。调研来源与核验记录见会话调研报告(shadcn globals.css 源码、tremor 文档、Grafana visual_refresh_light.json、superset config.py、lucide icons 全量核对)。
> 本设计稿取代当前的深色 navy + emoji 风格。

## 0. 三条禁令

1. **禁深色系**:页面底、卡片、侧栏一律浅色;大面积深色只允许出现在图表内部的数据墨水(如折线)上
2. **禁 emoji**:所有图标一律 lucide-react 线性图标(2px 线宽),空状态用图标 + 文字,不用表情
3. **禁"AI 味"配色**:渐变、发光、荧光青、深 navy 全部移除;品牌色只允许一个(选 indigo-600),其余彩色只做语义状态

## 1. 色彩 token(浅色,直接落 Tailwind 类)

| token | 值 | 用途 |
|---|---|---|
| background | white | 页面底 |
| foreground | zinc-950 (#09090b) | 主文字 |
| muted | zinc-100 (#f4f4f5) | 次级底(工具卡内、hover) |
| muted-foreground | zinc-500 (#71717a) | 辅助文字 |
| card | white + border zinc-200 (#e4e4e7) | 所有卡片 |
| primary | zinc-900 (#18181b) | 主按钮、主文字强调 |
| accent(品牌) | indigo-600 (#4f46e5) | 链接、选中态、图表主系列 |
| border | zinc-200 | 1px 分隔,无竖线 |
| ring | zinc-400 (#a1a1aa) | focus ring |
| 状态-成功 | emerald-600 字 + emerald-50 底 | on-time、DELIVERED、SENT |
| 状态-警告 | amber-600 字 + amber-50 底 | DELAYED、PENDING、MEDIUM |
| 状态-危险 | red-600 字 + red-50 底 | EXCEPTION、HIGH、OPEN |
| 状态-信息 | sky-600 字 + sky-50 度 | 中性提示 |

徽章一律"浅底(50)+深字(700)+1px 中间色边框(200/300)",rounded-md,text-[10px]。

## 2. 布局:左侧栏 + 顶栏(高密度 BI 标准形态)

- **左侧栏 240px,白底 border-r**:logo 区(Ship 图标 + "HKG Cargo Control Tower" 两行字,无徽章),导航分组:OPERATIONS(Overview=LayoutDashboard、Network=Network、Orders=ClipboardList)、EXCEPTIONS(Alerts=Bell)、DATA(Ingest=Upload)、INSIGHT(AI Agent=Bot)、ACCOUNT(Portal=Users)。选中态:zinc-100 底 + foreground 文字 + 左侧 2px indigo 指示条。底部 footer:数据诚实声明两行小字。
- **顶栏 52px,白底 border-b**:当前页标题(zinc-900 semibold)+ 右侧 OPEN 告警数徽章(Bell + 数字)。
- **内容区** px-6 py-6,白底,max-w-[1440px] 居中,网格 gap-4。

## 3. 组件规范

- **卡片**:white + border zinc-200 + rounded-lg + 无阴影(或 shadow-xs);卡头 title 用 zinc-900 text-sm font-semibold,副说明 zinc-500 text-xs
- **KPI 卡**(Tremor 范式):label(zinc-500 text-xs uppercase tracking-wide)/ value(zinc-900 text-2xl font-semibold tabular-nums)/ hint(zinc-500 text-xs);状态色只出现在 delta 与 badge,数值本身永远中性
- **表格**:行高 44px,border-b 分隔,无竖线,表头 zinc-500 text-xs font-medium uppercase,斑马纹不用(hover 用 zinc-50)
- **图表**(ECharts light):轴线/分隔线 #e4e4e7,文字 #71717a 11px,系列色固定 5 色 [#4f46e5, #0e9384, #d946ef, #f59e0b, #64748b];时间窗标注用 zinc-100 底带 + zinc-400 文字(非红色块)
- **按钮**:primary = zinc-900 白字;secondary = 白底 zinc-200 边;destructive = red-600 白字仅用于不可逆动作;全部 rounded-md text-xs
- **空状态**:lucide 图标(zinc-300)+ 一行 zinc-500 文字

## 4. 图标映射(全部 lucide-react,已核实存在)

| 旧(emoji/文字) | 新(lucide) |
|---|---|
| ✈️/🚢/🚛 logo | Ship(logo)、Plane / Ship / Truck(模态) |
| 🛰️ 空状态 | Radar |
| 🔔 Subscribe / 告警 | Bell |
| 💰 Settle | ReceiptText |
| 📄 文档 | FileText |
| 告警严重度 | TriangleAlert(high)、CircleAlert(medium)、Info(info) |
| 状态 | CircleCheck(成功)、Clock(进行)、CircleX(异常) |
| Ingest | Upload;Send 按钮 | Send | Send |
| 运单 | ClipboardList;AWB 徽章 | Ticket |

## 5. 页面逐一规格

1. **/** Overview:页头 → 8 KPI(两行 4 列,Tremor 结构)→ 2 列图表(每卡白底,ECharts light)→ 无桑基以外的彩色块;chain mix 改为横向进度条(zinc 底 + indigo 填充)
2. **/network**:上双栏(列表 380px / 右详情),里程碑条改徽章组(plan=白底边框、act=浅色语义底);Route Map 白底卡内 OSM 浅色瓦片;桑基降饱和(链路色全部 zinc-400 系,仅 HKG 枢纽 indigo)
3. **/alerts**:顶部汇总徽章(浅底深字)→ 过滤 chips(选中 = zinc-900 反白)→ 列表卡:severity 图标而非色块,按钮 secondary 化
4. **/orders**:新建表单改为栅格 + 锌色按钮;行内操作按钮全 secondary;AWB 徽章 = 锌底 mono
5. **/ingest**:统计四卡改 Tremor 结构;拒绝清单表 red-50 底;文本域白底
6. **/portal**:登录卡居中(max-w-md);demo 账号提示 zinc-50 底信息块
7. **/agent**:消息区白底;用户消息 = zinc-100 底右对齐,助手 = 白底 + border;工具活动卡 = zinc-50 底可折叠(图标 + 摘要),SQL 块 = zinc-900 反色代码块(唯一允许的深色,代码语义);输入框 border + ring

## 6. 验收清单

- [ ] 全部页面无 emoji、无深色大面积背景、无渐变/荧光
- [ ] 全部图标来自 lucide-react
- [ ] 全部状态徽章浅底深字
- [ ] ECharts 全 light 轴/网格
- [ ] build 通过 + 7 页浏览器截图走查无深色残留
