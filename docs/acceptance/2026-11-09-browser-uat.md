# 浏览器 GUI UAT 记录(Orca 内置浏览器)

> 日期:2026-11-09 | 工具:Orca CLI 内置浏览器(`orca tab/goto/snapshot/click/fill/eval` + `orca terminal` 托管服务进程)
> 结论:**此前顺延的 GUI 点击级 UAT 已补做并 PASS**;过程中**真实发现并修复 2 个前端缺陷**

## 环境
- 后端:`orca terminal` 托管 `uvicorn app.main:app --port 8000`,`/api/health` = ok(llm_mode=live,model=agnes-3.0-flash)
- 前端:`orca terminal` 托管 `pnpm start` → localhost:3000(生产构建)
- 浏览器:Orca 内置浏览器标签页,真实渲染 + 点击/输入/eval

## UAT 剧本与结果(页面数字 vs SQL 交叉核对)

| 页面 | 操作 | 页面显示 | SQL 核对 | 结果 |
|---|---|---|---|---|
| Overview | 加载 | AIR OTP 85.8% / SEA 87.2% / TRUCK 82.0% | AIR OTP SQL = 85.8 | ✓ 一致 |
| Network/Capacity | 加载 AIR | 最满班次 CX849 HKG-SYD 2025-09-22 **100%** | SQL 最满 AIR = CX849 100.0 | ✓ 一致(**修复后**) |
| Network/Capacity | 点 SEA 切换 | FDR-160 / FDR-968 CNYTN-HKG 22% | SQL 最满 SEA = FDR-160/FDR-968 22.0 | ✓ 一致 |
| Alerts | 加载 | OPEN 794 · high 637 · medium 157 | SQL open/severity = 794/637/157 | ✓ 一致 |
| AI Agent | 问"capacity impact of typhoon / how many roll" | 调 `capacity_impact` 工具卡 → 60 票 / $546,031 / DG·PHARMA D+3、HIGH_VALUE D+4、GENERAL D+6 | 与 DES 引擎单测输出一致 | ✓ 工具链+流式应答在真实 UI 跑通 |
| Network | 加载 | 货件列表(货主/链路/状态) | — | ✓ 渲染正常 |

## 本次 UAT 发现并修复的缺陷(GUI 专属,单测未覆盖)

1. **容量态势页"最满班次"表取样错误**:页面先拉 `/api/network/services`(默认按 `scheduled_depart_ts` 升序返回前 100 条,即只有 5 月初的班次),再客户端排序——于是永远显示不到真正最满(台风周 9 月)的班次,误导性强。
   - 修复:`/api/network/services` 增加 `sort=load`(服务端按 `load_factor` 降序);前端态势页改用 `sort=load` 拉 20 条。浏览器复验:顶行变为 CX849 100%(= SQL)。
   - 加回归测试 `test_services_sort_by_load`(断言降序 + 顶行等于 SQL 最满)。
2. **Agent 页介绍文案过期**:写"One agent, six tools",实际 10 个工具。
   - 修复:改为 "ten tools" 并列出 network_load/capacity_impact/reroute_options/manifest_lookup。浏览器复验通过。

## UAT 工具使用备注(非产品缺陷)
- `orca fill` 设置 `<input>` value 不触发 React `onChange`,导致首次发送未带内容;改用原生 setter + `dispatchEvent('input')` 后正常提交(SPA 受控组件常见现象)。
- `orca click --element <ref>` 偶发命中过期 ref;用 `orca eval` 直接 `element.click()` 更稳。

## 验证
- 修复后 `pytest tests/` = **140 passed**(新增 1 条 sort 回归,替换式计数不变)
- `pnpm build` 通过;前端重启后三页 + Agent 均复验正常
- 两处修复已提交

## 与既往验收记录的关系
P0–R5 各验收记录里标注的"GUI 浏览器点击级 UAT 顺延"项,**至此闭合**。唯一前提(浏览器控制能力)已由 Orca 内置浏览器满足。
