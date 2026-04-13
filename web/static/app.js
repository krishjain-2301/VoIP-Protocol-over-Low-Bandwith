/* ═══════════════════════════════════════════════════════════════
   Emergency VoIP Dashboard — Client Logic + Simulation Engine
   ═══════════════════════════════════════════════════════════════ */

// ── State ──────────────────────────────────────────────────
let currentRole = 'sender';
let systemStatus = { sender: 'stopped', receiver: 'stopped', proxy: 'stopped' };
const MAX_CHART_POINTS = 120;

// ── Socket.IO ──────────────────────────────────────────────
const socket = io({ reconnection: true, reconnectionDelay: 1000 });

socket.on('connect', () => {
    document.getElementById('ws-dot').classList.add('connected');
    document.getElementById('ws-label').textContent = 'Connected';
    addLog('WebSocket connected', 'info');
});

socket.on('disconnect', () => {
    document.getElementById('ws-dot').classList.remove('connected');
    document.getElementById('ws-label').textContent = 'Offline';
    addLog('WebSocket disconnected', 'warn');
});

socket.on('metrics_update', (data) => {
    updateMetrics(data);
    if (data.status) {
        systemStatus = data.status;
        updateStatusDots();
    }
});

socket.on('log_message', (entry) => {
    addLog(entry.msg, entry.level);
});

// ── Init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Show the Vercel alert modal immediately
    document.getElementById('vercel-modal').classList.add('active');
    
    fetchNetworkInfo();
    fetchReports();
    initChart();
    setupTabs();

    setupNavbar();
    initSimCanvas();
    setInterval(fetchReports, 10000);
});

// ── Navbar scroll effect + active section tracking ─────────
function setupNavbar() {
    const navbar = document.getElementById('navbar');
    const sections = document.querySelectorAll('.section, .hero');
    const navLinks = document.querySelectorAll('.nav-link[href^="#"]');

    window.addEventListener('scroll', () => {
        // Scroll effect
        if (window.scrollY > 20) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }

        // Active section
        let current = '';
        sections.forEach(sec => {
            const top = sec.offsetTop - 100;
            if (window.scrollY >= top) {
                current = sec.id;
            }
        });

        navLinks.forEach(link => {
            link.classList.remove('active');
            if (link.getAttribute('href') === '#' + current) {
                link.classList.add('active');
            }
        });
    });
}

// ── Network Info ───────────────────────────────────────────
async function fetchNetworkInfo() {
    try {
        const res = await fetch('/api/network-info');
        const data = await res.json();
        if (data.ips && data.ips.length > 0) {
            document.getElementById('local-ip').textContent = data.ips[0];
        }
    } catch (e) { console.error('Network info failed', e); }
}

// ── Tab Switching ──────────────────────────────────────────
function setupTabs() {
    document.querySelectorAll('.role-tab').forEach(tab => {
        tab.addEventListener('click', () => switchRole(tab.dataset.role));
    });
}

function switchRole(role) {
    currentRole = role;
    document.querySelectorAll('.role-tab').forEach(t => t.classList.remove('active'));
    document.getElementById(`tab-${role}`).classList.add('active');
    ['sender', 'receiver', 'proxy'].forEach(r => {
        const el = document.getElementById(`${r}-controls`);
        if (el) el.style.display = r === role ? 'block' : 'none';
    });
}

// ── Status Dots ────────────────────────────────────────────
function updateStatusDots() {
    ['sender', 'receiver', 'proxy'].forEach(name => {
        const dot = document.getElementById(`dot-${name}`);
        if (!dot) return;
        dot.classList.toggle('running', systemStatus[name] === 'running');
    });
    updateBtnState('sender', systemStatus.sender === 'running');
    updateBtnState('receiver', systemStatus.receiver === 'running');
    updateBtnState('proxy', systemStatus.proxy === 'running');
}

function updateBtnState(role, running) {
    const p = { sender: 'sender', receiver: 'recv', proxy: 'proxy' }[role];
    const s = document.getElementById(`btn-${p}-start`);
    const t = document.getElementById(`btn-${p}-stop`);
    if (s) s.disabled = running;
    if (t) t.disabled = !running;
}

// ── API Calls ──────────────────────────────────────────────
async function apiCall(url, body = null) {
    try {
        const opts = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(url, opts);
        const data = await res.json();
        if (!res.ok) addLog(`API Error: ${data.error || 'Unknown'}`, 'error');
        return data;
    } catch (e) { addLog(`Request failed: ${e.message}`, 'error'); return null; }
}

async function startSender() {
    const host = document.getElementById('sender-host').value.trim();
    if (!host) { addLog('Enter receiver IP', 'error'); return; }
    await apiCall('/api/sender/start', {
        host, port: +document.getElementById('sender-port').value,
        scenario: document.getElementById('sender-scenario').value,
        bitrate: +document.getElementById('sender-bitrate').value
    });
}
async function stopSender() { await apiCall('/api/sender/stop'); }

async function startReceiver() {
    await apiCall('/api/receiver/start', {
        port: +document.getElementById('recv-port').value,
        scenario: document.getElementById('recv-scenario').value,
        jitter_ms: +document.getElementById('recv-jitter').value
    });
}
async function stopReceiver() { await apiCall('/api/receiver/stop'); }

async function startProxy() {
    const fwd = document.getElementById('proxy-fwd-host').value.trim();
    if (!fwd) { addLog('Enter forward IP', 'error'); return; }
    await apiCall('/api/proxy/start', {
        listen_port: +document.getElementById('proxy-listen-port').value,
        forward_host: fwd,
        forward_port: +document.getElementById('proxy-fwd-port').value,
        loss: +document.getElementById('proxy-loss').value,
        delay: +document.getElementById('proxy-delay').value,
        jitter: +document.getElementById('proxy-jitter').value
    });
}
async function stopProxy() { await apiCall('/api/proxy/stop'); }

// ── Metrics ────────────────────────────────────────────────
function updateMetrics(data) {
    let m = null;
    if (data.sender && data.receiver) {
        m = { ...data.receiver };
        m.packets_sent = data.sender.packets_sent;
    } else {
        m = data.receiver || data.sender || null;
    }
    if (m) {
        document.getElementById('m-pkts-sent').textContent = m.packets_sent.toLocaleString();
        document.getElementById('m-pkts-recv').textContent = m.packets_recv.toLocaleString();

        const lossEl = document.getElementById('m-loss');
        lossEl.textContent = m.packet_loss_pct.toFixed(1) + '%';
        lossEl.className = 'metric-value ' + colorClass(m.packet_loss_pct, [1, 5]);

        const latEl = document.getElementById('m-latency');
        latEl.textContent = m.latency_avg_ms.toFixed(1) + ' ms';
        latEl.className = 'metric-value ' + colorClass(m.latency_avg_ms, [20, 80]);
        document.getElementById('m-latency-range').textContent =
            `min ${m.latency_min_ms.toFixed(1)} / max ${m.latency_max_ms.toFixed(1)} ms`;

        const jitEl = document.getElementById('m-jitter');
        jitEl.textContent = m.jitter_ms.toFixed(1);
        jitEl.className = 'metric-value ' + colorClass(m.jitter_ms, [10, 30]);

        updateMOS(m.mos_estimate);
        document.getElementById('m-bitrate').textContent = m.bitrate_kbps.toFixed(1) + ' kbps';
        pushChartData(m.latency_avg_ms, m.jitter_ms, m.packet_loss_pct);
    }

    if (data.proxy && systemStatus.proxy === 'running') {
        const t = data.proxy.total || 0, d = data.proxy.dropped || 0;
        document.getElementById('m-pkts-sent').textContent = t;
        document.getElementById('m-pkts-recv').textContent = t - d;
        const lp = t > 0 ? (d / t * 100).toFixed(1) : '0.0';
        const le = document.getElementById('m-loss');
        le.textContent = lp + '%';
        le.className = 'metric-value ' + colorClass(parseFloat(lp), [1, 5]);
    }
}

function colorClass(val, [low, high]) {
    if (val <= low) return 'good';
    if (val <= high) return 'warning';
    return 'critical';
}

function mosColor(mos) {
    if (mos >= 4) return '#10b981';
    if (mos >= 3) return '#f59e0b';
    if (mos >= 2) return '#f97316';
    return '#f43f5e';
}

function mosLabel(mos) {
    if (mos >= 4) return 'Good';
    if (mos >= 3.5) return 'Fair';
    if (mos >= 2.5) return 'Poor';
    return 'Bad';
}

function updateMOS(mos) {
    const arc = document.getElementById('mos-arc');
    const text = document.getElementById('m-mos');
    const label = document.getElementById('m-mos-label');
    const circ = 2 * Math.PI * 30;
    const offset = circ * (1 - Math.min(mos / 5, 1));
    arc.style.strokeDashoffset = offset;
    arc.style.stroke = mosColor(mos);
    text.textContent = mos.toFixed(1);
    text.style.color = mosColor(mos);
    label.textContent = mosLabel(mos);
    label.style.color = mosColor(mos);
}

// ── Chart ──────────────────────────────────────────────────
let liveChart = null;

function initChart() {
    const ctx = document.getElementById('live-chart').getContext('2d');
    const gridColor = 'rgba(255,255,255,0.025)';
    const tickColor = '#475569';
    const font = { family: 'JetBrains Mono', size: 10 };

    liveChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                { label: 'Latency (ms)', data: [], borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.08)', borderWidth: 2, fill: true, tension: 0.4, pointRadius: 0 },
                { label: 'Jitter (ms)', data: [], borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.06)', borderWidth: 2, fill: true, tension: 0.4, pointRadius: 0 },
                { label: 'Loss (%)', data: [], borderColor: '#f43f5e', borderWidth: 1.5, fill: false, tension: 0.4, pointRadius: 0, yAxisID: 'y1' }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: '#94a3b8', font: { family: 'Inter', size: 11 }, boxWidth: 12, boxHeight: 2, padding: 16 }
                },
                tooltip: {
                    backgroundColor: 'rgba(15,23,42,0.95)', borderColor: 'rgba(99,102,241,0.2)', borderWidth: 1,
                    titleFont: { family: 'Inter', size: 12 }, bodyFont: { family: 'JetBrains Mono', size: 11 },
                    padding: 12, cornerRadius: 8
                }
            },
            scales: {
                x: { grid: { color: gridColor }, ticks: { color: tickColor, font, maxTicksLimit: 8 } },
                y: { position: 'left', title: { display: true, text: 'ms', color: tickColor, font: { family: 'Inter', size: 11 } }, grid: { color: gridColor }, ticks: { color: tickColor, font }, min: 0 },
                y1: { position: 'right', title: { display: true, text: 'Loss %', color: tickColor, font: { family: 'Inter', size: 11 } }, grid: { drawOnChartArea: false }, ticks: { color: tickColor, font }, min: 0, max: 100 }
            },
            animation: { duration: 200 }
        }
    });
}

function pushChartData(lat, jit, loss) {
    const now = new Date();
    const label = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    liveChart.data.labels.push(label);
    liveChart.data.datasets[0].data.push(lat);
    liveChart.data.datasets[1].data.push(jit);
    liveChart.data.datasets[2].data.push(loss);
    if (liveChart.data.labels.length > MAX_CHART_POINTS) {
        liveChart.data.labels.shift();
        liveChart.data.datasets.forEach(ds => ds.data.shift());
    }
    liveChart.update('none');
}

// ── Console Log ────────────────────────────────────────────
function addLog(msg, level = 'info') {
    const c = document.getElementById('console-log');
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
    const div = document.createElement('div');
    div.className = 'log-line';
    div.innerHTML = `<span class="log-ts">${ts}</span><span class="log-msg ${level}">${esc(msg)}</span>`;
    c.appendChild(div);
    while (c.children.length > 100) c.removeChild(c.firstChild);
    c.scrollTop = c.scrollHeight;
}

function esc(t) {
    const m = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return t.replace(/[&<>"']/g, x => m[x]);
}

// ── Reports ────────────────────────────────────────────────
async function fetchReports() {
    try {
        const res = await fetch('/api/reports');
        const reports = await res.json();
        renderReports(reports);
    } catch (e) {}
}

function renderReports(reports) {
    const c = document.getElementById('reports-list');
    if (!reports || !reports.length) {
        c.innerHTML = '<div style="text-align:center;padding:32px;color:var(--text-dim);font-size:0.85rem">No reports yet</div>';
        return;
    }
    c.innerHTML = reports.map(r => `
        <div class="report-item" onclick='openReport(${JSON.stringify(r).replace(/'/g,"&#39;")})'>
            <span class="scenario-name">${esc(r.scenario||'Unknown')}</span>
            <span class="report-mos" style="color:${mosColor(r.mos_estimate)};background:${mosColor(r.mos_estimate)}18">MOS ${r.mos_estimate}</span>
        </div>`).join('');
}

function openReport(r) {
    document.getElementById('modal-scenario').textContent = r.scenario || 'Report';
    const metrics = [
        { label:'Packets Sent', value:r.packets_sent },
        { label:'Packets Recv', value:r.packets_recv },
        { label:'Packet Loss', value:r.packet_loss_pct+'%' },
        { label:'Avg Latency', value:r.latency_avg_ms+' ms' },
        { label:'Min Latency', value:r.latency_min_ms+' ms' },
        { label:'Max Latency', value:r.latency_max_ms+' ms' },
        { label:'Jitter', value:r.jitter_ms+' ms' },
        { label:'Bitrate', value:r.bitrate_kbps+' kbps' },
        { label:'MOS Score', value:r.mos_estimate+' / 5.0' },
        { label:'Duration', value:r.duration_s+' s' }
    ];
    document.getElementById('modal-metrics').innerHTML = metrics.map(m =>
        `<div class="modal-metric"><div class="m-label">${m.label}</div><div class="m-value">${m.value}</div></div>`
    ).join('');
    document.getElementById('report-modal').classList.add('active');
}

// ── Modals ─────────────────────────────────────────────────
function closeModal(id) { document.getElementById(id).classList.remove('active'); }
function openHelpModal() { document.getElementById('help-modal').classList.add('active'); }
function openDevModal() { document.getElementById('dev-modal').classList.add('active'); }

document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) e.target.classList.remove('active');
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
});


/* ═══════════════════════════════════════════════════════════
   PACKET TRANSMISSION SIMULATION ENGINE
   ═══════════════════════════════════════════════════════════ */

let simCanvas, simCtx, simAnim;
let simRunning = false;
let simPackets = [];
let simStats = { sent: 0, received: 0, lost: 0, totalDelay: 0 };
let simStepIndex = -1;

function initSimCanvas() {
    simCanvas = document.getElementById('sim-canvas');
    simCtx = simCanvas.getContext('2d');
    resizeSimCanvas();
    window.addEventListener('resize', resizeSimCanvas);
    drawSimIdle();
}

function resizeSimCanvas() {
    const wrap = simCanvas.parentElement;
    simCanvas.width = wrap.clientWidth;
    simCanvas.height = wrap.clientHeight || 400;
}

function drawSimIdle() {
    const w = simCanvas.width, h = simCanvas.height;
    simCtx.clearRect(0, 0, w, h);

    // Background
    simCtx.fillStyle = 'rgba(0,0,0,0.1)';
    simCtx.fillRect(0, 0, w, h);

    // Sender box
    drawBox(60, h / 2 - 40, 100, 80, 'Sender', '#6366f1');
    // Receiver box
    drawBox(w - 160, h / 2 - 40, 100, 80, 'Receiver', '#10b981');

    // Dashed line
    simCtx.setLineDash([6, 4]);
    simCtx.strokeStyle = 'rgba(255,255,255,0.08)';
    simCtx.lineWidth = 1;
    simCtx.beginPath();
    simCtx.moveTo(170, h / 2);
    simCtx.lineTo(w - 170, h / 2);
    simCtx.stroke();
    simCtx.setLineDash([]);

    // Label
    simCtx.fillStyle = '#475569';
    simCtx.font = '12px Inter';
    simCtx.textAlign = 'center';
    simCtx.fillText('Click "Run" to start simulation', w / 2, h / 2 + 80);
}

function drawBox(x, y, w, h, label, color) {
    // Glow
    simCtx.shadowColor = color;
    simCtx.shadowBlur = 20;
    simCtx.fillStyle = color + '15';
    simCtx.strokeStyle = color + '60';
    simCtx.lineWidth = 1.5;
    simCtx.beginPath();
    simCtx.roundRect(x, y, w, h, 10);
    simCtx.fill();
    simCtx.stroke();
    simCtx.shadowBlur = 0;

    // Icon
    simCtx.fillStyle = color;
    simCtx.font = '22px serif';
    simCtx.textAlign = 'center';
    simCtx.fillText(label === 'Sender' ? '🎙️' : '🔊', x + w / 2, y + h / 2 - 4);

    // Label
    simCtx.fillStyle = '#94a3b8';
    simCtx.font = '600 11px Inter';
    simCtx.fillText(label, x + w / 2, y + h / 2 + 18);
}

function startSimulation() {
    if (simRunning) return;
    simRunning = true;
    simPackets = [];
    simStats = { sent: 0, received: 0, lost: 0, totalDelay: 0 };
    simStepIndex = 0;
    updateStepUI(0);

    document.getElementById('btn-sim-start').disabled = true;
    document.getElementById('sim-output').innerHTML = '<span class="out-label">Simulation started...</span>';

    const lossPct = parseFloat(document.getElementById('sim-loss').value) / 100;
    const delayMs = parseFloat(document.getElementById('sim-delay').value);
    const jitterMs = parseFloat(document.getElementById('sim-jitter').value);
    const txRate = parseInt(document.getElementById('sim-tx-rate').value);
    const pktSize = parseInt(document.getElementById('sim-packet-size').value);
    const windowSize = parseInt(document.getElementById('sim-window').value);
    const bitrate = parseInt(document.getElementById('sim-bitrate').value);

    let packetId = 0;
    const totalPackets = Math.min(windowSize * 5, 100);

    // Generate packets over time
    const sendInterval = setInterval(() => {
        if (packetId >= totalPackets || !simRunning) {
            clearInterval(sendInterval);
            // Wait for remaining in-flight packets
            setTimeout(() => finishSimulation(lossPct, delayMs, jitterMs, pktSize, bitrate), 2000);
            return;
        }

        const isLost = Math.random() < lossPct;
        const baseDelay = delayMs + (Math.random() * 2 - 1) * jitterMs;
        const delay = Math.max(5, baseDelay);

        simPackets.push({
            id: packetId,
            x: 170,
            targetX: simCanvas.width - 170,
            speed: (simCanvas.width - 340) / (delay / 16.67), // pixels per frame
            lost: isLost,
            arrived: false,
            delay: delay,
            size: pktSize,
            opacity: 1
        });

        simStats.sent++;
        packetId++;

        // Update steps
        if (packetId === 1) updateStepUI(1); // encoding
        if (packetId === 2) updateStepUI(2); // framing
        if (packetId === 3) updateStepUI(3); // transmit
    }, 1000 / txRate);

    // Animation loop
    function animate() {
        if (!simRunning) return;
        drawSimFrame(lossPct);
        simAnim = requestAnimationFrame(animate);
    }
    animate();
}

function drawSimFrame() {
    const w = simCanvas.width, h = simCanvas.height;
    simCtx.clearRect(0, 0, w, h);
    simCtx.fillStyle = 'rgba(0,0,0,0.1)';
    simCtx.fillRect(0, 0, w, h);

    // Sender / Receiver boxes
    drawBox(60, h / 2 - 40, 100, 80, 'Sender', '#6366f1');
    drawBox(w - 160, h / 2 - 40, 100, 80, 'Receiver', '#10b981');

    // Network zone label
    simCtx.fillStyle = '#334155';
    simCtx.font = '10px Inter';
    simCtx.textAlign = 'center';
    simCtx.fillText('── NETWORK CHANNEL ──', w / 2, h / 2 - 55);

    // Draw network path
    simCtx.strokeStyle = 'rgba(255,255,255,0.04)';
    simCtx.lineWidth = 40;
    simCtx.lineCap = 'round';
    simCtx.beginPath();
    simCtx.moveTo(170, h / 2);
    simCtx.lineTo(w - 170, h / 2);
    simCtx.stroke();

    // Draw packets
    simPackets.forEach(pkt => {
        if (pkt.arrived && !pkt.lost) return;

        if (pkt.lost && pkt.x > (170 + pkt.targetX) / 2 - 30 && pkt.x < (170 + pkt.targetX) / 2 + 30) {
            // Drop animation
            pkt.opacity -= 0.02;
            if (pkt.opacity <= 0) {
                pkt.arrived = true;
                return;
            }
            // Draw X mark
            simCtx.globalAlpha = pkt.opacity;
            drawPacket(pkt.x, h / 2, '#f43f5e', pkt.id, true);
            simCtx.globalAlpha = 1;
        } else if (pkt.lost && pkt.x >= (170 + pkt.targetX) / 2 + 30) {
            pkt.arrived = true;
        } else if (!pkt.lost && pkt.x >= pkt.targetX) {
            pkt.arrived = true;
            if (!pkt.counted) {
                pkt.counted = true;
                simStats.received++;
                simStats.totalDelay += pkt.delay;
            }
        } else {
            // Move packet
            pkt.x += pkt.speed;

            // Vertical jitter wobble
            const wobble = Math.sin(pkt.id * 3 + pkt.x * 0.05) * 12;
            drawPacket(pkt.x, h / 2 + wobble, pkt.lost ? '#f59e0b' : '#6366f1', pkt.id, false);
        }
    });

    // Stats overlay
    simCtx.fillStyle = '#94a3b8';
    simCtx.font = '600 11px JetBrains Mono';
    simCtx.textAlign = 'left';
    simCtx.fillText(`Sent: ${simStats.sent}`, 20, 30);
    simCtx.fillStyle = '#10b981';
    simCtx.fillText(`Recv: ${simStats.received}`, 20, 48);
    simCtx.fillStyle = '#f43f5e';
    simCtx.fillText(`Lost: ${simStats.lost}`, 20, 66);
}

function drawPacket(x, y, color, id, isLost) {
    const size = 10;
    simCtx.shadowColor = color;
    simCtx.shadowBlur = 8;

    if (isLost) {
        // X mark for lost packets
        simCtx.strokeStyle = '#f43f5e';
        simCtx.lineWidth = 2;
        simCtx.beginPath();
        simCtx.moveTo(x - 6, y - 6);
        simCtx.lineTo(x + 6, y + 6);
        simCtx.moveTo(x + 6, y - 6);
        simCtx.lineTo(x - 6, y + 6);
        simCtx.stroke();
    } else {
        simCtx.fillStyle = color;
        simCtx.beginPath();
        simCtx.roundRect(x - size / 2, y - size / 2, size, size, 3);
        simCtx.fill();

        // Seq number
        simCtx.shadowBlur = 0;
        simCtx.fillStyle = 'rgba(255,255,255,0.6)';
        simCtx.font = '8px JetBrains Mono';
        simCtx.textAlign = 'center';
        simCtx.fillText(id, x, y - size / 2 - 4);
    }

    simCtx.shadowBlur = 0;
}

function finishSimulation(lossPct, delayMs, jitterMs, pktSize, bitrate) {
    simRunning = false;
    cancelAnimationFrame(simAnim);
    document.getElementById('btn-sim-start').disabled = false;

    // Count lost
    simStats.lost = simPackets.filter(p => p.lost).length;

    updateStepUI(4); // network transit
    setTimeout(() => updateStepUI(5), 500); // jitter buffer

    const avgDelay = simStats.received > 0 ? (simStats.totalDelay / simStats.received).toFixed(1) : 0;
    const actualLoss = simStats.sent > 0 ? ((simStats.lost / simStats.sent) * 100).toFixed(1) : 0;
    const effectiveBitrate = ((pktSize * 8 * 50) / 1000).toFixed(1);

    // MOS estimation
    const r = 93.2 - (avgDelay / 10) - (2.5 * actualLoss);
    const rClamped = Math.max(0, Math.min(100, r));
    const mos = (1 + 0.035 * rClamped + rClamped * (rClamped - 60) * (100 - rClamped) * 7e-6).toFixed(2);
    const mosClamped = Math.max(1, Math.min(5, mos));

    const lossClass = actualLoss <= 1 ? 'out-good' : actualLoss <= 5 ? 'out-warn' : 'out-bad';
    const latClass = avgDelay <= 20 ? 'out-good' : avgDelay <= 80 ? 'out-warn' : 'out-bad';
    const mosClass = mosClamped >= 4 ? 'out-good' : mosClamped >= 3 ? 'out-warn' : 'out-bad';

    document.getElementById('sim-output').innerHTML = `
<span class="out-label">━━━ Simulation Complete ━━━</span>
<span class="out-label">Packets Sent:</span>     <span class="out-value">${simStats.sent}</span>
<span class="out-label">Packets Received:</span> <span class="out-value">${simStats.received}</span>
<span class="out-label">Packets Lost:</span>     <span class="${lossClass}">${simStats.lost} (${actualLoss}%)</span>
<span class="out-label">Avg Delay:</span>        <span class="${latClass}">${avgDelay} ms</span>
<span class="out-label">Config Jitter:</span>    <span class="out-value">±${jitterMs} ms</span>
<span class="out-label">Packet Size:</span>      <span class="out-value">${pktSize} bytes</span>
<span class="out-label">Codec Bitrate:</span>    <span class="out-value">${(bitrate/1000).toFixed(0)} kbps</span>
<span class="out-label">Effective Rate:</span>   <span class="out-value">${effectiveBitrate} kbps</span>
<span class="out-label">MOS Estimate:</span>     <span class="${mosClass}">${mosClamped} / 5.0 (${mosClamped >= 4 ? 'Good' : mosClamped >= 3 ? 'Fair' : mosClamped >= 2 ? 'Poor' : 'Bad'})</span>
    `.trim();

    // Complete all steps
    setTimeout(() => {
        for (let i = 0; i <= 5; i++) {
            const el = document.getElementById(`step-${i + 1}`);
            if (el) { el.classList.remove('active'); el.classList.add('completed'); }
        }
    }, 800);
}

function resetSimulation() {
    simRunning = false;
    cancelAnimationFrame(simAnim);
    simPackets = [];
    simStats = { sent: 0, received: 0, lost: 0, totalDelay: 0 };
    document.getElementById('btn-sim-start').disabled = false;
    document.getElementById('sim-output').innerHTML = '<span class="out-label">Ready.</span> Configure parameters above and click <strong>Run</strong> to begin simulation.';

    // Reset steps
    for (let i = 1; i <= 6; i++) {
        const el = document.getElementById(`step-${i}`);
        if (el) { el.classList.remove('active', 'completed'); }
    }

    drawSimIdle();
}

function updateStepUI(idx) {
    for (let i = 0; i < idx; i++) {
        const el = document.getElementById(`step-${i + 1}`);
        if (el) { el.classList.remove('active'); el.classList.add('completed'); }
    }
    const active = document.getElementById(`step-${idx + 1}`);
    if (active) { active.classList.add('active'); active.classList.remove('completed'); }
}

/* ═══════════════════════════════════════════════════════════
   SPEECH-TO-TEXT TRANSCRIPTION (Server-side via speech_recognition)
   Audio is transcribed on the server from the actual VoIP stream
   AFTER it passes through the jitter buffer, so timing is accurate.
   ═══════════════════════════════════════════════════════════ */

let sttActive = false;

// Toggle from UI
function toggleTranscription(checked) {
    sttActive = checked;
    const panel = document.getElementById('stt-panel');
    
    if (sttActive) {
        panel.style.display = 'block';
        document.getElementById('stt-status-text').textContent = 'Listening...';
        document.getElementById('stt-status-text').style.color = 'var(--accent-emerald)';
        document.getElementById('stt-listening-dot').style.background = 'var(--accent-emerald)';
        document.getElementById('stt-listening-dot').style.boxShadow = '0 0 8px rgba(16, 185, 129, 0.6)';
        addLog('[STT] Server-side transcription enabled — transcribing VoIP audio stream', 'info');
    } else {
        panel.style.display = 'none';
        document.getElementById('stt-status-text').textContent = 'Stopped';
        document.getElementById('stt-status-text').style.color = 'var(--text-muted)';
        document.getElementById('stt-listening-dot').style.background = 'var(--text-muted)';
        document.getElementById('stt-listening-dot').style.boxShadow = 'none';
        addLog('[STT] Server-side transcription disabled', 'info');
    }
    
    // Notify server to start/stop the STT worker
    socket.emit('toggle_transcription', { active: sttActive });
}

// Receive transcription results from server
socket.on('stt_transcript', (data) => {
    if (!sttActive) return;
    if (data.text) {
        appendTranscript(data.text, data.final !== false);
    }
});

function appendTranscript(text, isFinal) {
    const area = document.getElementById('stt-transcript-area');
    const placeholder = document.getElementById('stt-placeholder');
    if (placeholder) placeholder.remove();
    
    if (!text.trim()) return;

    const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
    
    const div = document.createElement('div');
    div.className = `stt-line ${isFinal ? 'final' : 'interim'}`;
    div.innerHTML = `<span class="stt-ts">[${ts}]</span><span class="stt-text">${esc(text)}</span>`;
    
    area.appendChild(div);
    area.scrollTop = area.scrollHeight;
}

function clearTranscript() {
    const area = document.getElementById('stt-transcript-area');
    area.innerHTML = '<div class="stt-placeholder" id="stt-placeholder">Waiting for speech...</div>';
}
