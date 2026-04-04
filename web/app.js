const palette = {
    stressed: "#b91c1c",
    wild: "#7e22ce",
    relaxed: "#0284c7",
    sad: "#334155",
    angry: "#7c2d12",
    happy: "#16a34a",
    anxious: "#f97316",
    tired: "#78716c",
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
};

const chartContext = document.getElementById("emotionChart").getContext("2d");
const totalCountNode = document.getElementById("totalCount");
const updatedAtNode = document.getElementById("updatedAt");
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
    const response = await fetch(`/api/emotions/bars?window=${currentWindow}`);
    const payload = await response.json();
    upsertChart(payload.labels, payload.series);
    totalCountNode.textContent = `Total: ${payload.total}`;
    updatedAtNode.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
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
