"use strict";

(() => {
    const $ = (id) => document.getElementById(id);
    const stateUrl = new URL(document.body.dataset.stateUrl);
    const apiBase = new URL("../api/v1/", stateUrl);
    const page = document.body.dataset.page;
    const devicesUrl = new URL(document.body.dataset.devicesUrl);
    let state = JSON.parse($("dashboard-state").textContent);
    $("dashboard-state").remove();
    let selectedId = state.selected_id;
    let statusFilter = "all";
    let sortAscending = true;
    let authMode = "login";
    let addDeviceAfterAuth = false;
    let editingDeviceId = null;
    let deletingDeviceId = null;
    const busyDevices = new Set();
    let activityPage = 1;
    let activitySnapshot = null;
    let activityResult = null;
    let activitySequence = 0;
    let activityFilters = { limit: "25" };
    let activityOptionsKey = "";
    let activityLoading = false;
    let refreshInFlight = null;
    let pollTimer;
    let lastRefreshed = Date.now();

    function element(tag, className = "", text = "") {
        const node = document.createElement(tag);
        node.className = className;
        node.textContent = text;
        return node;
    }

    function icon(name, className = "") {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", `icon ${className}`);
        svg.setAttribute("aria-hidden", "true");
        const use = document.createElementNS(svg.namespaceURI, "use");
        use.setAttribute("href", `#icon-${name}`);
        svg.append(use);
        return svg;
    }

    function relativeTime(value) {
        if (!value) return "—";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "—";
        const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
        if (seconds < 5) return "Just now";
        if (seconds < 60) return `${seconds} sec ago`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
        return `${Math.floor(seconds / 86400)} days ago`;
    }

    function timeNode(value) {
        if (!value) return element("span", "unavailable", "—");
        const node = element("time", "", relativeTime(value));
        node.dateTime = value;
        node.title = new Date(value).toLocaleString();
        return node;
    }

    function statusBadge(status) {
        const badge = element("span", `status ${status}`);
        const dot = element("span", "status-dot");
        dot.setAttribute("aria-hidden", "true");
        badge.append(dot, document.createTextNode(status[0].toUpperCase() + status.slice(1)));
        return badge;
    }

    function filteredDevices() {
        const search = $("device-search").value.trim().toLocaleLowerCase();
        return state.devices.filter((device) =>
            (statusFilter === "all" || device.status === statusFilter) &&
            (!search || device.name.toLocaleLowerCase().includes(search) || device.host.toLocaleLowerCase().includes(search))
        ).sort((a, b) => (a.name.localeCompare(b.name) || a.id - b.id) * (sortAscending ? 1 : -1));
    }

    function renderDevices() {
        if (!$("device-rows")) return;
        const matching = filteredDevices();
        const devices = page === "overview" ? matching.slice(0, 6) : matching;
        const focusedId = document.activeElement?.dataset.select;
        const fragment = document.createDocumentFragment();
        for (const device of devices) {
            const row = element("tr", device.id === selectedId ? "selected" : "");
            row.dataset.deviceId = device.id;
            const heading = element("th");
            heading.scope = "row";
            const nameCell = element("div", "device-name-cell");
            const name = element("div");
            const button = element("button", "device-select", device.name);
            button.type = "button";
            button.dataset.select = device.id;
            button.setAttribute("aria-pressed", device.id === selectedId ? "true" : "false");
            name.append(button, element("span", "host", device.host));
            nameCell.append(icon("server", "device-icon"), name);
            heading.append(nameCell);
            const status = element("td");
            status.append(statusBadge(device.status));
            row.append(heading, status);
            if (page === "devices") {
                const visibility = element("td");
                if (state.can_manage) {
                    const toggle = element("button", `visibility-switch ${device.guest_visible ? "shared" : ""}`, device.guest_visible ? "Shared" : "Private");
                    toggle.type = "button";
                    toggle.dataset.visibility = device.id;
                    toggle.setAttribute("role", "switch");
                    toggle.setAttribute("aria-checked", String(device.guest_visible));
                    toggle.setAttribute("aria-label", `Share ${device.name} with guests`);
                    toggle.disabled = busyDevices.has(device.id);
                    visibility.append(toggle);
                } else visibility.textContent = "Shared";
                row.append(visibility, element("td", "", state.can_manage ? String(device.consecutive_failures) : "—"));
            } else {
                for (const metric of ["CPU", "Memory", "Uptime"]) {
                    const cell = element("td", "unavailable", "—");
                    cell.title = `${metric} is not collected yet`;
                    row.append(cell);
                }
            }
            const changed = element("td", "last-change");
            changed.append(timeNode(device.last_status_change));
            row.append(changed);
            if (page === "devices") {
                const actions = element("td");
                if (state.can_manage) {
                    const group = element("div", "row-actions");
                    for (const action of ["edit", "delete"]) {
                        const button = element("button", `text-button ${action === "delete" ? "delete-action" : ""}`, action === "edit" ? "Edit" : "Delete");
                        button.type = "button";
                        button.dataset[action] = device.id;
                        button.setAttribute("aria-label", `${action === "edit" ? "Edit" : "Delete"} ${device.name}`);
                        button.disabled = busyDevices.has(device.id);
                        group.append(button);
                    }
                    actions.append(group);
                } else actions.append(element("span", "muted", "Read only"));
                row.append(actions);
            }
            fragment.append(row);
        }
        $("device-rows").replaceChildren(fragment);
        if (focusedId) {
            const button = Array.from($("device-rows").querySelectorAll("[data-select]")).find((node) => node.dataset.select === focusedId);
            button?.focus({ preventScroll: true });
        }
        const empty = $("devices-empty");
        empty.hidden = devices.length > 0;
        empty.querySelector("h3").textContent = state.devices.length ? "No matching devices" : "No devices to display";
        empty.querySelector("p").textContent = state.devices.length
            ? "Try another search or status filter."
            : state.can_manage ? "Add your first device to start monitoring." : "Devices appear here when an administrator shares them with guests.";
        $("device-count").textContent = `${devices.length} of ${state.devices.length} devices${matching.length > devices.length ? " · Open Devices for the full list" : ""}`;
        $("visibility-label").textContent = state.can_manage ? "All registered devices" : "Guest-visible devices only";
        if ($("devices-mode-note")) $("devices-mode-note").textContent = state.can_manage
            ? "Manage device names, hosts and guest visibility. Select a device to inspect its history."
            : "Read-only view of shared devices. Log in as an admin to manage the inventory.";
    }

    function svgNode(name, attributes) {
        const node = document.createElementNS("http://www.w3.org/2000/svg", name);
        for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
        return node;
    }

    function historyChart(events) {
        const chronological = [...events].reverse();
        const chart = svgNode("svg", { viewBox: "0 0 620 145", class: "history-chart", role: "img", "aria-label": "Recorded device status transitions over time" });
        const y = { online: 28, unknown: 65, offline: 102 };
        for (const [status, position] of Object.entries(y)) {
            const label = svgNode("text", { x: 0, y: position + 4 });
            label.textContent = status[0].toUpperCase() + status.slice(1);
            chart.append(label, svgNode("line", { x1: 65, x2: 605, y1: position, y2: position, class: "grid-line" }));
        }
        const firstTime = new Date(chronological[0].occurred_at).getTime();
        const lastTime = new Date(chronological.at(-1).occurred_at).getTime();
        const positions = chronological.map((event, index) => ({
            x: lastTime === firstTime ? 65 + (chronological.length === 1 ? 270 : index * 540 / (chronological.length - 1))
                : 65 + (new Date(event.occurred_at).getTime() - firstTime) * 540 / (lastTime - firstTime),
            y: y[event.new_status],
            event,
        }));
        let path = `M ${positions[0].x} ${positions[0].y}`;
        for (const position of positions.slice(1)) path += ` H ${position.x} V ${position.y}`;
        chart.append(svgNode("path", { d: path, class: "history-line" }));
        for (const position of positions) {
            const point = svgNode("circle", { cx: position.x, cy: position.y, r: 4 });
            const title = svgNode("title", {});
            title.textContent = `${position.event.previous_status} → ${position.event.new_status} · ${new Date(position.event.occurred_at).toLocaleString()}`;
            point.append(title);
            chart.append(point);
        }
        return chart;
    }

    function renderSelected() {
        if (!$("selected-details")) return;
        const device = state.devices.find((item) => item.id === selectedId);
        const details = $("selected-details");
        details.replaceChildren();
        $("selected-name").textContent = device ? `· ${device.name}` : "· Select a device";
        if (!device) {
            details.append(element("p", "muted", "Select a device from the table to inspect its status and recent transitions."));
            return;
        }
        const facts = element("dl", "device-facts");
        const entries = [
            ["Host", device.host], ["Status", device.status],
            ["Consecutive failures", state.can_manage ? String(device.consecutive_failures) : "Admin only"],
            ["Guest visibility", state.can_manage ? (device.guest_visible ? "Shared" : "Private") : "Shared"],
            ["Last status change", device.last_status_change ? relativeTime(device.last_status_change) : "Not available"],
        ];
        for (const [label, value] of entries) {
            const fact = element("div");
            const content = element("dd");
            if (label === "Status") content.append(statusBadge(device.status));
            else content.textContent = value;
            fact.append(element("dt", "", label), content);
            facts.append(fact);
        }
        details.append(facts);
        const heading = element("div", "history-title");
        heading.append(element("h3", "", "Status history"), element("span", "", "Latest 50 transitions"));
        details.append(heading);
        if (!state.can_manage) {
            details.append(element("p", "muted", "Sign in as an admin to view recorded status transitions."));
        } else if (state.selected_id !== selectedId) {
            details.append(element("p", "muted", "Loading status history…"));
        } else if (!state.selected_events.length) {
            details.append(element("p", "muted", "No status transitions recorded yet for this device."));
        } else {
            details.append(historyChart(state.selected_events));
            const range = element("div", "history-range");
            range.append(timeNode(state.selected_events.at(-1).occurred_at), timeNode(state.selected_events[0].occurred_at));
            details.append(range);
            const list = element("ul", "history-list");
            for (const event of state.selected_events.slice(0, 5)) {
                const item = element("li");
                item.append(element("span", "", `${event.previous_status} → ${event.new_status}`), timeNode(event.occurred_at));
                list.append(item);
            }
            details.append(list);
        }
        details.append(element("p", "metrics-note", "CPU, memory, temperature, disk, uptime and ping latency are not collected yet. This chart shows recorded reachability transitions, not agent metrics."));
    }

    function renderActivity() {
        const list = $("activity-list");
        if (!list) return;
        list.replaceChildren();
        $("view-activity").hidden = !state.can_manage;
        if (!state.can_manage || !state.events.length) {
            list.append(element("p", "panel-placeholder", state.can_manage
                ? "No status transitions recorded yet. Run the monitor worker to start collecting history."
                : "Sign in as an admin to view device transition history."));
            return;
        }
        for (const event of state.events.slice(0, 3)) {
            const item = element("div", "activity-item");
            const text = element("div");
            const link = element("button", "device-select", event.name);
            link.type = "button";
            link.dataset.select = event.device_id;
            text.append(link, document.createTextNode(` became ${event.new_status}`), element("span", "host", event.host));
            item.append(icon(event.new_status === "unknown" ? "warning" : "ring", event.new_status), text, timeNode(event.occurred_at));
            list.append(item);
        }
    }

    function deviceLink(id) {
        const url = new URL(devicesUrl);
        url.searchParams.set("selected_id", id);
        url.hash = "device-details";
        return url;
    }

    function renderActivityAccess() {
        $("activity-access").hidden = state.can_manage;
        $("activity-content").hidden = !state.can_manage;
        $("activity-login").textContent = state.user ? "Change password" : state.setup_required ? "Set up owner" : "Log in";
        if (!state.can_manage) {
            activitySequence += 1;
            activityLoading = false;
            activityResult = null;
            activitySnapshot = null;
            activityOptionsKey = "";
            $("history-rows").replaceChildren();
            $("activity-device").replaceChildren(new Option("All devices", ""));
            $("activity-error").hidden = true;
            return;
        }
        const key = JSON.stringify(state.devices.map((device) => [device.id, device.name]));
        if (key !== activityOptionsKey) {
            const selected = $("activity-device").value;
            $("activity-device").replaceChildren(new Option("All devices", ""));
            for (const device of state.devices) $("activity-device").append(new Option(device.name, String(device.id)));
            if (selected && !state.devices.some((device) => String(device.id) === selected)) {
                $("activity-device").append(new Option("Device no longer available", selected));
            }
            $("activity-device").value = selected;
            activityOptionsKey = key;
        }
    }

    function renderHistory() {
        if (!activityResult || !state.can_manage) return;
        const fragment = document.createDocumentFragment();
        for (const event of activityResult.items) {
            const row = element("tr");
            const when = element("td");
            const time = timeNode(event.occurred_at);
            time.textContent = new Date(event.occurred_at).toLocaleString();
            when.append(time);
            const device = element("td");
            const link = element("a", "history-device-link", event.name);
            link.href = deviceLink(event.device_id);
            device.append(link);
            const transition = element("td", "history-transition");
            const change = element("div");
            const arrow = element("span", "transition-arrow", "→");
            arrow.setAttribute("aria-label", "to");
            change.append(statusBadge(event.previous_status), arrow, statusBadge(event.new_status));
            transition.append(change);
            row.append(when, device, element("td", "host-cell", event.host), transition);
            fragment.append(row);
        }
        $("history-rows").replaceChildren(fragment);
        $("history-empty").hidden = activityResult.items.length > 0;
        $("history-count").textContent = `${activityResult.total} matching transitions`;
        const pages = Math.max(1, Math.ceil(activityResult.total / activityResult.limit));
        $("history-page").textContent = `Page ${activityResult.page} of ${pages}`;
        $("history-previous").disabled = activityResult.page <= 1;
        $("history-next").disabled = activityResult.page >= pages;
    }

    async function loadActivity(latest = false) {
        if (page !== "activity" || !state.can_manage) return;
        const sequence = ++activitySequence;
        activityLoading = true;
        const url = new URL("admin/status-events", apiBase);
        for (const [key, value] of Object.entries(activityFilters)) {
            if (value !== "") url.searchParams.set(key, value);
        }
        url.searchParams.set("page", activityPage);
        if (!latest && activitySnapshot !== null) url.searchParams.set("snapshot_id", activitySnapshot);
        $("activity-loading").hidden = false;
        $("history-previous").disabled = true;
        $("history-next").disabled = true;
        try {
            const result = await request(url);
            if (sequence !== activitySequence || !state.can_manage) return;
            activityResult = result;
            activityPage = result.page;
            activitySnapshot = result.snapshot_id;
            $("activity-error").hidden = true;
            renderHistory();
        } catch (error) {
            if (sequence !== activitySequence) return;
            if (error.status === 401 || error.status === 403) {
                state.can_manage = false;
                renderActivityAccess();
                await refresh(true);
            } else {
                $("activity-error").textContent = `${error.message} The last loaded history is preserved; use Refresh latest to retry.`;
                $("activity-error").hidden = false;
                renderHistory();
            }
        } finally {
            if (sequence === activitySequence) {
                activityLoading = false;
                $("activity-loading").hidden = true;
            }
        }
    }

    async function toggleVisibility(id) {
        const device = state.devices.find((item) => item.id === id);
        if (!state.can_manage || !device || busyDevices.has(id)) return;
        busyDevices.add(id);
        renderDevices();
        try {
            const updated = await write(`admin/devices/${id}`, "PATCH", { guest_visible: !device.guest_visible });
            await refresh(true);
            notify(`${updated.name} is now ${updated.guest_visible ? "shared with guests" : "private"}.`);
        } catch (error) {
            notify(`Could not change visibility: ${error.message}`);
            if (error.status === 401 || error.status === 403) await refresh(true);
        } finally {
            busyDevices.delete(id);
            renderDevices();
        }
    }

    function render() {
        for (const node of document.querySelectorAll("[data-count]")) node.textContent = state.counts[node.dataset.count];
        $("account-identity").hidden = !state.user;
        $("account-name").textContent = state.user?.username || "";
        $("account-role").textContent = state.user ? state.user.role[0].toUpperCase() + state.user.role.slice(1) : "";
        $("logout-button").hidden = !state.user;
        $("auth-button").hidden = state.can_manage;
        $("auth-button").querySelector("span").textContent = state.user ? "Change password" : state.setup_required ? "Set up owner" : "Log in";
        if (!state.can_manage && $("device-dialog").open) $("device-dialog").close();
        if (!state.can_manage && $("delete-dialog").open) $("delete-dialog").close();
        renderDevices();
        renderSelected();
        renderActivity();
        if (page === "activity") {
            renderActivityAccess();
            if (state.can_manage && !activityLoading) loadActivity(activityPage === 1);
        }
        if (addDeviceAfterAuth && state.can_manage && !$("auth-dialog").open) {
            addDeviceAfterAuth = false;
            openDeviceForm();
        }
    }

    function errorMessage(payload, fallback) {
        if (typeof payload?.detail === "string") return payload.detail;
        if (Array.isArray(payload?.detail)) return payload.detail.map((error) => `${error.loc.at(-1)}: ${error.msg}`).join(". ");
        return fallback;
    }

    async function request(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 12000);
        try {
            const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, signal: controller.signal });
            const payload = response.status === 204 ? null : await response.json();
            if (!response.ok) {
                const error = new Error(errorMessage(payload, `Request failed (${response.status})`));
                error.status = response.status;
                throw error;
            }
            return payload;
        } catch (error) {
            if (error.name === "AbortError") throw new Error("Request timed out. Check the current state before retrying.");
            if (error instanceof TypeError) throw new Error("Cannot reach the server. Check your connection and try again.");
            throw error;
        } finally {
            clearTimeout(timer);
        }
    }

    function write(path, method, payload) {
        return request(new URL(path, apiBase), {
            method, headers: { "Content-Type": "application/json" },
            ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
        });
    }

    function post(path, payload) {
        return write(path, "POST", payload);
    }

    async function refresh(force = false) {
        const requestedId = selectedId;
        if (refreshInFlight && !force) return refreshInFlight;
        while (refreshInFlight) {
            await refreshInFlight;
        }
        const url = new URL(stateUrl);
        if (requestedId) url.searchParams.set("selected_id", requestedId);
        refreshInFlight = (async () => {
            try {
                const next = await request(url);
                state = next;
                if (selectedId === requestedId) selectedId = next.selected_id;
                lastRefreshed = Date.now();
                $("refresh-error").hidden = true;
                render();
                return true;
            } catch (error) {
                $("refresh-error").hidden = false;
                return false;
            }
        })();
        try { return await refreshInFlight; }
        finally { refreshInFlight = null; }
    }

    async function poll() {
        clearTimeout(pollTimer);
        await refresh();
        pollTimer = setTimeout(poll, 5000);
    }

    function notify(message) {
        $("action-message").textContent = message;
        $("action-message").hidden = false;
    }

    function openAuth() {
        const form = $("auth-form");
        form.reset();
        form.querySelector(".form-error").hidden = true;
        authMode = state.user?.must_change_password ? "change-password" : state.setup_required ? "setup" : "login";
        const changing = authMode === "change-password";
        const settingUp = authMode === "setup";
        $("auth-dialog-title").textContent = changing ? "Change password" : settingUp ? "Set up owner" : "Sign in";
        $("auth-dialog-description").textContent = changing ? "Choose a new password before managing devices." : settingUp ? "Create the first owner account using your setup token." : "Use your owner or admin account.";
        $("auth-submit").textContent = changing ? "Change password" : settingUp ? "Create owner" : "Sign in";
        $("auth-username-field").hidden = changing;
        $("auth-username").disabled = changing;
        $("auth-new-password-field").hidden = !changing;
        $("auth-new-password").disabled = !changing;
        $("auth-new-password").required = changing;
        $("auth-token-field").hidden = !settingUp;
        $("auth-token").disabled = !settingUp;
        $("auth-token").required = settingUp;
        $("auth-password-label").textContent = changing ? "Current password" : "Password";
        $("auth-password").minLength = settingUp ? 12 : 1;
        $("auth-password").autocomplete = settingUp ? "new-password" : "current-password";
        $("auth-dialog").showModal();
    }

    function openDeviceForm(device = null) {
        if (!state.can_manage) return;
        editingDeviceId = device?.id || null;
        $("device-form").reset();
        $("device-dialog-title").textContent = device ? "Edit device" : "Add device";
        $("device-dialog-description").textContent = device ? "Update the registered device configuration." : "Register a host for the monitoring worker.";
        $("device-submit-label").textContent = device ? "Save changes" : "Add device";
        $("device-form-hint").textContent = device ? "The monitor will use the saved host on its next cycle." : "New devices start as Unknown until the monitor establishes reachability.";
        if (device) {
            $("device-name").value = device.name;
            $("device-host").value = device.host;
            $("device-form").elements.guest_visible.checked = device.guest_visible;
        }
        $("device-form").querySelector(".form-error").hidden = true;
        $("device-dialog").showModal();
    }

    async function submitForm(form, operation) {
        const button = form.querySelector('button[type="submit"]');
        const error = form.querySelector(".form-error");
        button.disabled = true;
        error.hidden = true;
        try { await operation(new FormData(form)); }
        catch (exception) {
            error.textContent = exception.message;
            error.hidden = false;
        } finally { button.disabled = false; }
    }

    $("device-search")?.addEventListener("input", renderDevices);
    for (const button of document.querySelectorAll("[data-filter]")) {
        button.addEventListener("click", () => {
            statusFilter = button.dataset.filter;
            for (const tab of document.querySelectorAll("[data-filter]")) {
                const active = tab === button;
                tab.classList.toggle("active", active);
                tab.setAttribute("aria-pressed", String(active));
            }
            renderDevices();
        });
    }
    $("sort-name")?.addEventListener("click", () => {
        sortAscending = !sortAscending;
        $("sort-direction").textContent = sortAscending ? "▴" : "▾";
        $("sort-name").setAttribute("aria-label", `Sort devices by name ${sortAscending ? "descending" : "ascending"}`);
        renderDevices();
    });
    document.addEventListener("click", (event) => {
        const select = event.target.closest("[data-select]");
        if (select) {
            selectedId = Number(select.dataset.select);
            renderDevices();
            renderSelected();
            if (page === "devices") {
                const url = new URL(window.location.href);
                url.searchParams.set("selected_id", selectedId);
                window.history.replaceState(null, "", url);
            }
            refresh(true);
        }
        const edit = event.target.closest("[data-edit]");
        if (edit && state.can_manage) {
            const device = state.devices.find((item) => item.id === Number(edit.dataset.edit));
            if (device && !busyDevices.has(device.id)) openDeviceForm(device);
        }
        const visibility = event.target.closest("[data-visibility]");
        if (visibility && state.can_manage) toggleVisibility(Number(visibility.dataset.visibility));
        const remove = event.target.closest("[data-delete]");
        if (remove && state.can_manage) {
            const device = state.devices.find((item) => item.id === Number(remove.dataset.delete));
            if (device && !busyDevices.has(device.id)) {
                deletingDeviceId = device.id;
                $("delete-device-name").textContent = `${device.name} · ${device.host}`;
                $("delete-form").querySelector(".form-error").hidden = true;
                $("delete-dialog").showModal();
            }
        }
        const close = event.target.closest("[data-close]");
        if (close) {
            if (close.dataset.close === "auth-dialog") addDeviceAfterAuth = false;
            $(close.dataset.close).close();
        }
    });
    $("auth-button").addEventListener("click", () => {
        addDeviceAfterAuth = false;
        openAuth();
    });
    $("add-device-button").addEventListener("click", () => {
        if (state.can_manage) openDeviceForm();
        else {
            addDeviceAfterAuth = true;
            openAuth();
        }
    });
    $("device-form").addEventListener("submit", (event) => {
        event.preventDefault();
        submitForm(event.currentTarget, async (data) => {
            const name = data.get("name").trim();
            const host = data.get("host").trim();
            if (!name || !host) throw new Error("Enter a device name and host.");
            const editing = editingDeviceId;
            const payload = { name, host, guest_visible: data.has("guest_visible") };
            const created = editing
                ? await write(`admin/devices/${editing}`, "PATCH", payload)
                : await post("admin/devices", payload);
            selectedId = created.id;
            $("device-dialog").close();
            $("device-form").reset();
            if ($("device-search")) $("device-search").value = "";
            document.querySelector('[data-filter="all"]')?.click();
            await refresh(true);
            notify(editing ? `Updated ${created.name}.` : `Added ${created.name}. Its status starts as Unknown until the monitor checks it.`);
            if (page === "activity") {
                window.location.assign(deviceLink(created.id));
            }
        });
    });
    $("delete-form").addEventListener("submit", (event) => {
        event.preventDefault();
        submitForm(event.currentTarget, async () => {
            if (!state.can_manage || deletingDeviceId === null) throw new Error("Log in as an admin to delete a device.");
            const id = deletingDeviceId;
            await write(`admin/devices/${id}`, "DELETE");
            $("delete-dialog").close();
            deletingDeviceId = null;
            await refresh(true);
            notify("Device and its status history were deleted.");
        });
    });
    $("activity-login")?.addEventListener("click", () => {
        addDeviceAfterAuth = false;
        openAuth();
    });
    $("activity-filters")?.addEventListener("submit", (event) => {
        event.preventDefault();
        const filters = Object.fromEntries(new FormData(event.currentTarget));
        for (const key of ["start", "end"]) {
            if (filters[key]) filters[key] = new Date(filters[key]).toISOString();
        }
        if (filters.start && filters.end && new Date(filters.start) > new Date(filters.end)) {
            $("activity-error").textContent = "From must not be after To.";
            $("activity-error").hidden = false;
            return;
        }
        activityFilters = filters;
        activityPage = 1;
        activitySnapshot = null;
        loadActivity(true);
    });
    $("activity-clear")?.addEventListener("click", () => {
        $("activity-filters").reset();
        activityFilters = { limit: "25" };
        activityPage = 1;
        activitySnapshot = null;
        loadActivity(true);
    });
    $("activity-refresh")?.addEventListener("click", () => {
        activityPage = 1;
        activitySnapshot = null;
        loadActivity(true);
    });
    $("history-previous")?.addEventListener("click", () => {
        if (activityPage > 1) {
            activityPage -= 1;
            loadActivity();
        }
    });
    $("history-next")?.addEventListener("click", () => {
        activityPage += 1;
        loadActivity();
    });
    $("auth-form").addEventListener("submit", (event) => {
        event.preventDefault();
        submitForm(event.currentTarget, async (data) => {
            const payload = authMode === "change-password"
                ? { current_password: data.get("password"), new_password: data.get("new_password") }
                : { username: data.get("username").trim(), password: data.get("password") };
            if (authMode === "setup") payload.setup_token = data.get("setup_token");
            const user = await post(`auth/${authMode}`, payload);
            $("auth-dialog").close();
            $("auth-form").reset();
            state.user = { username: user.username, role: user.role, must_change_password: user.must_change_password };
            state.setup_required = false;
            await refresh(true);
            notify(user.must_change_password ? "Signed in. Change your temporary password to manage devices." : `Signed in as ${user.username}.`);
            if (user.must_change_password) openAuth();
        });
    });
    $("logout-button").addEventListener("click", async () => {
        const button = $("logout-button");
        button.disabled = true;
        try {
            await post("auth/logout", {});
            // Reload clears all previously loaded private device data from the page.
            window.location.reload();
        } catch (error) {
            if (error.status === 401) window.location.reload();
            else notify(`Could not sign out: ${error.message}`);
        } finally { button.disabled = false; }
    });
    for (const dialog of document.querySelectorAll("dialog")) {
        dialog.addEventListener("close", () => {
            // A successful temporary-password login immediately reopens this dialog.
            if (dialog.open) return;
            for (const input of dialog.querySelectorAll('input[type="password"]')) input.value = "";
        });
    }
    $("auth-dialog").addEventListener("cancel", () => { addDeviceAfterAuth = false; });
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) poll();
    });
    setInterval(() => {
        const seconds = Math.floor((Date.now() - lastRefreshed) / 1000);
        $("updated-label").textContent = seconds < 2 ? "Page just refreshed" : `Page refreshed ${seconds} seconds ago`;
    }, 1000);
    render();
    pollTimer = setTimeout(poll, 5000);
})();
