/* Mimmy 모바일 대시보드 — 순수 JS SPA */
(() => {
  'use strict';

  // ─── 공용 ───
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const root = $('#view-root');
  const toastEl = $('#toast');

  // 로컬스토리지에 저장한 user id. 설정 탭에서 입력.
  const getUserId = () => localStorage.getItem('mimmy_user_id') || '';
  const setUserId = (v) => localStorage.setItem('mimmy_user_id', v || '');

  const api = async (path, opts = {}) => {
    const headers = Object.assign(
      { 'Content-Type': 'application/json', 'X-Mimmy-User': getUserId() },
      opts.headers || {}
    );
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    if (!res.ok) {
      let msg = `${res.status}`;
      try { const j = await res.json(); msg = j.detail || j.reason || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  };

  const toast = (msg, kind = '') => {
    toastEl.className = 'toast ' + kind;
    toastEl.textContent = msg;
    toastEl.classList.remove('hidden');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.add('hidden'), 2400);
  };

  const fmtKRW = (n) => {
    if (n == null || Number.isNaN(+n)) return '—';
    const x = Math.round(+n);
    return x.toLocaleString('ko-KR') + '원';
  };
  const fmtPct = (n) => {
    if (n == null || Number.isNaN(+n)) return '—';
    const v = +n;
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  };
  const fmtSignedKRW = (n) => {
    if (n == null || Number.isNaN(+n)) return '—';
    const s = +n >= 0 ? '+' : '';
    return s + Math.round(+n).toLocaleString('ko-KR') + '원';
  };
  const fmtTime = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(+d)) return iso;
    return d.toLocaleString('ko-KR', { hour12: false });
  };
  const signCls = (n) => (n == null ? '' : (+n > 0 ? 'pos' : (+n < 0 ? 'neg' : '')));
  const h = (tag, attrs, children) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'on') for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
      else if (v != null) el.setAttribute(k, v);
    }
    for (const c of [].concat(children || [])) {
      if (c == null) continue;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return el;
  };

  // ─── 헤더 상태 업데이트 ───
  const updateHeader = (home) => {
    const dot = $('#status-dot');
    const bBroker = $('#badge-broker');
    const bRestart = $('#badge-restart');
    const bPaused = $('#badge-paused');
    if (!home) { dot.className = 'status-dot stale'; return; }
    dot.className = 'status-dot' + (home.paused ? ' paused' : '');
    bBroker.textContent = (home.broker || '').toUpperCase()
      + (home.broker === 'kis' ? ` / ${(home.kis_env || '').toUpperCase()}` : '');
    bRestart.classList.toggle('hidden', !home.needs_restart);
    bPaused.classList.toggle('hidden', !home.paused);
  };

  // ─── 스파크라인 SVG ───
  const sparkline = (series) => {
    const W = 320, H = 60, P = 2;
    if (!series || series.length < 2) {
      return h('div', { class: 'empty' }, '아직 변동 데이터가 없습니다');
    }
    const ys = series.map((s) => +s.equity);
    const min = Math.min(...ys), max = Math.max(...ys);
    const span = max - min || 1;
    const stepX = (W - 2 * P) / (series.length - 1);
    const pts = series
      .map((s, i) => `${(P + i * stepX).toFixed(1)},${(H - P - ((+s.equity - min) / span) * (H - 2 * P)).toFixed(1)}`)
      .join(' ');
    const up = ys[ys.length - 1] >= ys[0];
    const color = up ? '#34d399' : '#f87171';
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('class', 'spark');
    svg.setAttribute('preserveAspectRatio', 'none');
    const poly = document.createElementNS(svgNS, 'polyline');
    poly.setAttribute('fill', 'none');
    poly.setAttribute('stroke', color);
    poly.setAttribute('stroke-width', '2');
    poly.setAttribute('points', pts);
    svg.appendChild(poly);
    return svg;
  };

  // ─── 뷰: 홈 ───
  const viewHome = async () => {
    root.innerHTML = '';
    root.appendChild(h('div', { class: 'loading' }, [h('span', { class: 'spin' }), '불러오는 중…']));
    const home = await api('/api/home');
    updateHeader(home);
    root.innerHTML = '';

    const snap = home.snapshot || {};
    const equity = snap.equity;
    const daily = snap.daily_pnl;
    const base = equity && daily != null ? equity - daily : null;
    const dailyPct = base ? (daily / base) * 100 : null;

    // 요약 카드
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '오늘 평가금액'),
      h('div', { class: 'big-num', html: fmtKRW(equity) }),
      h('div', { class: 'sub-num ' + signCls(daily), html: `${fmtSignedKRW(daily)} (${fmtPct(dailyPct)})` }),
      sparkline(home.equity_series),
    ]));

    // 현금 / 미실현 / 실현
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '잔고'),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '현금'), h('span', { class: 'v' }, fmtKRW(snap.available_cash))]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '평가금액'), h('span', { class: 'v' }, fmtKRW(equity))]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '미실현 손익'), h('span', { class: 'v ' + signCls(snap.unrealized_pnl) }, fmtSignedKRW(snap.unrealized_pnl))]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '실현 손익'), h('span', { class: 'v ' + signCls(snap.realized_pnl) }, fmtSignedKRW(snap.realized_pnl))]),
    ]));

    // 트래킹 종목 + 상태
    const q = snap.last_quote || {};
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '추적 종목'),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '티커'), h('span', { class: 'v' }, home.ticker.key)]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '현재가'), h('span', { class: 'v' }, q.last != null ? fmtKRW(q.last) : '—')]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '매매 상태'), h('span', { class: 'v' }, (snap.trading_state || '—').toUpperCase())]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '마지막 업데이트'), h('span', { class: 'v' }, fmtTime(snap.created_at))]),
    ]));

    // 포지션
    const positions = snap.positions || [];
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, `포지션 (${positions.length})`),
      positions.length
        ? positions.map(posCard)
        : h('div', { class: 'empty' }, '보유 포지션 없음'),
    ]));

    // 비상 정지 / 재개 / 청산
    const paused = !!home.paused;
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '비상 액션'),
      paused
        ? h('button', { class: 'btn primary', on: { click: onResume } }, '▶ 매매 재개')
        : h('button', { class: 'btn warn', on: { click: onPause } }, '⏸ 매매 일시정지'),
      h('div', { style: 'height:8px' }),
      h('button', { class: 'btn danger', on: { click: onFlatten } }, '⚠ 전량 청산 (시장가)'),
    ]));
  };

  const posCard = (p) => {
    const kind = p.instrument?.kind || '';
    const sym = p.instrument?.symbol || '';
    const qty = p.quantity || 0;
    const avg = p.avg_price || 0;
    return h('div', { class: 'pos-item' }, [
      h('div', { class: 'kv' }, [
        h('span', { class: 'k' }, `${sym} (${kind})`),
        h('span', { class: 'v' }, `${qty}주`),
      ]),
      h('div', { class: 'kv' }, [
        h('span', { class: 'k' }, '평균단가'),
        h('span', { class: 'v' }, fmtKRW(avg)),
      ]),
      h('div', { class: 'kv' }, [
        h('span', { class: 'k' }, '실현손익'),
        h('span', { class: 'v ' + signCls(p.realized_pnl) }, fmtSignedKRW(p.realized_pnl)),
      ]),
    ]);
  };

  const onPause = async () => {
    try { await api('/api/pause', { method: 'POST' }); toast('일시정지됨', 'ok'); viewHome(); }
    catch (e) { toast('실패: ' + e.message, 'err'); }
  };
  const onResume = async () => {
    try { await api('/api/resume', { method: 'POST' }); toast('재개됨', 'ok'); viewHome(); }
    catch (e) { toast('실패: ' + e.message, 'err'); }
  };
  const onFlatten = async () => {
    if (!confirm('정말 전량 청산하시겠습니까? (시장가)')) return;
    const token = prompt("확인 문구 'FLATTEN' 을 입력하세요");
    if (token !== 'FLATTEN') { toast('취소됨'); return; }
    try {
      await api('/api/flatten', { method: 'POST', body: JSON.stringify({ confirm: 'FLATTEN' }) });
      toast('청산 요청 접수 — 다음 사이클 반영', 'ok');
    } catch (e) { toast('실패: ' + e.message, 'err'); }
  };

  // ─── 뷰: 시세 ───
  const viewMarket = async () => {
    root.innerHTML = '';
    root.appendChild(h('div', { class: 'loading' }, [h('span', { class: 'spin' }), '불러오는 중…']));
    const m = await api('/api/market');
    root.innerHTML = '';

    const q = m.quote || {};
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '현재가'),
      h('div', { class: 'big-num' }, q.last != null ? fmtKRW(q.last) : '—'),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '매수호가'), h('span', { class: 'v' }, q.bid != null ? fmtKRW(q.bid) : '—')]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '매도호가'), h('span', { class: 'v' }, q.ask != null ? fmtKRW(q.ask) : '—')]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '거래량'), h('span', { class: 'v' }, q.volume != null ? (+q.volume).toLocaleString() : '—')]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, '기준시각'), h('span', { class: 'v' }, fmtTime(q.as_of))]),
    ]));

    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, `뉴스 (${(m.news || []).length})`),
      (m.news || []).length
        ? m.news.map((n) => h('div', { class: 'news-item' }, [
            h('a', { href: n.url || '#', target: '_blank', rel: 'noopener' }, n.headline || '(제목 없음)'),
            h('div', { class: 'meta' }, `${n.source || ''}  ·  ${fmtTime(n.published_at)}`),
          ]))
        : h('div', { class: 'empty' }, '수집된 뉴스 없음'),
    ]));

    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, `공시 (${(m.disclosures || []).length})`),
      (m.disclosures || []).length
        ? m.disclosures.map((d) => h('div', { class: 'disc-item' }, [
            h('a', { href: d.url || '#', target: '_blank', rel: 'noopener' }, d.title || '(제목 없음)'),
            h('div', { class: 'meta' }, `${d.category || ''}  ·  ${fmtTime(d.filed_at)}`),
          ]))
        : h('div', { class: 'empty' }, '수집된 공시 없음'),
    ]));
  };

  // ─── 뷰: Agents ───
  const viewAgents = async () => {
    root.innerHTML = '';
    root.appendChild(h('div', { class: 'loading' }, [h('span', { class: 'spin' }), '불러오는 중…']));
    const a = await api('/api/agents');
    root.innerHTML = '';

    const by = a.agents || {};
    const order = ['news', 'disclosure', 'market', 'trader', 'risk'];
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '에이전트 의견 (최근 사이클)'),
      order.filter((k) => by[k]).map((k) => {
        const o = by[k];
        const p = o.payload || {};
        let right = '';
        let rightCls = '';
        if (o.kind === 'signal') {
          right = `${p.score >= 0 ? '+' : ''}${(+p.score || 0).toFixed(2)} · conf ${(+p.confidence || 0).toFixed(2)}`;
          rightCls = signCls(p.score);
        } else if (o.kind === 'decision') {
          right = `${(p.action || '').toUpperCase()} × ${p.quantity || 0}`;
          rightCls = p.action === 'buy' ? 'pos' : (p.action === 'sell' ? 'neg' : '');
        } else if (o.kind === 'risk_gate') {
          right = p.approved ? 'PASS' : 'BLOCK';
          rightCls = p.approved ? 'pos' : 'neg';
        }
        return h('div', { class: 'agent-item' }, [
          h('div', { class: 'head' }, [
            h('span', { class: 'name' }, k),
            h('span', { class: 'score ' + rightCls }, right),
          ]),
          h('div', { class: 'rat' }, o.summary || '—'),
        ]);
      }),
      Object.keys(by).length ? null : h('div', { class: 'empty' }, '아직 사이클이 돌지 않았습니다'),
    ]));

    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, `최근 결정 (${(a.recent_decisions || []).length})`),
      (a.recent_decisions || []).length
        ? a.recent_decisions.map((d) => h('div', { class: 'dec-item' }, [
            h('div', { class: 'kv' }, [
              h('span', { class: 'k' }, `${(d.action || '').toUpperCase()} × ${d.quantity || 0}`),
              h('span', { class: 'v' }, d.entry_price != null ? fmtKRW(d.entry_price) : '—'),
            ]),
            h('div', { class: 'kv' }, [
              h('span', { class: 'k' }, fmtTime(d.created_at)),
              h('span', { class: 'v ' + signCls(d.eval_score) }, d.eval_score != null ? `score ${(+d.eval_score).toFixed(2)}` : '평가전'),
            ]),
          ]))
        : h('div', { class: 'empty' }, '체결된 결정 없음'),
    ]));

    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, `누적 교훈 (${(a.lessons || []).length})`),
      (a.lessons || []).length
        ? a.lessons.slice().reverse().map((t) => h('div', { class: 'lesson-item' }, t))
        : h('div', { class: 'empty' }, '아직 교훈이 없습니다'),
    ]));

    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, `Audit (${(a.audit || []).length})`),
      (a.audit || []).length
        ? a.audit.map((e) => h('div', { class: 'audit-item' }, [
            h('div', { class: 'kv' }, [
              h('span', { class: 'k' }, `${e.actor} · ${e.kind}`),
              h('span', { class: 'v' }, fmtTime(e.created_at)),
            ]),
            h('div', { class: 'meta', style: 'font-size:12px;color:var(--text-dim);word-break:break-all' }, JSON.stringify(e.payload)),
          ]))
        : h('div', { class: 'empty' }, '이벤트 없음'),
    ]));
  };

  // ─── 뷰: 챗 ───
  const CHAT_KEY = 'mimmy_chat';
  const loadChat = () => { try { return JSON.parse(localStorage.getItem(CHAT_KEY) || '[]'); } catch { return []; } };
  const saveChat = (arr) => localStorage.setItem(CHAT_KEY, JSON.stringify(arr.slice(-40)));

  const viewChat = () => {
    root.innerHTML = '';
    const logEl = h('div', { class: 'chat-log' }, []);
    const card = h('div', { class: 'card' }, [
      h('h3', {}, '앱 수정 요청 (자연어 → PR)'),
      logEl,
    ]);
    const inputArea = h('div', { class: 'card' }, [
      h('label', { class: 'field' }, [
        h('span', {}, '요청'),
        h('textarea', { id: 'chat-input', placeholder: '예) 대시보드 홈에 보유 비중 파이차트 추가해줘' }),
      ]),
      h('button', { class: 'btn primary', id: 'chat-send' }, '전송'),
    ]);
    root.appendChild(card);
    root.appendChild(inputArea);

    const render = () => {
      logEl.innerHTML = '';
      for (const m of loadChat()) {
        const msg = h('div', { class: 'chat-msg ' + m.role }, []);
        if (m.pr) {
          msg.appendChild(document.createTextNode(m.text + '\n'));
          msg.appendChild(h('a', { href: m.pr, target: '_blank', rel: 'noopener' }, '▸ PR 열기'));
        } else {
          msg.textContent = m.text;
        }
        logEl.appendChild(msg);
      }
      logEl.scrollTop = logEl.scrollHeight;
    };
    render();

    $('#chat-send').addEventListener('click', async () => {
      const ta = $('#chat-input');
      const text = (ta.value || '').trim();
      if (!text) return;
      const uid = getUserId();
      if (!uid) { toast('설정에서 Telegram user id 를 먼저 입력하세요', 'err'); return; }
      const log = loadChat();
      log.push({ role: 'me', text });
      saveChat(log); render();
      ta.value = '';
      const pending = { role: 'bot', text: '처리 중…' };
      log.push(pending); saveChat(log); render();
      try {
        const r = await api('/chat', {
          method: 'POST',
          body: JSON.stringify({ text, user_id: uid }),
        });
        log.pop();
        log.push({ role: 'bot', text: r.reply, pr: r.artifact_url || null });
        saveChat(log); render();
      } catch (e) {
        log.pop();
        log.push({ role: 'bot', text: '실패: ' + e.message });
        saveChat(log); render();
      }
    });
  };

  // ─── 뷰: 설정 ───
  const viewSettings = async () => {
    root.innerHTML = '';
    root.appendChild(h('div', { class: 'loading' }, [h('span', { class: 'spin' }), '불러오는 중…']));
    const s = await api('/api/settings');
    root.innerHTML = '';
    const env = s.env, rt = s.runtime || {};

    // 사용자 ID (로컬)
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '사용자'),
      h('label', { class: 'field' }, [
        h('span', {}, 'Telegram user id (권한 확인용)'),
        h('input', { class: 'input', id: 'uid', value: getUserId(), inputmode: 'numeric' }),
      ]),
      h('button', { class: 'btn', on: { click: () => { setUserId($('#uid').value.trim()); toast('저장됨', 'ok'); } } }, '저장'),
    ]));

    // 매매 모드: broker + kis_env
    const curBroker = rt.broker || env.broker;
    const curKisEnv = rt.kis_env || env.kis_env;
    // KIS 키셋 활성 상태 — 어떤 키가 채워져있는지 한눈에.
    const paperOk = env.kis_paper_keys_filled;
    const liveOk = env.kis_live_keys_filled;
    const activeOk = env.kis_active_keys_filled;
    const kisHint = h('div', { class: 'empty', style: 'text-align:left;padding:8px 0 0 0' },
      `KIS 키 상태 — paper: ${paperOk ? '✅' : '❌'}  ·  live: ${liveOk ? '✅' : '❌'}  ` +
      `(현재 활성: ${activeOk ? '✅' : '❌ .env 누락'})`);
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '매매 모드'),
      h('label', { class: 'field' }, [
        h('span', {}, '브로커'),
        h('select', { class: 'select', id: 'broker' }, [
          h('option', { value: 'paper', ...(curBroker === 'paper' ? { selected: '' } : {}) }, 'paper (가상)'),
          h('option', { value: 'kis', ...(curBroker === 'kis' ? { selected: '' } : {}) }, 'KIS (한국투자증권)'),
        ]),
      ]),
      h('label', { class: 'field' }, [
        h('span', {}, 'KIS 환경'),
        h('select', { class: 'select', id: 'kis_env' }, [
          h('option', { value: 'paper', ...(curKisEnv === 'paper' ? { selected: '' } : {}) }, '모의투자 (VTS)'),
          h('option', { value: 'live', ...(curKisEnv === 'live' ? { selected: '' } : {}) }, '실계좌 ⚠'),
        ]),
      ]),
      h('button', { class: 'btn primary', on: { click: saveMode } }, '저장'),
      kisHint,
      h('div', { class: 'empty', style: 'text-align:left;padding:4px 0 0 0' },
        '※ 브로커/환경 변경은 재기동 필요. 아래 “재기동” 버튼으로 적용.'),
    ]));

    // LLM provider + model
    const curProvider = rt.ai_provider || env.ai_provider || 'anthropic';
    const curModel = (rt.ai_model != null ? rt.ai_model : env.ai_model) || '';
    const keys = env.ai_keys_filled || {};
    const llmHint = h('div', { class: 'empty', style: 'text-align:left;padding:8px 0 0 0' },
      `API 키 상태 — anthropic: ${keys.anthropic ? '✅' : '❌'}  ·  ` +
      `openai: ${keys.openai ? '✅' : '❌'}  ·  gemini: ${keys.gemini ? '✅' : '❌'}`);
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, 'LLM (AI Provider)'),
      h('label', { class: 'field' }, [
        h('span', {}, 'Provider'),
        h('select', { class: 'select', id: 'ai_provider' }, [
          ['anthropic', 'Anthropic (Claude)'],
          ['openai', 'OpenAI (GPT)'],
          ['gemini', 'Google (Gemini)'],
        ].map(([v, t]) => h('option', { value: v, ...(curProvider === v ? { selected: '' } : {}) }, t))),
      ]),
      h('label', { class: 'field' }, [
        h('span', {}, '모델 (비우면 provider 기본값)'),
        h('input', {
          class: 'input', id: 'ai_model', value: curModel,
          placeholder: 'claude-opus-4-7 / gpt-4o / gemini-1.5-pro',
        }),
      ]),
      h('button', { class: 'btn primary', on: { click: saveLLM } }, '저장'),
      llmHint,
      h('div', { class: 'empty', style: 'text-align:left;padding:4px 0 0 0' },
        '※ provider/모델 변경은 재기동 필요.'),
    ]));

    // 종목
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '추적 종목'),
      h('label', { class: 'field' }, [
        h('span', {}, '시장'),
        h('select', { class: 'select', id: 'market' }, [
          ['KR', 'KR (한국)'], ['US', 'US'], ['HK', 'HK'], ['CN', 'CN']
        ].map(([v, t]) => h('option', { value: v, ...((rt.ticker_market || env.market) === v ? { selected: '' } : {}) }, t))),
      ]),
      h('label', { class: 'field' }, [
        h('span', {}, '심볼'),
        h('input', { class: 'input', id: 'symbol', value: rt.ticker_symbol || env.ticker }),
      ]),
      h('button', { class: 'btn primary', on: { click: saveTicker } }, '저장'),
    ]));

    // 루프 설정
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '루프'),
      h('label', { class: 'field' }, [
        h('span', {}, 'cycle_seconds (60~3600)'),
        h('input', { class: 'input', id: 'cycle', value: rt.cycle_seconds || env.cycle_hint_s || 60, inputmode: 'numeric' }),
      ]),
      h('label', { class: 'field' }, [
        h('span', {}, 'eval_horizon_minutes'),
        h('input', { class: 'input', id: 'horizon', value: rt.eval_horizon_minutes || env.eval_horizon_minutes || 30, inputmode: 'numeric' }),
      ]),
      h('button', { class: 'btn primary', on: { click: saveLoop } }, '저장'),
    ]));

    // 재기동
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '재기동'),
      h('div', { class: 'kv' }, [
        h('span', { class: 'k' }, '재기동 필요'),
        h('span', { class: 'v ' + (rt.needs_restart ? 'neg' : 'pos') }, rt.needs_restart ? 'YES' : 'no'),
      ]),
      h('button', { class: 'btn warn', on: { click: onRestart } }, '↻ 서비스 재기동'),
    ]));

    // 모델/환경 정보
    root.appendChild(h('div', { class: 'card' }, [
      h('h3', {}, '환경'),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, 'provider'), h('span', { class: 'v' }, env.ai_provider)]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, 'model'), h('span', { class: 'v' }, env.ai_model)]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, 'market'), h('span', { class: 'v' }, env.market)]),
      h('div', { class: 'kv' }, [h('span', { class: 'k' }, 'ticker'), h('span', { class: 'v' }, env.ticker)]),
    ]));
  };

  const savePatch = async (patch, label) => {
    try {
      await api('/api/settings', { method: 'PATCH', body: JSON.stringify(patch) });
      toast((label || '설정') + ' 저장됨', 'ok');
      viewSettings();
    } catch (e) { toast('실패: ' + e.message, 'err'); }
  };
  const saveMode = () => savePatch({ broker: $('#broker').value, kis_env: $('#kis_env').value }, '매매 모드');
  const saveLLM = () => savePatch(
    { ai_provider: $('#ai_provider').value, ai_model: $('#ai_model').value.trim() },
    'LLM 설정',
  );
  const saveTicker = () => savePatch({ ticker_market: $('#market').value, ticker_symbol: $('#symbol').value.trim() }, '종목');
  const saveLoop = () => {
    const c = parseInt($('#cycle').value, 10);
    const h_ = parseInt($('#horizon').value, 10);
    if (Number.isNaN(c) || Number.isNaN(h_)) { toast('숫자로 입력', 'err'); return; }
    savePatch({ cycle_seconds: c, eval_horizon_minutes: h_ }, '루프');
  };
  const onRestart = async () => {
    if (!confirm('서비스를 재기동합니다. 계속하시겠습니까?')) return;
    const token = prompt("확인 문구 'RESTART' 를 입력하세요");
    if (token !== 'RESTART') { toast('취소됨'); return; }
    try {
      const r = await api('/api/restart', { method: 'POST', body: JSON.stringify({ confirm: 'RESTART' }) });
      if (r.status === 'ok') toast('재기동 OK', 'ok');
      else toast(r.status + ': ' + (r.reason || ''), 'err');
    } catch (e) { toast('실패: ' + e.message, 'err'); }
  };

  // ─── 탭 라우팅 ───
  const VIEWS = { home: viewHome, market: viewMarket, agents: viewAgents, chat: viewChat, settings: viewSettings };
  let currentTab = 'home';
  let refreshTimer = null;

  const go = (tab) => {
    currentTab = tab;
    $$('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
    (VIEWS[tab] || viewHome)().catch((e) => {
      root.innerHTML = '';
      root.appendChild(h('div', { class: 'card' }, [
        h('h3', {}, '에러'),
        h('div', { class: 'empty' }, e.message || String(e)),
      ]));
    });
    clearInterval(refreshTimer);
    // 홈/시세만 주기적 새로고침
    if (tab === 'home' || tab === 'market') {
      refreshTimer = setInterval(() => {
        if (document.hidden) return;
        (VIEWS[tab] || viewHome)().catch(() => {});
      }, 10_000);
    }
  };

  $$('.tab').forEach((b) => b.addEventListener('click', () => go(b.dataset.tab)));
  go('home');

  // 가시성 복귀 시 1회 리프레시
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) go(currentTab);
  });
})();
