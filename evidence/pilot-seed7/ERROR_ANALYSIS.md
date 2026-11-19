# What failed after fine-tuning

The SFT checkpoint lost 38 percentage points on this frozen synthetic test set:
112/200 correct versus 188/200 for base. The 78 task-level regressions and two
improvements are preserved in the raw traces. This is a negative result.

The change is not explained by rejected Markdown alone. The same predeclared
outer-fence normalization applied to both conditions. SFT had zero strict
format violations; base had 296 rejected strict-format turns that the common
normalization could handle. Both conditions completed every offered task.

## Where the accuracy fell

| Family | Base | SFT | Change in successful tasks |
| --- | ---: | ---: | ---: |
| Latest row per parent | 41/50 | 0/50 | -41 |
| NULL-safe anti-join | 49/50 | 13/50 | -36 |
| Distinct joined pairs | 48/50 | 49/50 | +1 |
| Relational division | 50/50 | 50/50 | 0 |

The following examples are the first task by ID in each affected family where
base succeeded and SFT failed. They illustrate errors; they are not a manual
classification of all failures.

### Latest row: prioritizing ID over time

Task `test-latest_window-0000` requested one row per non-NULL parent, choosing
the largest `tick` and breaking ties with the largest `id`.

SFT queried:

```sql
SELECT parent_id,id,value_962
FROM readings_962
WHERE parent_id IS NOT NULL
ORDER BY parent_id,id DESC,tick DESC
```

This returns all rows and orders IDs before timestamps. Its final answer then
selected high-ID rows that were not always the latest by time. For parent 2,
it returned row 42, value 35; the correct latest row was 26, value 20.

Base used nested maximum-time and maximum-ID subqueries and returned the
verified expected rows on this instance.

### Anti-join: removing the evidence before counting it

Task `test-anti_null-0000` requested parents with no child labelled `closed`,
including parents with no children.

SFT added:

```sql
WHERE c.id IS NULL OR c.label_602 <> 'closed'
GROUP BY p.id
HAVING SUM(CASE WHEN c.label_602='closed' THEN 1 ELSE 0 END)=0
```

The `WHERE` clause removes closed rows before the aggregate can count them.
Parents with both closed and non-closed children can therefore pass the
`HAVING` condition. SQL NULL semantics also affect which rows survive.
Base retained the joined rows and counted closed children in `HAVING`.

## Why the reward stage did not repair it

The reward stage sampled 18 groups of four trajectories from the training
distribution after SFT. All 72 trajectories were correct. Rewards within each
group were identical, so every group-centered advantage was zero. The preset
controller skipped all groups and made **zero RL updates**.

This establishes a mismatch between the sampled training difficulty and these
held-out failures. It does not show that reinforcement learning cannot help,
or that every possible training task would have equal rewards.

## Limits and the next experiment

One training seed, a small synthetic generator, and one sampling pass per test
condition limit the conclusion. The elementary regression suite also declined
from 68/100 to 54/100, mostly on literal-copy cases, but mixes formatting and
instruction following. It does not establish broad catastrophic forgetting.

For a new study, freeze fresh test instances and query families before running
anything. Compare smaller learning rates or fewer SFT steps using development
data, include harder training compositions that produce reward variance, and
repeat training seeds and base sampling. Do not use this published test set to
select a winning replacement checkpoint and call it a fresh held-out result.
