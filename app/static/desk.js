import {at, drawAxis, drawSlip, tag} from "./exhibits.js";
import {drawTable, views} from "./register.js";

const state = {document: null, history: [], transfers: [], transfer: null, stage: "zones", tab: 0, roll: "", busy: false};
const navigation = [...document.querySelectorAll("nav [data-view]")];
const form = at("plan-form");
const sample = at("sample");
const kerf = at("kerf");
const exportLink = at("export");
const transferForm = at("transfer-form");
const outRoll = at("out-roll");
const inRoll = at("in-roll");
const newRoll = {id: at("new-id"), fabric: at("new-fabric"), width: at("new-width"), length: at("new-length")};
const formatter = new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium"});

async function fetchData(path, method = "GET", body) {
  const options = body === undefined ? {method} : {method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message ?? `请求失败 ${response.status}`);
  return data;
}

function notice(text = "", failed = false) {
  const node = at("operation");
  node.hidden = !text;
  node.textContent = text;
  node.dataset.error = String(failed);
}

const transferMode = () => state.stage === "transfers" && Boolean(state.transfer);

function transferControls() {
  const manifest = state.document?.manifest;
  const archived = Boolean(manifest && manifest.sample === sample.value && manifest.kerf_mm === Number(kerf.value));
  const slips = state.document?.snapshot.slips ?? [];
  const fill = (select, predicate, extra = []) => {
    const keep = select.value;
    const options = slips.filter(predicate).map((slip) => {
      const option = tag("option", slip.roll);
      option.value = slip.roll;
      return option;
    });
    select.replaceChildren(...options, ...extra);
    if ([...select.options].some((option) => option.value === keep)) select.value = keep;
  };
  fill(outRoll, (slip) => slip.state === "待裁");
  const fresh = tag("option", "＋新卷入册");
  fresh.value = "__new__";
  fill(inRoll, (slip) => slip.state === "留存", [fresh]);
  const making = inRoll.value === "__new__";
  at("new-roll-fields").hidden = !making;
  for (const input of Object.values(newRoll)) input.required = making;
  const ready = archived && !state.busy && outRoll.options.length > 0 && inRoll.options.length > 0;
  for (const control of [outRoll, inRoll, ...Object.values(newRoll), at("swap")]) control.disabled = !ready;
}

function archiveControls() {
  const manifest = state.document?.manifest;
  const archived = manifest?.sample === sample.value && manifest?.kerf_mm === Number(kerf.value);
  for (const control of [sample, kerf, at("submit")]) control.disabled = state.busy;
  at("rerun").disabled = !archived || state.busy;
  at("print").disabled = state.busy || !(archived && state.roll || transferMode());
  if (archived && !state.busy) exportLink.href = `/api/export/${manifest.id}`;
  else exportLink.removeAttribute("href");
  exportLink.setAttribute("aria-disabled", String(!archived || state.busy));
  transferControls();
}

function heading() {
  const manifest = state.document?.manifest;
  at("archive-state").textContent = state.busy ? "正在排版" : manifest ? "已归档" : state.document ? "样例预览" : "暂无卷宗";
  at("archive-ref").textContent = manifest?.id.slice(0, 12) ?? "—";
  at("archive-ref").title = manifest?.id ?? "";
  const stamp = at("archive-date");
  stamp.dateTime = manifest?.created_at ?? "";
  stamp.textContent = manifest ? `${formatter.format(new Date(manifest.created_at))} · UTC+08:00` : "";
  const totals = state.document?.snapshot.ledger.totals;
  for (const name of ["length", "piece", "blocked", "kerf", "unused", "delta"]) {
    at(name === "kerf" ? "kerf-total" : name).textContent = totals?.[name] ?? "—";
  }
}

function rollPanel() {
  const data = state.document?.snapshot;
  const rolls = data?.zones.rolls ?? [];
  if (!rolls.some((roll) => roll.id === state.roll)) state.roll = rolls[0]?.id ?? "";
  const picker = at("roll-picker");
  const sourceFocus = picker.contains(document.activeElement);
  picker.replaceChildren(...rolls.map((roll) => {
    const button = tag("button", roll.id);
    button.type = "button";
    button.dataset.roll = roll.id;
    button.dataset.held = String(roll.held);
    button.setAttribute("aria-pressed", String(roll.id === state.roll));
    return button;
  }));
  if (sourceFocus) picker.querySelector("[aria-pressed=true]")?.focus();
  if (transferMode()) {
    const manifest = state.transfer.manifest;
    const book = state.transfer.rolls.find((roll) => roll.roll === manifest.in_roll);
    const slip = state.transfer.slips.find((item) => item.roll === manifest.in_roll);
    for (const button of picker.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.roll === manifest.in_roll));
    }
    drawAxis(book && {length: book.length, lengths: book.lengths_after, spans: book.spans_after, held: false}, slip);
    drawSlip(slip, manifest, data?.fit.kerf_mm);
    return;
  }
  const slip = data?.slips.find((item) => item.roll === state.roll);
  drawAxis(data?.ledger.rolls.find((roll) => roll.roll === state.roll), slip);
  drawSlip(slip, state.document?.manifest, data?.fit.kerf_mm);
}

function recordsPanel() {
  const tabs = views(state.stage, state.document?.snapshot, state.roll, state.history, state.transfer, state.transfers);
  at("view-title").textContent = navigation.find((button) => button.dataset.view === state.stage).textContent;
  const group = at("record-tabs");
  const restoreFocus = group.contains(document.activeElement);
  group.replaceChildren(...tabs.map(([label], index) => {
    const button = tag("button", label);
    button.type = "button";
    button.dataset.tab = index;
    button.setAttribute("aria-pressed", String(index === state.tab));
    return button;
  }));
  if (restoreFocus) group.querySelector("[aria-pressed=true]")?.focus();
  drawTable(tabs[state.tab]);
}

function draw() {
  heading();
  rollPanel();
  recordsPanel();
  archiveControls();
}

function setRun(document) {
  state.document = document;
  state.transfer = null;
  if (document.manifest) {
    sample.value = document.manifest.sample;
    kerf.value = document.manifest.kerf_mm;
  }
}

async function preview() {
  const query = new URLSearchParams({sample: sample.value, kerf_mm: kerf.value});
  setRun(await fetchData(`/api/preview?${query}`));
  state.transfers = [];
}

async function recent() {
  state.history = (await fetchData("/api/runs")).runs;
}

async function transfers(runId) {
  state.transfers = runId ? (await fetchData(`/api/transfers?run_id=${runId}`)).transfers : [];
}

function selectStage(stage) {
  state.stage = stage;
  state.tab = 0;
  navigation.forEach((item) => item.setAttribute("aria-pressed", String(item.dataset.view === stage)));
}

async function action(work) {
  if (state.busy) return;
  state.busy = true;
  notice();
  heading();
  archiveControls();
  try {
    await work();
    at("sync-state").textContent = "服务在线";
  } catch (error) {
    notice(`${error.message}，请核对后重试。`, true);
    at("sync-state").textContent = "作业失败";
  } finally {
    state.busy = false;
    draw();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const outcome = await fetchData("/api/runs", "POST", {sample: sample.value, kerf_mm: Number(kerf.value)});
    setRun(await fetchData(`/api/runs/${outcome.manifest.id}`));
    await recent();
    await transfers(outcome.manifest.id);
    notice(outcome.reused ? "沿用原归档" : "卷宗已归档");
  });
});
sample.addEventListener("change", () => {
  if (kerf.reportValidity()) action(preview);
  else archiveControls();
});
kerf.addEventListener("input", archiveControls);
transferForm.addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const body = {run_id: state.document.manifest.id, out_roll: outRoll.value, in_roll: inRoll.value};
    if (body.in_roll === "__new__") {
      body.in_roll = {id: newRoll.id.value, fabric: newRoll.fabric.value,
                      width: Number(newRoll.width.value), length: Number(newRoll.length.value)};
    }
    const outcome = await fetchData("/api/transfers", "POST", body);
    state.transfer = await fetchData(`/api/transfers/${outcome.manifest.id}`);
    await transfers(state.document.manifest.id);
    selectStage("transfers");
    notice(outcome.reused ? "沿用原调拨卷宗" : "调拨卷宗已签发");
  });
});
outRoll.addEventListener("change", () => {
  const slip = state.document?.snapshot.slips.find((item) => item.roll === outRoll.value);
  if (slip) {
    newRoll.id.value ||= `${outRoll.value}-调`;
    newRoll.fabric.value = slip.fabric;
    newRoll.width.value = slip.width;
    newRoll.length.value = slip.length;
  }
});
inRoll.addEventListener("change", transferControls);
at("rerun").addEventListener("click", () => action(async () => {
  const id = state.document.manifest.id;
  await fetchData(`/api/runs/${id}/rerun`, "POST");
  notice("重算与归档一致");
}));
at("print").addEventListener("click", () => window.print());
for (const button of navigation) button.addEventListener("click", () => {
  selectStage(button.dataset.view);
  recordsPanel();
});
at("record-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-tab]");
  if (button) {
    state.tab = Number(button.dataset.tab);
    recordsPanel();
  }
});
function chooseRoll(roll) {
  state.roll = roll;
  rollPanel();
  if (state.stage === "zones") recordsPanel();
  archiveControls();
}
at("roll-picker").addEventListener("click", (event) => {
  const button = event.target.closest("[data-roll]");
  if (button) chooseRoll(button.dataset.roll);
});
at("record-table").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (button?.dataset.roll) chooseRoll(button.dataset.roll);
  if (button?.dataset.open) action(async () => {
    setRun(await fetchData(`/api/runs/${button.dataset.open}`));
    await transfers(state.document.manifest.id);
  });
  if (button?.dataset.transfer) action(async () => {
    state.transfer = await fetchData(`/api/transfers/${button.dataset.transfer}`);
    selectStage("transfers");
  });
});

action(async () => {
  await recent();
  if (state.history.length) {
    setRun(await fetchData(`/api/runs/${state.history[0].id}`));
    await transfers(state.document.manifest.id);
  } else {
    await preview();
  }
});
