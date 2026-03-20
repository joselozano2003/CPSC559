async function realLogin(email, password, masterUrl) {
    const res = await fetch(`${masterUrl}/auth/login/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
        throw new Error(`Login failed: ${res.status}`);
    }

    return res.json();
}

async function handleLogin() {
    const master = document.getElementById('master-url').value.trim();
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const statusEl = document.getElementById('auth-status');
    const button = document.getElementById('btn-login');

    if (!master || !email || !password) {
        statusEl.textContent = 'Please fill in all fields.';
        statusEl.className = 'err';
        return;
    }

    button.disabled = true;

    try {
        const data = await realLogin(email, password, master);

        localStorage.setItem("accessToken", data.tokens.access);
        localStorage.setItem("refreshToken", data.tokens.refresh);
        localStorage.setItem("masterUrl", master);

        statusEl.textContent = `Logged in as ${data.user.email}`;
        statusEl.className = 'ok';

        window.location.href = "index.html";
    } catch (e) {
        statusEl.textContent = e.message;
        statusEl.className = 'err';
    } finally {
        button.disabled = false;
    }
}

document.getElementById("btn-login").addEventListener("click", handleLogin);

document.getElementById("password").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        handleLogin();
    }
});

window.addEventListener("DOMContentLoaded", () => {
    if (localStorage.getItem("refreshToken")) {
        window.location.href = "index.html";
    }
});
