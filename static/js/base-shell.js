function getCsrfToken() {
    const match = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
}

async function logout() {
    try {
        await fetch("/logout", {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "X-CSRF-Token": getCsrfToken(),
            },
        });
    } catch (error) {
        console.warn("Logout failed:", error);
    } finally {
        window.location.href = "/login";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const logoutButton = document.getElementById("baseLogoutBtn");
    if (!logoutButton) {
        return;
    }

    logoutButton.addEventListener("click", () => {
        logout();
    });
});
