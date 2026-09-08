/* Usagebar: GNOME Shell 42-44, legacy GJS module format. */
const {St, Gio, GLib, Clutter} = imports.gi;
const ByteArray = imports.byteArray;
const Cairo = imports.cairo;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ExtensionUtils = imports.misc.extensionUtils;
const Me = ExtensionUtils.getCurrentExtension();
const Model = Me.imports.model;

function readJson(path, fallback) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        if (ok && bytes.length < 128 * 1024)
            return JSON.parse(ByteArray.toString(bytes));
    } catch (_) {
        // Missing configuration or cache is normal on first launch.
    }
    return fallback;
}

function writeJson(path, value) {
    GLib.file_set_contents(path, JSON.stringify(value));
}

/**
 * Return provider identity from the newest trusted source.
 */
function providerId(config, snapshot) {
    const value = snapshot && typeof snapshot.providerId === 'string' ? snapshot.providerId : config.provider;
    return typeof value === 'string' && value ? value : 'codex';
}

/**
 * Return the user-facing service name without exposing provider account data.
 */
function serviceName(config, snapshot) {
    const value = snapshot && typeof snapshot.serviceName === 'string' ? snapshot.serviceName : config.service_name;
    return typeof value === 'string' && value ? value : 'Codex';
}

/**
 * Return the compact panel label for the selected provider.
 */
function panelLabel(config, snapshot) {
    const value = snapshot && typeof snapshot.panelLabel === 'string' ? snapshot.panelLabel : config.panel_label;
    return typeof value === 'string' && value ? value : `/${providerId(config, snapshot)}`;
}

/**
 * Return a short local reset timestamp for compact menu rows.
 */
function resetStamp(window) {
    if (!Model.finite(window.resetsAt))
        return '--';
    return new Date(window.resetsAt * 1000).toLocaleString([], {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function rounded(cr, x, y, w, h, radius) {
    if (w <= 0 || h <= 0)
        return;
    const r = Math.min(radius, w / 2, h / 2);
    cr.newSubPath();
    cr.arc(x + w - r, y + r, r, -Math.PI / 2, 0);
    cr.arc(x + w - r, y + h - r, r, 0, Math.PI / 2);
    cr.arc(x + r, y + h - r, r, Math.PI / 2, Math.PI);
    cr.arc(x + r, y + r, r, Math.PI, 3 * Math.PI / 2);
    cr.closePath();
}

function paintGauge(area, state) {
    const cr = area.get_context();
    try {
        const [width, height] = area.get_surface_size();
        cr.scale(width / 53, height / 23);
        cr.setOperator(Cairo.Operator.CLEAR);
        cr.paint();
        cr.setOperator(Cairo.Operator.OVER);
        // A softly outlined horizontal battery with a separate reset-time track.
        cr.setSourceRGBA(0.86, 0.90, 0.96, state.dim ? 0.27 : 0.60);
        cr.setLineWidth(1.15);
        rounded(cr, 1.5, 2.5, 46, 13, 4);
        cr.stroke();
        cr.setSourceRGBA(0.86, 0.90, 0.96, state.dim ? 0.25 : 0.60);
        rounded(cr, 49, 6.5, 2.3, 5, 1);
        cr.fill();
        cr.setSourceRGBA(0.86, 0.90, 0.96, 0.08);
        rounded(cr, 3.5, 4.5, 42, 9, 2.5);
        cr.fill();
        const colors = {
            good: [0.39, 0.83, 0.66],
            medium: [0.98, 0.72, 0.34],
            low: [0.98, 0.39, 0.44],
            unknown: [0.57, 0.61, 0.66],
        };
        const color = colors[state.tone];
        if (state.remaining !== null && state.remaining > 0) {
            cr.setSourceRGBA(...color, state.dim ? 0.48 : 1);
            rounded(cr, 3.5, 4.5, 42 * state.remaining, 9, 2.5);
            cr.fill();
        } else if (state.remaining === null) {
            cr.setSourceRGBA(0.67, 0.70, 0.76, 0.85);
            rounded(cr, 20, 8, 9, 2, 1);
            cr.fill();
        }
        cr.setSourceRGBA(0.47, 0.70, 0.98, 0.15);
        rounded(cr, 2, 19.2, 45, 1.8, 0.9);
        cr.fill();
        if (state.timeFraction !== null && state.timeFraction > 0) {
            cr.setSourceRGBA(0.47, 0.70, 0.98, state.dim ? 0.35 : 0.95);
            rounded(cr, 2, 19.2, 45 * state.timeFraction, 1.8, 0.9);
            cr.fill();
        }
    } finally {
        cr.$dispose();
    }
}

class Usagebar {
    enable() {
        this._alive = true;
        this._process = null;
        this._cancellable = null;
        this._error = '';
        this._configPath = GLib.build_filenamev([Me.path, 'config.json']);
        this._config = readJson(this._configPath, {});
        if (!this._config || typeof this._config !== 'object')
            this._config = {};
        const cacheNamespace = typeof this._config.cache_namespace === 'string' && this._config.cache_namespace ?
            this._config.cache_namespace : 'codex-battery';
        this._cacheDir = GLib.build_filenamev([GLib.get_user_cache_dir(), cacheNamespace]);
        GLib.mkdir_with_parents(this._cacheDir, 0o700);
        this._cachePath = GLib.build_filenamev([this._cacheDir, 'quota.json']);
        this._snapshot = readJson(this._cachePath, null);
        if (!this._snapshot || !Array.isArray(this._snapshot.windows) || !Array.isArray(this._snapshot.buckets))
            this._snapshot = null;
        this._button = new PanelMenu.Button(0.0, `${serviceName(this._config, this._snapshot)} remaining allowance and reset time`, false);
        this._box = new St.BoxLayout({style_class: 'codex-battery-box'});
        this._button.add_child(this._box);
        this._menuSignal = this._button.menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._buildMenu();
        });
        Main.panel.addToStatusArea(Me.metadata.uuid, this._button, 0, 'right');
        this._buildPanel();
        this._buildMenu();
        this._tickTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 15, () => {
            this._renderPanel();
            if (this._button.menu.isOpen)
                this._updateMenuText();
            return GLib.SOURCE_CONTINUE;
        });
        const interval = Number.isFinite(this._config.poll_seconds) ? this._config.poll_seconds : 120;
        this._pollSeconds = Math.max(60, Math.min(3600, Math.round(interval)));
        this._pollTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, this._pollSeconds, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
        this._refresh();
    }

    _isStale() {
        return Boolean(this._error) || !this._snapshot ||
            !Model.finite(this._snapshot.updatedAt) ||
            Date.now() / 1000 - this._snapshot.updatedAt > Math.max(300, (this._pollSeconds || 120) * 2.5);
    }

    _buildPanel() {
        this._box.destroy_all_children();
        this._brand = new St.Label({text: panelLabel(this._config, this._snapshot), y_align: Clutter.ActorAlign.CENTER,
            style_class: 'codex-battery-brand'});
        this._box.add_child(this._brand);
        this._gauges = [];
        const windows = this._snapshot && this._snapshot.windows.length ? this._snapshot.windows : [{}];
        for (const window of windows.slice(0, 2)) {
            const box = new St.BoxLayout({style_class: 'codex-battery-gauge-box'});
            const area = new St.DrawingArea({style_class: 'codex-battery-gauge',
                y_align: Clutter.ActorAlign.CENTER});
            const countdown = new St.Label({y_align: Clutter.ActorAlign.CENTER,
                style_class: 'codex-battery-countdown'});
            const item = {window, area, countdown, state: Model.visualState(window, Date.now() / 1000, this._isStale())};
            area.connect('repaint', () => paintGauge(area, item.state));
            box.add_child(area);
            box.add_child(countdown);
            this._box.add_child(box);
            this._gauges.push(item);
        }
        this._warning = new St.Label({text: '!', y_align: Clutter.ActorAlign.CENTER,
            style_class: 'codex-battery-warning'});
        this._box.add_child(this._warning);
        this._renderPanel();
    }

    _renderPanel() {
        const now = Date.now() / 1000;
        const stale = this._isStale();
        const names = [];
        let expired = false;
        for (const item of this._gauges) {
            item.state = Model.visualState(item.window, now, stale);
            expired = expired || item.state.expired;
            item.area.queue_repaint();
            item.countdown.visible = this._config.show_numbers === true;
            const value = Model.finite(item.window.remainingPercent) ? `${Math.round(item.window.remainingPercent)}%` : '?';
            item.countdown.text = `${value}  ↻ ${item.state.countdown}`;
            names.push(`${Model.windowName(item.window)}: ${value} remaining; reset ${item.state.countdown}`);
        }
        const blocked = this._snapshot && (this._snapshot.ordinaryUsageAllowed === false || this._snapshot.spendControlReached === true);
        this._warning.visible = stale || expired || Boolean(blocked);
        this._button.accessible_name = `${serviceName(this._config, this._snapshot)}. ${names.join('. ')}.${stale ? ' Last known data, refresh unavailable.' : ''}${expired ? ' Reset awaiting confirmation.' : ''}`;
    }

    _addText(label, detail = false) {
        const item = new PopupMenu.PopupMenuItem(label, {reactive: false});
        if (detail)
            item.label.add_style_class_name('codex-battery-menu-detail');
        this._button.menu.addMenuItem(item);
        return item.label;
    }

    _addWindowRow(destination, window) {
        const item = new PopupMenu.PopupMenuItem('', {reactive: false});
        item.label.add_style_class_name('codex-battery-menu-row');
        destination.addMenuItem(item);
        this._menuRows.push({window, label: item.label});
    }

    _addBucketHeading(label) {
        const item = new PopupMenu.PopupMenuItem(label, {reactive: false});
        item.label.add_style_class_name('codex-battery-menu-bucket');
        this._button.menu.addMenuItem(item);
    }

    _buildMenu() {
        const menu = this._button.menu;
        menu.removeAll();
        this._menuRows = [];
        const currentService = serviceName(this._config, this._snapshot);
        this._addText(`${currentService} Usagebar`).add_style_class_name('codex-battery-menu-heading');
        if (this._snapshot) {
            const meta = [this._snapshot.plan ? `Plan ${this._snapshot.plan}` : '', this._snapshot.status || '']
                .filter(text => text.length)
                .join('  ·  ');
            if (meta)
                this._addText(meta, true);
            if (this._snapshot.ordinaryUsageAllowed === false)
                this._addText('Included usage is currently blocked by the backend.');
            if (this._snapshot.spendControlReached === true)
                this._addText('An account spend limit has been reached.');
            this._addText('Window         Left     Reset       Local', true)
                .add_style_class_name('codex-battery-menu-column-head');
            // Show all reported pools on the first click; general quota stays first.
            const primaryBucketId = this._snapshot.primaryBucketId || providerId(this._config, this._snapshot);
            for (const bucket of Model.menuBuckets(this._snapshot.buckets, primaryBucketId)) {
                this._addBucketHeading(bucket.id === primaryBucketId ? `${currentService} general` : bucket.name);
                for (const window of bucket.windows) {
                    this._addWindowRow(menu, window);
                }
            }
            if (!this._snapshot.windows.length)
                this._addText(`General ${currentService} quota not reported; allowance is unknown.`);
            if (this._snapshot.note)
                this._addText(this._snapshot.note, true);
        } else {
            this._addText('No usage snapshot yet.');
        }
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._statusLabel = this._addText('', true);
        this._errorLabel = this._addText('', true);
        menu.addAction('Refresh now', () => this._refresh());
        const numbers = new PopupMenu.PopupSwitchMenuItem('Show percentages and countdowns', this._config.show_numbers === true);
        numbers.connect('toggled', (_item, state) => {
            this._config.show_numbers = state;
            try {
                writeJson(this._configPath, this._config);
            } catch (_) {
                this._error = 'Could not save display preference.';
            }
            this._renderPanel();
        });
        menu.addMenuItem(numbers);
        this._addText('Read-only usage check; no coding task is started.', true);
        this._updateMenuText();
    }

    _updateMenuText() {
        const now = Date.now() / 1000;
        for (const row of this._menuRows || []) {
            const w = row.window;
            const value = Model.finite(w.remainingPercent) ? `${Math.round(w.remainingPercent)}%` : 'Unknown';
            const state = Model.visualState(w, now, this._isStale());
            const reset = state.expired ? 'pending' : state.countdown;
            const stale = state.dim ? '*' : ' ';
            row.label.text = `${Model.windowName(w).padEnd(12)} ${value.padStart(7)} ${reset.padStart(9)}   ${resetStamp(w)}${stale}`;
        }
        if (this._statusLabel) {
            const age = this._snapshot && Model.finite(this._snapshot.updatedAt) ? Math.max(0, Math.floor((now - this._snapshot.updatedAt) / 60)) : null;
            this._statusLabel.text = this._process ? 'Refreshing…' : age === null ? 'No successful refresh yet' : `Last successful refresh: ${age < 1 ? 'less than a minute ago' : `${age} min ago`}`;
        }
        if (this._errorLabel) {
            this._errorLabel.text = this._error;
            this._errorLabel.visible = Boolean(this._error);
        }
    }

    _refresh() {
        if (!this._alive || this._process)
            return;
        try {
            this._cancellable = new Gio.Cancellable();
            const worker = new Gio.Subprocess({
                argv: ['/usr/bin/python3', GLib.build_filenamev([Me.path, 'quota.py']), '--config', this._configPath],
                flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            });
            worker.init(null);
            this._process = worker;
            this._updateMenuText();
            worker.communicate_utf8_async(null, this._cancellable, (proc, result) => {
                if (!this._alive || this._process !== proc)
                    return;
                this._process = null;
                this._cancellable = null;
                try {
                    const [, output] = proc.communicate_utf8_finish(result);
                    if (!output || output.length > 128 * 1024)
                        throw new Error('Usagebar helper returned no usable data. Re-run install.sh.');
                    const data = JSON.parse(output);
                    if (!data.ok)
                        throw new Error(data.error || 'Usage check failed.');
                    if (!Array.isArray(data.windows) || !Array.isArray(data.buckets))
                        throw new Error('Usage response format was not recognized.');
                    this._snapshot = data;
                    this._error = '';
                    try {
                        writeJson(this._cachePath, data);
                    } catch (_) {
                        // Display live data even when a cache cannot be saved.
                    }
                } catch (error) {
                    this._error = String(error.message || error);
                }
                this._buildPanel();
                this._buildMenu();
            });
        } catch (_) {
            this._process = null;
            this._cancellable = null;
            this._error = 'Could not start the Usagebar helper. Re-run install.sh.';
            this._renderPanel();
            this._updateMenuText();
        }
    }

    disable() {
        this._alive = false;
        for (const timer of [this._tickTimer, this._pollTimer]) {
            if (timer)
                GLib.source_remove(timer);
        }
        this._tickTimer = this._pollTimer = 0;
        if (this._process) {
            try {
                this._process.send_signal(15);
            } catch (_) {
                // Worker may already have exited.
            }
        }
        if (this._cancellable)
            this._cancellable.cancel();
        this._process = this._cancellable = null;
        if (this._button) {
            if (this._menuSignal)
                this._button.menu.disconnect(this._menuSignal);
            this._button.destroy();
        }
        this._button = null;
        this._gauges = this._menuRows = [];
        this._snapshot = null;
    }
}

function init() {
    return new Usagebar();
}
