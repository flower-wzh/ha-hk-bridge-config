# Changelog

## 2.0.10 (2026-06-15)
- **真根因**:v2.0.9 的 bucket flex 修复其实写对了,但用户看不到效果 — Flask 默认给 static 文件设很长的浏览器缓存,HA 升级 add-on 重建容器后浏览器还在用旧 `app.js` / `style.css`
- **修复**:`server.py` 加 `APP_VERSION` 常量,`index.html` 渲染时给 `<link>` / `<script>` 加 `?v={{ app_version }}`。每次 bump 版本浏览器看到新 URL 就会重新下载,绕过缓存
- **流程**:发版时同步 bump `config.yaml` 和 `server.py::APP_VERSION` 两个地方
- **自测**:本地起 Flask + chrome headless + same-origin iframe 模拟点击,验证 bucket 不再被压扁、head 折叠/展开 toggle 正常,截图存档

## 2.0.9 (2026-06-15)
- **修复**:`.buckets` 是 flex column 容器,5 个 bucket 默认 `flex-shrink: 1` 互相挤压塞进一个视口,实体多的被压成一条缝。给 `.bucket` 加 `flex-shrink: 0` 后,每个 bucket 按内容高度撑开,buckets 区域整体滚动
- **新功能**:bucket head 点击折叠/展开。head 加 ▼ 箭头,折叠时旋转到 ▶,body 隐藏。默认全展开,点击"清空"按钮不会触发折叠(stopPropagation)

## 2.0.8 (2026-06-15)
- **新功能**:URL 加 `?demo=1` 走静态数据模式(6 分类 × 4 区域 × ~40 实体),不走 API 不写文件,方便先看布局再联调。toast 会提示当前是 demo 模式
- **修复**:布局塌陷 — 给 `.sidebar` 和 `.content` 加 `min-height: 0`。CSS grid item 默认 min-height: auto,内容很高时会把 grid cell 撑开,内层 `.buckets { overflow-y: auto }` 失效,造成"块内不能滑动"且模块看起来重叠。补上 min-height: 0 后,buckets 区能正常在内部滚动
- **修复**:给 `.content` 加 `min-width: 0`,grid item 在 1fr 列里别因 entity_id 等长字符串被撑出横向滚动条

## 2.0.7 (2026-06-15)
- **真根因**:Flask 3.0 / Werkzeug 3.0 移除了 `request.script_name` 属性(之前 v2.0.1-v2.0.6 模板里都用的这个,Flask 2.x 静默返回 Undefined,3.0 显式抛 `UndefinedError`)。**所以从 v2.0.1 起 INGRESS_BASE 就一直是空字符串,所有版本都没真正生效过**。
- **修复**:index view 改用 `request.environ.get('SCRIPT_NAME', '')` 拿 prefix,作为 `ingress_prefix` 模板变量传入
- **修复**:v2.0.6 的 `request.url_root` 是后端地址 `http://0.0.0.0:8099/`,不是用户访问的 `https://ha.971128.xyz:2096/`。改用 `location.origin`(浏览器拿到的真实 origin)+ INGRESS_BASE 拼
- **调试**:API_BASE 改成 console.log 打出来,用户能在浏览器 console 直接看到

## 2.0.6 (2026-06-15)
- **修复**:Network 面板显示失败 API 请求 URL 是 `https://host:port/api/health`(没 ingress 前缀)。说明 INGRESS_BASE 实际是空字符串,相对 URL 兜底被 service worker 解析错。改成在模板里渲染**绝对 URL** `request.url_root + request.script_name` 作为 `window.API_BASE`,api() 用绝对 URL fetch,service worker / iframe baseURI 都不能改
- **调试**:IngressPrefixFix 中间件加 warning 日志,每次请求把 PATH_INFO / SCRIPT_NAME / 4 个候选 ingress 头都打到 add-on 日志。下次复现直接看日志就知道 HA 实际发什么

## 2.0.5 (2026-06-15)
- **修复**:IngressPrefixFix 中间件同时把 `PATH_INFO` 里的 ingress 前缀剥掉。HA 转发时可能保留或剥掉前缀,两种情况都兼容:剥过就跳过,没剥过我们剥,然后 Flask 路由只看到 `/api/...` 而不是 `/api/hassio_ingress/<token>/api/...`

## 2.0.4 (2026-06-15)
- **修复**:api() 不再依赖 `window.INGRESS_BASE`,改用相对 URL(去前导 `/`)。浏览器以当前文档 URL(`/api/hassio_ingress/<token>/`)为基准,自动解析到带前缀的正确路径,无论 `X-Ingress-Path` 头被读到没有都能工作。`INGRESS_BASE` 仍优先(精确)。

## 2.0.3 (2026-06-15)
- **修复**:v2.0.2 用了 Werkzeug 的 `ProxyFix(x_prefix=1)`,但 HA ingress 实际设的是 `X-Ingress-Path` 头(老 HA 是 `X-Forwarded-Prefix`),`ProxyFix` 读不到,`request.script_name` 是 Undefined,模板 `tojson` 报 `TypeError` 500。改用自写的 `IngressPrefixFix` 中间件直接读两个头并写到 `SCRIPT_NAME`。
- **修复**:模板用 `request.script_name|default('', true)` 兜底,万一头是空也不会 500

## 2.0.2 (2026-06-15)
- **修复**(已废):`ProxyFix(x_prefix=1)` 中间件 — 实际 HA 不用这个头,见 2.0.3
- **修复**:把 `request.script_name` 暴露为 `window.INGRESS_BASE`,`app.js` 里的 `fetch('/api/...')` 改为带 ingress 前缀(单点在 `api()` 函数内处理)

## 2.0.1 (2026-06-15)
- **修复**:外网 ingress 反代下 `/static/app.js` `/static/style.css` 写死路径导致 JS/CSS 404 → 改为 `{{ url_for('static', filename='...') }}` 让 Flask 生成正确路径

## 2.0.0 (2026-06-15)
- **重写 UI**:现代暗色风格,圆角/阴影/微动画/响应式
- **设备分组树**:左侧按 area → device 二级树,带勾选状态指示
- **实体卡片网格**:6 个分类桶各自独立卡片,显示 friendly_name + entity_id + domain + state
- **自定义分类**:分类管理抽屉,拖拽排序、增删改、规则配置(domain / 名字包含 / entity_id 包含)
- **手动 + 规则双匹配**:实体先按手动规则,后按自动规则(按分类顺序)
- **未分配桶**:自动把不匹配任何分类的实体归到这里,可视化看到漏网之鱼
- **全量保存**:`/api/save_all` 一次写完 6 个 bridge yaml + 分类配置 + 触发 reload
- **保留兼容**:`/api/bridges` `/api/save` `/api/preview` `/api/auto_assign` 等老接口仍可用
- **分组数据源**:HA area/device/entity registry(失败则降级到 entity_id 启发式)
- **自动跳过**:旧 `midea_` 前缀实体(参考 reference_ha_integrations)

## 1.0.0 (2026-06-14)
- 首次发布
- 可视化调整 6 个 HomeKit bridge 的 include_entities 和 entity_config
- 按 domain / 搜索过滤 entity
- 中文人名编辑
- 一键保存 + 备份 + reload 6 个 bridge entry
- 预览 diff
- 撤销最近保存(从 .bak 恢复)
