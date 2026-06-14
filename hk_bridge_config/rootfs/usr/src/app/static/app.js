/*
 * HomeKit Bridge 配置器 - 前端逻辑
 */

// ============== 状态 ==============
const state = {
  bridges: [],              // 来自 /api/bridges
  allEntities: [],          // 来自 /api/entities(用于添加)
  selectedBridgeIdx: null,  // 当前打开「+ 添加 entity」模态对应的 bridge
  addSelection: new Set(),  // 模态里勾选的 entity
  collapsed: new Set(),     // 折叠的 bridge idx
  dirty: {},                // {bridgeIdx: {included: Set, names: {entity_id: name}}}
  lastYamlStatus: null,
};

let allDomains = new Set();

// ============== 工具 ==============
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function toast(msg, type = 'info', duration = 3000) {
  const el = document.createElement('div');
  el.className = 'toast-item ' + type;
  el.textContent = msg;
  $('#toast').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .25s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 250);
  }, duration);
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    throw new Error(data.error || `HTTP ${r.status}`);
  }
  return data;
}

// ============== 初始化 ==============
window.addEventListener('DOMContentLoaded', async () => {
  bindToolbar();
  bindModalClosers();
  bindFooter();
  await loadStatus();
  await loadBridges();
});

async function loadStatus() {
  try {
    const h = await api('GET', '/api/health');
    $('#stat-yaml').textContent = '✓ ' + (h.yaml_path || 'yaml');
    $('#stat-token').textContent = h.has_token ? '🔑 token OK' : '⚠ 无 token';
  } catch (e) {
    $('#stat-yaml').textContent = '✗ 后端不可达';
  }
}

async function loadBridges() {
  try {
    const data = await api('GET', '/api/bridges');
    state.bridges = data.bridges;
    $('#stat-bridges').textContent = `🌉 ${data.bridges.length} bridge · ${data.total_included} entity`;
    rebuildDomainFilter();
    renderBridges();
  } catch (e) {
    toast('加载 bridge 失败: ' + e.message, 'error');
  }
}

function rebuildDomainFilter() {
  allDomains = new Set();
  state.bridges.forEach(b => b.entities.forEach(e => allDomains.add(e.domain)));
  const sel = $('#domain-filter');
  const current = sel.value;
  sel.innerHTML = '<option value="">全部 domain</option>';
  Array.from(allDomains).sort().forEach(d => {
    const opt = document.createElement('option');
    opt.value = d;
    opt.textContent = d;
    sel.appendChild(opt);
  });
  if (Array.from(sel.options).some(o => o.value === current)) sel.value = current;
}

// ============== 渲染 ==============
function renderBridges() {
  const list = $('#bridge-list');
  list.innerHTML = '';
  const search = ($('#search').value || '').trim().toLowerCase();
  const domain = $('#domain-filter').value;

  state.bridges.forEach((b, idx) => {
    const panel = document.createElement('div');
    panel.className = 'bridge-panel' + (state.collapsed.has(idx) ? ' collapsed' : '');
    panel.dataset.idx = idx;

    // 过滤后的 entity
    const filtered = b.entities.filter(e => {
      if (domain && e.domain !== domain) return false;
      if (search) {
        const hay = (e.entity_id + ' ' + e.name + ' ' + e.friendly_name + ' ' + e.domain).toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });
    const dirtyCount = countDirty(b, idx);
    const totalCount = b.entities.length;

    const head = document.createElement('div');
    head.className = 'bridge-head';
    head.innerHTML = `
      <div class="bridge-title">
        <span>${escapeHtml(b.name || '未命名')}</span>
        <span class="port">${b.port}</span>
        <span class="count">显示 ${filtered.length} / 共 ${totalCount}${dirtyCount > 0 ? ` · <span class="dirty">${dirtyCount} 项待保存</span>` : ''}</span>
      </div>
      <div class="toggle">${state.collapsed.has(idx) ? '▶ 展开' : '▼ 折叠'}</div>
    `;
    head.addEventListener('click', () => {
      if (state.collapsed.has(idx)) state.collapsed.delete(idx);
      else state.collapsed.add(idx);
      renderBridges();
    });
    panel.appendChild(head);

    if (!state.collapsed.has(idx)) {
      const body = document.createElement('div');
      body.className = 'bridge-body';
      filtered.forEach(e => body.appendChild(buildEntityRow(idx, b, e)));
      panel.appendChild(body);

      const addBar = document.createElement('div');
      addBar.className = 'bridge-add';
      const addBtn = document.createElement('button');
      addBtn.textContent = '+ 添加 entity 到此 bridge';
      addBtn.addEventListener('click', () => openAddModal(idx));
      addBar.appendChild(addBtn);
      panel.appendChild(addBar);
    }

    list.appendChild(panel);
  });

  updateFooter();
}

function buildEntityRow(bridgeIdx, bridge, e) {
  const row = document.createElement('div');
  row.className = 'entity-row';
  row.dataset.entity = e.entity_id;

  // checkbox
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = isIncluded(bridgeIdx, e.entity_id, e);
  cb.addEventListener('change', () => {
    toggleIncluded(bridgeIdx, e.entity_id, e, cb.checked);
    renderBridges();
  });
  row.appendChild(cb);

  // entity id
  const idBox = document.createElement('div');
  idBox.className = 'entity-id';
  idBox.innerHTML = `<span class="domain-tag">${escapeHtml(e.domain)}</span>${escapeHtml(e.entity_id)}`;
  if (e.friendly_name && e.friendly_name !== e.entity_id) {
    const fn = document.createElement('div');
    fn.style.fontSize = '12px';
    fn.style.color = 'var(--text-mute)';
    fn.style.marginTop = '2px';
    fn.textContent = 'HA 名: ' + e.friendly_name;
    idBox.appendChild(fn);
  }
  row.appendChild(idBox);

  // name input
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'name-edit';
  nameInput.placeholder = e.friendly_name || e.entity_id;
  nameInput.value = getName(bridgeIdx, e.entity_id, e);
  nameInput.addEventListener('input', () => {
    setName(bridgeIdx, e.entity_id, nameInput.value);
    renderBridges();
  });
  row.appendChild(nameInput);

  // actions
  const actions = document.createElement('div');
  actions.className = 'actions';
  const remove = document.createElement('button');
  remove.title = '从此 bridge 移除';
  remove.textContent = '✕';
  remove.addEventListener('click', () => {
    toggleIncluded(bridgeIdx, e.entity_id, e, false);
    renderBridges();
  });
  actions.appendChild(remove);
  row.appendChild(actions);

  return row;
}

// ============== Dirty state ==============
function isIncluded(bridgeIdx, ent, e) {
  const d = state.dirty[bridgeIdx];
  if (d) return d.included.has(ent);
  // 默认:已包含 = 在原 included list 中
  return state.bridges[bridgeIdx].entities.some(x => x.entity_id === ent);
}

function toggleIncluded(bridgeIdx, ent, e, included) {
  ensureDirty(bridgeIdx);
  if (included) {
    state.dirty[bridgeIdx].included.add(ent);
    if (!state.dirty[bridgeIdx].names[ent]) {
      state.dirty[bridgeIdx].names[ent] = state.bridges[bridgeIdx].entities.find(x => x.entity_id === ent)?.name || '';
    }
  } else {
    state.dirty[bridgeIdx].included.delete(ent);
    delete state.dirty[bridgeIdx].names[ent];
  }
}

function getName(bridgeIdx, ent, e) {
  const d = state.dirty[bridgeIdx];
  if (d && ent in d.names) return d.names[ent];
  return e.name || '';
}

function setName(bridgeIdx, ent, name) {
  ensureDirty(bridgeIdx);
  if (!state.dirty[bridgeIdx].included.has(ent)) {
    state.dirty[bridgeIdx].included.add(ent);
  }
  state.dirty[bridgeIdx].names[ent] = name;
}

function ensureDirty(bridgeIdx) {
  if (!state.dirty[bridgeIdx]) {
    state.dirty[bridgeIdx] = { included: new Set(), names: {} };
    // 初始化:原 included 全部 mark 为 included
    state.bridges[bridgeIdx].entities.forEach(e => {
      state.dirty[bridgeIdx].included.add(e.entity_id);
      state.dirty[bridgeIdx].names[e.entity_id] = e.name || '';
    });
  }
}

// 查一个 entity 在「所有 bridge 的 entity list」+「allEntities」里的 friendly_name
function findFriendlyName(ent) {
  for (const b of state.bridges) {
    const hit = b.entities.find(x => x.entity_id === ent);
    if (hit && hit.friendly_name) return hit.friendly_name;
  }
  const hit2 = state.allEntities.find(x => x.entity_id === ent);
  if (hit2 && hit2.friendly_name) return hit2.friendly_name;
  return '';
}

function countDirty(bridge, idx) {
  const d = state.dirty[idx];
  if (!d) return 0;
  const origIds = new Set(bridge.entities.map(e => e.entity_id));
  let cnt = 0;
  // 添加的
  d.included.forEach(ent => { if (!origIds.has(ent)) cnt++; });
  // 移除的
  origIds.forEach(ent => { if (!d.included.has(ent)) cnt++; });
  // 名字改动
  bridge.entities.forEach(e => {
    const orig = e.name || '';
    if (d.included.has(e.entity_id) && (d.names[e.entity_id] || '') !== orig) cnt++;
  });
  return cnt;
}

function clearDirty() {
  state.dirty = {};
}

function buildSavePayload(bridgeIdx) {
  const b = state.bridges[bridgeIdx];
  const d = state.dirty[bridgeIdx] || { included: new Set(b.entities.map(e => e.entity_id)), names: {} };
  const included = Array.from(d.included);
  const ec = {};
  included.forEach(ent => {
    const nm = d.names[ent];
    if (nm) {
      ec[ent] = { name: nm };
    } else {
      // 用户没改名 → 用 HA friendly_name 兜底
      const fn = findFriendlyName(ent);
      if (fn) ec[ent] = { name: fn };
    }
  });
  return { bridge_id: b.port, included_entities: included, entity_config: ec };
}

// ============== 工具条 ==============
function bindToolbar() {
  $('#search').addEventListener('input', renderBridges);
  $('#domain-filter').addEventListener('change', renderBridges);
  $('#btn-refresh').addEventListener('click', () => loadBridges().then(() => toast('已重新加载', 'success')));
  $('#btn-backups').addEventListener('click', openBackupsModal);
  $('#btn-reload').addEventListener('click', reloadAllBridges);
}

function bindModalClosers() {
  $$('[data-close]').forEach(b => {
    b.addEventListener('click', () => {
      const id = b.dataset.close;
      $('#' + id).style.display = 'none';
    });
  });
  $$('.modal-mask').forEach(m => {
    m.addEventListener('click', () => {
      m.parentElement.style.display = 'none';
    });
  });
}

function bindFooter() {
  $('#btn-preview').addEventListener('click', openPreviewModal);
  $('#btn-save').addEventListener('click', saveAll);
}

function updateFooter() {
  let total = 0;
  Object.keys(state.dirty).forEach(idx => {
    total += countDirty(state.bridges[idx], parseInt(idx, 10));
  });
  const info = $('#dirty-info');
  if (total > 0) {
    info.textContent = `${total} 项待保存`;
    info.parentElement.classList.add('dirty');
  } else {
    info.textContent = '无修改';
    info.parentElement.classList.remove('dirty');
  }
}

// ============== 添加 entity 模态 ==============
async function openAddModal(bridgeIdx) {
  state.selectedBridgeIdx = bridgeIdx;
  state.addSelection = new Set();
  $('#add-modal-title').textContent = `添加 entity 到 Bridge ${state.bridges[bridgeIdx].port}`;
  $('#add-modal').style.display = 'flex';
  $('#add-search').value = '';

  if (state.allEntities.length === 0) {
    $('#add-list').innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-mute)">加载中…</div>';
    try {
      const data = await api('GET', '/api/entities');
      state.allEntities = data.entities;
    } catch (e) {
      $('#add-list').innerHTML = '<div style="padding:20px;color:var(--danger)">加载失败: ' + escapeHtml(e.message) + '</div>';
      return;
    }
  }
  renderAddList();
  $('#add-search').focus();
  $('#add-search').oninput = renderAddList;
  $('#btn-add-confirm').onclick = confirmAdd;
}

function renderAddList() {
  const bridge = state.bridges[state.selectedBridgeIdx];
  const already = new Set(bridge.entities.map(e => e.entity_id));
  const q = ($('#add-search').value || '').trim().toLowerCase();
  const list = $('#add-list');
  list.innerHTML = '';
  const candidates = state.allEntities.filter(e => {
    if (already.has(e.entity_id)) return false;
    if (state.dirty[state.selectedBridgeIdx]?.included.has(e.entity_id)) return false;
    if (q) {
      const hay = (e.entity_id + ' ' + e.friendly_name + ' ' + e.domain).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  if (candidates.length === 0) {
    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-mute)">无候选 entity</div>';
    return;
  }
  candidates.forEach(e => {
    const row = document.createElement('div');
    row.className = 'entity-row';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = state.addSelection.has(e.entity_id);
    cb.addEventListener('change', () => {
      if (cb.checked) state.addSelection.add(e.entity_id);
      else state.addSelection.delete(e.entity_id);
    });
    row.appendChild(cb);
    const idBox = document.createElement('div');
    idBox.className = 'entity-id';
    idBox.innerHTML = `<span class="domain-tag">${escapeHtml(e.domain)}</span>${escapeHtml(e.entity_id)}<div class="friendly">${escapeHtml(e.friendly_name || '')}</div>`;
    row.appendChild(idBox);
    list.appendChild(row);
  });
}

function confirmAdd() {
  const bridgeIdx = state.selectedBridgeIdx;
  if (state.addSelection.size === 0) {
    toast('未选择', 'warn');
    return;
  }
  ensureDirty(bridgeIdx);
  state.addSelection.forEach(ent => {
    state.dirty[bridgeIdx].included.add(ent);
    // 名字默认空,服务端会用 friendly_name
    state.dirty[bridgeIdx].names[ent] = '';
  });
  $('#add-modal').style.display = 'none';
  toast(`已暂存 ${state.addSelection.size} 个 entity,记得保存`, 'success');
  renderBridges();
}

// ============== 预览 diff ==============
async function openPreviewModal() {
  const dirtyIdxs = Object.keys(state.dirty).filter(i => countDirty(state.bridges[i], parseInt(i, 10)) > 0);
  if (dirtyIdxs.length === 0) {
    toast('无修改', 'warn');
    return;
  }
  const body = $('#preview-body');
  body.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-mute)">生成 diff 中…</div>';
  $('#preview-modal').style.display = 'flex';
  body.innerHTML = '';

  for (const idxStr of dirtyIdxs) {
    const idx = parseInt(idxStr, 10);
    const b = state.bridges[idx];
    const payload = buildSavePayload(idx);
    try {
      const diff = await api('POST', '/api/preview', payload);
      const sec = document.createElement('div');
      sec.className = 'diff-section';
      sec.innerHTML = `<h4>${escapeHtml(b.name || '')} <span class="port" style="background:#e0e7ff;color:#4338ca;padding:1px 6px;border-radius:4px;font-family:monospace">${b.port}</span> · ${diff.count_old} → ${diff.count_new} entity</h4>`;
      diff.added.forEach(ent => sec.appendChild(diffItem('added', '+', ent, '新增')));
      diff.removed.forEach(ent => sec.appendChild(diffItem('removed', '-', ent, '移除')));
      diff.name_changes.forEach(c => sec.appendChild(diffItem('changed', '~', c.entity_id, `${c.old || '(无)'} → ${c.new || '(无)'}`)));
      if (diff.added.length + diff.removed.length + diff.name_changes.length === 0) {
        sec.appendChild(diffItem('', '·', '无差异', ''));
      }
      body.appendChild(sec);
    } catch (e) {
      body.appendChild(diffItem('removed', '✗', `Bridge ${b.port} 失败: ${e.message}`, ''));
    }
  }
  $('#btn-save-from-preview').onclick = () => {
    $('#preview-modal').style.display = 'none';
    saveAll();
  };
}

function diffItem(cls, arrow, label, sub) {
  const div = document.createElement('div');
  div.className = 'diff-item ' + cls;
  div.innerHTML = `<span class="arrow">${arrow}</span><div><div>${escapeHtml(label)}</div>${sub ? `<div style="font-size:11px;opacity:.8">${escapeHtml(sub)}</div>` : ''}</div>`;
  return div;
}

// ============== 保存 ==============
async function saveAll() {
  const dirtyIdxs = Object.keys(state.dirty).filter(i => countDirty(state.bridges[i], parseInt(i, 10)) > 0);
  if (dirtyIdxs.length === 0) {
    toast('无修改', 'warn');
    return;
  }
  if (!confirm(`确认保存 ${dirtyIdxs.length} 个 bridge 的修改?\n将自动备份 yaml + reload HomeKit 集成。`)) return;

  let okCnt = 0, failCnt = 0;
  for (const idxStr of dirtyIdxs) {
    const idx = parseInt(idxStr, 10);
    const payload = buildSavePayload(idx);
    try {
      const r = await api('POST', '/api/save', payload);
      okCnt++;
      const reloadInfo = Array.isArray(r.reload) ? r.reload.filter(x => x.ok).length : 0;
      toast(`✓ Bridge ${payload.bridge_id} 保存成功 (${r.bridge.count} ent, reload ${reloadInfo}/6)`, 'success', 4000);
    } catch (e) {
      failCnt++;
      toast(`✗ Bridge ${payload.bridge_id} 失败: ${e.message}`, 'error', 6000);
    }
  }
  if (okCnt > 0) {
    clearDirty();
    await loadBridges();
  }
  if (failCnt > 0) toast(`${failCnt} 个 bridge 保存失败`, 'error', 5000);
}

// ============== 备份 ==============
async function openBackupsModal() {
  $('#backups-modal').style.display = 'flex';
  const body = $('#backups-body');
  body.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-mute)">加载中…</div>';
  try {
    const data = await api('GET', '/api/backups');
    body.innerHTML = '';
    if (data.backups.length === 0) {
      body.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-mute)">暂无备份</div>';
      return;
    }
    data.backups.forEach(b => {
      const item = document.createElement('div');
      item.className = 'backup-item';
      const date = new Date(b.mtime * 1000);
      const ts = date.toLocaleString('zh-CN');
      item.innerHTML = `
        <div>
          <div>${ts}</div>
          <div class="path">${escapeHtml(b.name)}</div>
        </div>
        <div class="actions">
          <button class="btn-secondary">⤴ 恢复</button>
        </div>
      `;
      item.querySelector('button').addEventListener('click', () => restoreBackup(b.path));
      body.appendChild(item);
    });
  } catch (e) {
    body.innerHTML = '<div style="padding:20px;color:var(--danger)">加载失败: ' + escapeHtml(e.message) + '</div>';
  }
}

async function restoreBackup(path) {
  if (!confirm('从该备份恢复?\n将覆盖当前 yaml 并 reload 所有 bridge。')) return;
  try {
    await api('POST', '/api/restore', { backup_path: path });
    toast('已恢复并 reload', 'success', 3000);
    $('#backups-modal').style.display = 'none';
    await loadBridges();
  } catch (e) {
    toast('恢复失败: ' + e.message, 'error');
  }
}

// ============== Reload ==============
async function reloadAllBridges() {
  if (!confirm('重新加载 6 个 HomeKit bridge(不修改 yaml)?')) return;
  try {
    const r = await api('POST', '/api/reload');
    const ok = r.results ? r.results.filter(x => x.ok).length : 0;
    toast(`Reload 完成: ${ok}/${r.count}`, ok === r.count ? 'success' : 'warn');
  } catch (e) {
    toast('Reload 失败: ' + e.message, 'error');
  }
}

// ============== 杂项 ==============
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
