function getCookieValue(cookieName) {
    const escapedName = String(cookieName || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = document.cookie.match(new RegExp(`(?:^|; )${escapedName}=([^;]+)`));
    return match ? decodeURIComponent(match[1]) : "";
}

async function logout(logoutPath, csrfCookieName, redirectPath) {
    try {
        await fetch(logoutPath, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "X-CSRF-Token": getCookieValue(csrfCookieName),
            },
        });
    } catch (error) {
        console.warn("Logout failed:", error);
    } finally {
        window.location.href = redirectPath;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const logoutButton = document.getElementById("baseLogoutBtn");
    if (!logoutButton) {
        return;
    }

    logoutButton.addEventListener("click", () => {
        logout(
            logoutButton.dataset.logoutPath || "/logout",
            logoutButton.dataset.csrfCookieName || "csrf_token",
            logoutButton.dataset.logoutRedirect || "/login",
        );
    });
});
