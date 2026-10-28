# AntiDupe

[English](README.md) | [简体中文](README.zh-CN.md)

AntiDupe 是 Endstone 插件，用于限制基岩版中与收纳袋及容器有关的部分物品复制路径。它会拦截高风险容器附近的可疑库存请求，隔离受污染的玩家会话，不会自动破坏或重建容器库存。

**版本：** 0.2.7

**要求：** Python >=3.11；插件声明使用 Endstone API 0.11。CI 兼容性矩阵面向 CPython 3.11–3.15。

**许可证：** GPL-3.0-only。

## 防护范围

- 可阻止携带收纳袋的玩家打开高风险容器。
- 检查库存事务包（30、147）以及 PlayerAuthInput（144）中嵌入的相关请求。
- 按容器 ID 关联 ContainerOpen（46）与 InventoryContent/InventorySlot（49、50），识别容器污染。
- 对可疑窗口进行非破坏性隔离；物品名称中的文字不能证明物品类型。
- 尽早跳过无关数据包；可选性能计数器默认关闭。
- 在协议 **2193 和 2225** 下，从服务端发送 ChangeDimension（61）开始防护，直到收到匹配的服务端维度切换完成事件，再等待一个调度 tick。即使没有容器会话，也会拦截独立库存包（30、147）。

受保护的容器包括漏斗、投掷器、发射器、熔炉、烟熏炉、酿造台和合成器，也包括漏斗矿车。这是针对特定路径的缓解措施，**不能防止所有物品复制漏洞**。

## 安装与升级

下载发布版 wheel 或自行构建，然后在 Endstone 使用的 Python 环境中运行 `uv pip install --upgrade ./endstone_antidupe-0.2.7-py3-none-any.whl`。完整重启 BDS，不要通过 `/reload` 替换已安装的插件。

## 维度切换防护

插件通过公开的 Endstone 事件限制已观察到的未完成跨维度传送路径。等待传送完成时，仅允许以下数据包：Disconnect（5）、Respawn（45）、NetworkStackLatency（115）、PlayerAction（36）中的指定过渡动作（7、14、30、38）、通过格式校验的 ServerboundLoadingScreen（312）开始/结束消息（可带一个可选的 uint32 ID）、通过格式校验的地形加载请求（RequestChunkRadius 69、ClientCacheBlobStatus 135、SubChunkRequest 175），以及不含可操作标志或嵌入修改请求的 PlayerAuthInput（144）移动数据。未知包 ID 会被拒绝。协议 2193/2225 解析器会独立检查三个可选修改字段，因此省略相应的声明标志也无法绕过防护。

地形加载请求、加载界面开始/结束消息、玩家移动、静止、传送确认和玩家对象有效，都不能证明传送已经完成。

达到配置的超时时间后，插件立即隔离该连接：取消**所有入站应用层数据包**，并在下一个 tick 踢出该连接。延迟踢出只针对原连接，不会误踢后来重新连接的玩家。插件会在 HIGHEST 优先级确保隔离会话的踢出事件不被取消，但公开 API 无法保证连接一定断开。如果踢出后玩家仍在线，插件会记录日志，并保持隔离直到 PlayerQuitEvent。超时**不能单独证明玩家已进入幽灵状态**，正常传送也可能因缓慢或中断而超时。

正常维度切换及防护期间的常规数据包拦截不会记录日志。防护异常日志会包含玩家名称、目标维度、原因及采取的保护措施。传送及拦截数据包的汇总计数仍可通过 `/antidupe status` 查看。

解除防护依赖服务端维度切换 AFTER 事件在下一次调度心跳之前完成同步原生清理。这是有限范围的隔离措施，并未修复原生服务端漏洞，也无法全面检查存档状态。同维度重生和服务端独立生成的掉落物**尚未证明在防护范围内**。

`/antidupe reload` 会保留同一在线连接正在进行的传送防护与隔离，即使新配置关闭了防护；容器清理也不能解除这些状态。在受支持协议上启用插件时，如果已有玩家在线，插件会隔离这些尚未确认会话来源的玩家并安排踢出，要求他们重新连接。建议完整重启服务端。插件停用期间无法保证防护。不受支持的协议只会关闭新增的传送防护并发出警告，已有容器防护保持原有行为。

## 命令

| 命令 | 用途 |
| --- | --- |
| `/antidupe` 或 `/antidupe status` | 查看防护状态与计数 |
| `/antidupe reload` | 重新加载配置 |
| `/antidupe perf` | 查看可选的数据包性能计数 |
| `/antidupe perf reset` | 重置性能计数 |

需要 `antidupe.command` 权限，默认授予操作员。

## 配置

首次启用时，插件会创建 `plugins/antidupe/config.toml`。已有配置文件及其键值会保留，缺失的键使用默认值。默认配置如下，玩家提示默认使用英文：

```toml
enabled = true
alert-ops = true
log-attempts = true
player-message = "§c[AntiDupe] Bundles cannot interact with this container. Store the Bundle in a normal chest or barrel first."
block-open-with-bundle = true
guard-player-auth-input = true
guard-dimension-transfer = true
dimension-transfer-timeout-seconds = 10.0
dimension-transfer-kick-message = "[AntiDupe] Dimension transfer did not complete safely. Please reconnect."
quarantine-contaminated-session = true
rebuild-on-contamination = true
rebuild-container-types = ["minecraft:hopper"]
rebuild-delay-ticks = 1
alert-cooldown-seconds = 3.0
session-timeout-seconds = 60.0
candidate-timeout-seconds = 1.5
perf-counters = false
```

**安全变更：** 自动破坏性重建已停用，即使保留的 `rebuild-*` 配置仍为启用也不会执行。公开 API 无法证明容器物品的类型及方块实体代次；普通物品自定义名称中的 `bundle` 只能触发可疑窗口隔离，绝不能授权销毁库存。也不会安排延迟重建任务。

玩家库存仍使用真实物品类型检查，读取异常时拒绝危险操作。容器数据包中的文字只是启发式线索，可能误报改名物品，也不能保证识别所有收纳袋。精确容器检测仍需经真实抓包验证的数值物品 ID 解码器。

窗口不会因空闲或配置重载而失去保护。`session-timeout-seconds` 保留兼容但不再使已打开窗口过期。客户端关闭请求本身不能解除隔离，须等待匹配的服务端关闭、退出、维度切换或服务端替换窗口。相同坐标的其他当前查看者仍受保护；最后一个查看者关闭后清除该位置的临时疑虑，之后打开会重新检查。管理员应关闭相关窗口并检查实际库存，重载配置不等于修复。

传送超时会被限制在 1–120 秒之间，并按每秒 20 tick 安排检查。状态输出包含传送开始、完成、隔离和被拦截数据包的计数。

### 配置中文玩家提示

在已有的 `plugins/antidupe/config.toml` 中修改以下两个键；如果缺失就添加，已有的键不要重复添加：

```toml
player-message = "§c[AntiDupe] 收纳袋不能与该类容器进行库存交互。请先将收纳袋存入普通箱子或木桶。"
dimension-transfer-kick-message = "[AntiDupe] 维度切换未能安全完成，请重新连接服务器。"
```

将文件保存为 UTF-8，然后执行 `/antidupe reload` 使配置生效。升级不会自动翻译或重写现有消息；仍使用旧中文提示的配置也会保留原值。这两个配置项仅修改玩家提示，管理命令输出和日志仍为英文，插件不提供完整的多语言切换机制。

## 验证结果与限制

已在 Linux BDS 26.52、Endstone 0.11.14 上进行实服验证：不带鹦鹉时跨维度传送正常；测试中携带鹦鹉后卡住的传送在 10 秒后被隔离，玩家确实断开连接，且断开发生在手动丢弃物品阶段之前。

这证明了对该次观察路径的隔离效果，不能据此认定已经直接验证丢弃物品数据包的拦截或物品数量守恒，也不能证明所有复制路径都已覆盖。自动化测试同样无法证明这些实服结果。

## 开发

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv build --wheel
```

测试套件模拟 Endstone 宿主 API，不能代替实服集成测试。这里的 Python 3.15 支持指纯 Python 插件及其通用 wheel；使用 Python 3.15 运行 BDS 还需要兼容的 Endstone 原生发行版。CI 构建并校验 wheel 的元数据和内容，不会部署到服务端或发布版本。

历史性能分析见 [`docs/performance.md`](docs/performance.md)（英文，保留 0.2.3 的历史数据）。
