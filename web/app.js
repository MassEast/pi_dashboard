const emergencyFallbackCatalog = [{ name: "don't know", emoji: "🤷", color: "#9ca3af" }];
let sharedFallbackCatalog = null;
let sharedFallbackCatalogPromise = null;

function normalizeCatalog(catalog) {
    if (!Array.isArray(catalog)) {
        return [...(sharedFallbackCatalog || emergencyFallbackCatalog)];
    }

    const seen = new Set();
    const normalized = [];
    for (const entry of catalog) {
        const name = String(entry?.name || "").trim().toLowerCase();
        if (!name || seen.has(name)) {
            continue;
        }
        normalized.push({
            name,
            emoji: entry?.emoji || "?",
            color: entry?.color || "#9ca3af",
        });
        seen.add(name);
    }

    return normalized.length > 0 ? normalized : [...(sharedFallbackCatalog || emergencyFallbackCatalog)];
}

let emotionCatalog = normalizeCatalog(sharedFallbackCatalog);

async function ensureSharedFallbackCatalog() {
    if (sharedFallbackCatalog) {
        return sharedFallbackCatalog;
    }
    if (!sharedFallbackCatalogPromise) {
        sharedFallbackCatalogPromise = fetch("/emotion_catalog.defaults.json")
            .then((response) => response.json())
            .then((catalog) => {
                sharedFallbackCatalog = normalizeCatalog(catalog);
                return sharedFallbackCatalog;
            })
            .catch(() => {
                sharedFallbackCatalog = [...emergencyFallbackCatalog];
                return sharedFallbackCatalog;
            });
    }
    return sharedFallbackCatalogPromise;
}

function catalogMaps() {
    const palette = {};
    const emojis = {};
    const order = [];
    for (const entry of emotionCatalog) {
        palette[entry.name] = entry.color;
        emojis[entry.name] = entry.emoji;
        order.push(entry.name);
    }
    return { palette, emojis, order };
}

const chartContext = document.getElementById("emotionChart").getContext("2d");
const totalCountNode = document.getElementById("totalCount");
const updatedAtNode = document.getElementById("updatedAt");
const uptimeCards = [...document.querySelectorAll(".uptime-window")];
const windowButtons = [...document.querySelectorAll(".window-btn")];

let currentWindow = "7d";
let emotionChart;

function setActiveWindow(windowValue) {
    currentWindow = windowValue;
    for (const btn of windowButtons) {
        btn.classList.toggle("active", btn.dataset.window === currentWindow);
    }
}

function getEmotionOrder(series) {
    const { order: emotionOrder } = catalogMaps();
    const orderedKnown = emotionOrder.filter((emotion) => emotion in series);
    const custom = Object.keys(series)
        .filter((emotion) => !emotionOrder.includes(emotion))
        .sort((left, right) => {
            const leftTotal = series[left].reduce((sum, value) => sum + value, 0);
            const rightTotal = series[right].reduce((sum, value) => sum + value, 0);
            if (rightTotal !== leftTotal) {
                return rightTotal - leftTotal;
            }
            return left.localeCompare(right);
        });
    return [...orderedKnown, ...custom];
}

function toDatasets(series) {
    const { palette, emojis } = catalogMaps();
    return getEmotionOrder(series).map((emotion) => ({
        emotionKey: emotion,
        label: `${emojis[emotion] || "?"} ${emotion}`,
        data: series[emotion],
        backgroundColor: palette[emotion] || "#9ca3af",
        borderRadius: 3,
        borderSkipped: false,
        stack: "emotion",
    }));
}

function formatHours(value) {
    if (value == null || Number.isNaN(value)) {
        return "-";
    }

    return `${value.toFixed(1)}h`;
}

function formatPercent(value) {
    if (value == null || Number.isNaN(value)) {
        return "-";
    }

    return `${value.toFixed(1)}%`;
}

function formatCount(value) {
    if (value == null || Number.isNaN(value)) {
        return "-";
    }

    return `${value}`;
}

function renderUptime(payload) {
    const windows = payload?.windows || {};

    for (const card of uptimeCards) {
        const windowKey = card.dataset.window;
        const windowData = windows[windowKey] || {};
        const screenNode = card.querySelector('[data-field="screen"]');
        const bvgNode = card.querySelector('[data-field="bvg"]');
        const weatherNode = card.querySelector('[data-field="weather"]');
        const rebootNode = card.querySelector('[data-field="reboots"]');

        if (screenNode) {
            screenNode.textContent = formatHours(windowData.screen_avg_hours_per_day);
        }
        if (bvgNode) {
            bvgNode.textContent = formatPercent(windowData.bvg?.uptime_pct);
        }
        if (weatherNode) {
            weatherNode.textContent = formatPercent(windowData.weather?.uptime_pct);
        }
        if (rebootNode) {
            rebootNode.textContent = formatCount(windowData.reboot_count);
        }
    }

}

const emojiPlugin = {
    id: "emojiOverlay",
    afterDatasetsDraw(chart) {
        const { ctx, data, scales } = chart;
        ctx.save();

        const { emojis } = catalogMaps();
        data.datasets.forEach((dataset, datasetIdx) => {
            const emoji = emojis[dataset.emotionKey] || "?";

            dataset.data.forEach((value, dataIdx) => {
                if (value === 0 || value === null) return;

                const meta = chart.getDatasetMeta(datasetIdx);
                const bar = meta.data[dataIdx];

                if (!bar) return;

                const x = bar.x;
                const y = bar.y + bar.height / 2;

                ctx.font = "16px Arial";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(emoji, x, y);
            });
        });

        ctx.restore();
    },
};

function upsertChart(labels, series) {
    const datasets = toDatasets(series);
    if (!emotionChart) {
        emotionChart = new Chart(chartContext, {
            type: "bar",
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            font: {
                                size: 14,
                                weight: "500",
                            },
                            padding: 16,
                        },
                    },
                },
                scales: {
                    x: { stacked: true },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        ticks: { precision: 0 },
                    },
                },
            },
            plugins: [emojiPlugin],
        });
        return;
    }

    emotionChart.data.labels = labels;
    emotionChart.data.datasets = datasets;
    emotionChart.update();
}

async function refresh() {
    await ensureSharedFallbackCatalog();

    let window = currentWindow;
    if (window === "alltime") {
        window = "alltime";
    }
    const [catalogResult, emotionResult, uptimeResult] = await Promise.allSettled([
        fetch("/api/emotions/catalog").then((response) => response.json()),
        fetch(`/api/emotions/bars?window=${window}`).then((response) => response.json()),
        fetch("/api/uptime").then((response) => response.json()),
    ]);

    if (catalogResult.status === "fulfilled") {
        emotionCatalog = normalizeCatalog(catalogResult.value.catalog);
    }

    if (emotionResult.status === "fulfilled") {
        upsertChart(emotionResult.value.labels, emotionResult.value.series);
        totalCountNode.textContent = `Total: ${emotionResult.value.total}` + (currentWindow === "alltime" ? " (all time)" : "");
        updatedAtNode.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
    }

    if (uptimeResult.status === "fulfilled") {
        renderUptime(uptimeResult.value);
    }
}

for (const btn of windowButtons) {
    btn.addEventListener("click", async () => {
        setActiveWindow(btn.dataset.window);
        await refresh();
    });
}

setActiveWindow(currentWindow);
refresh();
setInterval(refresh, 30000);
