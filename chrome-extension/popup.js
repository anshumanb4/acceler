let people = [];
let sourceUrl = "";

const loadingEl = document.getElementById("loading");
const errorEl = document.getElementById("error");
const emptyEl = document.getElementById("empty");
const resultsEl = document.getElementById("results");
const successEl = document.getElementById("success");
const peopleListEl = document.getElementById("people-list");
const countEl = document.getElementById("count");
const submitBtn = document.getElementById("submit-btn");
const retryBtn = document.getElementById("retry-btn");
const settingsBtn = document.getElementById("settings-btn");

function showState(state) {
  [loadingEl, errorEl, emptyEl, resultsEl, successEl].forEach(el => el.classList.add("hidden"));
  state.classList.remove("hidden");
}

function showError(msg) {
  errorEl.querySelector(".error-text").textContent = msg;
  showState(errorEl);
}

function renderPeople() {
  peopleListEl.innerHTML = "";

  people.forEach((person, index) => {
    const card = document.createElement("div");
    card.className = "person-card";
    card.innerHTML = `
      <button class="delete-btn" data-index="${index}" title="Remove">&times;</button>
      <div class="field">
        <label>Name</label>
        <input type="text" data-index="${index}" data-field="name" value="${escapeAttr(person.name)}">
      </div>
      <div class="field">
        <label>Title</label>
        <input type="text" data-index="${index}" data-field="title" value="${escapeAttr(person.title)}">
      </div>
      <div class="field">
        <label>Organization</label>
        <input type="text" data-index="${index}" data-field="organization" value="${escapeAttr(person.organization)}">
      </div>
      <div class="field-row">
        <div class="field">
          <label>Email</label>
          <input type="email" data-index="${index}" data-field="email" value="${escapeAttr(person.email)}" placeholder="email@example.com">
        </div>
        <div class="field">
          <label>LinkedIn</label>
          <input type="url" data-index="${index}" data-field="linkedin" value="${escapeAttr(person.linkedin)}" placeholder="linkedin.com/in/...">
        </div>
      </div>
      <div class="field">
        <label>Context</label>
        <textarea data-index="${index}" data-field="context">${escapeHtml(person.context)}</textarea>
      </div>
    `;
    peopleListEl.appendChild(card);
  });

  countEl.textContent = `${people.length} ${people.length === 1 ? "person" : "people"}`;
}

function escapeAttr(str) {
  return (str || "").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeHtml(str) {
  return (str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Event: edit fields
peopleListEl.addEventListener("input", (e) => {
  const idx = parseInt(e.target.dataset.index, 10);
  const field = e.target.dataset.field;
  if (field && people[idx]) {
    people[idx][field] = e.target.value;
  }
});

// Event: delete
peopleListEl.addEventListener("click", (e) => {
  if (e.target.classList.contains("delete-btn")) {
    const idx = parseInt(e.target.dataset.index, 10);
    people.splice(idx, 1);
    if (people.length === 0) {
      showState(emptyEl);
    } else {
      renderPeople();
    }
  }
});

// Event: submit
submitBtn.addEventListener("click", async () => {
  if (people.length === 0) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "Submitting...";

  const forValue = document.querySelector('input[name="for-value"]:checked').value;

  chrome.runtime.sendMessage(
    { action: "submitToSupabase", data: { people, sourceUrl, forValue } },
    (response) => {
      if (response?.error) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit";
        showError(response.error);
      } else {
        const parts = [];
        if (response.insertedRows > 0) parts.push(`${response.insertedRows} added`);
        if (response.skippedRows > 0) parts.push(`${response.skippedRows} duplicates skipped`);
        successEl.querySelector(".success-text").textContent = parts.join(", ") || "Done.";
        showState(successEl);
      }
    }
  );
});

// Event: retry
retryBtn.addEventListener("click", () => {
  extractPeople();
});

// Event: settings
settingsBtn.addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

// Main extraction flow
function extractPeople() {
  showState(loadingEl);

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab?.id) {
      showError("No active tab found.");
      return;
    }

    chrome.tabs.sendMessage(tab.id, { action: "extractPageContent" }, (pageData) => {
      if (chrome.runtime.lastError) {
        showError("Could not access page content. Try refreshing the page.");
        return;
      }

      sourceUrl = pageData.url;

      chrome.runtime.sendMessage(
        { action: "extractPeople", data: pageData },
        (response) => {
          if (response?.error) {
            showError(response.error);
          } else if (!response?.people || response.people.length === 0) {
            showState(emptyEl);
          } else {
            people = response.people;
            renderPeople();
            showState(resultsEl);
          }
        }
      );
    });
  });
}

// Start extraction on popup open
extractPeople();
