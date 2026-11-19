const $ = id => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, text) {
  const node = document.createElementNS(svgNS, tag);
  for (const [k,v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  $("chart").append(node);
}
function step(label, value, error = false) {
  const row = document.createElement("div"); row.className = `step ${error ? "error" : ""}`;
  const name = document.createElement("div"); name.className = "step-label"; name.textContent = label;
  const pre = document.createElement("pre"); pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  row.append(name, pre); $("trace-steps").append(row);
}
try {
  const response = await fetch("demo.json");
  if (!response.ok) throw new Error("Generate the local demo first; see the README.");
  const data = await response.json();
  if (data.kind !== "infrastructure_self_test" || data.model_calls !== 0) throw new Error("Unexpected demo format");
  const noRetry = data.conditions.scripted_no_retry, retry = data.conditions.scripted_retry;
  const total = retry.summary.offered_tasks;
  $("task-count").textContent = total;
  $("checksum").textContent = `DATASET SHA256 / ${data.dataset_sha256.slice(0, 16)}`;
  for (const [index, [name, condition]] of [["No-retry script", noRetry], ["Retry script", retry]].entries()) {
    const y = 56 + index*86, correct = condition.summary.correct;
    svg("text", {x:0,y:y-12}, name);
    svg("rect", {x:0,y,width:540,height:25,rx:5,fill:"#35443b"});
    svg("rect", {x:0,y,width:540*correct/total,height:25,rx:5,fill:"#b5ed87"});
    svg("text", {x:557,y:y+18,style:"fill:#e4ece6;font-size:15px"}, `${correct}/${total}`);
  }
  svg("text", {x:0,y:224}, "Verified task count · same tasks and tool-call budget");
  const options = retry.rows.filter(r => /-000[13]$/.test(r.task_id));
  for (let i=0;i<options.length;i++) {
    const option = document.createElement("option"); option.value = i;
    option.textContent = options[i].task_id; $("trace-select").append(option);
  }
  function renderTrace() {
    const row = options[Number($("trace-select").value)];
    $("trace-steps").replaceChildren();
    $("trace-meta").textContent = `${row.family} · injected transient error · ${row.tool_calls} SQL calls · ${row.correct ? "verified correct" : "incorrect"} · scripted reference-SQL agent`;
    row.trace.forEach(t => {
      step("SCRIPT", t.assistant);
      if (t.tool) step("SQL TOOL", t.tool, Boolean(t.tool.error));
    });
  }
  $("trace-select").addEventListener("change", renderTrace);
  renderTrace();
} catch (error) {
  $("trace-meta").textContent = error.message;
  $("checksum").textContent = "Demo data unavailable";
}
