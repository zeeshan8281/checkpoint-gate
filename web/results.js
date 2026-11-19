const $ = id => document.getElementById(id);
const labels = {base: "Base", sft: "SFT", sft_rl: "SFT + reward"};
const pp = number => `${number >= 0 ? "+" : ""}${(number * 100).toFixed(1)}`;
function step(label, value, error = false) {
  const row = document.createElement("div");
  row.className = `step ${error ? "error" : ""}`;
  const name = document.createElement("div");
  name.className = "step-label"; name.textContent = label;
  const pre = document.createElement("pre");
  pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  row.append(name, pre); $("trace-steps").append(row);
}
try {
  const response = await fetch("pilot.json");
  if (!response.ok) throw new Error("Completed pilot evidence has not been published yet.");
  const data = await response.json(), results = data.results;
  if (results.kind !== "baseten_experiment" || results.complete !== true) {
    throw new Error("This page only accepts completed real-model experiments.");
  }
  const arms = ["base", "sft", "sft_rl"].filter(k => results.conditions[k]);
  $("task-count").textContent = results.conditions.base.offered_tasks;
  $("sft-count").textContent = data.training.filter(x => x.stage === "sft").length;
  $("rl-count").textContent = results.rl_updates;
  $("reservation").textContent = `$${results.budget.conservative_reserved_usd.toFixed(2)}`;
  $("checksum").textContent = `DATASET SHA256 / ${data.dataset_sha256.slice(0,16)}`;
  const final = arms.includes("sft_rl") ? "sft_rl" : "sft";
  const comparison = results.paired_vs_base[final];
  $("finding").textContent = `${labels[final]} versus base: ${pp(comparison.delta_accuracy)} percentage points.`;
  $("paired-note").textContent = `Paired 95% interval: ${pp(comparison.paired_bootstrap_95[0])} to ${pp(comparison.paired_bootstrap_95[1])} points. ${comparison.wins} improved, ${comparison.losses} regressed, ${comparison.ties} tied.`;
  $("rl-note").textContent = results.rl_updates
    ? `${results.rl_updates} reward updates completed. Full reward traces and elementary regression results are preserved in the repository.`
    : "Every sampled reward group had equal rewards. No reward update occurred, so only base and supervised fine-tuning are compared.";
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
    $("trace-meta").textContent = `${row.family} · ${row.fault} · ${row.status} · ${row.tool_calls} SQL calls · ${row.output_tokens} output tokens · ${row.format_violations} strict format violations`;
    step("SCHEMA", task.schema); step("QUESTION", task.question);
    for (const turn of row.trace) {
      step("MODEL", turn.assistant);
      if (turn.tool) step("SQL TOOL", turn.tool, Boolean(turn.tool.error));
      if (turn.error) step("EVALUATOR", turn.error, true);
    }
  }
  function setTasks() {
    const previous = $("trace-select").value;
    $("trace-select").replaceChildren();
    for (const row of data.rows[$("condition-select").value]) {
      const option = document.createElement("option");
      option.value = row.task_id;
      option.textContent = `${row.correct ? "✓" : "×"} ${row.task_id}`;
      $("trace-select").append(option);
    }
    if ([...$("trace-select").options].some(o => o.value === previous)) {
      $("trace-select").value = previous;
    }
    renderTrace();
  }
  $("condition-select").addEventListener("change", setTasks);
  $("trace-select").addEventListener("change", renderTrace);
  setTasks();
} catch (error) {
  $("finding").textContent = error.message;
  $("checksum").textContent = "Completed evidence unavailable";
}
