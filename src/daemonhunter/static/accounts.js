"use strict";

(() => {
    const $ = (id) => document.getElementById(id);
    const page = document.body.dataset.page;
    const apiBase = new URL("../api/v1/", document.body.dataset.stateUrl);
    let viewer = JSON.parse($("account-viewer").textContent);
    $("account-viewer").remove();
    let users = [];
    let usersLoaded = false;
    let usersLoading = false;
    let usersSequence = 0;
    let ownerBlocked = false;
    const busyUsers = new Set();
    let userMode = "create";
    let targetUser = null;
    let returnFocus = null;

    function notice(message, type = "success") {
        window.dispatchEvent(new CustomEvent("daemonhunter:notice", { detail: { message, type } }));
    }

    function refreshDashboard() {
        window.dispatchEvent(new Event("daemonhunter:refresh"));
    }

    function isOwner() {
        return viewer?.role === "owner" && !viewer.must_change_password && !ownerBlocked;
    }

    async function api(path, method = "GET", payload) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 12000);
        try {
            const response = await fetch(new URL(path, apiBase), {
                method, credentials: "same-origin", cache: "no-store", signal: controller.signal,
                headers: { "Content-Type": "application/json" },
                ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
            });
            const data = response.status === 204 ? null : await response.json().catch(() => null);
            if (!response.ok) {
                const detail = typeof data?.detail === "string" ? data.detail
                    : Array.isArray(data?.detail) ? data.detail.map((item) => `${item.loc.at(-1)}: ${item.msg}`).join(". ")
                        : `Request failed (${response.status})`;
                const error = new Error(detail);
                error.status = response.status;
                throw error;
            }
            return data;
        } catch (error) {
            if (error.name === "AbortError") throw new Error("Request timed out. Check the current state before retrying.");
            if (error instanceof TypeError) throw new Error("Cannot reach the server. Check your connection and try again.");
            throw error;
        } finally { clearTimeout(timer); }
    }

    function requestError(error) {
        if (error.status === 401) applyViewer(null);
        if (error.status === 403 && page === "users") {
            ownerBlocked = true;
            renderUsersAccess();
        }
        if (error.status === 401 || error.status === 403) refreshDashboard();
    }

    async function submit(form, operation) {
        const button = form.querySelector('button[type="submit"]');
        const error = form.querySelector(".form-error");
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        error.hidden = true;
        try { await operation(new FormData(form)); }
        catch (exception) {
            error.textContent = exception.message;
            error.hidden = false;
            requestError(exception);
        } finally {
            button.disabled = false;
            button.removeAttribute("aria-busy");
        }
    }

    function applyViewer(user) {
        const changedAccount = viewer?.username !== user?.username;
        viewer = user;
        ownerBlocked = false;
        if (page === "account") {
            $("account-access").hidden = !!viewer;
            $("account-content").hidden = !viewer;
            $("account-login").textContent = $("auth-button").textContent.trim();
            $("profile-username").textContent = viewer?.username || "";
            $("profile-role").textContent = viewer ? viewer.role[0].toUpperCase() + viewer.role.slice(1) : "";
            $("account-password-required").hidden = !viewer?.must_change_password;
            if (!viewer || changedAccount) $("account-password-form").reset();
            for (const input of $("account-password-form").querySelectorAll("input, button")) {
                input.disabled = !viewer || input.getAttribute("aria-busy") === "true";
            }
        } else {
            if (changedAccount) {
                usersSequence += 1;
                users = [];
                usersLoaded = false;
                usersLoading = false;
                $("user-rows").replaceChildren();
            }
            renderUsersAccess();
            if (isOwner() && !usersLoading) loadUsers();
        }
    }

    function renderUsersAccess() {
        const allowed = isOwner();
        $("users-access").hidden = allowed;
        $("users-content").hidden = !allowed;
        $("users-login").hidden = !!viewer && !viewer.must_change_password;
        $("users-login").textContent = $("auth-button").textContent.trim();
        $("users-access-message").textContent = viewer?.must_change_password
            ? "Change your temporary password before continuing. Only the owner can manage admin accounts."
            : viewer ? "Only the owner can manage admin accounts." : "Log in with the owner account to manage admins.";
        if (!allowed) {
            usersSequence += 1;
            users = [];
            usersLoaded = false;
            usersLoading = false;
            $("user-rows").replaceChildren();
            $("users-count").textContent = "Accounts";
            $("users-error").hidden = true;
            if ($("user-dialog").open) $("user-dialog").close();
            $("user-form").reset();
            setUsersBusy(false);
        }
    }

    function setUsersBusy(busy) {
        $("users-refreshing").classList.toggle("is-active", busy);
        $("users-refreshing").setAttribute("aria-hidden", String(!busy));
        $("users-loading").hidden = !busy || usersLoaded;
        $("users-results").setAttribute("aria-busy", String(busy));
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        node.className = className || "";
        node.textContent = text || "";
        return node;
    }

    function actionReference(node = document.activeElement) {
        if (node?.dataset.userAction) return { action: node.dataset.userAction, id: node.dataset.userId };
        if (node?.id === "add-admin-button") return { action: "create" };
        return null;
    }

    function restoreAction(reference) {
        const button = reference?.action === "create" ? $("add-admin-button")
            : reference ? Array.from(document.querySelectorAll("[data-user-action]")).find((node) =>
                node.dataset.userAction === reference.action && node.dataset.userId === reference.id) : null;
        if (button && !button.disabled && button.getClientRects().length) button.focus({ preventScroll: true });
        else if ($("add-admin-button").getClientRects().length) $("add-admin-button").focus({ preventScroll: true });
        else $("main").focus({ preventScroll: true });
    }

    function renderUsers() {
        if (!isOwner()) return;
        const focus = $("user-rows").contains(document.activeElement) ? actionReference() : null;
        const fragment = document.createDocumentFragment();
        for (const user of users) {
            const row = element("tr");
            row.dataset.userId = user.id;
            const name = element("th", "", user.username);
            name.scope = "row";
            row.append(name);
            for (const [label, value, color] of [
                ["Role", user.role === "owner" ? "Owner" : "Admin", ""],
                ["Account", user.active ? "Active" : "Disabled", user.active ? "online" : "offline"],
                ["Password", user.must_change_password ? "Change required" : "Set", user.must_change_password ? "unknown" : ""],
            ]) {
                const cell = element("td", color, value);
                cell.dataset.label = label;
                row.append(cell);
            }
            const actions = element("td", "user-actions-cell");
            actions.dataset.label = "Actions";
            if (user.role === "owner") actions.append(element("span", "user-protected", "Protected owner"));
            else {
                const group = element("div", "user-actions");
                for (const [action, label] of [["edit", "Rename"], ["active", user.active ? "Disable" : "Enable"], ["reset", "Reset password"], ["delete", "Delete"]]) {
                    const button = element("button", `text-button ${action === "delete" ? "delete-action" : ""}`, label);
                    button.type = "button";
                    button.dataset.userAction = action;
                    button.dataset.userId = user.id;
                    button.setAttribute("aria-label", `${label} ${user.username}`);
                    button.disabled = busyUsers.has(user.id);
                    group.append(button);
                }
                actions.append(group);
            }
            row.append(actions);
            fragment.append(row);
        }
        $("user-rows").replaceChildren(fragment);
        $("users-count").textContent = `${users.length} accounts`;
        if (focus && !document.querySelector("dialog[open]")) restoreAction(focus);
    }

    async function loadUsers(force = false) {
        if (!isOwner() || (usersLoading && !force)) return;
        const sequence = ++usersSequence;
        usersLoading = true;
        setUsersBusy(true);
        try {
            const result = await api("admin/users");
            if (sequence !== usersSequence || !isOwner()) return;
            users = result;
            usersLoaded = true;
            $("users-error").hidden = true;
            renderUsers();
        } catch (error) {
            if (sequence !== usersSequence) return;
            $("users-error").textContent = error.message;
            $("users-error").hidden = false;
            requestError(error);
        } finally {
            if (sequence === usersSequence) {
                usersLoading = false;
                setUsersBusy(false);
            }
        }
    }

    function openUserForm(mode, user = null) {
        if (!isOwner() || (user && (user.role === "owner" || busyUsers.has(user.id)))) return;
        returnFocus = actionReference();
        userMode = mode;
        targetUser = user;
        $("user-form").reset();
        $("user-form").querySelector(".form-error").hidden = true;
        const username = mode === "create" || mode === "edit";
        const password = mode === "create" || mode === "reset";
        $("admin-username-field").hidden = !username;
        $("admin-username").disabled = !username;
        $("admin-username").required = username;
        $("admin-username").value = user?.username || "";
        $("admin-password-field").hidden = !password;
        for (const input of $("admin-password-field").querySelectorAll("input")) {
            input.disabled = !password;
            input.required = password;
        }
        $("admin-password-hint").hidden = !password;
        const title = { create: "Add admin", edit: "Rename admin", reset: "Reset admin password", delete: "Delete admin?" }[mode];
        $("user-dialog-title").textContent = title;
        $("user-dialog-description").textContent = mode === "create" ? "Create an administrator with a temporary password."
            : mode === "edit" ? `Update the username for ${user.username}.`
                : mode === "reset" ? `Reset the password for ${user.username}. Existing sessions will be signed out.`
                    : `Permanently delete ${user.username}. Existing sessions will lose access. This cannot be undone.`;
        $("user-submit").textContent = { create: "Add admin", edit: "Save changes", reset: "Reset password", delete: "Delete admin" }[mode];
        $("user-submit").className = mode === "delete" ? "danger-button" : "primary-button";
        $("user-dialog").showModal();
    }

    async function toggleActive(user) {
        if (!isOwner() || user.role === "owner" || busyUsers.has(user.id)) return;
        const focus = actionReference();
        busyUsers.add(user.id);
        renderUsers();
        try {
            const result = await api(`admin/users/${user.id}`, "PATCH", { active: !user.active });
            await loadUsers(true);
            notice(`${result.username} is now ${result.active ? "enabled" : "disabled"}.`);
        } catch (error) {
            notice(`Could not update account: ${error.message}`, "error");
            requestError(error);
        } finally {
            busyUsers.delete(user.id);
            renderUsers();
            if (document.activeElement === document.body && !document.querySelector("dialog[open]")) restoreAction(focus);
        }
    }

    $("account-login")?.addEventListener("click", () => $("auth-button").click());
    $("users-login")?.addEventListener("click", () => $("auth-button").click());
    $("account-password-form")?.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        submit(form, async (data) => {
            if (!viewer) throw new Error("Log in to change your password.");
            if (data.get("new_password") !== data.get("confirm_password")) throw new Error("New passwords do not match.");
            const result = await api("auth/change-password", "POST", {
                current_password: data.get("current_password"), new_password: data.get("new_password"),
            });
            form.reset();
            applyViewer(result);
            refreshDashboard();
            notice("Password changed. Your other sessions were signed out; this session stays signed in.");
        });
    });
    $("add-admin-button")?.addEventListener("click", () => openUserForm("create"));
    $("user-rows")?.addEventListener("click", (event) => {
        const button = event.target.closest("[data-user-action]");
        if (!button || !isOwner()) return;
        const user = users.find((item) => item.id === Number(button.dataset.userId));
        if (!user) return;
        if (button.dataset.userAction === "active") toggleActive(user);
        else openUserForm(button.dataset.userAction, user);
    });
    $("user-form")?.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        submit(form, async (data) => {
            if (!isOwner()) throw new Error("Owner access required.");
            const mode = userMode;
            const target = targetUser;
            if (mode === "create" || mode === "reset") {
                if (data.get("temporary_password") !== data.get("confirm_password")) throw new Error("Temporary passwords do not match.");
            }
            if (mode === "create") await api("admin/users", "POST", { username: data.get("username").trim(), temporary_password: data.get("temporary_password") });
            else if (mode === "edit") await api(`admin/users/${target.id}`, "PATCH", { username: data.get("username").trim() });
            else if (mode === "reset") await api(`admin/users/${target.id}/reset-password`, "POST", { temporary_password: data.get("temporary_password") });
            else if (mode === "delete") await api(`admin/users/${target.id}`, "DELETE");
            $("user-dialog").close();
            form.reset();
            await loadUsers(true);
            notice({ create: "Admin created. They must change their temporary password at first login.", edit: "Admin username updated.", reset: "Password reset. The admin must change it at their next login.", delete: "Admin account deleted." }[mode]);
            refreshDashboard();
            if (document.activeElement === document.body) restoreAction(returnFocus);
        });
    });
    $("user-dialog")?.addEventListener("close", () => {
        if ($("user-dialog").open) return;
        $("user-form").reset();
        for (const input of $("user-form").querySelectorAll('input[type="password"]')) input.value = "";
        if (!document.querySelector("dialog[open]")) restoreAction(returnFocus);
    });
    window.addEventListener("daemonhunter:state", (event) => applyViewer(event.detail.user));
    applyViewer(viewer);
})();
