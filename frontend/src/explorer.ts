import type { Pilot, TraceRow } from "./types";
function element<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element: ${id}`);
  return node as T;
}
const names: Record<string, string> = {latest_window: "Latest row", anti_null: "NULL-safe anti-join", distinct_pairs: "Distinct pairs", relational_division: "Relational division"};
type Arm = "base" | "sft";
type Outcome = "all" | "regressed" | "improved";
function readableJson(value: unknown, depth = 0): string {
  const indent = "  ".repeat(depth), next = "  ".repeat(depth + 1);
  if (Array.isArray(value)) {
    if (value.every(item => item === null || typeof item !== "object")) return JSON.stringify(value);
    return `[\n${value.map(item => next + readableJson(item, depth + 1)).join(",\n")}\n${indent}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{\n${Object.entries(value).map(([key, item]) => next + JSON.stringify(key) + ": " + readableJson(item, depth + 1)).join(",\n")}\n${indent}}`;
  }
  return JSON.stringify(value) ?? "null";
}
function step(label: string, value: unknown, error = false) {
  const row = document.createElement("div"), heading = document.createElement("div"), pre = document.createElement("pre");
  row.className = `step${error ? " error" : ""}`; heading.className = "step-label"; heading.textContent = label; pre.tabIndex = 0;
  pre.textContent = typeof value === "string" ? value : readableJson(value);
  row.append(heading, pre); element("trace-steps").append(row);
}
try {
  const response = await fetch("/pilot.json");
  if (!response.ok) throw new Error("The published traces could not be loaded. Reload this page or download the raw evidence.");
  const data: Pilot = await response.json();
  if (data.results.kind !== "baseten_experiment" || !data.results.complete || !data.rows.base?.length || !data.rows.sft?.length) throw new Error("Completed experiment evidence is unavailable.");
  const base = new Map(data.rows.base.map(row => [row.task_id, row]));
  const sft = new Map(data.rows.sft.map(row => [row.task_id, row]));
  const query = new URLSearchParams(location.search);
  let arm: Arm = query.get("condition") === "sft" ? "sft" : "base";
  let family = query.get("family") || "all";
  if (!(family in names)) family = "all";
  let outcome: Outcome = query.get("outcome") === "regressed" ? "regressed" : query.get("outcome") === "improved" ? "improved" : "all";
  let selected = query.get("task") || "";
  let filtered: TraceRow[] = [];
  const search = element<HTMLInputElement>("task-search"), list = element("task-list");
  search.value = query.get("q") || "";
  const previous = element<HTMLButtonElement>("previous-task"), next = element<HTMLButtonElement>("next-task");
  function syncUrl() {
    const url = new URL(location.href); url.search = "";
    url.searchParams.set("condition", arm);
    if (selected) url.searchParams.set("task", selected);
    if (family !== "all") url.searchParams.set("family", family);
    if (outcome !== "all") url.searchParams.set("outcome", outcome);
    if (search.value.trim()) url.searchParams.set("q", search.value.trim());
    history.replaceState(null, "", url);
  }
  function renderDetail() {
    const row = (arm === "base" ? base : sft).get(selected);
    element("task-detail").hidden = !row; element("empty-detail").hidden = Boolean(row);
    previous.disabled = !row || filtered.findIndex(r => r.task_id === selected) <= 0;
    next.disabled = !row || filtered.findIndex(r => r.task_id === selected) >= filtered.length - 1;
    if (!row) return;
    element("selected-task").textContent = `${names[row.family]} / ${row.task_id.split("-").at(-1)}`;
    element("selected-task").title = row.task_id; element("paired-result").replaceChildren();
    for (const [label, record] of [["Base", base.get(selected)], ["SFT", sft.get(selected)]] as const) {
      const tag = document.createElement("span"); tag.className = `result-tag ${record?.correct ? "is-correct" : "is-incorrect"}`;
      tag.textContent = `${label}: ${record?.correct ? "correct" : "incorrect"}`; element("paired-result").append(tag);
    }
    const meta = [row.fault === "none" ? "No tool fault" : "Transient tool fault", `${row.tool_calls} SQL ${row.tool_calls === 1 ? "call" : "calls"}`, `${row.output_tokens} tokens`, `${row.format_violations} format ${row.format_violations === 1 ? "violation" : "violations"}`];
    element("trace-meta").replaceChildren(...meta.map(text => {const span = document.createElement("span"); span.textContent = text; return span;}));
    element("task-question").textContent = data.tasks[selected].question; element("task-schema").textContent = data.tasks[selected].schema;
    element("transcript-arm").textContent = arm === "base" ? "Base checkpoint" : "After SFT";
    element("trace-steps").replaceChildren();
    row.trace.forEach((turn, index) => {
      step(`Model response ${index + 1}`, turn.assistant);
      if (turn.tool) step("SQL tool result", turn.tool, Boolean(turn.tool.error));
      if (turn.error) step("Evaluator", turn.error, true);
    });
  }
  function selectTask(id: string) {
    selected = id;
    list.querySelectorAll<HTMLButtonElement>("button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.task === id)));
    renderDetail(); syncUrl();
  }
  function renderList() {
    const text = search.value.trim().toLowerCase();
    filtered = data.rows.base.filter(row => {
      const trained = sft.get(row.task_id)!;
      return (family === "all" || row.family === family) && (outcome === "all" || (outcome === "regressed" ? row.correct && !trained.correct : !row.correct && trained.correct)) && (!text || `${row.task_id} ${names[row.family]} ${data.tasks[row.task_id].question}`.toLowerCase().includes(text));
    });
    if (!filtered.some(row => row.task_id === selected)) selected = filtered[0]?.task_id || "";
    element("task-count-label").textContent = `${filtered.length} of ${data.rows.base.length} task pairs`;
    element("clear-filters").hidden = family === "all" && outcome === "all" && !search.value;
    const fragment = document.createDocumentFragment();
    for (const row of filtered) {
      const shown = (arm === "base" ? base : sft).get(row.task_id)!;
      const button = document.createElement("button"); button.type = "button"; button.className = "task-row"; button.dataset.task = row.task_id;
      button.setAttribute("aria-pressed", String(selected === row.task_id)); button.setAttribute("aria-label", `${row.task_id}, ${shown.correct ? "correct" : "incorrect"}`);
      const label = document.createElement("span"), number = document.createElement("span"), mark = document.createElement("span");
      label.textContent = names[row.family]; number.className = "task-id"; number.textContent = row.task_id.split("-").at(-1) || "";
      mark.className = shown.correct ? "task-mark is-correct" : "task-mark is-incorrect"; mark.textContent = shown.correct ? "✓" : "×"; mark.setAttribute("aria-hidden", "true");
      button.append(mark, label, number); button.addEventListener("click", () => selectTask(row.task_id)); fragment.append(button);
    }
    list.replaceChildren(fragment); renderDetail(); syncUrl();
  }
  function syncControls() {
    for (const [key, value] of [["arm", arm], ["family", family], ["outcome", outcome]]) {
      document.querySelectorAll<HTMLButtonElement>(`button[data-${key}]`).forEach(button => {button.disabled = false; button.setAttribute("aria-pressed", String(button.dataset[key] === value));});
    }
  }
  document.querySelectorAll<HTMLButtonElement>("button[data-arm]").forEach(button => button.addEventListener("click", () => {arm = button.dataset.arm as Arm; syncControls(); renderList();}));
  document.querySelectorAll<HTMLButtonElement>("button[data-family]").forEach(button => button.addEventListener("click", () => {family = button.dataset.family!; syncControls(); renderList(); list.scrollTop = 0;}));
  document.querySelectorAll<HTMLButtonElement>("button[data-outcome]").forEach(button => button.addEventListener("click", () => {outcome = button.dataset.outcome as Outcome; syncControls(); renderList(); list.scrollTop = 0;}));
  search.disabled = false; search.addEventListener("input", () => {renderList(); list.scrollTop = 0;});
  previous.addEventListener("click", () => move(-1)); next.addEventListener("click", () => move(1));
  function move(direction: number) {
    const row = filtered[filtered.findIndex(r => r.task_id === selected) + direction];
    if (row) {
      selectTask(row.task_id);
      const button = [...list.querySelectorAll<HTMLButtonElement>("button")].find(item => item.dataset.task === selected);
      if (button) list.scrollTop = button.offsetTop - (list.clientHeight - button.offsetHeight) / 2;
    }
  }
  element("clear-filters").addEventListener("click", () => {family = "all"; outcome = "all"; search.value = ""; syncControls(); renderList();});
  syncControls(); renderList();
} catch (error) {
  element("explorer-error").hidden = false; element("explorer-error").textContent = error instanceof Error ? error.message : "Could not load the evidence. Reload this page.";
  element("task-count-label").textContent = "Evidence unavailable"; element("trace-meta").textContent = "Task data unavailable";
  element("selected-task").textContent = "Unable to load task"; element("task-question").textContent = "Reload the page or use the raw evidence download."; element("task-schema").textContent = "Schema unavailable";
}
