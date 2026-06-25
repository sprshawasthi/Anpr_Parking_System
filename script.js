// ===== CONFIG =====
const API = "http://localhost:5000/api";
let MAX_CAPACITY = 200;
let activeVehicles = [];
let parkingHistory = [];
let recentDetections = [];
let trendData = { labels: [], values: [] };
let flaskOnline = false;

// ===== CLOCK =====
function updateClock() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const dateStr = now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', weekday: 'long' });
    const el1 = document.getElementById("sidebarTime");
    const el2 = document.getElementById("sidebarDate");
    if (el1) el1.textContent = timeStr;
    if (el2) el2.textContent = dateStr;
}
setInterval(updateClock, 1000);
updateClock();

// ===== PAGE NAVIGATION =====
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

// ===== SIDEBAR TOGGLE (mobile) =====
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

// ===== TAB SWITCHER =====
function switchTab(tabId, btnClass) {
    document.querySelectorAll('.' + btnClass).forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.target.classList.add('active');
}

// ===== CHART: OCCUPANCY DONUT =====
const occupancyChart = new Chart(
    document.getElementById('occupancyChart').getContext('2d'), {
    type: 'doughnut',
    data: {
        labels: ['Occupied', 'Available'],
        datasets: [{ data: [0, 200], backgroundColor: ['#1a56db', '#bfdbfe'], borderWidth: 0 }]
    },
    options: {
        cutout: '72%',
        plugins: { legend: { display: false }, tooltip: { enabled: true } },
        animation: { duration: 600 }
    }
});

// ===== CHART: TREND LINE =====
const trendChart = new Chart(
    document.getElementById('trendChart').getContext('2d'), {
    type: 'line',
    data: {
        labels: [],
        datasets: [{
            label: 'Occupancy',
            data: [],
            borderColor: '#1a56db',
            backgroundColor: 'rgba(26,86,219,0.1)',
            fill: true,
            tension: 0.4,
            pointRadius: 3
        }]
    },
    options: {
        plugins: { legend: { display: false } },
        scales: {
            x: { grid: { display: false }, ticks: { font: { size: 11 } } },
            y: { beginAtZero: true, max: MAX_CAPACITY, ticks: { font: { size: 11 } } }
        },
        animation: { duration: 300 }
    }
});

// ===== ANALYTICS PAGE CHARTS =====
let trendChart2, hourlyChart;

function initAnalyticsCharts() {
    if (trendChart2) trendChart2.destroy();
    if (hourlyChart) hourlyChart.destroy();

    trendChart2 = new Chart(document.getElementById('trendChart2').getContext('2d'), {
        type: 'line',
        data: {
            labels: trendData.labels,
            datasets: [{
                label: 'Occupied Slots',
                data: trendData.values,
                borderColor: '#1a56db',
                backgroundColor: 'rgba(26,86,219,0.1)',
                fill: true, tension: 0.4
            }]
        },
        options: { plugins: { legend: { display: true } }, scales: { y: { beginAtZero: true } } }
    });

    const buckets = Array(24).fill(0);
    [...activeVehicles, ...parkingHistory].forEach(v => {
        const t = v.entry_time;
        if (t instanceof Date && !isNaN(t)) buckets[t.getHours()]++;
    });

    hourlyChart = new Chart(document.getElementById('hourlyChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels: Array.from({ length: 24 }, (_, i) => i + ':00'),
            datasets: [{
                label: 'Vehicles',
                data: buckets,
                backgroundColor: '#1a56db',
                borderRadius: 4
            }]
        },
        options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
    });
}

// ===== TREND DATA RECORDER =====
function recordTrendPoint(occupied) {
    const now = new Date();
    const label = now.getHours() + ':' + String(now.getMinutes()).padStart(2, '0');
    if (trendData.labels[trendData.labels.length - 1] !== label) {
        trendData.labels.push(label);
        trendData.values.push(occupied);
        if (trendData.labels.length > 20) {
            trendData.labels.shift();
            trendData.values.shift();
        }
        trendChart.data.labels = trendData.labels;
        trendChart.data.datasets[0].data = trendData.values;
        trendChart.update();
    }
}

// ===== DURATION HELPER =====
function calcDuration(entryTime) {
    const diff = Math.floor((new Date() - entryTime) / 1000);
    const h = Math.floor(diff / 3600);
    const m = Math.floor((diff % 3600) / 60);
    const s = diff % 60;
    if (h > 0) return h + 'h ' + m + 'm ' + s + 's';
    if (m > 0) return m + 'm ' + s + 's';
    return s + 's';
}

// ===== RENDER ACTIVE VEHICLES TABLE (dashboard) =====
function renderActiveTable() {
    const tbody = document.getElementById('activeTable');
    if (!activeVehicles.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No active vehicles</td></tr>';
        return;
    }
    tbody.innerHTML = activeVehicles.map((v, i) => `
        <tr>
            <td>${i + 1}</td>
            <td><strong>${v.vehicle_no}</strong></td>
            <td>${v.entry_time.toLocaleTimeString('en-IN')}</td>
            <td id="dur-${v.vehicle_no}">${calcDuration(v.entry_time)}</td>
            <td><button class="btn-view" onclick="viewVehicle('${v.vehicle_no}')">View</button></td>
        </tr>
    `).join('');
}

// ===== RENDER HISTORY TABLE (dashboard) =====
function renderHistoryTable() {
    const tbody = document.getElementById('historyTable');
    if (!parkingHistory.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No history yet</td></tr>';
        return;
    }
    tbody.innerHTML = parkingHistory.slice(0, 5).map((v, i) => `
        <tr>
            <td>${i + 1}</td>
            <td><strong>${v.vehicle_no}</strong></td>
            <td>${v.entry_time.toLocaleTimeString('en-IN')}</td>
            <td>${v.exit_time.toLocaleTimeString('en-IN')}</td>
            <td>${v.duration}</td>
        </tr>
    `).join('');
}

// ===== RENDER RECORDS PAGE TABLES =====
function renderRecordsTables() {
    const rActive = document.getElementById('recordsActiveTable');
    if (!activeVehicles.length) {
        rActive.innerHTML = '<tr><td colspan="4" class="empty-row">No active vehicles</td></tr>';
    } else {
        rActive.innerHTML = activeVehicles.map((v, i) => `
            <tr>
                <td>${i + 1}</td>
                <td><strong>${v.vehicle_no}</strong></td>
                <td>${v.entry_time.toLocaleTimeString('en-IN')}</td>
                <td>${calcDuration(v.entry_time)}</td>
            </tr>
        `).join('');
    }

    const rHistory = document.getElementById('recordsHistoryTable');
    if (!parkingHistory.length) {
        rHistory.innerHTML = '<tr><td colspan="5" class="empty-row">No history yet</td></tr>';
    } else {
        rHistory.innerHTML = parkingHistory.map((v, i) => `
            <tr>
                <td>${i + 1}</td>
                <td><strong>${v.vehicle_no}</strong></td>
                <td>${v.entry_time.toLocaleTimeString('en-IN')}</td>
                <td>${v.exit_time.toLocaleTimeString('en-IN')}</td>
                <td>${v.duration}</td>
            </tr>
        `).join('');
    }
}

// ===== RENDER RECENT DETECTIONS LIST =====
function renderRecentList() {
    const ul = document.getElementById('recentList');

    if (!recentDetections.length) {
        ul.innerHTML = '<li class="recent-empty">No detections yet</li>';
        return;
    }

    ul.innerHTML = recentDetections.slice(0, 6).map(d => `
        <li class="recent-item">
            <span>🚗</span>
            <span class="recent-plate">${d.plate}</span>
            <span class="recent-badge ${d.type === 'Entry' ? 'badge-entry' : 'badge-exit'}">↓ ${d.type}</span>
            <span class="recent-time">${d.time}</span>
        </li>
    `).join('');
}

// ===== UPDATE STAT CARDS =====
function updateStatCards(occupied, available, total, todayEntries) {
    document.getElementById('totalCap').textContent = total;
    document.getElementById('occupiedSpaces').textContent = occupied;
    document.getElementById('availableSpaces').textContent = available;
    document.getElementById('todayEntries').textContent = todayEntries;

    const occPct = total > 0 ? ((occupied / total) * 100).toFixed(2) : '0.00';
    const avaPct = total > 0 ? ((available / total) * 100).toFixed(2) : '100.00';

    document.getElementById('occupiedPct').textContent = occPct + '% ↑';
    document.getElementById('availablePct').textContent = avaPct + '% ↑';

    occupancyChart.data.datasets[0].data = [occupied, available];
    occupancyChart.update();

    document.getElementById('donutCenter').innerHTML = occPct + '%<br><small>Occupied</small>';
    document.getElementById('legOccupied').textContent = occupied + ' (' + occPct + '%)';
    document.getElementById('legAvailable').textContent = available + ' (' + avaPct + '%)';
    document.getElementById('legTotal').textContent = total;

    recordTrendPoint(occupied);
}

// ===== UPDATE LAST DETECTED =====
function updateLastDetected(plate, timeStr, status) {
    const p = document.getElementById('ldPlate');
    const t = document.getElementById('ldTime');
    const s = document.getElementById('ldStatus');
    if (p) p.textContent = plate || '—';
    if (t) t.textContent = timeStr || '—';
    if (s) {
        s.textContent = status || '—';
        s.className = 'ld-status' + (status === 'Exit Detected' ? ' exit' : '');
    }
}

// ===== POLL FLASK API =====
function pollData() {
    fetch(API + '/status')
        .then(r => r.json())
        .then(data => {
            flaskOnline = true;
            document.getElementById('systemStatus').textContent = 'Online';
            if (!MAX_CAPACITY) MAX_CAPACITY = data.max_slots;
            updateStatCards(data.occupied, data.available, data.max_slots, data.today_entries);
            document.getElementById('notifBadge').textContent = data.occupied > 0 ? data.occupied : '0';
        })
        .catch(() => {
            flaskOnline = false;
            document.getElementById('systemStatus').textContent = 'Offline';
        });

    fetch(API + '/active')
        .then(r => r.json())
        .then(vehicles => {
            const prev = activeVehicles.map(v => v.vehicle_no);
            activeVehicles = vehicles.map(v => ({
                vehicle_no: v.plate_number,
                entry_time: new Date(v.entry_time)
            }));

            vehicles.forEach(v => {
                if (!prev.includes(v.plate_number)) {
                    const now = new Date(v.entry_time);
                    const timeStr = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
                    recentDetections.unshift({ plate: v.plate_number, type: 'Entry', time: timeStr });
                    if (recentDetections.length > 20) recentDetections.pop();
                    updateLastDetected(v.plate_number, timeStr, 'Entry Detected');
                }
            });

            renderActiveTable();
            renderRecentList();
        })
        .catch(() => {});

    fetch(API + '/history')
        .then(r => r.json())
        .then(history => {
            const prev = parkingHistory.map(v => v.vehicle_no + v.raw_exit);
            
            parkingHistory = history.map(v => ({
                vehicle_no: v.plate_number,
                entry_time: new Date(v.entry_time),
                exit_time:  new Date(v.exit_time),
                raw_exit:   v.exit_time,
                duration:   v.duration_minutes + ' mins'
            }));

            history.forEach(v => {
                const key = v.plate_number + v.exit_time;
                if (prev.length > 0 && !prev.includes(key)) {
                    const now = new Date(v.exit_time);
                    const timeStr = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
                    recentDetections.unshift({ plate: v.plate_number, type: 'Exit', time: timeStr });
                    if (recentDetections.length > 20) recentDetections.pop();
                    updateLastDetected(v.plate_number, timeStr, 'Exit Detected');
                }
            });

            renderHistoryTable();
            renderRecentList();
        })
        .catch(() => {});
}

// Live durations update every second
setInterval(() => {
    activeVehicles.forEach(v => {
        const el = document.getElementById('dur-' + v.vehicle_no);
        if (el) el.textContent = calcDuration(v.entry_time);
    });
}, 1000);

// Poll every 3 seconds
setInterval(pollData, 3000);

// ===== MANUAL VEHICLE ENTRY =====
function detectVehicle() {
    const input = document.getElementById('vehicleInput');
    if (!input) return;
    const plate = input.value.trim().toUpperCase();

    if (!plate) {
        alert('Enter a vehicle number first.');
        return;
    }

    fetch(API + '/vehicle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plate })
    })
    .then(r => r.json())
    .then(() => {
        input.value = '';
        pollData();
    })
    .catch(() => {
        alert('Flask offline — could not process.');
    });
}

// ===== VIEW VEHICLE DETAIL =====
function viewVehicle(plate) {
    const v = activeVehicles.find(x => x.vehicle_no === plate);
    if (!v) return;
    alert(`Vehicle: ${v.vehicle_no}\nEntry: ${v.entry_time.toLocaleString('en-IN')}\nDuration: ${calcDuration(v.entry_time)}`);
}

// ===== SETTINGS =====
function setCapacity() {
    const val = parseInt(document.getElementById('capacityInput').value);
    if (!val || val <= 0) { alert('Enter a valid capacity'); return; }
    MAX_CAPACITY = val;
    alert('Capacity updated to ' + val);
}

function confirmReset() {
    if (confirm('⚠️ This will clear all active vehicles. Continue?')) {
        alert('To reset, run reset.py in your terminal:\n\npython reset.py');
    }
}

// ===== EXPORT CSV =====
function exportCSV() {
    const rows = [['Vehicle', 'Entry', 'Exit', 'Duration']];
    parkingHistory.forEach(v => {
        rows.push([
            v.vehicle_no,
            v.entry_time.toLocaleString('en-IN'),
            v.exit_time.toLocaleString('en-IN'),
            v.duration
        ]);
    });
    const csv = rows.map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'sjvn_parking_' + new Date().toISOString().slice(0,10) + '.csv';
    a.click();
}

// ===== INIT =====
pollData();