# 产品运营严格验收报告(货运运营负责人视角,agent 实测)

## 总评
工程纪律出色(67 测试、CI、确定性模拟、plan 锚定事件模型),作者自知短板。但站在运营负责人角度,它是"分析后视镜 + 流程骨架":分析闭环强于执行闭环,单点功能强于系统级承诺。最严重的不是缺功能,而是三处"主张与实现不符":级联模拟的 scenario 类型是装饰、客户隔离只存在于一个 portal 端点、AWB 号码不合规。**产品成熟度 6/10**(作品集语境 7.5,真实运营语境 4)。

## 验收矩阵
| 域 | verdict | 证据 | 缺口 |
|---|---|---|---|
| a 生命周期与单证链 | PARTIAL | guards 实测 409/200 正确;PDF 三种 | AWB 校验位算法错;无报关单;eawb_status 硬编码 sent |
| b 里程碑与事件标准 | PARTIAL | plan 76,081 vs event 73,606(96.7%,缺 2,498 喂 R1/R2);FSU 拒收未知 | 6 码自定义管道格式非 CIMP;sea 用 RCS 形似神不似 |
| c 多式联运级联 | **FAIL** | chain.py 全程不读 event_type;yantian/szbp 同样"取消 HKG 空运离港" | 无海侧泊位/关口模型,无改配分支 |
| d 异常管理闭环 | PASS | 流转/销警实测通过;794 OPEN | 无聚类/SLA/升级,assignee 恒空 |
| e 数据接入现实 | PARTIAL | 幂等实测 1,0,0;拒绝队列带 reason | 时间戳无信任分级:17 个月"延误"可入库 |
| f 结算 | **FAIL** | fuel/THC 写死;demurrage 记账基础错(应箱型×滞留天);disputed 不可达;对账为 0 | 费率与合同脱钩 |
| g 角色与门户 | **FAIL** | portal 内真隔离;但无凭证 /api/shipments、/api/alerts、/api/settlement、/api/documents 全部 200 | 隔离只守一个门 |
| h 地图可视化 | PARTIAL | 大圆插值+模态着色+桑基 | 是"航迹重放"非"态势"(无当前位置/告警落图) |
| i AI Agent | PASS | 六工具可用;防火墙三层;mock 诚实 | ALLOWED_TABLES 不含告警/事件表;simulate 的 event_type 是摆设 |

## 最远的 3 个差距
1. 级联模拟是"单模态扰动重放" — 补法:每 event_type 配"首损节点+传播边",加改配替代枢纽分支,先把"场景≠同一模型"做实
2. 事件时间戳无信任分级 — 补法:fsu.py 加 |event_ts−planned_ts|>X 天 → reject('implausible timestamp')
3. 结算无对账、费率与合同脱钩 — 补法:fuel/THC 挂真实费率卡,加 dispute + 账龄,一天工作量

## 容易被戳穿的 3 个细节
1. **AWB 校验位错**:IATA 规则 = 7 位流水号 mod 7;orders.py 用 (prefix*10^7+serial)%7,实测 CX/KE/EK 三航司全错,仅 UPS 碰巧对
2. **"行级隔离"一句话戳穿**:无 cookie 打 /api/shipments 返回全部客户收入
3. **三个场景同一套代码**:问"盐田拥堵模拟"却输出"取消 HKG 空运离港";chain.py 127-131 有死代码暴露迭代不干净
