const apiKeyInput = document.getElementById("apiKey");
const supabaseUrlInput = document.getElementById("supabaseUrl");
const supabaseAnonKeyInput = document.getElementById("supabaseAnonKey");
const saveBtn = document.getElementById("save-btn");
const statusEl = document.getElementById("status");

// Load saved settings
chrome.storage.sync.get(["apiKey", "supabaseUrl", "supabaseAnonKey"], (data) => {
  if (data.apiKey) apiKeyInput.value = data.apiKey;
  if (data.supabaseUrl) supabaseUrlInput.value = data.supabaseUrl;
  if (data.supabaseAnonKey) supabaseAnonKeyInput.value = data.supabaseAnonKey;
});

saveBtn.addEventListener("click", () => {
  const apiKey = apiKeyInput.value.trim();
  const supabaseUrl = supabaseUrlInput.value.trim();
  const supabaseAnonKey = supabaseAnonKeyInput.value.trim();

  if (!apiKey) {
    statusEl.textContent = "API key is required.";
    statusEl.className = "status error";
    return;
  }

  chrome.storage.sync.set({ apiKey, supabaseUrl, supabaseAnonKey }, () => {
    statusEl.textContent = "Settings saved.";
    statusEl.className = "status";
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  });
});
