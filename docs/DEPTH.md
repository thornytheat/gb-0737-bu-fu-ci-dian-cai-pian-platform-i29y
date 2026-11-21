# 布幅疵点裁片台深度登记

- 规模为中型。制服工场管理员导入验布记录和工单，复核可下刀的区间，按领卷顺序打印验收签条。
- 核心规则把安全膨胀后的疵区取并集，在实际连续可用段内安排裁片和刀口，再按整批需求裁决换卷。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 验布采信 | 核对三类源文件与重复、隔离行 | `GET /api/intake` | `app/modules/m1_intake/csvfile.py` `app/modules/m1_intake/identity.py` | `tests/test_intake.py` |
| M2 疵点定位 | 复核卷首坐标、点疵占位和测量异常 | `GET /api/locate` | `app/modules/m2_locate/geometry.py` `app/modules/m2_locate/service.py` | `tests/test_locate.py` |
| M3 禁切区间 | 选卷核对膨胀并集与可用段 | `GET /api/zones` | `app/modules/m3_zones/intervals.py` `app/modules/m3_zones/service.py` | `tests/test_zones.py` |
| M4 裁片配长 | 按幅宽、缝份和刀口查看可行裁量组合 | `GET /api/fit` | `app/modules/m4_fit/choices.py` `app/modules/m4_fit/service.py` | `tests/test_fit.py` |
| M5 换卷核算 | 确认领卷次序、实际坐标和欠料 | `GET /api/changeovers` | `app/modules/m5_changeovers/solver.py` `app/modules/m5_changeovers/placements.py` | `tests/test_changeovers.py` |
| M6 用布勾稽 | 按卷审核切口守恒及源记录分流 | `GET /api/ledger` | `app/modules/m6_ledger/partition.py` `app/modules/m6_ledger/service.py` | `tests/test_ledger.py` |
| M7 裁床签条 | 排版归档、同源重跑、按卷打印并下载卷宗 | `GET /api/slips` `POST /api/runs` | `app/modules/m7_slips/receipts.py` `app/modules/m7_slips/archiving.py` | `tests/test_slips.py` |
| M8 换卷调拨 | 急单换卷签发调拨卷宗、对平核验、整批同版签条 | `POST /api/transfers` | `app/modules/m8_transfers/dossier.py` `app/modules/m8_transfers/archiving.py` | `tests/test_transfers.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | `dirty-orders.csv` 使用 GB18030 | 工单中文列名读不出 | 严格探测与回退 | `app/modules/m1_intake/csvfile.py` | `tests/test_intake.py::test_gb18030_and_mixed_seam_units` |
| TRAP-02 | `dirty-rolls.csv` 有 UTF-8 BOM | 卷号列无法识别 | 剥离起始 BOM | `app/modules/m1_intake/csvfile.py` | `tests/test_intake.py::test_bom_full_width_and_thousands` |
| TRAP-03 | `dirty-defects.csv` 的 2–3 行为同条记录 | 换行备注被算两行 | 保存物理起止行 | `app/modules/m1_intake/csvfile.py` | `tests/test_intake.py::test_multiline_physical_range_and_repeated_header` |
| TRAP-04 | `dirty-defects.csv` 重复表头 | 虚增疵点 | 跳过重复表头且记段数 | `app/modules/m1_intake/csvfile.py` | `tests/test_intake.py::test_multiline_physical_range_and_repeated_header` |
| TRAP-05 | 疵点第 17 行多列 | 错位进入裁片求解 | 原行隔离且对应已知卷封存 | `app/modules/m1_intake/service.py` | `tests/test_intake.py::test_bad_columns_missing_unit_and_sub_mm_are_kept_as_evidence` |
| TRAP-06 | `dirty-rolls.csv` 使用全角和千分位 | 卷长解析失败 | NFKC 归一后精确换算 | `app/measure.py` | `tests/test_intake.py::test_bom_full_width_and_thousands` |
| TRAP-07 | R-006 卷长为 `-`，D-008 余量待测 | 赋零造成误下刀 | 原值保留并隔离 | `app/measure.py` | `tests/test_intake.py::test_bad_columns_missing_unit_and_sub_mm_are_kept_as_evidence` |
| TRAP-14 | D-010 有两个不同测值，R-002 等值重送 | 后写覆盖或重复扣料 | 冲突两行都隔离，等值保留首行 | `app/modules/m1_intake/identity.py` | `tests/test_intake.py::test_equivalent_units_deduplicate_and_differing_payloads_conflict` |
| TRAP-15 | 脏工单缝份厘米、毫米混用 | 裁长差一个数量级 | 双端精确纳入缝份 | `app/modules/m1_intake/contract.py` | `tests/test_fit.py::test_seam_is_counted_at_both_ends_and_width_normalized` |
| TRAP-16 | 在 `dirty-defects.csv` 末尾造未闭引号 | 半条数据被采信 | 严格 CSV 解析失败并给物理行 | `app/modules/m1_intake/csvfile.py` | `tests/test_intake.py::test_truncated_multiline_is_source_error_with_line` |
| TRAP-18 | 空文件、空白和仅表头 | 无法区分缺采与无疵 | 分开处理，仅疵点表允许明确零条 | `app/modules/m1_intake/csvfile.py` | `tests/test_intake.py::test_empty_blank_only_header_and_explicit_no_defects_are_distinct` |
| TRAP-19 | R-001 两条带安全余量的疵区重叠 20 mm | 重复扣料或留出假缝 | 归并并集并合并源行 | `app/modules/m3_zones/intervals.py` | `tests/test_zones.py::test_overlapping_allowances_are_counted_once` |
| TRAP-23 | R-005 的裁片和刀口刚好用尽到卷尾 | 漏计最后刀口或右端算两次 | 半开区间，最后刀口须完整容纳 | `app/modules/m5_changeovers/placements.py` | `tests/test_fit.py::test_kerf_exact_fit_succeeds_when_right_edge_is_exclusive` |
| TRAP-26 | 已归档后改变源记录文件 | 陈旧重跑覆盖原裁片坐标 | 比较文件哈希及规则身份，返回 409 | `app/modules/m7_slips/archiving.py` | `tests/test_slips.py::test_stale_source_replay_is_rejected_without_rewriting_archive` |
| TRAP-27 | 急单换卷但仓管要求整批同版 | 只换一卷造成新旧签条混用 | 调拨卷宗只重排换下卷，整批签条同发新版 | `app/modules/m8_transfers/dossier.py` | `tests/test_transfers.py::test_swap_rehomes_pieces_and_reissues_whole_batch_at_one_version` |
| TRAP-28 | 同一调拨重复提交 | 每点一次多一版签条 | 调拨键哈希幂等，重跑复用原卷宗 | `app/modules/m8_transfers/archiving.py` | `tests/test_transfers.py::test_same_transfer_rerun_never_issues_another_slip_version` |
| TRAP-29 | 换卷后账目未对平 | 签发后新旧两版都对不上 | 八项对平核验任一不过即拒签，旧版保留 | `app/modules/m8_transfers/archiving.py` | `tests/test_transfers.py::test_unbalanced_base_is_refused_and_old_slips_survive` |

## 勾稽与局限

- 卷长逐卷校验，等于合格裁片、禁切、切口和未用段之和。封存卷全长算禁切。每个区间恰好在一类中。
- 各来源原始条数等于有效、重复和隔离之和。疵点定位隔离会在最终条数账里移动分项。
- 只做沿卷长的条带裁切。幅宽用于每片布种匹配和最小幅宽约束。精确规划上限与输入文件限制见数据字典。
- 换卷调拨只重排换下卷的裁片，其余卷裁片坐标不变；放不下的裁片转欠料。换上卷可以是在册留存卷，也可以是按已验合格无禁切入册的新卷。调拨不改写原归档，整批签条以调拨版本同发；任一守恒核验不过即拒签，旧版签条保留。
