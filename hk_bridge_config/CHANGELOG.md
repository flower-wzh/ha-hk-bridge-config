# Changelog

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
