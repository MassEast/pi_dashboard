## Plan: Weather Then Emotion Catalog

Split the work into two phases so the weather layout fix can be committed separately before any emotion-system changes. Phase 1 is weather-only; Phase 2 covers the emotion catalog, custom inputs, and LLM-backed classification. The dashboard should stay analyzable: base emotions remain ordered from positive to negative, while custom emotions are introduced in a way that preserves a stable UI, predictable replacement behavior, and an editable catalog instead of code changes.

**Phase 1: Weather first**
1. Audit the current weather rendering and forecast data flow in `PiDashboard.py`, then update the layout so forecast rows read day temp first, night temp second.
2. Tighten the rain-specific spacing between the forecast block and the first bus row, because the current layout feels cramped when precipitation is shown.
3. Keep the current day temperature presentation explicit if it is hidden or ambiguous, and verify this phase can be committed separately from the emotion work.

**Phase 2: Emotion catalog and custom entry**
1. Add an explicit `don't know` emotion to the configured emotion list so it consumes the spare slot in the existing grid. Confirm it flows through the on-device prompt, backend storage, and web chart without special-case failures.
2. Replace the proposed OS keyboard approach with our own small in-app virtual keyboard so custom emotion entry works both on the Pi touchscreen and on the MacBook during testing.
3. Design the bottom custom row for the on-device prompt: two persistent custom emotion slots plus a third button labeled `custom`. When `custom` is activated, show the virtual keyboard and overwrite the less-used of the two custom slots. If the usage counts are tied, define a deterministic tie-breaker.
4. Make `config.json` the source of truth for the emotion catalog, including order, emoji, color, and any sentiment metadata the web UI needs. The app should update this catalog when a new custom emotion is accepted, rather than rewriting code. Keep `emotions.json` as the event log and derive usage frequency from it when needed; only add separate metadata storage if the derived computation becomes too slow or brittle.
5. Add an LLM-based classification step for newly typed custom emotions. Define a prompt that includes the currently displayed emotions, the existing custom slots, and the new label, then ask the model to return JSON with the final display name, sentiment order, emoji, and color guidance. Define a fallback JSON shape that uses a gray color and a `?` emoji when the model response is missing or malformed.
6. Extend the web dashboard to read the updated emotion catalog from config, render the legend in catalog order, and apply the same emoji/color metadata that the LLM or custom entry produced. Custom emotions should still render deterministically even if the LLM fallback path is used.
7. Verify the full flow end to end: weather screen layout on device, emotion prompt interaction, persistence across restart, LLM prompt/JSON parsing for custom emotions, and web chart/legend rendering for both built-in and custom emotions.

**Relevant files**
- `/Users/jw/Documents/pi_dashboard/PiDashboard.py` — weather surface rendering, forecast text, emotion prompt layout, keyboard/touch handling for the custom row.
- `/Users/jw/Documents/pi_dashboard/config.json` — editable emotion catalog, default order, emoji, color, and any sentiment metadata.
- `/Users/jw/Documents/pi_dashboard/emotion_store.py` — event storage/aggregation for deriving usage frequency and replaying event history.
- `/Users/jw/Documents/pi_dashboard/web_server.py` — API surface if the web dashboard needs to serve catalog metadata or custom emotion updates.
- `/Users/jw/Documents/pi_dashboard/web/app.js` — legend ordering, palette/emoji mapping, and fallback rendering based on catalog metadata.
- `/Users/jw/Documents/pi_dashboard/web/index.html` — any extra UI text or controls on the dashboard.
- `/Users/jw/Documents/pi_dashboard/web/styles.css` — visual treatment for day/night temperature stacking, the `don't know` button, the custom-emotion row, and the virtual keyboard.

**Verification**
1. Run the app and confirm the weather card shows current conditions plus day/night forecast values in the new order, then commit that change separately.
2. Add the `don't know` option and confirm it is logged, displayed, and charted like the other base emotions.
3. Open the custom-entry flow, type a new label with the virtual keyboard, and confirm the less-used slot is replaced while the other remains.
4. Confirm `config.json` reflects the current emotion catalog after adding a custom emotion and that the web legend uses that catalog order.
5. Check that LLM fallback output still produces a usable `?` / gray display and does not break chart rendering.
6. Check for regressions in the existing emotion window filters (`today`, `7d`, `30d`, `weekday`, `alltime`) and the current uptime display.

**Decisions**
- Scope includes both the on-device PiDashboard UI and the web dashboard because custom emotions need to remain analyzable everywhere.
- `emotions.json` remains the source of truth for historical events and usage frequency; it does not need a separate usage metadata block unless we later find a performance or migration reason.
- `config.json` should hold the editable emotion catalog so new emotion order/color/emoji data does not require code changes.
- The LLM path is the preferred way to place a newly typed custom emotion into the catalog, with a safe `?`/gray fallback when the model cannot classify it.
- The custom input flow uses our own virtual keyboard instead of spawning a system keyboard, so it is testable on the Pi and on the MacBook.
- "All emotions are valid" stays as UI copy and can be kept near the hallway check-in prompt or emotion area.
- The custom row uses the existing spare slot in the main emotion grid for `don't know`, so no extra base row is needed.

**Further Considerations**
1. If you want, we can still split Phase 2 into two commits: virtual keyboard and custom row first, then catalog and web rendering.
2. If custom emotions should be editable later, we should store the catalog in a dedicated section inside `config.json` rather than mixing it into unrelated settings.
3. If you decide the LLM route is worth it, we should define the fallback prompt/output contract first so the UI still works when the API is unavailable.
