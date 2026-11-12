// Licensing presentation and API orchestration. The optional 3D renderer lives in network.js.
const el = id => document.getElementById(id);
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const pageSize = 20, networkLimit = 24;
let csrf = '', offset = 0, licenseOffset = 0, pending = null, historyDevice = '', historyOffset = 0;
let pendingRenew = null, pendingEdit = null, pendingArchive = null, pendingUnlink = null;
let pendingDeleteDevice = null, pendingAssignDevice = null, pendingRegenerateKey = null;
let renewTargetDate = null, renewExtensionDays = 30;
const formatDateInput = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
let refreshVersion = 0, lastSync = null, scene, sceneLoading = false, sceneVisible = false;
let networkDevices = [], selectedDevice = '', motionPaused = reducedMotion.matches, detailVersion = 0, usingFallback = false;
const counters = new Map();

const stamp = value => value ? new Date(value).toLocaleString(undefined, {dateStyle:'medium', timeStyle:'short'}) : 'Not recorded';
const stampExact = value => value ? new Date(value).toLocaleString(undefined, {dateStyle:'medium', timeStyle:'medium'}) : 'Not recorded';
function timeAgo(date, ref = new Date()) {
  if (!date) return '';
  const sec = Math.floor((new Date(ref).getTime() - new Date(date).getTime()) / 1000);
  if (sec < 0) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

let heartbeatThreshold = 900, recentThreshold = 86400, lastServerTime = null;

function getDeviceActivity(d, refTime = lastServerTime || new Date(), hbSec = heartbeatThreshold, rcSec = recentThreshold) {
  if (d.activity_status === 'online' || d.activity === 'online') {
    return { status: 'Online*', dot: 'green', detail: 'Recent heartbeat' };
  }
  if (d.activity_status === 'recently_online' || d.activity === 'recently_online') {
    return { status: 'Recently online', dot: 'amber', detail: `Heartbeat ${timeAgo(d.last_seen, refTime)}` };
  }
  if (d.activity_status === 'offline' || d.activity === 'offline') {
    return { status: 'Offline', dot: 'muted', detail: 'Outside heartbeat threshold' };
  }
  if (!d.last_seen) return { status: 'Offline', dot: 'muted', detail: 'Never recorded' };
  const lastMs = new Date(d.last_seen).getTime();
  const refMs = new Date(refTime).getTime();
  const diffSec = Math.max(0, (refMs - lastMs) / 1000);
  if (d.online || diffSec <= hbSec) {
    return { status: 'Online*', dot: 'green', detail: 'Recent heartbeat' };
  }
  if (diffSec <= rcSec) {
    return { status: 'Recently online', dot: 'amber', detail: `Heartbeat ${timeAgo(d.last_seen, refTime)}` };
  }
  return { status: 'Offline', dot: 'muted', detail: 'Outside heartbeat threshold' };
}

const friendly = value => value.toLowerCase().replaceAll('_', ' ').replace(/^\w/, c => c.toUpperCase());
function node(tag, text, cls) {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (cls) item.className = cls;
  return item;
}
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('icon'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(svg.namespaceURI, 'use'); use.setAttribute('href', '#i-' + name); svg.append(use); return svg;
}
function button(text, onClick, cls = 'secondary') {
  const b = node('button', text, cls); b.type = 'button'; b.onclick = onClick; return b;
}
function badge(status) {return node('span', friendly(status), 'badge ' + status);}
function deviceColor(d) {
  if (d.effective_status === 'REVOKED') return 'red';
  if (d.detection === 'NEW') return 'amber';
  return getDeviceActivity(d).dot;
}

async function api(path, body, signal) {
  const timeout = AbortSignal.timeout(15000);
  let response;
  try {
    response = await fetch('/admin' + path, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      headers: body === undefined ? {} : {'Content-Type':'application/json','X-CSRF-Token':csrf},
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(body === undefined ? 'The licensing API could not be reached. Displayed records may be outdated. Refresh to retry.' : 'The request could not be confirmed. Refresh to check the recorded status before retrying.');
  }
  if (response.status === 401) {location.assign('/admin/sign-in'); throw new Error('Please sign in.');}
  const text = await response.text();
  let data = null;
  if (text && text.trim()) {
    try {
      data = JSON.parse(text);
    } catch {
      if (!response.ok) {
        const clean = text.replace(/<[^>]*>/g, '').trim();
        throw new Error(clean ? (clean.length > 150 ? clean.slice(0, 150) + '…' : clean) : `Server error (${response.status})`);
      }
      data = { message: text };
    }
  } else {
    data = { ok: response.ok };
  }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The action could not be completed.');
  return data;
}

function connection(state, label) {el('connection').className = 'connection ' + state; el('connection-label').textContent = label;}
function emptyRow(target, columns, text) {const row = node('tr'), cell = node('td', text, 'empty'); cell.colSpan = columns; row.append(cell); target.replaceChildren(row);}
function pager(prefix, current, length, total) {
  el(prefix + 'page').textContent = total ? `${current + 1}–${current + length} of ${total}` : 'No records';
  el(prefix + 'previous').disabled = current === 0;
  el(prefix + 'next').disabled = current + length >= total;
}

const stats = [
  ['total','Registered devices','Installation inventory','device','',null],
  ['online','Online devices','Within heartbeat threshold','signal','green-card','total'],
  ['offline','Offline devices','Outside heartbeat threshold','clock','gray-card','total'],
  ['new_alerts','New installation alerts','Awaiting acknowledgement','alert','amber-card','total'],
  ['active_licenses','Active licenses','Current software access','shield','green-card',null],
  ['revoked_licenses','Revoked licenses','License access disabled','shield','red-card',null],
  ['revoked','Revoked devices','Device access disabled','device','red-card','total']
];

for (const [key,label,sub,glyph,cls] of stats) {
  const card = node('article', null, 'card loading ' + cls), top = node('div', null, 'card-top');
  const object = node('span', null, 'stat-icon'); object.append(icon(glyph));
  const graphic = node('span', null, 'stat-mini'); graphic.setAttribute('aria-hidden','true');
  for (let i=0;i<4;i++) graphic.append(node('i'));
  top.append(object, graphic); const value = node('div', '—', 'stat-value');
  card.append(top, value, node('span',label,'stat-label'), node('span',sub,'stat-sub'));
  el('summary').append(card); counters.set(key,{card,value,graphic,number:null,frame:0});
  card.addEventListener('pointermove', event => {
    if (reducedMotion.matches || event.pointerType !== 'mouse') return;
    const rect = card.getBoundingClientRect(), x = (event.clientX-rect.left)/rect.width, y = (event.clientY-rect.top)/rect.height;
    card.style.setProperty('--tilt-x', `${(0.5-y)*2}deg`); card.style.setProperty('--tilt-y', `${(x-.5)*3}deg`);
  });
  card.addEventListener('pointerleave', () => {card.style.setProperty('--tilt-x','0deg');card.style.setProperty('--tilt-y','0deg');});
}

function renderSummary(data) {
  for (const [key,label,,, ,denominator] of stats) {
    const c = counters.get(key), next = data[key], previous = c.number;
    cancelAnimationFrame(c.frame); c.card.classList.remove('loading'); c.card.setAttribute('aria-label',`${label}: ${next}`);
    c.number = next;
    const base = denominator ? data[denominator] : key.includes('licenses') ? data.active_licenses + data.revoked_licenses : data.total;
    const ratio = base ? Math.min(1,next/base) : 0;
    c.graphic.title = `${next} of ${base} in the displayed status counts`;
    [...c.graphic.children].forEach((bar,i) => {bar.style.height = `${Math.max(2,22*Math.min(1,Math.max(0,ratio*4-i)))}px`;});
    if (previous == null || previous === next || reducedMotion.matches) {c.value.textContent = next.toLocaleString();continue;}
    const start = performance.now();
    const tick = time => {const t = Math.min(1,(time-start)/600);c.value.textContent = Math.round(previous+(next-previous)*(1-(1-t)**3)).toLocaleString();if(t<1)c.frame=requestAnimationFrame(tick);};
    c.frame = requestAnimationFrame(tick);
  }
  el('summary').setAttribute('aria-busy','false'); el('nav-devices').textContent = data.total; el('nav-alerts').textContent = data.new_alerts;
  const mobDevices = el('mob-nav-devices'); if (mobDevices) mobDevices.textContent = data.total;
  const mobAlerts = el('mob-nav-alerts'); if (mobAlerts) mobAlerts.textContent = data.new_alerts;
}

function renderDevices(data) {
  const target = el('devices'); target.replaceChildren();
  const refTime = data.server_time ? new Date(data.server_time) : (lastServerTime ? new Date(lastServerTime) : new Date());
  const hbSec = data.heartbeat_threshold_seconds || heartbeatThreshold;
  const rcSec = recentThreshold;

  for (const d of data.devices) {
    const row = node('tr'); row.dataset.deviceId = d.device_id;
    function cell(value, detail, cls) {const td = node('td',value,cls);if(detail)td.append(node('small',detail));row.append(td);return td;}
    const identity = cell(null); identity.append(button(d.device_id, () => showDevice(d.device_id), 'text-button mono'),node('small','App ' + (d.app_version || 'Unknown')));
    cell(d.customer || 'Unassociated',d.license_id || 'No license'); cell(null).append(badge(d.detection)); cell(null).append(badge(d.effective_status));

    const act = getDeviceActivity(d, refTime, hbSec, rcSec);
    const activity = node('span',null,'activity-state'); activity.append(node('i',null,'dot ' + act.dot),node('span',act.status));
    cell(null,act.detail).append(activity);

    cell(stamp(d.first_seen),'Activated: ' + stamp(d.first_activation));
    cell(stampExact(d.last_seen), d.last_seen ? timeAgo(d.last_seen, refTime) : null);
    const actionBtns = node('div', null, 'action-cell-buttons');
    actionBtns.append(button('History', () => showHistory(d.device_id)));
    if (d.license_id) {
      actionBtns.append(button('Unlink', () => openUnlinkDialog(d), 'danger'));
    } else {
      actionBtns.append(button('Assign License', () => openAssignDeviceDialog(d), 'primary'));
    }
    actionBtns.append(button(d.status === 'REVOKED' ? 'Reactivate' : 'Revoke', () => confirmAction('devices', d.device_id, d.status === 'REVOKED'), d.status === 'REVOKED' ? 'secondary' : 'danger'));
    actionBtns.append(button('Delete', () => openDeleteDeviceDialog(d), 'danger'));
    cell(null, null, 'actions').append(actionBtns);
    target.append(row);
  }
  if (!data.devices.length) emptyRow(target,8,'No devices match your search or filters.');
  pager('',offset,data.devices.length,data.total); el('device-total').textContent = `${data.total.toLocaleString()} matching devices`;
}

function renderLicenses(data) {
  const target = el('licenses'); target.replaceChildren();
  for (const l of data.licenses) {
    const row = node('tr'), customer = node('td');
    const custBtn = button(l.customer, () => showLicense(l), 'text-button');
    const idRow = node('div', null, 'id-copy-row');
    const idSpan = node('span', l.license_id, 'mono small-id');
    const copyBtn = button('Copy ID', async (e) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(l.license_id);
        copyBtn.textContent = 'Copied!';
        setTimeout(() => { if (copyBtn) copyBtn.textContent = 'Copy ID'; }, 2000);
      } catch {
        prompt('Copy this License ID:', l.license_id);
      }
    }, 'mini-copy-btn');
    idRow.append(idSpan, copyBtn);
    customer.append(custBtn, idRow);
    row.append(customer);

    const status = node('td');status.append(badge(l.status));row.append(status,node('td',stamp(l.expires_at)));
    const usage = node('td',null,'capacity'), label = node('div',null,'capacity-label'); label.append(node('span',`${l.authorized_devices} / ${l.max_devices}`),node('span','authorized'));
    const track = node('div',null,'capacity-track'), fill = node('div',null,'capacity-fill');fill.style.width = `${Math.min(100,l.authorized_devices/l.max_devices*100)}%`;track.append(fill);usage.append(label,track);row.append(usage);
    const actions = node('td',null,'actions');
    const actionBtns = node('div', null, 'action-cell-buttons');
    const isInactive = l.status === 'REVOKED' || l.status === 'ARCHIVED';
    actionBtns.append(
      button('Renew', () => openRenewDialog(l)),
      button('Edit', () => openEditLicenseDialog(l)),
      button(isInactive ? 'Reactivate' : 'Revoke', () => confirmAction('licenses', l.license_id, isInactive), isInactive ? 'secondary' : 'danger')
    );
    if (l.status !== 'ARCHIVED') {
      actionBtns.append(button('Archive', () => openArchiveDialog(l), 'danger'));
    }
    actionBtns.append(button('History', () => showLicenseHistory(l.license_id, l.customer)));
    actions.append(actionBtns);
    row.append(actions);
    target.append(row);
  }
  if (!data.licenses.length) emptyRow(target,5,'No licenses match your search or filters.');
  pager('licenses-',licenseOffset,data.licenses.length,data.total);el('license-total').textContent = `${data.total.toLocaleString()} matching licenses`;
}

function renderAlerts(alerts, total) {
  const target = el('alerts'); target.replaceChildren(); el('alert-count').textContent = total;
  if (!alerts.length) {const object = node('div',null,'empty-icon');object.append(icon('check'));const empty = node('p',null,'empty');empty.append(node('strong','All installations reviewed'),node('span','No unacknowledged installation alerts.'));target.append(object,empty);}
  for (const a of alerts) {
    const card = node('article',null,'alert'), top = node('div',null,'alert-top');top.append(button(a.customer || 'Unassociated installation',()=>showDevice(a.device_id),'text-button alert-title'),badge('NEW'));
    const meta = node('div',null,'alert-meta');meta.append(node('div','License: ' + (a.license_id || 'Not associated'),'mono'),node('div','App version ' + (a.app_version || 'Unknown')),node('small','First seen ' + stamp(a.first_seen)));
    const bottom = node('div',null,'alert-bottom'), ack = button('Acknowledge',async () => {
      ack.disabled = true;
      try {await api(`/alerts/${encodeURIComponent(a.id)}/acknowledge`,{});el('result').textContent='Installation alert acknowledged.';await refresh();}
      catch(error){el('error').textContent=error.message;}finally{ack.disabled=false;}
    });
    bottom.append(node('span','Awaiting review'),ack);card.append(top,node('p',a.device_id,'mono'),meta,bottom);target.append(card);
  }
  if (total > alerts.length) target.append(node('p',`Showing the latest ${alerts.length} of ${total} outstanding alerts. Acknowledge reviewed alerts to reveal older records.`,'detail-note'));
  target.setAttribute('aria-busy','false');
}

function auditRow(a) {
  const row = node('div',null,'audit-row'), glyph=node('span',null,'audit-icon');glyph.append(icon(a.event.includes('revok') || a.event.includes('license') ? 'shield' : a.event.includes('device') ? 'device' : 'clock'));
  const body = node('div');body.append(node('strong',friendly(a.event)),node('p',`${a.actor}${a.device_id ? ' · '+a.device_id : ''}${a.reason ? ' · '+a.reason : ''}`));row.append(glyph,body,node('time',stamp(a.created_at),'audit-time'));return row;
}

const POLL_INTERVAL = 30000;
const BASE_RETRY_DELAY = 2000;
const MAX_RETRIES = 5;
let pollTimer = null;
let retryCount = 0;
let isRefreshing = false;
let queuedRefresh = false;

function scheduleNextPoll(delay = POLL_INTERVAL) {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  if (document.hidden) return;
  pollTimer = setTimeout(async () => {
    if (document.querySelector('dialog[open]')) {
      scheduleNextPoll(POLL_INTERVAL);
      return;
    }
    await refresh();
  }, delay);
}

async function refresh() {
  if (isRefreshing) {
    queuedRefresh = true;
    return;
  }
  isRefreshing = true;
  queuedRefresh = false;

  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }

  const version = ++refreshVersion;
  el('refresh').disabled = true;
  el('refresh').setAttribute('aria-busy', 'true');
  el('error').textContent = '';

  const deviceParams = new URLSearchParams({offset, limit: pageSize, activity: el('activity').value, status: el('device-status').value, q: el('device-search').value});
  const licenseParams = new URLSearchParams({offset: licenseOffset, limit: pageSize, status: el('license-status').value, q: el('license-search').value});

  try {
    if (!csrf) {
      const me = await api('/me');
      csrf = me.csrf_token;
      el('user').textContent = me.username;
      el('environment').textContent = me.environment;
    }
    const [summary, devices, licenses, alerts, audit, network] = await Promise.all([
      api('/summary'),
      api('/devices?' + deviceParams),
      api('/licenses?' + licenseParams),
      api('/alerts'),
      api('/audit'),
      api(`/devices?limit=${networkLimit}`)
    ]);

    if (version !== refreshVersion) return;

    heartbeatThreshold = summary.heartbeat_threshold_seconds || 900;
    recentThreshold = summary.recent_threshold_seconds || 86400;
    lastServerTime = network.server_time || devices.server_time || new Date().toISOString();

    // A revocation can remove the last item on a filtered final page. Return to a valid page.
    if (offset && !devices.devices.length && devices.total <= offset) {
      offset = Math.max(0, Math.floor(Math.max(0, devices.total - 1) / pageSize) * pageSize);
      isRefreshing = false;
      refresh();
      return;
    }
    if (licenseOffset && !licenses.licenses.length && licenses.total <= licenseOffset) {
      licenseOffset = Math.max(0, Math.floor(Math.max(0, licenses.total - 1) / pageSize) * pageSize);
      isRefreshing = false;
      refresh();
      return;
    }

    renderSummary(summary);
    renderDevices(devices);
    renderLicenses(licenses);
    renderAlerts(alerts, summary.new_alerts);
    el('audit').replaceChildren(...audit.map(auditRow));
    el('audit').setAttribute('aria-busy', 'false');
    if (!audit.length) el('audit').append(node('p', 'No administrator events recorded.', 'empty'));

    lastSync = new Date();
    retryCount = 0;
    el('last-sync').textContent = 'Synced ' + lastSync.toLocaleTimeString(undefined, {hour:'2-digit', minute:'2-digit'});
    connection('', 'API reachable');
    el('connection').title = 'Last successful API sync: ' + lastSync.toLocaleString();
    el('freshness').textContent = `*Online: heartbeat within ${heartbeatThreshold / 60} minutes. Updated ${stampExact(lastServerTime)}. Earlier heartbeats are offline, not live connections.`;

    networkDevices = network.devices;
    el('network-count').textContent = `${network.devices.length} of ${network.total} devices`;
    el('network-count').title = 'Latest registered devices; all installations are searchable in the inventory.';
    renderRoster();
    if (scene) scene.update(networkDevices);
    else if (usingFallback) {
      const count = el('network-stage').querySelectorAll('.fallback-device').length;
      if (count !== networkDevices.length) fallbackNetwork();
    } else ensureScene();

    scheduleNextPoll(POLL_INTERVAL);
  } catch (error) {
    el('error').textContent = error.message;
    connection('disconnected', 'Sync unavailable');
    if (!lastSync) {
      el('scene-loading').textContent = 'Device data unavailable. Refresh to retry.';
      el('scene-state').textContent = 'Waiting for API data';
    }
    if (retryCount < MAX_RETRIES) {
      const delay = Math.min(BASE_RETRY_DELAY * Math.pow(2, retryCount), POLL_INTERVAL);
      retryCount++;
      scheduleNextPoll(delay);
    } else {
      scheduleNextPoll(POLL_INTERVAL);
    }
  } finally {
    isRefreshing = false;
    if (version === refreshVersion) {
      el('refresh').disabled = false;
      el('refresh').setAttribute('aria-busy', 'false');
    }
    if (queuedRefresh) {
      queuedRefresh = false;
      refresh();
    }
  }
}

function renderRoster() {
  el('network-roster').replaceChildren(...networkDevices.map(d => {
    const act = getDeviceActivity(d);
    const b = button(null, () => showDevice(d.device_id), '');
    b.dataset.deviceId = d.device_id;
    b.setAttribute('aria-label', `${d.customer || 'Unassociated'} · ${d.device_id} · ${act.status} · ${friendly(d.effective_status)}`);
    b.append(node('i', null, 'dot ' + deviceColor(d)), node('span', d.device_id.slice(0, 8)));
    b.classList.toggle('selected', selectedDevice === d.device_id);
    return b;
  }));
  if (!networkDevices.length) el('network-roster').append(node('p', 'No registered devices.', 'detail-note'));
}

function selectDevice(id) {
  selectedDevice = id;
  scene?.select(id);
  el('network-roster').querySelectorAll('button').forEach(b => {
    b.classList.toggle('selected', b.dataset.deviceId === id);
    b.setAttribute('aria-pressed', String(b.dataset.deviceId === id));
  });
}

function fallbackNetwork() {
  usingFallback = true;
  const map = node('div', null, 'fallback-map');
  map.append(node('div', 'Licensing server', 'fallback-server'));
  for (const d of networkDevices) {
    const act = getDeviceActivity(d);
    const b = button(null, () => showDevice(d.device_id), 'fallback-device');
    b.append(icon('device'), node('span', d.customer || d.device_id.slice(0, 8)), node('span', act.status), badge(d.effective_status));
    map.append(b);
  }
  el('scene-loading')?.remove();
  el('network-stage').querySelector('.fallback-map')?.remove();
  el('network-stage').append(map);
  el('scene-state').textContent = '3D unavailable · accessible device map';
  el('motion-toggle').disabled = true;
}

async function ensureScene() {
  if (!sceneVisible || sceneLoading || scene || !lastSync) return;
  sceneLoading = true;
  try {
    const module = await import('./network.js');
    scene = module.createNetwork(el('network-stage'), {
      onSelect: id => showDevice(id),
      onState: text => el('scene-state').textContent = text,
      onFailure: () => { scene?.dispose(); scene = null; fallbackNetwork(); },
      paused: motionPaused,
      reducedMotion: reducedMotion.matches
    });
    scene.update(networkDevices);
    scene.select(selectedDevice);
    el('scene-loading')?.remove();
  } catch {
    fallbackNetwork();
  }
}

const sceneObserver = new IntersectionObserver(entries => {
  sceneVisible = entries[0].isIntersecting;
  scene?.setVisible(sceneVisible);
  if (sceneVisible) ensureScene();
}, {threshold: .05});
sceneObserver.observe(el('network-stage'));

function updateMotion() {
  el('motion-toggle').textContent = reducedMotion.matches ? 'Reduced motion enabled' : motionPaused ? 'Resume motion' : 'Pause motion';
  el('motion-toggle').disabled = reducedMotion.matches;
  el('motion-toggle').setAttribute('aria-pressed', String(motionPaused));
  scene?.setMotion(motionPaused, reducedMotion.matches);
}
el('motion-toggle').onclick = () => { motionPaused = !motionPaused; updateMotion(); };
reducedMotion.addEventListener('change', () => { motionPaused = reducedMotion.matches; updateMotion(); });
updateMotion();

function detailFields(fields) {
  const grid = node('dl', null, 'detail-grid');
  for (const [key, value] of fields) {
    const row = node('div');
    row.append(node('dt', key), node('dd', value ?? 'Not associated'));
    grid.append(row);
  }
  return grid;
}

function openDetail(title, eyebrow) {
  el('detail-title').textContent = title;
  el('detail-eyebrow').textContent = eyebrow;
  el('detail-body').replaceChildren(node('p', 'Loading information…', 'empty'));
  el('detail-actions').replaceChildren();
  if (!el('detail-dialog').open) el('detail-dialog').showModal();
}

async function showDevice(id) {
  selectDevice(id);
  const version = ++detailVersion;
  openDetail('Device details', 'INSTALLATION INFORMATION');
  try {
    const d = await api(`/devices/${encodeURIComponent(id)}`);
    if (version !== detailVersion || !el('detail-dialog').open) return;
    const refTime = lastServerTime ? new Date(lastServerTime) : new Date();
    const act = getDeviceActivity(d, refTime);
    const identity = node('div', null, 'detail-identity');
    identity.append(icon('device'), node('h3', d.customer || 'Unassociated installation'), badge(d.effective_status), node('p', d.device_id, 'mono'));
    el('detail-body').replaceChildren(identity, detailFields([
      ['Device status', friendly(d.status)],
      ['Effective access', friendly(d.effective_status)],
      ['Detection', d.detection === 'NEW' ? 'Awaiting review' : 'Reviewed / seen'],
      ['License', d.license_id],
      ['License status', d.license_status === 'DISABLED' ? 'Revoked' : d.license_status],
      ['License expiry', stamp(d.license_expires_at)],
      ['Application', d.app_version],
      ['Registered', stamp(d.first_seen)],
      ['First activation', stamp(d.first_activation)],
      ['Last seen', stampExact(d.last_seen) + (d.last_seen ? ` (${timeAgo(d.last_seen, refTime)})` : '')],
      ['Activity', `${act.status} (${act.detail})`]
    ]), node('p', 'Activity reports the last observed heartbeat. Licensing authorization is a separate status.', 'detail-note'));
    const deviceDetailActions = [
      button('Activity history', () => { el('detail-dialog').close(); showHistory(id); })
    ];
    if (d.license_id) {
      deviceDetailActions.push(button('Unlink device', () => { el('detail-dialog').close(); openUnlinkDialog(d); }, 'danger'));
    }
    deviceDetailActions.push(button(d.status === 'REVOKED' ? 'Reactivate device' : 'Revoke device', () => confirmAction('devices', id, d.status === 'REVOKED'), d.status === 'REVOKED' ? 'secondary' : 'danger'));
    el('detail-actions').replaceChildren(...deviceDetailActions);
  } catch (error) {
    if (version === detailVersion) el('detail-body').replaceChildren(node('p', error.message, 'error'));
  }
}

async function showLicense(l) {
  const version = ++detailVersion;
  openDetail('License details', 'SOFTWARE AUTHORIZATION');
  const identity = node('div', null, 'detail-identity');
  identity.append(icon('shield'), node('h3', l.customer), badge(l.status), node('p', l.license_id, 'mono'));
  const associations = node('div', null, 'associated-devices');
  associations.append(node('h3', 'Associated installations'), node('p', 'Loading devices…', 'detail-note'));
  el('detail-body').replaceChildren(identity, detailFields([
    ['Customer ID', l.customer_id],
    ['Expires', stamp(l.expires_at)],
    ['Authorized', `${l.authorized_devices} devices`],
    ['Device limit', l.max_devices]
  ]), associations);
  const isInactive = l.status === 'REVOKED' || l.status === 'ARCHIVED';
  const licenseDetailActions = [
    button('Renew license', () => { el('detail-dialog').close(); openRenewDialog(l); }),
    button('Edit configuration', () => { el('detail-dialog').close(); openEditLicenseDialog(l); }),
    button('License history', () => { el('detail-dialog').close(); showLicenseHistory(l.license_id, l.customer); }),
    button(isInactive ? 'Reactivate license' : 'Revoke license', () => confirmAction('licenses', l.license_id, isInactive), isInactive ? 'secondary' : 'danger')
  ];
  if (l.status !== 'ARCHIVED') {
    licenseDetailActions.push(button('Archive license', () => { el('detail-dialog').close(); openArchiveDialog(l); }, 'danger'));
  }
  el('detail-actions').replaceChildren(...licenseDetailActions);
  try {
    const data = await api('/devices?' + new URLSearchParams({license_id: l.license_id, limit: 20}));
    if (version !== detailVersion || !el('detail-dialog').open) return;
    associations.replaceChildren(node('h3', 'Associated installations'));
    for (const d of data.devices) {
      const b = button(null, () => showDevice(d.device_id), '');
      b.append(node('span', d.device_id.slice(0, 8) + ' · App ' + d.app_version), badge(d.effective_status));
      associations.append(b);
    }
    associations.append(node('p', data.total ? `Showing ${data.devices.length} of ${data.total} associated devices. Search the license ID in the device inventory to browse all.` : 'No associated devices.', 'detail-note'));
  } catch (error) {
    if (version === detailVersion) associations.replaceChildren(node('p', error.message, 'error'));
  }
}

function confirmAction(kind, id, reactivate) {
  el('detail-dialog').close();
  pending = {kind, id, action: reactivate ? 'reactivate' : 'revoke'};
  el('action-title').textContent = `${reactivate ? 'Reactivate' : 'Revoke'} ${kind === 'licenses' ? 'license' : 'device'}`;
  el('action-device').textContent = id;
  el('action-description').textContent = reactivate ? 'Access resumes after a successful signed validation. License reactivation keeps individually revoked devices revoked.' : `Revocation applies to ${kind === 'licenses' ? 'all associated devices' : 'this device'} after the next successful validation. Active database transactions finish safely.`;
  el('reason').value = '';
  el('confirm').checked = false;
  el('action-error').textContent = '';
  el('apply').className = reactivate ? '' : 'danger';
  el('confirmation').showModal();
  el('reason').focus();
}

async function showHistory(id, change = 0) {
  if (historyDevice !== id) historyOffset = 0;
  historyDevice = id;
  historyOffset = Math.max(0, historyOffset + change);
  try {
    const data = await api(`/devices/${encodeURIComponent(id)}/history?offset=${historyOffset}&limit=${pageSize}`);
    el('history-device').textContent = `${id} · Registered ${stamp(data.first_seen)} · First activation ${stamp(data.first_activation)}`;
    el('history').replaceChildren(...data.events.map(auditRow));
    if (!data.events.length) el('history').append(node('p', 'No activation events recorded.', 'empty'));
    pager('history-', historyOffset, data.events.length, data.total);
    if (!el('history-dialog').open) el('history-dialog').showModal();
  } catch (error) {
    el('error').textContent = error.message;
  }
}

el('action').onsubmit = async event => {
  event.preventDefault();
  el('apply').disabled = true;
  el('cancel').disabled = true;
  try {
    const match = pending.kind === 'licenses' ? {confirmed_license_id: pending.id} : {confirmed_device_id: pending.id};
    const result = await api(`/${pending.kind}/${encodeURIComponent(pending.id)}/${pending.action}`, {confirm: el('confirm').checked, ...match, reason: el('reason').value});
    el('result').textContent = result.message;
    el('confirmation').close();
    await refresh();
  } catch (error) {
    el('action-error').textContent = error.message;
  } finally {
    el('apply').disabled = false;
    el('cancel').disabled = false;
  }
};

el('confirmation').addEventListener('cancel', event => { if (el('apply').disabled) event.preventDefault(); });
el('cancel').onclick = () => el('confirmation').close();
el('detail-close').onclick = () => el('detail-dialog').close();
el('detail-dialog').addEventListener('close', () => { detailVersion++; });
el('history-close').onclick = () => el('history-dialog').close();
el('history-previous').onclick = () => showHistory(historyDevice, -pageSize);
el('history-next').onclick = () => showHistory(historyDevice, pageSize);

el('open-issue-license').onclick = () => {
  el('issue-customer').value = '';
  el('issue-notes').value = '';
  el('issue-error').textContent = '';
  el('issue-error').style.display = 'none';
  el('issue-max-devices').value = '1';

  const today = new Date();
  const pad = n => String(n).padStart(2, '0');
  const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
  const nextYear = new Date(today);
  nextYear.setFullYear(today.getFullYear() + 1);
  const nextYearStr = `${nextYear.getFullYear()}-${pad(nextYear.getMonth() + 1)}-${pad(nextYear.getDate())}`;

  el('issue-expiry').min = todayStr;
  el('issue-expiry').value = nextYearStr;

  el('issue-dialog').showModal();
  el('issue-customer').focus();
};

el('issue-cancel').onclick = () => el('issue-dialog').close();
el('issue-dismiss').onclick = () => el('issue-dialog').close();
el('issue-dialog').addEventListener('cancel', event => { if (el('issue-submit').disabled) event.preventDefault(); });

el('issue-form').onsubmit = async event => {
  event.preventDefault();

  const customer = el('issue-customer').value.trim();
  if (!customer) {
    el('issue-error').textContent = 'Customer / Pharmacy Name is required.';
    el('issue-error').style.display = 'block';
    return;
  }

  const expiryVal = el('issue-expiry').value;
  const expiryDate = new Date(expiryVal + 'T23:59:59Z');
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  const todayStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;

  if (!expiryVal || isNaN(expiryDate.getTime()) || expiryVal < todayStr || expiryDate <= now) {
    el('issue-error').textContent = 'Please select a valid future expiration date.';
    el('issue-error').style.display = 'block';
    return;
  }

  const maxDevices = parseInt(el('issue-max-devices').value, 10);
  if (isNaN(maxDevices) || maxDevices < 1) {
    el('issue-error').textContent = 'Maximum allowed devices must be at least 1.';
    el('issue-error').style.display = 'block';
    return;
  }

  el('issue-error').style.display = 'none';
  el('issue-error').textContent = '';
  el('issue-submit').disabled = true;
  el('issue-dismiss').disabled = true;

  try {
    const result = await api('/licenses/issue', {
      customer,
      expires_at: expiryDate.toISOString(),
      max_devices: maxDevices,
      notes: el('issue-notes').value.trim()
    });

    el('issue-dialog').close();
    el('generated-key-input').value = result.activation_key;
    el('issued-customer').textContent = result.customer;
    el('issued-license-id').textContent = result.license_id;
    el('issued-expires').textContent = stamp(result.expires_at);
    el('issued-devices').textContent = `${result.max_devices} workstation${result.max_devices > 1 ? 's' : ''}`;
    el('copy-btn-text').textContent = 'Copy Key';
    el('copy-feedback').textContent = '';
    el('success-key-dialog').showModal();
    await refresh();
  } catch (error) {
    el('issue-error').textContent = error.message;
    el('issue-error').style.display = 'block';
  } finally {
    el('issue-submit').disabled = false;
    el('issue-dismiss').disabled = false;
  }
};

el('copy-key-btn').onclick = async () => {
  const key = el('generated-key-input').value;
  if (!key) return;
  try {
    if (!navigator.clipboard?.writeText) {
      throw new Error('Clipboard API unavailable');
    }
    await navigator.clipboard.writeText(key);
    el('copy-btn-text').textContent = 'Copied!';
    el('copy-feedback').textContent = '✓ Activation key copied to clipboard';
    setTimeout(() => { if (el('copy-btn-text')) el('copy-btn-text').textContent = 'Copy Key'; }, 3000);
  } catch {
    el('generated-key-input').select();
    el('copy-feedback').textContent = 'Clipboard access denied. Please select and copy manually.';
  }
};

el('success-key-close').onclick = () => el('success-key-dialog').close();
el('success-done-btn').onclick = () => el('success-key-dialog').close();

el('success-key-dialog').addEventListener('close', () => {
  el('generated-key-input').value = '';
  el('copy-feedback').textContent = '';
});

function applyRenewPreset(days) {
  if (!pendingRenew) return;
  const isExpired = pendingRenew.status === 'EXPIRED' || (pendingRenew.expires_at && new Date(pendingRenew.expires_at).getTime() <= Date.now());
  const baseDate = isExpired || !pendingRenew.expires_at ? new Date() : new Date(pendingRenew.expires_at);
  const newDate = new Date(baseDate.getTime() + days * 86400 * 1000);
  el('renew-custom-date').value = formatDateInput(newDate);
  ['30', '90', '365'].forEach(d => {
    el('renew-preset-' + d)?.classList.toggle('active', parseInt(d, 10) === days);
  });
  renewTargetDate = newDate;
  renewExtensionDays = days;
  const currentStamp = stamp(pendingRenew.expires_at);
  const newStamp = stamp(newDate);
  el('renew-preview-text').textContent = `Current: ${currentStamp} → New: ${newStamp}`;
}

function openRenewDialog(license) {
  pendingRenew = license;
  const isExpired = license.status === 'EXPIRED' || (license.expires_at && new Date(license.expires_at).getTime() <= Date.now());
  el('renew-license-id').textContent = license.license_id;
  el('renew-customer-name').textContent = license.customer || 'Unknown';
  el('renew-current-expiry').textContent = stamp(license.expires_at) + (isExpired ? ' (Expired)' : '');
  el('renew-reason').value = '';
  el('renew-confirm').checked = false;
  el('renew-error').textContent = '';
  el('renew-error').style.display = 'none';
  el('renew-custom-date').min = formatDateInput(new Date());
  applyRenewPreset(30);
  el('renew-dialog').showModal();
  el('renew-reason').focus();
}

for (const days of [30, 90, 365]) {
  el('renew-preset-' + days).onclick = () => applyRenewPreset(days);
}

el('renew-custom-date').oninput = () => {
  if (!pendingRenew) return;
  ['30', '90', '365'].forEach(d => el('renew-preset-' + d)?.classList.remove('active'));
  renewExtensionDays = null;
  const val = el('renew-custom-date').value;
  if (!val) {
    el('renew-preview-text').textContent = 'Please select a valid date';
    renewTargetDate = null;
    return;
  }
  const newDate = new Date(val + 'T23:59:59Z');
  renewTargetDate = newDate;
  const currentStamp = stamp(pendingRenew.expires_at);
  const newStamp = stamp(newDate);
  el('renew-preview-text').textContent = `Current: ${currentStamp} → New: ${newStamp}`;
};

el('renew-cancel').onclick = () => el('renew-dialog').close();
el('renew-dialog').addEventListener('cancel', event => { if (el('renew-submit').disabled) event.preventDefault(); });

el('renew-form').onsubmit = async event => {
  event.preventDefault();
  if (!pendingRenew) return;
  const reason = el('renew-reason').value.trim();
  if (reason.length < 3) {
    el('renew-error').textContent = 'Please provide a valid reason (at least 3 characters).';
    el('renew-error').style.display = 'block';
    return;
  }
  if (!el('renew-confirm').checked) {
    el('renew-error').textContent = 'Please check the confirmation box.';
    el('renew-error').style.display = 'block';
    return;
  }
  if (!renewTargetDate || isNaN(renewTargetDate.getTime()) || renewTargetDate.getTime() <= Date.now()) {
    el('renew-error').textContent = 'Renewal expiration date must be in the future.';
    el('renew-error').style.display = 'block';
    return;
  }
  el('renew-error').style.display = 'none';
  el('renew-submit').disabled = true;
  el('renew-cancel').disabled = true;
  try {
    const payload = {
      confirm: true,
      confirmed_license_id: pendingRenew.license_id,
      expires_at: renewTargetDate.toISOString(),
      reason
    };
    if (renewExtensionDays) {
      payload.extension_days = renewExtensionDays;
    }
    const result = await api(`/licenses/${encodeURIComponent(pendingRenew.license_id)}/renew`, payload);
    el('renew-dialog').close();
    el('result').textContent = result.message || 'License renewed successfully.';
    await refresh();
  } catch (error) {
    el('renew-error').textContent = error.message;
    el('renew-error').style.display = 'block';
  } finally {
    el('renew-submit').disabled = false;
    el('renew-cancel').disabled = false;
  }
};

function openEditLicenseDialog(license) {
  pendingEdit = license;
  el('edit-license-id').textContent = license.license_id;
  el('edit-license-status').textContent = friendly(license.status);
  el('edit-license-status').className = 'badge ' + license.status;
  el('edit-customer-name').value = license.customer || '';
  el('edit-max-devices').value = license.max_devices;
  el('edit-expiry-date').value = license.expires_at ? license.expires_at.slice(0, 10) : '';
  el('edit-license-reason').value = '';
  el('edit-license-confirm').checked = false;
  el('edit-license-error').textContent = '';
  el('edit-license-error').style.display = 'none';
  el('edit-license-dialog').showModal();
  el('edit-customer-name').focus();
}

el('edit-license-cancel').onclick = () => el('edit-license-dialog').close();
el('edit-license-dialog').addEventListener('cancel', event => { if (el('edit-license-submit').disabled) event.preventDefault(); });

el('edit-license-form').onsubmit = async event => {
  event.preventDefault();
  if (!pendingEdit) return;
  const customer_name = el('edit-customer-name').value.trim();
  if (!customer_name) {
    el('edit-license-error').textContent = 'Customer name cannot be blank.';
    el('edit-license-error').style.display = 'block';
    return;
  }
  const max_devices = parseInt(el('edit-max-devices').value, 10);
  if (isNaN(max_devices) || max_devices < 1) {
    el('edit-license-error').textContent = 'Maximum devices must be at least 1.';
    el('edit-license-error').style.display = 'block';
    return;
  }
  const expiryVal = el('edit-expiry-date').value;
  if (!expiryVal) {
    el('edit-license-error').textContent = 'Expiration date is required.';
    el('edit-license-error').style.display = 'block';
    return;
  }
  const expiryDate = new Date(expiryVal + 'T23:59:59Z');
  if (isNaN(expiryDate.getTime()) || expiryDate.getTime() <= Date.now()) {
    el('edit-license-error').textContent = 'Expiration date must be in the future.';
    el('edit-license-error').style.display = 'block';
    return;
  }
  const reason = el('edit-license-reason').value.trim();
  if (reason.length < 3) {
    el('edit-license-error').textContent = 'Please provide a reason (at least 3 characters).';
    el('edit-license-error').style.display = 'block';
    return;
  }
  if (!el('edit-license-confirm').checked) {
    el('edit-license-error').textContent = 'Please check the confirmation box.';
    el('edit-license-error').style.display = 'block';
    return;
  }
  el('edit-license-error').style.display = 'none';
  el('edit-license-submit').disabled = true;
  el('edit-license-cancel').disabled = true;
  try {
    const result = await api(`/licenses/${encodeURIComponent(pendingEdit.license_id)}/edit`, {
      confirm: true,
      confirmed_license_id: pendingEdit.license_id,
      customer_name,
      max_devices,
      expires_at: expiryDate.toISOString(),
      reason
    });
    el('edit-license-dialog').close();
    el('result').textContent = result.message || 'License updated successfully.';
    await refresh();
  } catch (error) {
    el('edit-license-error').textContent = error.message;
    el('edit-license-error').style.display = 'block';
  } finally {
    el('edit-license-submit').disabled = false;
    el('edit-license-cancel').disabled = false;
  }
};

function openArchiveDialog(license) {
  pendingArchive = license;
  el('archive-license-id').textContent = license.license_id;
  el('archive-customer-name').textContent = license.customer || 'Unknown';
  el('archive-reason').value = '';
  el('archive-confirm').checked = false;
  el('archive-error').textContent = '';
  el('archive-error').style.display = 'none';
  el('archive-license-dialog').showModal();
  el('archive-reason').focus();
}

el('archive-cancel').onclick = () => el('archive-license-dialog').close();
el('archive-license-dialog').addEventListener('cancel', event => { if (el('archive-submit').disabled) event.preventDefault(); });

el('archive-license-form').onsubmit = async event => {
  event.preventDefault();
  if (!pendingArchive) return;
  const reason = el('archive-reason').value.trim();
  if (reason.length < 3) {
    el('archive-error').textContent = 'Please provide a reason (at least 3 characters).';
    el('archive-error').style.display = 'block';
    return;
  }
  if (!el('archive-confirm').checked) {
    el('archive-error').textContent = 'Please confirm archiving this license.';
    el('archive-error').style.display = 'block';
    return;
  }
  el('archive-error').style.display = 'none';
  el('archive-submit').disabled = true;
  el('archive-cancel').disabled = true;
  try {
    const result = await api(`/licenses/${encodeURIComponent(pendingArchive.license_id)}/archive`, {
      confirm: true,
      confirmed_license_id: pendingArchive.license_id,
      reason
    });
    el('archive-license-dialog').close();
    el('result').textContent = result.message || 'License safely archived.';
    await refresh();
  } catch (error) {
    el('archive-error').textContent = error.message;
    el('archive-error').style.display = 'block';
  } finally {
    el('archive-submit').disabled = false;
    el('archive-cancel').disabled = false;
  }
};

async function showLicenseHistory(license_id, customerName) {
  el('license-history-id').textContent = license_id;
  el('license-history-customer').textContent = customerName ? `${customerName} · License Audit` : 'License Audit Timeline';
  el('license-history').replaceChildren(node('p', 'Loading audit history…', 'empty'));
  if (!el('license-history-dialog').open) el('license-history-dialog').showModal();
  try {
    const data = await api(`/licenses/${encodeURIComponent(license_id)}/history`);
    const events = data.events || data;
    el('license-history').replaceChildren(...events.map(auditRow));
    if (!events.length) {
      el('license-history').append(node('p', 'No audit events recorded for this license.', 'empty'));
    }
  } catch (error) {
    el('license-history').replaceChildren(node('p', error.message, 'error'));
  }
}
el('license-history-close').onclick = () => el('license-history-dialog').close();

function openUnlinkDialog(device) {
  pendingUnlink = device;
  el('unlink-device-id').textContent = device.device_id;
  el('unlink-customer').textContent = `${device.customer || 'Unassociated'} (License: ${device.license_id || 'None'})`;
  el('unlink-reason').value = '';
  el('unlink-confirm').checked = false;
  el('unlink-error').textContent = '';
  el('unlink-error').style.display = 'none';
  el('unlink-device-dialog').showModal();
  el('unlink-reason').focus();
}

el('unlink-cancel').onclick = () => el('unlink-device-dialog').close();
el('unlink-device-dialog').addEventListener('cancel', event => { if (el('unlink-submit').disabled) event.preventDefault(); });

el('unlink-device-form').onsubmit = async event => {
  event.preventDefault();
  if (!pendingUnlink) return;
  const reason = el('unlink-reason').value.trim();
  if (reason.length < 3) {
    el('unlink-error').textContent = 'Please provide a reason (at least 3 characters).';
    el('unlink-error').style.display = 'block';
    return;
  }
  if (!el('unlink-confirm').checked) {
    el('unlink-error').textContent = 'Please check the confirmation box.';
    el('unlink-error').style.display = 'block';
    return;
  }
  el('unlink-error').style.display = 'none';
  el('unlink-submit').disabled = true;
  el('unlink-cancel').disabled = true;
  try {
    const result = await api(`/devices/${encodeURIComponent(pendingUnlink.device_id)}/unlink`, {
      confirm: true,
      confirmed_device_id: pendingUnlink.device_id,
      reason
    });
    el('unlink-device-dialog').close();
    el('result').textContent = result.message || 'Device unlinked successfully.';
    await refresh();
  } catch (error) {
    el('unlink-error').textContent = error.message;
    el('unlink-error').style.display = 'block';
  } finally {
    el('unlink-submit').disabled = false;
    el('unlink-cancel').disabled = false;
  }
};

function openDeleteDeviceDialog(device) {
  pendingDeleteDevice = device;
  el('delete-device-id').textContent = device.device_id;
  el('delete-device-customer').textContent = `${device.customer || 'Unassociated'} (License: ${device.license_id || 'None'})`;
  el('delete-device-reason').value = '';
  el('delete-device-confirm').checked = false;
  el('delete-device-error').textContent = '';
  el('delete-device-error').style.display = 'none';
  el('delete-device-dialog').showModal();
  el('delete-device-reason').focus();
}

el('delete-device-cancel').onclick = () => el('delete-device-dialog').close();
el('delete-device-dialog').addEventListener('cancel', event => { if (el('delete-device-submit').disabled) event.preventDefault(); });

el('delete-device-form').onsubmit = async event => {
  event.preventDefault();
  if (!pendingDeleteDevice) return;
  const reason = el('delete-device-reason').value.trim();
  if (reason.length < 3) {
    el('delete-device-error').textContent = 'Please provide a reason (at least 3 characters).';
    el('delete-device-error').style.display = 'block';
    return;
  }
  if (!el('delete-device-confirm').checked) {
    el('delete-device-error').textContent = 'Please check the confirmation box.';
    el('delete-device-error').style.display = 'block';
    return;
  }
  el('delete-device-error').style.display = 'none';
  el('delete-device-submit').disabled = true;
  el('delete-device-cancel').disabled = true;
  try {
    const result = await api(`/devices/${encodeURIComponent(pendingDeleteDevice.device_id)}/delete`, {
      confirm: true,
      confirmed_device_id: pendingDeleteDevice.device_id,
      reason
    });
    el('delete-device-dialog').close();
    el('result').textContent = result.message || 'Device deleted successfully.';
    await refresh();
  } catch (error) {
    el('delete-device-error').textContent = error.message;
    el('delete-device-error').style.display = 'block';
  } finally {
    el('delete-device-submit').disabled = false;
    el('delete-device-cancel').disabled = false;
  }
};

async function openAssignDeviceDialog(device) {
  pendingAssignDevice = device;
  const idInput = el('assign-device-id-input');
  if (device) {
    if (idInput) idInput.value = device.device_id;
    el('assign-device-id').textContent = device.device_id;
    el('assign-device-status').textContent = device.effective_status || device.status || 'PENDING';
  } else {
    if (idInput) idInput.value = '';
    el('assign-device-id').textContent = 'New Workstation';
    el('assign-device-status').textContent = 'Direct Authorization';
  }
  el('assign-device-reason').value = 'Authorized customer workstation';
  el('assign-device-error').textContent = '';
  el('assign-device-error').style.display = 'none';
  el('assign-device-submit').disabled = false;
  el('assign-device-dialog').showModal();

  const select = el('assign-device-license-select');
  select.innerHTML = '<option value="">Loading active licenses…</option>';
  try {
    const data = await api('/licenses?status=ACTIVE&limit=100');
    select.innerHTML = '';
    const available = data.licenses.filter(l => l.authorized_devices < l.max_devices);
    if (!available.length) {
      select.innerHTML = '<option value="">No licenses with available capacity found</option>';
      el('assign-device-submit').disabled = true;
      return;
    }
    for (const l of available) {
      const opt = document.createElement('option');
      opt.value = l.license_id;
      opt.textContent = `${l.customer} (Seats: ${l.authorized_devices}/${l.max_devices} used | Expires: ${new Date(l.expires_at).toLocaleDateString()})`;
      select.append(opt);
    }
    el('assign-device-submit').disabled = false;
  } catch (err) {
    select.innerHTML = '<option value="">Failed to load licenses</option>';
    el('assign-device-error').textContent = err.message;
    el('assign-device-error').style.display = 'block';
    el('assign-device-submit').disabled = true;
  }
}

el('assign-device-cancel').onclick = () => el('assign-device-dialog').close();
el('assign-device-dialog').addEventListener('cancel', event => { if (el('assign-device-submit').disabled) event.preventDefault(); });

if (el('open-authorize-device')) {
  el('open-authorize-device').onclick = () => openAssignDeviceDialog(null);
}

el('assign-device-form').onsubmit = async event => {
  event.preventDefault();
  const idInput = el('assign-device-id-input');
  const targetDeviceId = (idInput ? idInput.value : (pendingAssignDevice?.device_id || '')).trim();
  if (!targetDeviceId) {
    el('assign-device-error').textContent = 'Please enter or paste a valid Computer Device ID.';
    el('assign-device-error').style.display = 'block';
    return;
  }
  const licenseId = el('assign-device-license-select').value;
  if (!licenseId) {
    el('assign-device-error').textContent = 'Please select a customer license.';
    el('assign-device-error').style.display = 'block';
    return;
  }
  const reason = el('assign-device-reason').value.trim() || 'Authorized customer workstation';
  el('assign-device-error').style.display = 'none';
  el('assign-device-submit').disabled = true;
  el('assign-device-cancel').disabled = true;
  try {
    const result = await api('/devices/authorize', {
      device_id: targetDeviceId,
      license_id: licenseId,
      reason
    });
    el('assign-device-dialog').close();
    el('result').textContent = result.message || 'Workstation authorized successfully.';
    await refresh();
  } catch (error) {
    el('assign-device-error').textContent = error.message;
    el('assign-device-error').style.display = 'block';
  } finally {
    el('assign-device-submit').disabled = false;
    el('assign-device-cancel').disabled = false;
  }
};

function openRegenerateKeyDialog(license) {
  pendingRegenerateKey = license;
  el('regenerate-key-license-id').textContent = license.license_id;
  el('regenerate-key-customer-name').textContent = license.customer || 'Unknown';
  el('regenerate-key-reason').value = '';
  el('regenerate-key-confirm').checked = false;
  el('regenerate-key-error').textContent = '';
  el('regenerate-key-error').style.display = 'none';
  el('regenerate-key-dialog').showModal();
  el('regenerate-key-reason').focus();
}

el('regenerate-key-cancel').onclick = () => el('regenerate-key-dialog').close();
el('regenerate-key-dialog').addEventListener('cancel', event => { if (el('regenerate-key-submit').disabled) event.preventDefault(); });

el('regenerate-key-form').onsubmit = async event => {
  event.preventDefault();
  if (!pendingRegenerateKey) return;
  const reason = el('regenerate-key-reason').value.trim();
  if (reason.length < 3) {
    el('regenerate-key-error').textContent = 'Please provide a reason (at least 3 characters).';
    el('regenerate-key-error').style.display = 'block';
    return;
  }
  if (!el('regenerate-key-confirm').checked) {
    el('regenerate-key-error').textContent = 'Please confirm replacement of the key.';
    el('regenerate-key-error').style.display = 'block';
    return;
  }
  el('regenerate-key-error').style.display = 'none';
  el('regenerate-key-submit').disabled = true;
  el('regenerate-key-cancel').disabled = true;
  try {
    const result = await api(`/licenses/${encodeURIComponent(pendingRegenerateKey.license_id)}/regenerate-key`, {
      confirm: true,
      confirmed_license_id: pendingRegenerateKey.license_id,
      reason
    });
    el('regenerate-key-dialog').close();
    el('generated-key-input').value = result.activation_key;
    el('issued-customer').textContent = result.customer;
    el('issued-license-id').textContent = result.license_id;
    el('issued-expires').textContent = stamp(result.expires_at);
    el('issued-devices').textContent = `${result.max_devices} workstation${result.max_devices > 1 ? 's' : ''}`;
    el('copy-btn-text').textContent = 'Copy Key';
    el('copy-feedback').textContent = '';
    el('success-key-dialog').showModal();
    el('result').textContent = result.message || 'New activation key generated successfully.';
    await refresh();
  } catch (error) {
    el('regenerate-key-error').textContent = error.message;
    el('regenerate-key-error').style.display = 'block';
  } finally {
    el('regenerate-key-submit').disabled = false;
    el('regenerate-key-cancel').disabled = false;
  }
};

el('refresh').onclick = () => {
  retryCount = 0;
  refresh();
};

let searchTimer;
for (const id of ['device-search', 'license-search']) {
  el(id).addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      if (id === 'device-search') offset = 0;
      else licenseOffset = 0;
      refresh();
    }, 300);
  });
}

for (const id of ['activity', 'device-status', 'license-status']) {
  el(id).onchange = () => {
    if (id === 'license-status') licenseOffset = 0;
    else offset = 0;
    refresh();
  };
}

el('previous').onclick = () => { offset = Math.max(0, offset - pageSize); refresh(); };
el('next').onclick = () => { offset += pageSize; refresh(); };
el('licenses-previous').onclick = () => { licenseOffset = Math.max(0, licenseOffset - pageSize); refresh(); };
el('licenses-next').onclick = () => { licenseOffset += pageSize; refresh(); };

el('logout').onclick = async () => {
  el('logout').disabled = true;
  try {
    await api('/logout', {});
    location.assign('/admin/sign-in');
  } catch (error) {
    el('error').textContent = error.message;
    el('logout').disabled = false;
  }
};

function closeNavigation() {
  el('main-navigation').classList.remove('open');
  el('nav-toggle').setAttribute('aria-expanded', 'false');
  el('nav-toggle').setAttribute('aria-label', 'Open navigation');
  const backdrop = el('nav-backdrop');
  if (backdrop) backdrop.classList.remove('open');
}
el('nav-toggle').onclick = () => {
  const open = el('main-navigation').classList.toggle('open');
  el('nav-toggle').setAttribute('aria-expanded', String(open));
  el('nav-toggle').setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  const backdrop = el('nav-backdrop');
  if (backdrop) backdrop.classList.toggle('open', open);
};
const navBackdrop = el('nav-backdrop');
if (navBackdrop) navBackdrop.onclick = closeNavigation;

el('main-navigation').addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    closeNavigation();
    el('nav-toggle').focus();
  }
});

function setActiveNav(hash) {
  document.querySelectorAll('.nav-link').forEach(a => {
    const isTarget = a.getAttribute('href') === hash;
    a.classList.toggle('active', isTarget);
    if (isTarget) a.setAttribute('aria-current', 'location');
    else a.removeAttribute('aria-current');
  });
  document.querySelectorAll('.mobile-tab-item').forEach(tab => {
    tab.classList.toggle('active', tab.getAttribute('href') === hash);
  });
}

for (const link of document.querySelectorAll('.nav-link')) {
  link.addEventListener('click', () => {
    setActiveNav(link.hash);
    closeNavigation();
    const target = document.querySelector(link.hash);
    if (target && !reducedMotion.matches) target.animate([{transform:'perspective(1400px) rotateX(.6deg)'}, {transform:'none'}], {duration:400, easing:'ease-out'});
  });
}

for (const tab of document.querySelectorAll('.mobile-tab-item')) {
  tab.addEventListener('click', () => {
    setActiveNav(tab.getAttribute('href'));
    const target = document.querySelector(tab.getAttribute('href'));
    if (target && !reducedMotion.matches) target.animate([{transform:'perspective(1400px) rotateX(.6deg)'}, {transform:'none'}], {duration:400, easing:'ease-out'});
  });
}

const footerSync = el('footer-sync-link');
if (footerSync) {
  footerSync.addEventListener('click', e => {
    e.preventDefault();
    refresh();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
}

const freshnessWatchdog = setInterval(() => {
  if (lastSync && Date.now() - lastSync.getTime() > 65000 && !document.hidden) {
    connection('pending', 'Sync outdated');
  }
}, 15000);

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  } else {
    if (document.querySelector('dialog[open]')) return;
    const now = Date.now();
    const elapsed = lastSync ? now - lastSync.getTime() : Infinity;
    if (elapsed >= POLL_INTERVAL) {
      refresh();
    } else {
      scheduleNextPoll(POLL_INTERVAL - elapsed);
    }
  }
});

window.addEventListener('pagehide', () => {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  clearTimeout(searchTimer);
  clearInterval(freshnessWatchdog);
  sceneObserver.disconnect();
  scene?.dispose();
  for (const c of counters.values()) cancelAnimationFrame(c.frame);
});

refresh();
