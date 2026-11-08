const $ = id => document.getElementById(id);
let active = null, profiles = [], generation = 0, frameURL, busy = false, timer;
function notify(message) { $('status').textContent = message; $('status').hidden = false; clearTimeout(timer); timer = setTimeout(() => $('status').hidden = true, 7000); }
function reset() { generation++; active = null; if (frameURL) URL.revokeObjectURL(frameURL); frameURL = null; $('screen').removeAttribute('src'); $('typing').value = ''; }
function loginView() { reset(); $('loginPanel').hidden = false; $('dashboard').hidden = true; $('viewer').hidden = true; $('logout').hidden = true; }
async function request(path, body, image = false) {
  const response = await fetch('/api/' + path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Nawafidh': '1'}, body: JSON.stringify(body)});
  if (response.status === 401 && path !== 'login') loginView();
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error || 'تعذر الاتصال. أعد المحاولة.'); }
  return image ? response.blob() : response.json();
}
async function refresh() {
  const data = await request('profiles'); profiles = data.profiles;
  $('limit').textContent = `يمكن تشغيل ${data.limit} جلسات في الوقت نفسه. الجلسات المغلقة تحتفظ بتسجيل الدخول.`;
  const list = $('profiles'); list.replaceChildren();
  if (!profiles.length) { const empty = document.createElement('p'); empty.textContent = 'لا توجد ملفات بعد. أضف ملفك الأول بالأعلى.'; list.append(empty); }
  for (const profile of profiles) {
    const card = document.createElement('div'); card.className = 'profile';
    const info = document.createElement('div'), name = document.createElement('strong'), state = document.createElement('small');
    name.textContent = profile.name; state.textContent = profile.running ? '● الجلسة تعمل' : 'جلسة مستقلة'; info.append(name, state);
    const buttons = document.createElement('div'); buttons.className = 'row';
    const open = document.createElement('button'); open.textContent = profile.running ? 'عرض المتصفح' : 'فتح المتصفح';
    open.onclick = () => showBrowser(profile, open); buttons.append(open);
    if (profile.running) { const close = document.createElement('button'); close.className = 'danger'; close.textContent = 'إغلاق'; close.onclick = async () => { close.disabled = true; try { await request('action', {id: profile.id, action: 'close'}); await refresh(); } catch(e) { notify(e.message); close.disabled = false; } }; buttons.append(close); }
    card.append(info, buttons); list.append(card);
  }
}
async function dashboard() { reset(); $('viewer').hidden = true; $('loginPanel').hidden = true; $('dashboard').hidden = false; $('logout').hidden = false; try { await refresh(); } catch (e) { notify(e.message); } }
async function showBrowser(profile, button) {
  if (busy) return; busy = true; button.disabled = true; button.textContent = 'جارٍ فتح المتصفح…';
  try {
    await request('action', {id: profile.id, action: 'open'});
    reset(); active = profile.id; $('remoteName').textContent = profile.name;
    $('dashboard').hidden = true; $('viewer').hidden = false; $('connection').textContent = 'جارٍ تحميل الصورة…';
    window.scrollTo(0, 0); frames(generation);
  } catch (e) { notify(e.message); await refresh().catch(() => {}); }
  finally { busy = false; button.disabled = false; }
}
async function frames(ticket) {
  let failures = 0;
  while (active && ticket === generation) {
    if (!document.hidden) {
      try {
        const blob = await request('frame/' + active, undefined, true);
        if (ticket !== generation) return;
        const next = URL.createObjectURL(blob); $('screen').src = next;
        if (frameURL) URL.revokeObjectURL(frameURL); frameURL = next;
        $('connection').textContent = '● متصل — تحديث تلقائي'; failures = 0;
      } catch(e) { if (ticket !== generation) return; $('connection').textContent = e.message; if (++failures >= 5) { notify('توقف العرض. ارجع إلى الملفات وافتح الجلسة مجددًا.'); return; } }
    }
    await new Promise(resolve => setTimeout(resolve, 850));
  }
}
let actionQueue = Promise.resolve();
function control(action, extra = {}) {
  const id = active;
  actionQueue = actionQueue.then(async () => { if (!id || id !== active) return; await request('action', {id, action, ...extra}); }).catch(e => notify(e.message));
  return actionQueue;
}
$('loginForm').onsubmit = async e => { e.preventDefault(); const button = e.target.querySelector('button'); button.disabled = true; try { await request('login', {password: $('password').value}); $('password').value = ''; await dashboard(); } catch(e) { notify(e.message); } finally { button.disabled = false; } };
$('addForm').onsubmit = async e => { e.preventDefault(); const button = e.target.querySelector('button'); button.disabled = true; try { await request('add', {name: $('name').value}); $('name').value = ''; await refresh(); } catch(e) { notify(e.message); } finally { button.disabled = false; } };
$('logout').onclick = async () => { try { await request('logout', {}); loginView(); } catch(e) { notify(e.message); } };
$('dashboardBack').onclick = dashboard;
$('keyboard').onsubmit = async e => { e.preventDefault(); const text = $('typing').value; if (!text) return; $('typing').value = ''; await control('text', {text}); };
$('showText').onclick = () => { const hide = $('typing').type === 'text'; $('typing').type = hide ? 'password' : 'text'; $('showText').textContent = hide ? 'إظهار النص' : 'إخفاء النص'; };
document.querySelectorAll('[data-key]').forEach(button => button.onclick = () => control('key', {key: button.dataset.key}));
$('up').onclick = () => control('scroll', {dy: -450}); $('down').onclick = () => control('scroll', {dy: 450});
$('reload').onclick = () => control('reload'); $('back').onclick = () => control('back');
$('close').onclick = async () => { await control('close'); await dashboard(); };
let pointer;
$('screen').onpointerdown = e => { pointer = {x: e.clientX, y: e.clientY}; $('screen').setPointerCapture(e.pointerId); };
$('screen').onpointercancel = () => { pointer = null; };
$('screen').onpointerup = e => {
  if (!pointer || !$('screen').getAttribute('src')) return;
  const rect = $('screen').getBoundingClientRect(), dy = pointer.y - e.clientY, dx = pointer.x - e.clientX; pointer = null;
  if (Math.abs(dy) > 18) control('scroll', {dy: Math.round(dy * 700 / rect.height)});
  else if (Math.abs(dx) < 18) control('tap', {x: Math.max(0, Math.min(389, Math.floor((e.clientX - rect.left) * 390 / rect.width))), y: Math.max(0, Math.min(699, Math.floor((e.clientY - rect.top) * 700 / rect.height)))});
};
request('profiles').then(dashboard).catch(() => loginView());
