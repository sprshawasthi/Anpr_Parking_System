const API = "http://localhost:5000/api";
let activeVehicles = [];
let parkingHistory = [];
let recentDetections = [];
let trendData = { labels: [], values: [] };
let flaskOnline = false;
let floors = [];          
let floorsLoaded = false;

function updateClock() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const dateStr = now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', weekday: 'long' });
    if (document.getElementById("sidebarTime")) document.getElementById("sidebarTime").textContent = timeStr;
    if (document.getElementById("sidebarDate")) document.getElementById("sidebarDate").textContent = dateStr;
}
setInterval(updateClock, 1000); updateClock();

function showPage(name) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const page = document.getElementById('page-' + name);
    if (page) page.classList.add('active');
    const navItems = document.querySelectorAll('.nav-item');
    const labels = { dashboard: 0, records: 1, analytics: 2, reports: 3, settings: 4 };
    if (navItems[labels[name]]) navItems[labels[name]].classList.add('active');
    if (name === 'analytics') initAnalyticsCharts();
    if (name === 'records') renderRecordsTables();
}

function toggleSidebar() { document.getElementById('sidebar').classList.toggle('open'); }

function switchTab(tabId, btnClass) {
    document.querySelectorAll('.' + btnClass).forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.target.classList.add('active');
}

const occupancyChart = new Chart(document.getElementById('occupancyChart').getContext('2d'), {
    type: 'doughnut', data: { labels: ['Occupied', 'Available'], datasets: [{ data: [0, 200], backgroundColor: ['#1a56db', '#bfdbfe'], borderWidth: 0 }] },
    options: { cutout: '72%', plugins: { legend: { display: false }, tooltip: { enabled: true } }, animation: { duration: 600 } }
});

const trendChart = new Chart(document.getElementById('trendChart').getContext('2d'), {
    type: 'line', data: { labels: [], datasets: [{ label: 'Occupancy', data: [], borderColor: '#1a56db', backgroundColor: 'rgba(26,86,219,0.1)', fill: true, tension: 0.4, pointRadius: 3 }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { font: { size: 11 } } }, y: { beginAtZero: true, ticks: { font: { size: 11 } } } }, animation: { duration: 300 } }
});

let trendChart2, hourlyChart;
function initAnalyticsCharts() {
    if (trendChart2) trendChart2.destroy();
    if (hourlyChart) hourlyChart.destroy();
    trendChart2 = new Chart(document.getElementById('trendChart2').getContext('2d'), {
        type: 'line', data: { labels: trendData.labels, datasets: [{ label: 'Occupied Slots', data: trendData.values, borderColor: '#1a56db', backgroundColor: 'rgba(26,86,219,0.1)', fill: true, tension: 0.4 }] },
        options: { plugins: { legend: { display: true } }, scales: { y: { beginAtZero: true } } }
    });
    const buckets = Array(24).fill(0);
    [...activeVehicles, ...parkingHistory].forEach(v => { const t = v.entry_time; if (t instanceof Date && !isNaN(t)) buckets[t.getHours()]++; });
    hourlyChart = new Chart(document.getElementById('hourlyChart').getContext('2d'), {
        type: 'bar', data: { labels: Array.from({ length: 24 }, (_, i) => i + ':00'), datasets: [{ label: 'Vehicles', data: buckets, backgroundColor: '#1a56db', borderRadius: 4 }] },
        options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
    });
}

function recordTrendPoint(occupied) {
    const now = new Date();
    const label = now.getHours() + ':' + String(now.getMinutes()).padStart(2, '0');
    if (trendData.labels[trendData.labels.length - 1] !== label) {
        trendData.labels.push(label); trendData.values.push(occupied);
        if (trendData.labels.length > 20) { trendData.labels.shift(); trendData.values.shift(); }
        trendChart.data.labels = trendData.labels; trendChart.data.datasets[0].data = trendData.values; trendChart.update();
    }
}

function calcDuration(entryTime) {
    const diff = Math.floor((new Date() - entryTime) / 1000);
    const h = Math.floor(diff / 3600), m = Math.floor((diff % 3600) / 60), s = diff % 60;
    if (h > 0) return h + 'h ' + m + 'm ' + s + 's';
    if (m > 0) return m + 'm ' + s + 's';
    return s + 's';
}

function loadFloors() {
    return fetch(API + '/floors').then(r => r.json()).then(data => {
        const idsChanged = !floorsLoaded || data.length !== floors.length || data.some((f, i) => !floors[i] || f.id !== floors[i].id);
        floors = data; floorsLoaded = true;
        if (idsChanged) {
            buildFloorContainer('activeFloorsContainer', 'active', 5);
            buildFloorContainer('recordsFloorsContainer', 'records', 4);
            renderFloorManageList();
            renderVehicleFloorSelect();
        } else { renderFloorManageList(); }
    }).catch(() => {});
}

function buildFloorContainer(containerId, prefix, columns) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!floors.length) {
        container.innerHTML = '<div class="empty-row">No parking locations configured.</div>';
        return;
    }

    // 1. Group floors by building
    const grouped = floors.reduce((acc, f) => {
        if (!acc[f.building]) acc[f.building] = [];
        acc[f.building].push(f);
        return acc;
    }, {});

    // 2. Render groups
    container.innerHTML = Object.keys(grouped).map(buildingName => `
        <div class="building-section" style="margin-bottom: 30px;">
            <h2 class="building-heading" style="color: #0d1b3e; margin-bottom: 10px;">${buildingName}</h2>
            ${grouped[buildingName].map(f => {
                const actionTh = columns === 5 ? '<th>Action</th>' : '';
                return `
                    <div class="floor-section" style="margin-bottom: 20px;">
                        <h4 class="floor-heading">${f.name}</h4>
                        <table>
                            <thead>
                                <tr><th>#</th><th>Vehicle Number</th><th>Entry Time</th><th>Duration</th>${actionTh}</tr>
                            </thead>
                            <tbody id="${prefix}-floor-${f.id}">
                                <tr><td colspan="${columns}" class="empty-row">No active vehicles</td></tr>
                            </tbody>
                        </table>
                    </div>
                `;
            }).join('')}
        </div>
    `).join('');
}

function renderActiveTable() {
    floors.forEach(f => {
        const tbody = document.getElementById('active-floor-' + f.id);
        if (!tbody) return;
        const vehicles = activeVehicles.filter(v => v.floor_id === f.id);
        if (!vehicles.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No active vehicles</td></tr>'; return; }
        tbody.innerHTML = vehicles.map((v, i) => `<tr><td>${i + 1}</td><td><strong>${v.vehicle_no}</strong></td><td>${v.entry_time.toLocaleTimeString('en-IN')}</td><td id="dur-${v.vehicle_no}">${calcDuration(v.entry_time)}</td><td><button class="btn-view" onclick="viewVehicle('${v.vehicle_no}')">View</button></td></tr>`).join('');
    });
}

function renderHistoryTable() {
    const tbody = document.getElementById('historyTable');
    if (!parkingHistory.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No history yet</td></tr>'; return; }
    tbody.innerHTML = parkingHistory.slice(0, 5).map((v, i) => `<tr><td>${i + 1}</td><td><strong>${v.vehicle_no}</strong></td><td>${v.entry_time.toLocaleTimeString('en-IN')}</td><td>${v.exit_time.toLocaleTimeString('en-IN')}</td><td>${v.duration}</td></tr>`).join('');
}

function renderRecordsTables() {
    floors.forEach(f => {
        const tbody = document.getElementById('records-floor-' + f.id);
        if (!tbody) return;
        const vehicles = activeVehicles.filter(v => v.floor_id === f.id);
        if (!vehicles.length) tbody.innerHTML = '<tr><td colspan="4" class="empty-row">No active vehicles</td></tr>';
        else tbody.innerHTML = vehicles.map((v, i) => `<tr><td>${i + 1}</td><td><strong>${v.vehicle_no}</strong></td><td>${v.entry_time.toLocaleTimeString('en-IN')}</td><td>${calcDuration(v.entry_time)}</td></tr>`).join('');
    });
    const rHistory = document.getElementById('recordsHistoryTable');
    if (!parkingHistory.length) rHistory.innerHTML = '<tr><td colspan="5" class="empty-row">No history yet</td></tr>';
    else rHistory.innerHTML = parkingHistory.map((v, i) => `<tr><td>${i + 1}</td><td><strong>${v.vehicle_no}</strong></td><td>${v.entry_time.toLocaleTimeString('en-IN')}</td><td>${v.exit_time.toLocaleTimeString('en-IN')}</td><td>${v.duration}</td></tr>`).join('');
}

function renderRecentList() {
    const ul = document.getElementById('recentList');
    if (!recentDetections.length) { ul.innerHTML = '<li class="recent-empty">No detections yet</li>'; return; }
    ul.innerHTML = recentDetections.slice(0, 6).map(d => `<li class="recent-item"><span>🚗</span><span class="recent-plate">${d.plate}</span><span class="recent-badge ${d.type === 'Entry' ? 'badge-entry' : 'badge-exit'}">↓ ${d.type}</span><span class="recent-time">${d.time}</span></li>`).join('');
}

function updateStatCards(occupied, available, total, todayEntries) {
    document.getElementById('totalCap').textContent = total;
    document.getElementById('occupiedSpaces').textContent = occupied;
    document.getElementById('availableSpaces').textContent = available;
    document.getElementById('todayEntries').textContent = todayEntries;
    const occPct = total > 0 ? ((occupied / total) * 100).toFixed(2) : '0.00', avaPct = total > 0 ? ((available / total) * 100).toFixed(2) : '100.00';
    document.getElementById('occupiedPct').textContent = occPct + '% ↑';
    document.getElementById('availablePct').textContent = avaPct + '% ↑';
    occupancyChart.data.datasets[0].data = [occupied, available]; occupancyChart.update();
    document.getElementById('donutCenter').innerHTML = occPct + '%<br><small>Occupied</small>';
    document.getElementById('legOccupied').textContent = occupied + ' (' + occPct + '%)';
    document.getElementById('legAvailable').textContent = available + ' (' + avaPct + '%)';
    document.getElementById('legTotal').textContent = total;
    recordTrendPoint(occupied);
}

function updateLastDetected(plate, timeStr, status) {
    if (document.getElementById('ldPlate')) document.getElementById('ldPlate').textContent = plate || '—';
    if (document.getElementById('ldTime')) document.getElementById('ldTime').textContent = timeStr || '—';
    const s = document.getElementById('ldStatus');
    if (s) { s.textContent = status || '—'; s.className = 'ld-status' + (status === 'Exit Detected' ? ' exit' : ''); }
}

function pollData() {
    loadFloors();
    fetch(API + '/status').then(r => r.json()).then(data => {
        flaskOnline = true; document.getElementById('systemStatus').textContent = 'Online';
        updateStatCards(data.occupied, data.available, data.max_slots, data.today_entries);
    }).catch(() => { flaskOnline = false; document.getElementById('systemStatus').textContent = 'Offline'; });

    fetch(API + '/active').then(r => r.json()).then(vehicles => {
        const prev = activeVehicles.map(v => v.vehicle_no);
        activeVehicles = vehicles.map(v => ({ vehicle_no: v.plate_number, entry_time: new Date(v.entry_time), floor_id: v.floor_id, floor: v.floor }));
        vehicles.forEach(v => {
            if (!prev.includes(v.plate_number)) {
                const timeStr = new Date(v.entry_time).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
                recentDetections.unshift({ plate: v.plate_number, type: 'Entry', time: timeStr });
                if (recentDetections.length > 20) recentDetections.pop();
                updateLastDetected(v.plate_number, timeStr, 'Entry Detected');
            }
        });
        renderActiveTable(); renderRecentList();
    }).catch(() => {});

    fetch(API + '/history').then(r => r.json()).then(history => {
        const prev = parkingHistory.map(v => v.vehicle_no + v.raw_exit);
        parkingHistory = history.map(v => ({ vehicle_no: v.plate_number, entry_time: new Date(v.entry_time), exit_time: new Date(v.exit_time), raw_exit: v.exit_time, floor_id: v.floor_id, duration: v.duration_minutes + ' mins' }));
        history.forEach(v => {
            const key = v.plate_number + v.exit_time;
            if (prev.length > 0 && !prev.includes(key)) {
                const timeStr = new Date(v.exit_time).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
                recentDetections.unshift({ plate: v.plate_number, type: 'Exit', time: timeStr });
                if (recentDetections.length > 20) recentDetections.pop();
                updateLastDetected(v.plate_number, timeStr, 'Exit Detected');
            }
        });
        renderHistoryTable(); renderRecentList();
    }).catch(() => {});
}

setInterval(() => { activeVehicles.forEach(v => { const el = document.getElementById('dur-' + v.vehicle_no); if (el) el.textContent = calcDuration(v.entry_time); }); }, 1000);
setInterval(pollData, 3000);

function detectVehicle() {
    const input = document.getElementById('vehicleInput'); const floorSelect = document.getElementById('vehicleFloorSelect');
    if (!input) return; const plate = input.value.trim().toUpperCase();
    if (!plate) return alert('Enter a vehicle number first.');
    const body = { plate }; if (floorSelect && floorSelect.value) body.floor_id = floorSelect.value;
    fetch(API + '/vehicle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(r => r.json()).then(() => { input.value = ''; pollData(); }).catch(() => alert('Flask offline.'));
}

function viewVehicle(plate) {
    const v = activeVehicles.find(x => x.vehicle_no === plate);
    if (v) alert(`Vehicle: ${v.vehicle_no}\nFloor: ${v.floor || v.floor_id}\nEntry: ${v.entry_time.toLocaleString('en-IN')}\nDuration: ${calcDuration(v.entry_time)}`);
}

function renderFloorManageList() {
    const list = document.getElementById('floorsManageList');
    if (!list) return;
    if (!floors.length) { list.innerHTML = '<div class="empty-row">No floors yet — add your first one above.</div>'; return; }
    list.innerHTML = floors.map(f => `<div class="floor-manage-row"><div class="floor-manage-name"><strong>${f.building}</strong>: ${f.name}</div><div class="floor-manage-stat">${f.occupied} / ${f.capacity} occupied</div><button class="btn-remove-floor" onclick="removeFloor('${f.id}')" ${f.occupied > 0 ? 'disabled' : ''}>Remove</button></div>`).join('');
}

function renderVehicleFloorSelect() {
    const select = document.getElementById('vehicleFloorSelect');
    if (select) select.innerHTML = floors.map(f => `<option value="${f.id}">${f.building} - ${f.name}</option>`).join('');
}

function addFloor() {
    const bldgInput = document.getElementById('newFloorBuilding');
    const nameInput = document.getElementById('newFloorName');
    const capInput = document.getElementById('newFloorCapacity');
    const building = bldgInput.value.trim() || 'Main Building';
    const name = nameInput.value.trim();
    const capacity = parseInt(capInput.value);
    if (!name) return alert('Enter a name for the new floor.');
    if (!capacity || capacity <= 0) return alert('Enter a valid capacity.');
    fetch(API + '/floors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ building, name, capacity }) })
    .then(r => r.json().then(data => ({ ok: r.ok, data }))).then(({ ok, data }) => {
        if (!ok) return alert(data.error || 'Could not add floor.');
        nameInput.value = ''; capInput.value = ''; loadFloors();
    }).catch(() => alert('Flask offline.'));
}

function removeFloor(floorId) {
    if (!confirm('Remove this floor? This cannot be undone.')) return;
    fetch(API + '/floors/' + floorId, { method: 'DELETE' }).then(r => r.json().then(data => ({ ok: r.ok, data }))).then(({ ok, data }) => {
        if (!ok) return alert(data.error || 'Could not remove floor.');
        loadFloors();
    }).catch(() => alert('Flask offline.'));
}

function confirmReset() {
    if (confirm('⚠️ Clear all active vehicles?')) fetch(API + '/reset', { method: 'POST' }).then(() => pollData()).catch(() => alert('Flask offline.'));
}

function exportCSV() {
    const rows = [['Vehicle', 'Floor', 'Entry', 'Exit', 'Duration']];
    parkingHistory.forEach(v => {
        const floorName = (floors.find(f => f.id === v.floor_id) || {}).name || v.floor_id || '';
        rows.push([v.vehicle_no, floorName, v.entry_time.toLocaleString('en-IN'), v.exit_time.toLocaleString('en-IN'), v.duration]);
    });
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([rows.map(r => r.join(',')).join('\n')], { type: 'text/csv' }));
    a.download = 'sjvn_parking_' + new Date().toISOString().slice(0,10) + '.csv'; a.click();
}

loadFloors().then(pollData);