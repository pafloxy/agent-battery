/* Pure display calculations, shared by GNOME Shell and the test suite. */
function finite(value) {
    return typeof value === 'number' && Number.isFinite(value);
}

function windowName(window) {
    const minutes = window.windowMinutes;
    if (!finite(minutes) || minutes <= 0)
        return window.key === 'secondary' ? 'Secondary window' : 'Primary window';
    if (minutes === 10080)
        return 'Weekly';
    if (minutes % 1440 === 0)
        return `${minutes / 1440}-day`;
    if (minutes % 60 === 0)
        return `${minutes / 60}-hour`;
    return `${minutes}-minute`;
}

function countdown(reset, now) {
    if (!finite(reset))
        return 'unknown';
    const seconds = reset - now;
    if (seconds <= 0)
        return 'pending';
    const minutes = Math.ceil(seconds / 60);
    if (minutes >= 1440)
        return `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h`;
    if (minutes >= 60)
        return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
    return `${minutes}m`;
}

function visualState(window, now, stale) {
    const remaining = finite(window.remainingPercent) ?
        Math.max(0, Math.min(1, window.remainingPercent / 100)) : null;
    const expired = finite(window.resetsAt) && window.resetsAt <= now;
    const timeFraction = finite(window.resetsAt) && finite(window.windowMinutes) && window.windowMinutes > 0 ?
        Math.max(0, Math.min(1, (window.resetsAt - now) / (60 * window.windowMinutes))) : null;
    // Never infer a refill merely because the local clock passed a reset time.
    const dim = Boolean(stale) || expired;
    return {
        remaining,
        timeFraction,
        expired,
        dim,
        tone: dim || remaining === null ? 'unknown' : remaining <= 0.15 ? 'low' : remaining <= 0.35 ? 'medium' : 'good',
        countdown: countdown(window.resetsAt, now),
    };
}
