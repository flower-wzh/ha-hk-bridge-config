# HomeKit Bridge 配置器 — HA 加载项

可视化调整 Home Assistant 内置 HomeKit Bridge 配置的 Web 工具。

> 直接在 HA 侧边栏点开,**像编辑表格一样**调整 6 个 bridge 的 entity 进/出、
> 中文 Siri 友好名,保存后自动备份 yaml + reload 6 个 HomeKit 集成。

## 解决的痛点

- ❌ 每次都 SSH 进去手改 yaml(没有写权限,得用 HA 文件编辑器)
- ❌ 改完还得手动调 HA API reload 6 个 bridge entry
- ❌ 不能预览「这个 entity 进/出后,iOS Home 会变什么」

## 特性

- 🌉 **6 个 bridge 折叠面板**:一目了然看到每个 bridge 的 entity 列表
- ☑️ **复选框进/出**:勾选/取消立刻生效,可预览 diff 后再保存
- 🏷️ **中文 Siri 友好名编辑**:直接 inline 改名
- 🔍 **搜索 + domain 过滤**:248 个 entity 里秒级定位
- ➕ **「+ 添加 entity」模态**:列出所有未进此 bridge 的 HA entity
- 👁 **预览 Diff**:保存前看到 added/removed/name_changes
- 💾 **一键保存**:写 yaml + 自动备份(`.bak.YYYYMMDD_HHMMSS`)+ reload 6 个 bridge
- 📦 **备份列表 + 一键恢复**:误操作秒回滚
- 🎨 **浅绿主题**:复用 `homekit_room_planner` 的 SF Pro + PingFang 风格

## 安装

### 1. 准备 GitHub 仓库(用户执行)

在 GitHub 网页上创建空仓库(本 README 假设用户名 `flower-wzh`、仓库名 `ha-hk-bridge-config`):

1. 打开 <https://github.com/new>
2. Repository name: `ha-hk-bridge-config`
3. 选择 Public 或 Private(都支持)
4. **不要**勾选 Add a README / Add .gitignore(我们要推自己的)
5. 点 Create repository

### 2. 推送项目到 GitHub

在 `ha-hk-bridge-config/` 项目根目录执行:

```bash
cd /Users/mangguo/myOwnWorkspace/homeassistant/ha-hk-bridge-config

git init
git add .
git commit -m "feat: HomeKit Bridge 配置器 v1.0.0"
git branch -M main
git remote add origin https://github.com/flower-wzh/ha-hk-bridge-config.git
git push -u origin main
```

> 如果是 private 仓库,HA 加载时需要填 GitHub PAT,见 [HA 文档:私有仓库](https://www.home-assistant.io/addons/repository/#private-repositories)。

### 3. 在 HA 添加仓库并安装

1. HA 侧边栏 → **设置** → **加载项** → **加载项商店**
2. 右上角 ⋯ → **仓库**
3. 粘 `https://github.com/flower-wzh/ha-hk-bridge-config` → **添加**
4. 刷新页面后,加载项商店底部出现 **「HomeKit Bridge 配置器」**
5. 点进去 → **安装**(首次会拉 Docker 镜像,1-3 分钟)
6. 启动后,**Configuration** 标签页确认 `yaml_path` 是 `/config/homekit_bridges.yaml`(默认值)

### 4. 在侧边栏打开

- 侧边栏会出现 **「HK Bridges」** 图标(🌉)
- 点开就是配置器 UI
- 也可以从 加载项详情页 → **在 Ingress 中打开** 进入

## 使用流程

### 改某个 entity 的中文名

1. 找到该 entity 所在 bridge 面板(可用搜索框定位)
2. 直接在 **中文名** 输入框修改
3. 底部出现 **「N 项待保存」** 黄字提示
4. 点 **💾 保存 + Reload** → 自动:
   - 备份 yaml 到 `.bak.YYYYMMDD_HHMMSS`
   - 写新 yaml
   - 调 HA API reload 6 个 HomeKit bridge
5. **iOS Home 端**:删除该 bridge,重新扫码配对,即可看到新名字
   (iOS Home 缓存旧名字,只能 reset 配对才能刷新)

### 把 entity 加入/移出 bridge

1. 取消勾选 = 移出
2. 点 **「+ 添加 entity」** = 弹出候选列表(已过滤掉已在该 bridge 的)
3. 勾选后点 **「✓ 添加选中」** → 自动加入 dirty list
4. 点 **「💾 保存 + Reload」** 生效

### 撤销误操作

1. 顶部 **📦 备份列表**
2. 选最近一次 `.bak.YYYYMMDD_HHMMSS` 文件 → **⤴ 恢复**
3. 自动 reload + UI 刷新

## 架构

```
HA 侧边栏 (Ingress 入口,免端口/免鉴权)
   ↓
Add-on 容器 (Flask + Python, port 8099)
   ↓
   ├─ 读 /config/homekit_bridges.yaml
   ├─ 调 http://supervisor/core/api/states 拿 entity friendly_name
   ├─ 写回 /config/homekit_bridges.yaml(自动备份)
   └─ 调 http://supervisor/core/api/services/homeassistant/reload_config_entry
```

## 后端 API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | UI 入口 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/bridges` | 读 yaml,返回 6 bridge 详情 + entity |
| GET | `/api/entities` | 调 HA API,返回全 entity(用于添加候选) |
| POST | `/api/save` | 写 yaml + 备份 + reload |
| POST | `/api/reload` | 仅 reload 6 bridge(不改 yaml) |
| POST | `/api/preview` | 生成 diff(不改 yaml) |
| GET | `/api/backups` | 备份文件列表 |
| POST | `/api/restore` | 从备份恢复 |

## 文件结构

```
ha-hk-bridge-config/                    # GitHub 仓库根
├── README.md                           # 本文件
├── repository.yaml                     # HA 仓库元数据
└── hk_bridge_config/                   # add-on 目录
    ├── config.yaml                     # add-on 声明
    ├── Dockerfile                      # 镜像构建
    ├── CHANGELOG.md                    # 版本日志
    └── rootfs/
        ├── etc/services.d/app/run      # s6-overlay 启动脚本
        └── usr/src/app/
            ├── server.py               # Flask 后端
            ├── yaml_ops.py             # yaml 读写(保序 + 备份)
            ├── templates/index.html    # UI 结构
            └── static/
                ├── style.css           # 浅绿主题
                └── app.js              # 前端逻辑
```

## 关键实现说明

### yaml 字段顺序保留

`entity_config` 是 dict,Python 3.7+ dict 保序,但 PyYAML 默认 dump 可能乱序。
代码里用 `OrderedDumper` + `BRIDGE_FIELD_ORDER` 显式排序:

```python
BRIDGE_FIELD_ORDER = ['name', 'port', 'filter', 'entity_config', 'mode', 'advertise_ip', 'ip_address']
```

写入的 yaml 保持 `name → port → filter → entity_config → ...` 的稳定顺序,
git diff 友好。

### 写前自动备份

`yaml_ops.write_yaml()` 在覆盖前先 `shutil.copy2()` 到 `homekit_bridges.yaml.bak.YYYYMMDD_HHMMSS`。
最多保留 20 个最新备份(由 `list_backups(limit=20)` 控制)。

### 自动 reload 6 bridge

`server.py` 调 `/api/services/homeassistant/reload_config_entry` 给每个
`domain=homekit, source=import` 的 config entry 触发 reload。
该 service 只重载 yaml 配置,不重置配对(不会丢 iOS Home 端的桥接)。

> **注意**:iOS Home 端的 accessory 名字缓存**只能**通过「删除 + 重新扫码」刷新。
> reload_config_entry 不会让 iOS 看到新名字。

### Ingress 鉴权

`config.yaml` 里 `ingress: true` + `hassio_api: true` + `homeassistant_api: true`,
HA 反代自动加鉴权,后端用 `SUPERVISOR_TOKEN` 环境变量调 HA API。

## 故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| 侧边栏没出现 HK Bridges 图标 | `panel_admin: true` 但当前用户不是 admin | 用 admin 账户登录,或改 `panel_admin: false` |
| 「加载 bridge 失败」 | yaml 文件路径不对 | 改 add-on Configuration 的 `yaml_path` |
| 「No SUPERVISOR_TOKEN」 | 没勾 `homeassistant_api: true` | 重新装 add-on,确认 manifest |
| 「Failed to fetch HA states」 | Supervisor API 不可达 | 重启 add-on,看 add-on 日志 |
| 保存后 iOS Home 名字没变 | iOS Home 缓存 | 删除该 bridge + 重新扫码 |
| 写 yaml 后 HA 启动报错 | yaml 语法破坏 | 用「备份列表」恢复到上一个 `.bak` |

## 升级

```bash
cd /Users/mangguo/myOwnWorkspace/homeassistant/ha-hk-bridge-config
# 改代码
git add .
git commit -m "feat: ..."
git push
# HA 侧边栏:加载项 → HomeKit Bridge 配置器 → 右上角 ⋯ → 重新加载
```

## License

MIT
