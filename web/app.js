const palette = {
    stressed: "#b91c1c",
    wild: "#7e22ce",
    relaxed: "#0284c7",
    sad: "#334155",
    angry: "#7c2d12",
    happy: "#16a34a",
    anxious: "#f97316",
    tired: "#78716c",
    grateful: "#0f766e",
    excited: "#db2777",
    energized: "#ea580c",
    proud: "#2563eb",
    focused: "#4338ca",
    bored: "#94a3b8",
};

const emojis = {
    stressed: "😰",
    wild: "🎉",
    relaxed: "😌",
    sad: "😢",
    angry: "😠",
    happy: "😊",
    anxious: "😨",
    tired: "😴",
    grateful: "🙏",
    excited: "🤩",
    energized: "⚡",
    proud: "😎",
    focused: "🎯",
    bored: "🥱",
};

const chartContext = document.getElementById("emotionChart").getContext("2d");
const totalCountNode = document.getElementById("totalCount");
const updatedAtNode = document.getElementById("updatedAt");
const uptimeCards = [...document.querySelectorAll(".uptime-window")];
const windowButtons = [...document.querySelectorAll(".window-btn")];

let currentWindow = "today";
let emotionChart;

function setActiveWindow(windowValue) {
    currentWindow = windowValue;
    for (const btn of windowButtons) {
        btn.classList.toggle("active", btn.dataset.window === currentWindow);
    }
}

function toDatasets(series) {
    return Object.entries(series).map(([emotion, values]) => ({
        label: `${emojis[emotion] || "●"} ${emotion}`,
        data: values,
        backgroundColor: palette[emotion] || "#64748b",
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

        data.datasets.forEach((dataset, datasetIdx) => {
            const emotion = Object.keys(emojis).find(
                (e) => emojis[e] === dataset.label.charAt(0)
            );
            const emoji = emojis[emotion] || "●";

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
    const [emotionResult, uptimeResult] = await Promise.allSettled([
        fetch(`/api/emotions/bars?window=${currentWindow}`).then((response) => response.json()),
        fetch("/api/uptime").then((response) => response.json()),
    ]);

    if (emotionResult.status === "fulfilled") {
        upsertChart(emotionResult.value.labels, emotionResult.value.series);
        totalCountNode.textContent = `Total: ${emotionResult.value.total}`;
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
