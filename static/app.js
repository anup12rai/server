
const wifiForm = document.getElementById("wifiForm");

const adminToken = document.getElementById("adminToken");
const ssidInput = document.getElementById("ssid");
const passwordInput = document.getElementById("password");

const saveButton = document.getElementById("saveButton");
const buttonText = document.getElementById("buttonText");

const message = document.getElementById("message");

const togglePassword = document.getElementById("togglePassword");
const refreshButton = document.getElementById("refreshButton");


// Show and hide password
togglePassword.addEventListener("click", () => {

    const hidden = passwordInput.type === "password";

    passwordInput.type = hidden ? "text" : "password";

    togglePassword.textContent = hidden ? "Hide" : "Show";

});


// Display message
function showMessage(text, type) {

    message.textContent = text;

    message.className = "message " + type;

}


// Submit Wi-Fi configuration
wifiForm.addEventListener("submit", async (event) => {

    event.preventDefault();

    const token = adminToken.value.trim();
    const ssid = ssidInput.value.trim();
    const password = passwordInput.value;

    if (!token || !ssid || !password) {

        showMessage("Please complete all fields.", "error");

        return;
    }

    saveButton.disabled = true;

    buttonText.textContent = "Saving...";

    try {

        const response = await fetch("/api/admin/wifi", {

            method: "POST",

            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },

            body: JSON.stringify({
                ssid: ssid,
                password: password
            })

        });

        const result = await response.json();

        if (!response.ok) {

            throw new Error(result.error || "Unable to save configuration.");

        }

        showMessage(
            "Wi-Fi configuration saved. Waiting for ESP8266...",
            "success"
        );

        passwordInput.value = "";

        loadStatus();

    } catch (error) {

        showMessage(error.message, "error");

    } finally {

        saveButton.disabled = false;

        buttonText.textContent = "Save & Connect";

    }

});


// Check device status
async function loadStatus() {

    const token = adminToken.value.trim();

    if (!token) return;

    try {

        const response = await fetch("/api/admin/status", {

            headers: {
                "Authorization": "Bearer " + token
            }

        });

        if (!response.ok) {

            throw new Error("Unable to authenticate or load status.");

        }

        const data = await response.json();

        document.getElementById("currentSSID").textContent =
            data.ssid || "Not configured";

        document.getElementById("version").textContent =
            data.version;

        document.getElementById("lastSeen").textContent =
            data.last_seen
                ? new Date(data.last_seen).toLocaleString()
                : "Not available";

        const statusBox = document.getElementById("deviceStatus");

        const statusText = document.getElementById("statusText");

        const description = document.getElementById("statusDescription");

        statusBox.className = "device-status";

        if (data.status === "connected") {

            statusBox.classList.add("online");

            statusText.textContent = "Connected";

            description.textContent = "ESP8266 connected successfully.";

        } else if (data.status === "failed") {

            statusBox.classList.add("offline");

            statusText.textContent = "Connection Failed";

            description.textContent = "Check the Wi-Fi credentials.";

        } else {

            statusText.textContent = "Waiting";

            description.textContent = "Waiting for ESP8266 response.";

        }

    } catch (error) {

        document.getElementById("statusText").textContent = "Unavailable";

        document.getElementById("statusDescription").textContent =
            error.message;

    }

}


// Manual refresh
refreshButton.addEventListener("click", loadStatus);


// Automatic refresh every 15 seconds
setInterval(loadStatus, 15000);
