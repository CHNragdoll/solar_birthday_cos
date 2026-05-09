const rowIdEl = document.getElementById("rowId");
const nameEl = document.getElementById("name");
const dateEl = document.getElementById("date");
const birthTimeEl = document.getElementById("birthTime");
const alarmDaysEl = document.getElementById("alarmDays");
const tagEl = document.getElementById("tag");
const noteEl = document.getElementById("note");
const rowsEl = document.getElementById("rows");
const statusEl = document.getElementById("status");
const metaEl = document.getElementById("meta");
const countEl = document.getElementById("count");
const emptyEl = document.getElementById("empty");
const tagFilterEl = document.getElementById("tagFilter");
const trashRowsEl = document.getElementById("trashRows");
const trashEmptyEl = document.getElementById("trashEmpty");
const trashCountEl = document.getElementById("trashCount");
const restoreAllBtn = document.getElementById("restoreAllBtn");
const defaultAlarmDaysEl = document.getElementById("defaultAlarmDays");
const saveDefaultAlarmBtn = document.getElementById("saveDefaultAlarmBtn");

let items = [];
let deletedItems = [];
let activeTagFilter = "all";

function nameWithTag(name, tag) {
  const t = tag || "生日";
  if (t === "生日") {
    return `${name}的生日`;
  }
  return name;
}

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function resetForm() {
  rowIdEl.value = "";
  nameEl.value = "";
  dateEl.value = "";
  birthTimeEl.value = "";
  alarmDaysEl.value = "";
  tagEl.value = "生日";
  noteEl.value = "";
  nameEl.focus();
}

function normalizeAlarmDaysText(value) {
  const raw = (value || "").trim();
  if (!raw) return "";
  if (raw === "-1") return "-1";
  const nums = raw.split(",").map((s) => s.trim()).filter(Boolean).map((s) => Number(s));
  const uniq = [...new Set(nums)].sort((a, b) => b - a);
  return uniq.join(",");
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, options);
  const ctype = (res.headers.get("content-type") || "").toLowerCase();
  if (!ctype.includes("application/json")) {
    throw new Error(`接口返回非 JSON：${url}`);
  }
  const data = await res.json();
  if (!data.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function renderRows() {
  rowsEl.innerHTML = "";
  const filtered = items.filter((item) => {
    if (activeTagFilter === "all") {
      return true;
    }
    return (item.tag || "生日") === activeTagFilter;
  });
  countEl.textContent = `${filtered.length} 条`;
  emptyEl.style.display = filtered.length ? "none" : "block";

  filtered.forEach((item) => {
    const tr = document.createElement("tr");
    const alarmText = item.alarm_days || "默认";
    tr.innerHTML = `
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td><div class="rowActions"></div></td>
    `;
    const tag = item.tag || "生日";
    tr.children[0].textContent = nameWithTag(item.name, tag);
    tr.children[1].textContent = tag;
    tr.children[2].textContent = item.date;
    tr.children[3].textContent = item.birth_time || "-";
    tr.children[4].textContent = item.lunar || "-";
    tr.children[5].textContent = item.zodiac || "-";
    tr.children[6].textContent = item.note || "-";
    tr.children[7].textContent = alarmText;

    const actions = tr.querySelector(".rowActions");
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.textContent = "编辑";
    editBtn.addEventListener("click", () => {
      rowIdEl.value = item.id;
      nameEl.value = item.name;
      dateEl.value = item.date;
      birthTimeEl.value = item.birth_time || "";
      alarmDaysEl.value = item.alarm_days || "";
      tagEl.value = item.tag || "生日";
      noteEl.value = item.note || "";
      nameEl.focus();
    });

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "danger";
    deleteBtn.textContent = "删除";
    deleteBtn.addEventListener("click", async () => {
      if (!confirm(`删除 ${item.name}？`)) {
        return;
      }
      try {
        await requestJson(`/api/birthdays/${item.id}`, { method: "DELETE" });
        setStatus("已删除");
        await load();
      } catch (err) {
        setStatus(`删除失败：${err.message}`, true);
      }
    });

    actions.append(editBtn, deleteBtn);
    rowsEl.appendChild(tr);
  });
}

function renderDeletedRows() {
  trashRowsEl.innerHTML = "";
  trashCountEl.textContent = `${deletedItems.length} 条`;
  trashEmptyEl.style.display = deletedItems.length ? "none" : "block";

  deletedItems.forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td><div class="rowActions"></div></td>
    `;
    tr.children[0].textContent = nameWithTag(item.name, item.tag || "生日");
    tr.children[1].textContent = item.tag || "生日";
    tr.children[2].textContent = item.date || "-";
    tr.children[3].textContent = item.deleted_at || "-";

    const actions = tr.querySelector(".rowActions");
    const restoreBtn = document.createElement("button");
    restoreBtn.type = "button";
    restoreBtn.textContent = "恢复";
    restoreBtn.addEventListener("click", async () => {
      try {
        await requestJson(`/api/restore/${item.id}`, { method: "POST" });
        setStatus("已恢复");
        await load();
      } catch (err) {
        setStatus(`恢复失败：${err.message}`, true);
      }
    });
    actions.appendChild(restoreBtn);
    trashRowsEl.appendChild(tr);
  });
}

async function load() {
  const [data, deletedData] = await Promise.all([
    requestJson("/api/birthdays"),
    requestJson("/api/deleted").catch(() => ({ ok: true, items: [] })),
  ]);
  items = data.items || [];
  deletedItems = deletedData.items || [];
  const cfg = data.config || {};
  metaEl.textContent =
    `数据库：${cfg.db}\n` +
    `输出：${cfg.out}\n` +
    `规则：出生年份用出生公历日期，之后按农历生日逐年转公历，到 ${cfg.end_year}\n` +
    `默认提醒：${cfg.alarm_days} 天`;
  defaultAlarmDaysEl.value = normalizeAlarmDaysText(cfg.alarm_days || "");
  renderRows();
  renderDeletedRows();
}

async function save() {
  const payload = {
    id: rowIdEl.value || null,
    name: nameEl.value.trim(),
    date: dateEl.value,
    birth_time: birthTimeEl.value.trim(),
    alarm_days: alarmDaysEl.value.trim() || null,
    tag: tagEl.value,
    note: noteEl.value.trim(),
  };
  if (!payload.name || !payload.date) {
    setStatus("名称和公历生日都要填写", true);
    return;
  }
  try {
    await requestJson("/api/birthdays", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setStatus(rowIdEl.value ? "已更新" : "已新增");
    resetForm();
    await load();
  } catch (err) {
    setStatus(`保存失败：${err.message}`, true);
  }
}

async function generate() {
  try {
    setStatus("生成中...");
    const data = await requestJson("/api/generate", { method: "POST" });
    setStatus(`${data.message}，可下载 birthdays.ics`);
  } catch (err) {
    setStatus(`生成失败：${err.message}`, true);
  }
}

document.getElementById("saveBtn").addEventListener("click", save);
document.getElementById("resetBtn").addEventListener("click", resetForm);
document.getElementById("generateBtn").addEventListener("click", generate);
tagFilterEl.addEventListener("change", () => {
  activeTagFilter = tagFilterEl.value;
  renderRows();
});
restoreAllBtn.addEventListener("click", async () => {
  try {
    await requestJson("/api/restore-all", { method: "POST" });
    setStatus("已全部恢复");
    await load();
  } catch (err) {
    setStatus(`全部恢复失败：${err.message}`, true);
  }
});
saveDefaultAlarmBtn.addEventListener("click", async () => {
  try {
    const normalized = normalizeAlarmDaysText(defaultAlarmDaysEl.value);
    if (!normalized) {
      setStatus("默认提醒天数不能为空", true);
      return;
    }
    await requestJson("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alarm_days: normalized }),
    });
    setStatus("默认提醒已更新");
    await load();
  } catch (err) {
    setStatus(`默认提醒更新失败：${err.message}`, true);
  }
});

load().catch((err) => setStatus(`加载失败：${err.message}`, true));
