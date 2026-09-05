const state = { contract: false, invoice: false, shipments: false };

function fmtMoney(n) {
  return "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function setStatus(key, ok, message, needsReview) {
  const el = document.getElementById(`status-${key}`);
  el.querySelector(".status-text").textContent = message;
  const cls = !ok ? "error" : needsReview ? "warn" : "ok";
  el.className = "status " + cls;
  state[key] = ok;
  updateAuditButton();
}

function updateAuditButton() {
  const btn = document.getElementById("btn-audit");
  btn.disabled = !(state.contract && state.invoice && state.shipments);
}

async function uploadFile(key, endpoint, fieldMessage) {
  const input = document.getElementById(`file-${key}`);
  const file = input.files[0];
  if (!file) return;

  const el = document.getElementById(`status-${key}`);
  el.querySelector(".status-text").textContent = "Uploading...";
  el.className = "status";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(endpoint, { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) {
      setStatus(key, false, data.detail || "Upload failed");
      return;
    }
    setStatus(key, true, fieldMessage(data), data.needs_review_count > 0);
  } catch (err) {
    setStatus(key, false, "Upload failed: " + err.message);
  }
}

const UPLOAD_CONFIG = {
  contract: {
    endpoint: "/api/upload/contract",
    message: (d) => d.message || `Loaded ${d.rate_cards_found} rate(s), ${d.accessorial_caps_found} accessorial cap(s)`,
  },
  invoice: {
    endpoint: "/api/upload/invoice",
    message: (d) => d.message || `Loaded ${d.line_items_found} line item(s)`,
  },
  shipments: { endpoint: "/api/upload/shipments", message: (d) => `Loaded ${d.shipments_found} shipment(s)` },
};

for (const key of Object.keys(UPLOAD_CONFIG)) {
  const input = document.getElementById(`file-${key}`);
  const card = document.getElementById(`card-${key}`);
  const cfg = UPLOAD_CONFIG[key];

  input.addEventListener("change", () => uploadFile(key, cfg.endpoint, cfg.message));

  card.addEventListener("dragover", (e) => {
    e.preventDefault();
    card.classList.add("dragover");
  });
  card.addEventListener("dragleave", () => card.classList.remove("dragover"));
  card.addEventListener("drop", (e) => {
    e.preventDefault();
    card.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      uploadFile(key, cfg.endpoint, cfg.message);
    }
  });
}

document.getElementById("btn-audit").addEventListener("click", async () => {
  const errEl = document.getElementById("audit-error");
  errEl.textContent = "";
  const btn = document.getElementById("btn-audit");
  btn.disabled = true;
  const label = btn.lastChild;
  const originalLabel = label.textContent;
  label.textContent = " Auditing...";

  try {
    const res = await fetch("/api/audit", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.detail || "Audit failed";
      return;
    }
    renderResults(data);
  } catch (err) {
    errEl.textContent = "Audit failed: " + err.message;
  } finally {
    btn.disabled = false;
    label.textContent = originalLabel;
  }
});

function renderResults(audit) {
  document.getElementById("results").classList.remove("hidden");
  document.getElementById("stat-billed").textContent = fmtMoney(audit.total_billed);
  document.getElementById("stat-expected").textContent = fmtMoney(audit.total_expected);
  document.getElementById("stat-overcharge").textContent = fmtMoney(audit.total_overcharge);

  const metaParts = [
    `${audit.shipments_audited} shipment(s) audited`,
    `${audit.shipments_with_discrepancies} with discrepancies`,
  ];
  if (audit.unmatched_shipment_ids.length) {
    metaParts.push(`${audit.unmatched_shipment_ids.length} unmatched (no shipment/rate record): ${audit.unmatched_shipment_ids.join(", ")}`);
  }
  document.getElementById("stat-meta").textContent = metaParts.join(" • ");

  const tbody = document.getElementById("discrepancy-rows");
  tbody.innerHTML = "";
  for (const d of audit.discrepancies) {
    const tr = document.createElement("tr");
    if (d.needs_review) tr.classList.add("needs-review");
    const reviewBadge = d.needs_review ? `<span class="review-badge">Needs review</span>` : "";
    tr.innerHTML = `
      <td><span class="shipment-id">${d.shipment_id}</span><br/><span class="sub">${d.invoice_number}</span></td>
      <td>${d.lane}<br/><span class="sub">${d.service_level}</span></td>
      <td>${reviewBadge}${d.reason}</td>
      <td class="amount">${fmtMoney(d.billed_amount)}</td>
      <td class="amount">${fmtMoney(d.expected_amount)}</td>
      <td class="amount overcharge">${fmtMoney(d.overcharge_amount)}</td>
      <td class="evidence">
        <div><b>Contract:</b> ${d.contract_evidence}</div>
        <div><b>Invoice:</b> ${d.invoice_evidence}</div>
      </td>
    `;
    tbody.appendChild(tr);
  }

  document.getElementById("results").scrollIntoView({ behavior: "smooth" });
}
