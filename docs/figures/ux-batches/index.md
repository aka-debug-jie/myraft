# Benchmark visualizations

- [Performance](performance.svg)
- [Observed event timeline](timeline.svg)

Performance summarizes successful elapsed times only. Failures are counted as attempts and are never treated as zero seconds. Timeline points use recorded monotonic `offset_seconds`; when events are absent, the timeline says they were not recorded and does not infer times from wall-clock logs.
