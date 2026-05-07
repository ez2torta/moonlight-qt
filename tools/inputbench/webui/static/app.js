(() => {
  const page = document.body.dataset.page;
  const state = { pin: localStorage.getItem('inputbench.pin') || '' };

  function authHeaders() {
    const h = { 'Content-Type': 'application/json' };
    if (state.pin) h['X-Auth'] = state.pin;
    return h;
  }

  async function api(path, method = 'GET', body = null) {
    const resp = await fetch(path, { method, headers: authHeaders(), body: body ? JSON.stringify(body) : null });
    if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
    return await resp.json();
  }

  function wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const q = state.pin ? `?auth=${encodeURIComponent(state.pin)}` : '';
    return `${proto}://${location.host}/ws${q}`;
  }

  if (page === 'index') {
    const pinInput = document.getElementById('pin-input');
    const saveBtn = document.getElementById('save-pin');
    pinInput.value = state.pin;
    saveBtn.addEventListener('click', () => {
      state.pin = pinInput.value.trim();
      localStorage.setItem('inputbench.pin', state.pin);
      alert('PIN guardado localmente');
    });
    return;
  }

  if (page === 'live') initLive();
  if (page === 'sweep') initSweep();

  function initLive() {
    const conn = document.getElementById('conn-status');
    const pingEl = document.getElementById('ping-ms');
    const heldEls = [document.getElementById('held-0'), document.getElementById('held-1')];
    const heldButtons = [new Set(), new Set()];
    const pointers = [new Map(), new Map()];

    const expandDirection = (name) => {
      switch (name) {
        case 'UP_LEFT': return ['UP', 'LEFT'];
        case 'UP_RIGHT': return ['UP', 'RIGHT'];
        case 'DOWN_LEFT': return ['DOWN', 'LEFT'];
        case 'DOWN_RIGHT': return ['DOWN', 'RIGHT'];
        default: return [name];
      }
    };

    const syncPad = async (pad) => {
      const b = [...heldButtons[pad]].sort();
      heldEls[pad].textContent = `Held: ${b.join(' ') || '-'}`;
      try { await api('/api/hold', 'POST', { pad, b }); } catch (e) { console.error(e); }
    };

    const press = async (pad, pointerId, logicalButton, element) => {
      pointers[pad].set(pointerId, logicalButton);
      for (const b of expandDirection(logicalButton)) heldButtons[pad].add(b);
      element.classList.add('active');
      await syncPad(pad);
    };

    const release = async (pad, pointerId, element) => {
      pointers[pad].delete(pointerId);
      const still = new Set();
      for (const lb of pointers[pad].values()) for (const b of expandDirection(lb)) still.add(b);
      heldButtons[pad] = still;
      element.classList.remove('active');
      await syncPad(pad);
    };

    document.querySelectorAll('.touch[data-pad][data-button]').forEach((el) => {
      el.addEventListener('pointerdown', async (ev) => {
        ev.preventDefault();
        await press(Number(el.dataset.pad), ev.pointerId, el.dataset.button, el);
      });
      const endHandler = async (ev) => {
        ev.preventDefault();
        await release(Number(el.dataset.pad), ev.pointerId, el);
      };
      el.addEventListener('pointerup', endHandler);
      el.addEventListener('pointercancel', endHandler);
      el.addEventListener('pointerleave', endHandler);
      el.addEventListener('contextmenu', (ev) => ev.preventDefault());
    });

    document.getElementById('panic-stop').addEventListener('click', async () => {
      heldButtons[0].clear(); heldButtons[1].clear(); pointers[0].clear(); pointers[1].clear();
      document.querySelectorAll('.touch.active').forEach((el) => el.classList.remove('active'));
      await api('/api/stop', 'POST', {});
      await syncPad(0); await syncPad(1);
    });

    document.getElementById('release-all').addEventListener('click', async () => {
      heldButtons[0].clear(); heldButtons[1].clear(); pointers[0].clear(); pointers[1].clear();
      document.querySelectorAll('.touch.active').forEach((el) => el.classList.remove('active'));
      await syncPad(0); await syncPad(1);
    });

    async function pollPing() {
      const t0 = performance.now();
      try {
        const r = await api('/api/ping');
        pingEl.textContent = String(Math.round(performance.now() - t0));
        conn.textContent = r.op || 'ok'; conn.classList.add('good'); conn.classList.remove('bad');
      } catch {
        conn.textContent = 'offline'; conn.classList.add('bad'); conn.classList.remove('good');
      }
    }

    pollPing(); setInterval(pollPing, 2000);
  }

  function rangeBox(prefix) {
    return `<label>${prefix} min <input data-k="${prefix}.min" type="number" value="0" /></label>
      <label>${prefix} max <input data-k="${prefix}.max" type="number" value="10" /></label>
      <label>${prefix} step <input data-k="${prefix}.step" type="number" value="1" /></label>`;
  }

  function initSweep() {
    const p1El = document.getElementById('p1-template');
    const p2El = document.getElementById('p2-template');
    const statusEl = document.getElementById('sweep-status');
    const connEl = document.getElementById('sweep-conn');
    const judgeBox = document.getElementById('judge-box');
    const judgeLabel = document.getElementById('judge-label');
    const resultsBody = document.querySelector('#results-table tbody');

    const tplHtml = `<label>Directions(csv) <input data-k="directions" value="FORWARD,UP_RIGHT,UP,UP_LEFT,LEFT,DOWN_LEFT,DOWN,DOWN_RIGHT" /></label>
      <label>Actions(csv) <input data-k="actions" value="none,jump_forward,jump_neutral,jump_back,walk_forward,walk_back" /></label>
      <label>Buttons(csv) <input data-k="buttons" value="A,B,X,Y,RB" /></label>${rangeBox('walk_frames')}${rangeBox('pre_button_frames')}${rangeBox('button_timing')}${rangeBox('press_frames')}`;
    p1El.innerHTML = tplHtml;
    p2El.innerHTML = tplHtml;

    function parseTemplate(el) {
      const v = {};
      el.querySelectorAll('input[data-k]').forEach((i) => { v[i.dataset.k] = i.value; });
      const r = (name) => ({ min: Number(v[`${name}.min`] || 0), max: Number(v[`${name}.max`] || 0), step: Number(v[`${name}.step`] || 1) });
      return {
        directions: (v.directions || '').split(',').map((x) => x.trim()).filter(Boolean),
        actions: (v.actions || '').split(',').map((x) => x.trim()).filter(Boolean),
        buttons: (v.buttons || '').split(',').map((x) => x.trim()).filter(Boolean),
        walk_frames: r('walk_frames'), pre_button_frames: r('pre_button_frames'), button_timing: r('button_timing'), press_frames: r('press_frames'),
      };
    }

    function rules() {
      return {
        fps: Number(document.getElementById('cfg-fps').value || 120),
        repeats: Number(document.getElementById('cfg-repeats').value || 1),
        settle_frames: Number(document.getElementById('cfg-settle').value || 10),
        pause_between_attempts_frames: Number(document.getElementById('cfg-pause').value || 15),
        save_generated_sequences: true,
        winner_mode: document.getElementById('cfg-winner-mode').value,
      };
    }

    async function refreshStatus() {
      try {
        const st = await api('/api/sweep/status');
        statusEl.textContent = JSON.stringify(st, null, 2);
        connEl.textContent = 'online'; connEl.classList.add('good'); connEl.classList.remove('bad');
        const pending = st.pending_judgement;
        if (pending) { judgeBox.classList.remove('hidden'); judgeLabel.textContent = `Pendiente #${pending.index}`; }
        else judgeBox.classList.add('hidden');
      } catch {
        connEl.textContent = 'offline'; connEl.classList.add('bad'); connEl.classList.remove('good');
      }
    }

    async function refreshResults() {
      const r = await api('/api/sweep/results');
      resultsBody.innerHTML = '';
      for (const row of r.rows || []) {
        const tr = document.createElement('tr');
        const td = (text) => { const cell = document.createElement('td'); cell.textContent = text ?? ''; return cell; };
        tr.appendChild(td(String(row.index))); tr.appendChild(td(row.winner));
        tr.appendChild(td(JSON.stringify(row.params?.p1 || {}))); tr.appendChild(td(JSON.stringify(row.params?.p2 || {})));
        tr.appendChild(td(row.input_json_path || '')); tr.appendChild(td(row.video_path || ''));
        resultsBody.appendChild(tr);
      }
    }

    document.getElementById('reset-training').addEventListener('click', async () => { await api('/api/reset-training', 'POST', {}); });
    document.getElementById('sweep-start').addEventListener('click', async () => { await api('/api/sweep/start', 'POST', { p1: parseTemplate(p1El), p2: parseTemplate(p2El), rules: rules() }); refreshStatus(); });
    document.getElementById('sweep-stop').addEventListener('click', async () => { await api('/api/sweep/stop', 'POST', {}); refreshStatus(); });
    document.getElementById('sweep-pause').addEventListener('click', async () => { await api('/api/sweep/pause', 'POST', {}); refreshStatus(); });
    document.getElementById('sweep-resume').addEventListener('click', async () => { await api('/api/sweep/resume', 'POST', {}); refreshStatus(); });
    document.getElementById('sweep-skip').addEventListener('click', async () => { await api('/api/sweep/skip', 'POST', {}); refreshStatus(); });
    document.getElementById('refresh-results').addEventListener('click', refreshResults);

    document.querySelectorAll('[data-judge]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        await api('/api/sweep/judge', 'POST', { winner: btn.dataset.judge, note: '' });
        await refreshStatus(); await refreshResults();
      });
    });

    try {
      const ws = new WebSocket(wsUrl());
      ws.onmessage = async (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type && (msg.type.startsWith('sweep_') || msg.type === 'ws_connected')) {
          await refreshStatus();
          if (msg.type === 'sweep_attempt_done' || msg.type === 'sweep_finished') {
            await refreshResults();
            if (msg.type === 'sweep_finished') {
              if (window.Notification && Notification.permission === 'granted') new Notification('Sweep terminado', { body: 'Se completaron las combinaciones.' });
            }
          }
        }
      };
    } catch (e) { console.error(e); }

    if (window.Notification && Notification.permission === 'default') Notification.requestPermission().catch(() => {});
    refreshStatus(); setInterval(refreshStatus, 2500);
  }
})();
