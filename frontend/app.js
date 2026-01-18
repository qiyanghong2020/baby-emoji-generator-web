const form = document.getElementById("uploadForm");
const fileInput = document.getElementById("fileInput");
const promptInput = document.getElementById("promptInput");
const promptCounter = document.getElementById("promptCounter");
const submitBtn = document.getElementById("submitBtn");
const statusEl = document.getElementById("status");
const grid = document.getElementById("grid");
const tips = document.getElementById("tips");
const analysisEl = document.getElementById("analysis");
const captionStatusEl = document.getElementById("captionStatus");
const previewWrap = document.getElementById("previewWrap");
const previewImg = document.getElementById("previewImg");
const previewMeta = document.getElementById("previewMeta");

let previewObjectUrl = null;

function setStatus(text) {
  statusEl.textContent = text || "";
}

function setAnalysis(text) {
  analysisEl.textContent = text || "";
}

function setCaptionStatus(html) {
  if (!captionStatusEl) return;
  captionStatusEl.innerHTML = html || "";
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setTips(items) {
  if (!items || items.length === 0) {
    tips.innerHTML = "";
    return;
  }
  const li = items.map((t) => `<li>${escapeHtml(t)}</li>`).join("");
  tips.innerHTML = `<div>补拍建议：</div><ul>${li}</ul>`;
}

function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}

async function getImageDimensions(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const out = { w: img.naturalWidth || 0, h: img.naturalHeight || 0 };
      URL.revokeObjectURL(url);
      resolve(out);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve({ w: 0, h: 0 });
    };
    img.src = url;
  });
}

async function showPreview(file) {
  if (!file) {
    if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
    previewObjectUrl = null;
    previewWrap.classList.add("hidden");
    previewImg.removeAttribute("src");
    previewMeta.textContent = "";
    return;
  }

  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = URL.createObjectURL(file);
  previewImg.src = previewObjectUrl;
  previewWrap.classList.remove("hidden");

  const dims = await getImageDimensions(file);
  const dimText = dims.w && dims.h ? `${dims.w}×${dims.h}` : "尺寸未知";
  previewMeta.textContent = `${file.name} · ${formatBytes(file.size)} · ${dimText}`;
}

function renderResults(results) {
  grid.innerHTML = "";
  (results || []).forEach((r, idx) => {
    const url = r.url;
    const caption = r.caption || "";
    const filename = `baby_meme_${idx + 1}.png`;
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <img src="${escapeHtml(url)}" alt="meme ${idx + 1}" loading="lazy" />
      <div class="meta">
        <div class="caption">${escapeHtml(caption)}</div>
        <div class="actions">
          <a href="${escapeHtml(url)}" download="${filename}">下载</a>
        </div>
      </div>
    `;
    grid.appendChild(item);
  });
}

fileInput.addEventListener("change", async () => {
  const file = fileInput.files && fileInput.files[0];
  await showPreview(file);
  if (file) setStatus(`已选择：${file.name}`);
  setAnalysis("");
  setCaptionStatus("");
});

function updatePromptCounter() {
  if (!promptInput || !promptCounter) return;
  const v = promptInput.value || "";
  promptCounter.textContent = `${v.length}/240`;
}

if (promptInput) {
  promptInput.addEventListener("input", updatePromptCounter);
  updatePromptCounter();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = fileInput.files && fileInput.files[0];
  if (!file) return;

  const userPrompt = (promptInput && promptInput.value ? String(promptInput.value) : "").trim();

  submitBtn.disabled = true;
  await showPreview(file);
  setStatus(`已上传：${file.name}，生成中…（通常 5-15 秒，取决于网络与模型）`);
  setAnalysis("");
  setCaptionStatus("");
  setTips([]);
  renderResults([]);

  try {
    const fd = new FormData();
    fd.append("file", file, file.name);
    if (userPrompt) fd.append("prompt", userPrompt);
    const resp = await fetch("/upload", { method: "POST", body: fd });
    const data = await resp.json();

    if (!resp.ok) {
      setStatus(`失败：${data.message || data.error || resp.status}`);
      submitBtn.disabled = false;
      return;
    }

    const label = data.expression_label ? `（表情：${data.expression_label}）` : "";
    const fallback = data.fallback_used ? "已启用回退" : "AI 规划已生效";
    const reason = data.fallback_used && data.fallback_reason ? `：${data.fallback_reason}` : "";
    const aiStatus = data.used_ai ? "AI=成功" : data.ai_attempted ? "AI=失败" : "AI=未启用";
    const stage = !data.used_ai && data.ai_error_stage ? `/${data.ai_error_stage}` : "";
    const calls = typeof data.ai_calls === "number" && data.ai_calls > 0 ? `（调用${data.ai_calls}次）` : "";
    let promptInfo = "";
    if (userPrompt) {
      if (data.user_prompt_status === "ok") promptInfo = "（提示词已生效）";
      else if (data.user_prompt_status && data.user_prompt_status !== "empty") promptInfo = "（提示词已忽略：不合规/过长）";
    }
    setStatus(`${fallback}${label}${reason}（${aiStatus}${stage}${calls}）${promptInfo}`);

    const aligned = Boolean(data.captions_aligned_to_crops);
    const source = data.captions_source || "";
    const badgeClass = aligned ? "badge good" : "badge warn";
    const badgeText = aligned ? "配文对齐最终特写：是" : "配文对齐最终特写：否";
    const sourceText = source ? `来源：${escapeHtml(source)}` : "";
    const errText = !aligned && data.captions_ai_error ? `原因：${escapeHtml(data.captions_ai_error)}` : "";
    const capDebug =
      !aligned && data.captions_debug_url
        ? `<a class="debugLink" href="${escapeHtml(data.captions_debug_url)}" target="_blank" rel="noreferrer">查看配文调试</a>`
        : "";
    const planDebug =
      !data.used_ai && data.ai_debug_url
        ? `<a class="debugLink" href="${escapeHtml(data.ai_debug_url)}" target="_blank" rel="noreferrer">查看裁剪调试</a>`
        : "";
    const extra = [sourceText, errText, capDebug, planDebug].filter(Boolean).join(" · ");
    setCaptionStatus(
      `<span class="${badgeClass}">${badgeText}</span>` +
        (extra ? `<span class="badgeText">${extra}</span>` : "")
    );
    setAnalysis(data.expression_notes ? `识别说明：${data.expression_notes}` : "");
    setTips(data.suggestions || []);
    renderResults(data.results || []);
  } catch (err) {
    setStatus(`失败：${err && err.message ? err.message : String(err)}`);
    setAnalysis("");
    setCaptionStatus("");
  } finally {
    submitBtn.disabled = false;
  }
});
