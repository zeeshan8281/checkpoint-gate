import type { Pilot } from "./types";
function $(id: "condition-select" | "trace-select"): HTMLSelectElement;
function $(id: string): HTMLElement;
function $(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing UI element: ${id}`);
  return element;
}
const labels: Record<string, string> = {base: "Base", sft: "SFT", sft_rl: "SFT + reward"};
const pp = (number: number) => `${number < 0 ? "−" : "+"}${Math.abs(number * 100).toFixed(1)}`;
function readableJson(value: unknown, depth = 0): string {
  const indent = "  ".repeat(depth);
  const childIndent = "  ".repeat(depth + 1);
  if (Array.isArray(value)) {
    if (value.every(item => item === null || typeof item !== "object")) return JSON.stringify(value);
    return `[\n${value.map(item => childIndent + readableJson(item, depth + 1)).join(",\n")}\n${indent}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{\n${Object.entries(value).map(([key, item]) => childIndent + JSON.stringify(key) + ": " + readableJson(item, depth + 1)).join(",\n")}\n${indent}}`;
  }
  return JSON.stringify(value) ?? "null";
}
function step(label: string, value: unknown, error = false) {
  const row = document.createElement("div");
  row.className = `step ${error ? "error" : ""}`;
  const name = document.createElement("div");
  name.className = "step-label"; name.textContent = label;
  const pre = document.createElement("pre");
  pre.textContent = typeof value === "string" ? value : readableJson(value);
  row.append(name, pre); $("trace-steps").append(row);
}
try {
  const response = await fetch("pilot.json");
  if (!response.ok) throw new Error("Completed pilot evidence could not be loaded. Reload the page or open Source & evidence.");
  const data: Pilot = await response.json(), results = data.results;
  if (results.kind !== "baseten_experiment" || results.complete !== true) {
    throw new Error("This page only accepts completed real-model experiments.");
  }
  const arms = ["base", "sft", "sft_rl"].filter(k => results.conditions[k]);
  $("task-count").textContent = String(results.conditions.base.offered_tasks);
  $("sft-count").textContent = String(data.training.filter(x => x.stage === "sft").length);
  $("rl-count").textContent = String(results.rl_updates);
  $("reservation").textContent = `$${results.budget.conservative_reserved_usd.toFixed(2)}`;
  $("checksum").textContent = `Dataset SHA256 / ${data.dataset_sha256.slice(0,16)}`;
  $("checksum").title = data.dataset_sha256;
  const final = arms.includes("sft_rl") ? "sft_rl" : "sft";
  const comparison = results.paired_vs_base[final];
  $("finding").textContent = `${labels[final]} versus base: ${pp(comparison.delta_accuracy)} percentage points.`;
  $("delta-value").textContent = pp(comparison.delta_accuracy).replace(/\.0$/, "");
  $("paired-note").textContent = `Paired 95% interval: ${pp(comparison.paired_bootstrap_95[0])} to ${pp(comparison.paired_bootstrap_95[1])} points. ${comparison.wins} improved, ${comparison.losses} regressed, ${comparison.ties} tied.`;
  $("rl-note").textContent = results.rl_updates
    ? `${results.rl_updates} reward updates completed. Full reward traces and elementary regression results are preserved in the repository.`
    : "Every sampled reward group had equal rewards. No reward update occurred, so only base and supervised fine-tuning are compared.";
  for (const arm of ["base", "sft"]) {
    const condition = results.conditions[arm];
    const percent = document.createElement("span"); percent.textContent = "%";
    $(arm + "-accuracy").replaceChildren(document.createTextNode((condition.accuracy * 100).toFixed(0)), percent);
    $(arm + "-score").textContent = `${condition.correct} of ${condition.offered_tasks} correct`;
    $(arm + "-bar").setAttribute("width", String(464 * condition.accuracy));
    const [lo, hi] = condition.wilson_95.map(value => 100 + 464 * value);
    const y = arm === "base" ? 36 : 86;
    $(arm + "-whisker").setAttribute("d", `M${lo} ${y-7}V${y+7}M${lo} ${y}H${hi}M${hi} ${y-7}V${y+7}`);
  }
  $("condition-select").replaceChildren();
  $("fault-table").replaceChildren();
  for (const arm of arms) {
    const tr = document.createElement("tr"), fault = results.conditions[arm].by_fault;
    for (const text of [labels[arm], ...["none","transient_first_call"].map(k => `${fault[k].correct}/${fault[k].n}`)]) {
      const td = document.createElement("td"); td.textContent = text; tr.append(td);
    }
    $("fault-table").append(tr);
    const option = document.createElement("option"); option.value = arm;
    option.textContent = labels[arm]; $("condition-select").append(option);
  }
  function renderTrace() {
    const arm = $("condition-select").value;
    const row = data.rows[arm].find(x => x.task_id === $("trace-select").value);
    if (!row) return;
    const task = data.tasks[row.task_id];
    $("trace-steps").replaceChildren();
    $("trace-meta").replaceChildren();
    const meta = [row.correct ? "Correct answer" : "Incorrect answer", row.family.replaceAll("_", " "), row.fault === "none" ? "No tool fault" : "Transient tool fault", `${row.tool_calls} SQL ${row.tool_calls === 1 ? "call" : "calls"}`, `${row.output_tokens} output tokens`, `${row.format_violations} strict format ${row.format_violations === 1 ? "violation" : "violations"}`];
    meta.forEach((text, index) => {
      const part = document.createElement("span"); part.textContent = text;
      if (index === 0) { part.className = "trace-status"; part.dataset.correct = String(row.correct); }
      $("trace-meta").append(part);
    });
    $("task-question").textContent = task.question;
    $("task-schema").textContent = task.schema;
    row.trace.forEach((turn, index) => {
      step(`Model response ${index + 1}`, turn.assistant);
      if (turn.tool) step("SQL tool result", turn.tool, Boolean(turn.tool.error));
      if (turn.error) step("Evaluator", turn.error, true);
    });
  }
  function setTasks(preferred: string | null = $("trace-select").value) {
    $("trace-select").replaceChildren();
    for (const row of data.rows[$("condition-select").value]) {
      const option = document.createElement("option");
      option.value = row.task_id;
      option.textContent = `${row.correct ? "✓" : "×"} ${row.task_id}`;
      $("trace-select").append(option);
    }
    if (preferred !== null && [...$("trace-select").options].some(o => o.value === preferred)) $("trace-select").value = preferred;
    renderTrace();
  }
  function updateUrl() {
    const url = new URL(location.href);
    url.searchParams.set("condition", $("condition-select").value);
    url.searchParams.set("task", $("trace-select").value);
    history.replaceState(null, "", url);
  }
  const params = new URLSearchParams(location.search);
  const initialCondition = params.get("condition");
  if (initialCondition && arms.includes(initialCondition)) $("condition-select").value = initialCondition;
  setTasks(params.get("task"));
  $("condition-select").disabled = false;
  $("trace-select").disabled = false;
  $("condition-select").addEventListener("change", () => { setTasks(); updateUrl(); });
  $("trace-select").addEventListener("change", () => { renderTrace(); updateUrl(); });
} catch (error: unknown) {
  const message = error instanceof Error ? error.message : "Could not load the published evidence. Reload the page.";
  $("finding").textContent = message;
  $("trace-meta").textContent = message;
  $("trace-meta").setAttribute("role", "alert");
  $("task-question").textContent = "Task data unavailable. The static summary and publication graph show the last published pilot.";
  $("task-schema").textContent = "Schema unavailable.";
  $("checksum").textContent = "Live evidence unavailable; showing published summary";
}
