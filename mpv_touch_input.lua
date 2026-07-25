-- Touch controls for the secret-video corner gesture (see PiDashboard.py,
-- play_secret_video()). The touchscreen driver emits taps as MBTN_LEFT
-- (same as every other tap this app handles), and we need to tell a quick
-- tap (close the video) apart from a held touch (scrub), so this is done
-- here as a single script-owned binding rather than split with a static
-- input.conf entry - a plain `MBTN_LEFT quit` fires on press, before hold
-- duration could ever be measured.
--
-- Quick tap anywhere  -> quit
-- Hold right half     -> 2x fast-forward while held
-- Hold left half      -> 2x rewind while held (mpv has no negative `speed`,
--                        so this is simulated via periodic backward seeks)

local TAP_MAX_SECONDS = 0.25
local REWIND_STEP_INTERVAL = 0.1
local REWIND_STEP_SECONDS = REWIND_STEP_INTERVAL * 2 -- 2x rewind rate

local press_time = nil
local rewind_timer = nil
local paused_for_rewind = false

local function screen_side()
    local mx = mp.get_mouse_pos()
    local w = mp.get_osd_size()
    if not mx or not w or w == 0 then
        return nil
    end
    if mx < w / 2 then
        return "left"
    end
    return "right"
end

local function stop_hold()
    mp.set_property_number("speed", 1)
    if rewind_timer then
        rewind_timer:kill()
        rewind_timer = nil
    end
    if paused_for_rewind then
        mp.set_property_bool("pause", false)
        paused_for_rewind = false
    end
end

local function start_hold(side)
    if side == "right" then
        mp.set_property_number("speed", 2)
    elseif side == "left" then
        paused_for_rewind = true
        mp.set_property_bool("pause", true)
        rewind_timer = mp.add_periodic_timer(REWIND_STEP_INTERVAL, function()
            mp.commandv("seek", -REWIND_STEP_SECONDS, "relative", "exact")
        end)
    end
end

local function on_touch(table)
    if table.event == "down" then
        press_time = mp.get_time()
        local side = screen_side()
        if side then
            start_hold(side)
        end
    elseif table.event == "up" then
        local held = press_time and (mp.get_time() - press_time) or 0
        stop_hold()
        if held < TAP_MAX_SECONDS then
            mp.command("quit")
        end
        press_time = nil
    end
end

mp.add_key_binding("MBTN_LEFT", "secret_video_touch_control", on_touch, { complex = true })
