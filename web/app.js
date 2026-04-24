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
let currentPayload = null;
let chartIsHistogram = null;
let hiddenEmotionKeys = new Set();

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

function getEmotionHistogramOrder(series) {
    return Object.keys(series)
        .map((emotion) => ({
            emotion,
            total: series[emotion].reduce((sum, value) => sum + value, 0),
        }))
        .filter(({ total }) => total > 0)
        .sort((left, right) => {
            if (right.total !== left.total) {
                return right.total - left.total;
            }
            return left.emotion.localeCompare(right.emotion);
        })
        .map(({ emotion }) => emotion);
}

function toHistogramData(series) {
    const { palette, emojis } = catalogMaps();
    const order = getEmotionHistogramOrder(series);
    const visibleOrder = order.filter((emotion) => !hiddenEmotionKeys.has(emotion));
    const histogramLabels = visibleOrder.map((emotion) => emojis[emotion] || "?");
    const totals = order.map((emotion) => series[emotion].reduce((sum, value) => sum + value, 0));
    const totalByEmotion = Object.fromEntries(order.map((emotion, index) => [emotion, totals[index]]));

    const datasets = visibleOrder.map((emotion, index) => ({
        emotionKey: emotion,
        label: `${emojis[emotion] || "?"} ${emotion}`,
        data: visibleOrder.map((item, dataIndex) => (dataIndex === index ? totalByEmotion[item] : 0)),
        backgroundColor: palette[emotion] || "#9ca3af",
        borderRadius: 3,
        borderSkipped: false,
        stack: "histogram",
    }));

    return { labels: histogramLabels, datasets };
}

function formatTimestampDisplay(value) {
    const raw = String(value || "").trim();
    const [datePart, timePart = ""] = raw.split(" ");
    const [year, month, day] = datePart.split("-");

    if (!year || !month || !day || !timePart) {
        return raw;
    }

    return `${day}.${month}.${year.slice(-2)}@${timePart}`;
}

function formatDateLabel(value, includeYear = false) {
    const raw = String(value || "").trim();
    const [year, month, day] = raw.split("-");
    if (!year || !month || !day) {
        return raw;
    }

    if (includeYear) {
        return `${day}.${month}.${year.slice(-2)}`;
    }
    return `${day}.${month}`;
}

function tooltipTimeLines(tooltipItems) {
    if (!currentPayload || currentWindow === "emotion") {
        return [];
    }

    const eventTimes = currentPayload.event_times || {};
    const lines = [];

    for (const item of tooltipItems) {
        const emotion = item.dataset?.emotionKey;
        const label = item.label;
        const times = eventTimes?.[emotion]?.[label] || [];

        if (!times.length) {
            continue;
        }

        if (currentWindow === "hour") {
            const uniqueDates = [...new Set(times.map((value) => String(value).split(" ")[0]))];
            const previewDates = uniqueDates.slice(0, 3).join(", ");
            const moreDates = uniqueDates.length > 3 ? ` (+${uniqueDates.length - 3} more)` : "";
            lines.push(`Logged dates: ${previewDates}${moreDates}`);
            continue;
        }

        if (times.length === 1) {
            lines.push(`Logged at: ${formatTimestampDisplay(times[0])}`);
            continue;
        }

        const preview = times.slice(0, 3).map(formatTimestampDisplay).join(", ");
        const extra = times.length > 3 ? ` (+${times.length - 3} more)` : "";
        lines.push(`Logged times: ${preview}${extra}`);
    }

    return lines;
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
        const { ctx, data } = chart;
        ctx.save();

        const { emojis } = catalogMaps();
        data.datasets.forEach((dataset, datasetIdx) => {
            if (!chart.isDatasetVisible(datasetIdx)) {
                return;
            }

            const emoji = emojis[dataset.emotionKey] || "?";

            dataset.data.forEach((value, dataIdx) => {
                if (value === 0 || value === null) return;

                const meta = chart.getDatasetMeta(datasetIdx);
                const bar = meta.data[dataIdx];

                if (!bar) return;

                const props = bar.getProps(["x", "y", "base"], true);
                if (!Number.isFinite(props.x) || !Number.isFinite(props.y) || !Number.isFinite(props.base)) {
                    return;
                }

                const x = props.x;
                const y = props.y + (props.base - props.y) / 2;

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
    const isHistogram = currentWindow === "emotion";
    const chartData = isHistogram ? toHistogramData(series) : { labels, datasets: toDatasets(series) };
    const plugins = [emojiPlugin];
    const useSmartDateTicks = currentWindow === "alltime" || currentWindow === "30d";
    const shouldFormatDateLabels = currentWindow === "7d" || currentWindow === "30d" || currentWindow === "alltime";
    const options = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            tooltip: {
                callbacks: {
                    title(tooltipItems) {
                        const base = tooltipItems?.[0]?.label || "";
                        if (!shouldFormatDateLabels) {
                            return base;
                        }
                        return formatDateLabel(base, currentWindow === "alltime");
                    },
                    afterBody: tooltipTimeLines,
                },
            },
            legend: {
                position: "bottom",
                onClick(legendEvent, legendItem, legend) {
                    if (currentWindow !== "emotion") {
                        Chart.defaults.plugins.legend.onClick.call(this, legendEvent, legendItem, legend);
                        return;
                    }

                    const dataset = legend.chart.data.datasets[legendItem.datasetIndex];
                    const emotionKey = dataset?.emotionKey;
                    if (!emotionKey || !currentPayload) {
                        return;
                    }

                    if (hiddenEmotionKeys.has(emotionKey)) {
                        hiddenEmotionKeys.delete(emotionKey);
                    } else {
                        hiddenEmotionKeys.add(emotionKey);
                    }

                    upsertChart(currentPayload.labels, currentPayload.series);
                },
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
            x: {
                stacked: true,
                ticks: {
                    autoSkip: useSmartDateTicks,
                    maxTicksLimit: useSmartDateTicks ? (currentWindow === "30d" ? 10 : 12) : undefined,
                    maxRotation: useSmartDateTicks ? 32 : 0,
                    minRotation: 0,
                    callback(value, index, ticks) {
                        const label = this.getLabelForValue(value);
                        if (!useSmartDateTicks) {
                            if (shouldFormatDateLabels) {
                                return formatDateLabel(label, currentWindow === "alltime");
                            }
                            return label;
                        }

                        const targetTicks = currentWindow === "30d" ? 10 : 12;
                        const step = Math.max(1, Math.ceil(ticks.length / targetTicks));
                        if (index % step !== 0) {
                            return "";
                        }

                        // Keep long date windows compact while preserving chronological context.
                        return formatDateLabel(label, currentWindow === "alltime");
                    },
                },
            },
            y: {
                stacked: true,
                beginAtZero: true,
                ticks: { precision: 0 },
            },
        },
    };

    if (!emotionChart || chartIsHistogram !== isHistogram) {
        if (emotionChart) {
            emotionChart.destroy();
        }
        emotionChart = new Chart(chartContext, {
            type: "bar",
            data: chartData,
            options,
            plugins,
        });
        chartIsHistogram = isHistogram;
        return;
    }

    emotionChart.data.labels = chartData.labels;
    emotionChart.data.datasets = chartData.datasets;
    emotionChart.options = options;
    emotionChart.update();
}

async function refresh() {
    await ensureSharedFallbackCatalog();

    const window = currentWindow === "emotion" ? "alltime" : currentWindow;
    const [catalogResult, emotionResult, uptimeResult] = await Promise.allSettled([
        fetch("/api/emotions/catalog").then((response) => response.json()),
        fetch(`/api/emotions/bars?window=${window}`).then((response) => response.json()),
        fetch("/api/uptime").then((response) => response.json()),
    ]);

    if (catalogResult.status === "fulfilled") {
        emotionCatalog = normalizeCatalog(catalogResult.value.catalog);
    }

    if (emotionResult.status === "fulfilled") {
        currentPayload = emotionResult.value;
        if (currentWindow !== "emotion" && hiddenEmotionKeys.size > 0) {
            hiddenEmotionKeys = new Set();
        }
        upsertChart(emotionResult.value.labels, emotionResult.value.series);
        totalCountNode.textContent = `Total: ${emotionResult.value.total}` + (currentWindow === "alltime" || currentWindow === "emotion" ? " (all time)" : "");
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
